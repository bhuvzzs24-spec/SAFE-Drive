"""Synthetic contract tests only: no trained checkpoint, camera or inference metrics."""
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from safe_drive.helmet import HELMET_CLASSES,HelmetAssessment,HelmetDetection,HelmetInference,HelmetReviewConfirmer,ordered_class_names
from safe_drive.helmet_dataset import label_rows,validate_dataset
from safe_drive.storage import SQLiteStore
from safe_drive.runtime_status import model_status

class HelmetReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.adapter=HelmetInference(SimpleNamespace(task='detect',names=list(HELMET_CLASSES)))
        self.people=[('rider',[20,0,80,160]),('bystander',[140,0,180,160])]
        self.bikes=[('bike',[0,90,120,190])]
        self.head=HelmetDetection((38,10,62,36),'no_helmet',.9)

    def test_taxonomy_task_sparse_ids_and_thresholds_fail_closed(self):
        self.assertEqual(len(HELMET_CLASSES),3)
        for names in [{1:'full_face_helmet',2:'half_face_helmet',3:'no_helmet'},list(HELMET_CLASSES)+['uncertain']]:
            with self.assertRaises(ValueError): HelmetInference(SimpleNamespace(task='detect',names=names))
        with self.assertRaises(ValueError): HelmetInference(SimpleNamespace(task='classify',names=list(HELMET_CLASSES)))
        with self.assertRaises(ValueError): HelmetInference(self.adapter.model,confidence=float('nan'))
        with self.assertRaises(ValueError): ordered_class_names({0:'a',3:'b'})

    def test_unique_rider_gate_excludes_unrelated_person_and_preserves_person_id(self):
        result=self.adapter.associate_riders(self.people,self.bikes,[self.head,HelmetDetection((145,10,165,30),'half_face_helmet',.9)])
        self.assertEqual(set(result),{'rider'})
        self.assertEqual(result['rider'],HelmetAssessment('no_helmet',.9,'prediction','bike'))
        self.assertEqual(self.adapter.associate_riders(self.people,[],[self.head]),{})

    def test_pillion_ambiguity_small_low_confidence_and_occlusion_abstain(self):
        result=self.adapter.associate_riders(self.people+[('other',[20,0,80,160])],self.bikes,[self.head])
        self.assertEqual(result['rider'].class_name,'uncertain')
        for head,reason in [(HelmetDetection((40,10,44,14),'no_helmet',.9),'small_head'),(HelmetDetection((38,10,62,36),'no_helmet',.55),'low_confidence')]:
            assessment=self.adapter.associate_riders(self.people,self.bikes,[head])['rider']
            self.assertEqual((assessment.class_name,assessment.reason),('uncertain',reason))
        self.assertIsNone(self.adapter.associate_riders(self.people,self.bikes,[])['rider'].class_name)

    def test_temporal_review_is_not_single_frame_or_confirmed_violation_and_survives_reopen(self):
        confirmer=HelmetReviewConfirmer(duration_s=.6,min_observations=4,max_gap_s=.3)
        assessment=HelmetAssessment('half_face_helmet',.9,'prediction','bike')
        for i in range(3): self.assertIsNone(confirmer.update('rider',assessment,i*.2,i))
        event=confirmer.update('rider',assessment,.6,3)
        self.assertEqual(event['review_status'],'pending');self.assertTrue(event['experimental'])
        self.assertEqual((event['track_id'],event['motorcycle_track_id'],event['frame']),('rider','bike',3))
        self.assertIsNone(confirmer.update('rider',assessment,.8,4))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'db.sqlite3';store=SQLiteStore(path)
            store.create_session('s','c','synthetic_fixture','not-a-video','not-a-model','missing')
            event['event_id']='helmet-event';store.insert_event('s',event);store.review_event('helmet-event','verified','QA reviewer')
            saved=SQLiteStore(path).list_events('s')[0]
            self.assertEqual(saved['helmet_class'],'half_face_helmet');self.assertEqual(saved['review_status'],'verified')
            self.assertEqual(saved['reviewer'],'QA reviewer');self.assertTrue(saved['reviewed_at'])

    def test_missing_ambiguous_gaps_and_changed_motorcycles_reset_confirmation(self):
        assessment=HelmetAssessment('no_helmet',.9,'prediction','bike')
        for interruption in [None,HelmetAssessment('uncertain',None,'occlusion'),HelmetAssessment('no_helmet',.9,'prediction','other-bike')]:
            c=HelmetReviewConfirmer(.5,3,.4)
            c.update('r',assessment,0,0);c.update('r',assessment,.3,1)
            self.assertIsNone(c.update('r',interruption,.6,2))
            self.assertIsNone(c.update('r',assessment,.9,3))
        c=HelmetReviewConfirmer(.5,3,.4);c.update('r',assessment,0,0)
        self.assertIsNone(c.update('r',assessment,2,20))
        self.assertIsNone(c.update('r',assessment,1,10))

    def test_filename_alone_never_claims_model_loaded_or_inference_tested(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'fake.pt';p.write_bytes(b'NOT A CHECKPOINT')
            state=model_status(p,[])
            self.assertTrue(state['file_exists'])
            self.assertIn('Not verified',state['load_status']);self.assertIn('Not verified',state['inference_status'])

    def test_evaluation_maps_class_indices_and_does_not_invent_missing_metrics(self):
        from scripts.validate_helmet_model import class_metrics
        box=SimpleNamespace(ap_class_index=[2,0],p=[.2,.8],r=[.3,.9],ap50=[.4,.7],ap=[.1,.6])
        values=class_metrics(box)
        self.assertEqual(values['full_face_helmet']['precision'],.8)
        self.assertEqual(values['no_helmet']['precision'],.2)
        self.assertIsNone(values['half_face_helmet']['precision'])

class HelmetDatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.rows=[]
        for split in ['train','val','test']:
            for sub in ['images','labels']: (self.root/sub/split).mkdir(parents=True)
            for cls in range(3):
                name=f'{split}-{cls}.png'
                (self.root/'images'/split/name).write_bytes(b'\x89PNG\r\n\x1a\nSYNTHETIC-HEADER-FIXTURE'+name.encode())
                (self.root/'labels'/split/Path(name).with_suffix('.txt')).write_text(f'{cls} .5 .5 .2 .2\n')
                self.rows.append({'image':name,'split':split,'group_id':split,'license':'synthetic annotation contract fixture, not training data'})
        self.write_manifest()
        self.config=self.root/'data.yaml';self.config.write_text(json.dumps({'path':str(self.root),'train':'images/train','val':'images/val','test':'images/test','names':list(HELMET_CLASSES)}))
    def write_manifest(self):
        with (self.root/'manifest.csv').open('w',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=['image','split','group_id','license']);writer.writeheader();writer.writerows(self.rows)
    def test_three_class_split_manifest_and_annotations(self):
        result=validate_dataset(self.config)
        self.assertEqual(result['objects']['train'],[1,1,1]);self.assertEqual(result['images']['test'],3)
        (self.root/'labels/train/train-0.txt').write_text('0 .5 .5 .3 .3\n')
        self.assertNotEqual(result['dataset_sha256'],validate_dataset(self.config)['dataset_sha256'])
    def test_group_leakage_duplicate_images_and_bad_boxes_rejected(self):
        self.rows[3]['group_id']='train';self.write_manifest()
        with self.assertRaisesRegex(ValueError,'leakage'):validate_dataset(self.config)
        self.rows[3]['group_id']='val';self.write_manifest()
        (self.root/'images/test/test-0.png').write_bytes((self.root/'images/train/train-0.png').read_bytes())
        with self.assertRaisesRegex(ValueError,'duplicate'):validate_dataset(self.config)
        p=self.root/'invalid.txt'
        for content in ['3 .5 .5 .2 .2','0 nan .5 .2 .2','0 .9 .5 .5 .2','0 .5 .5 0 .2']:
            p.write_text(content)
            with self.assertRaises(ValueError):label_rows(p)

if __name__=='__main__':unittest.main()
