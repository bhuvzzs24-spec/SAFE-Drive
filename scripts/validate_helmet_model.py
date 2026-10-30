"""Evaluate a supplied local checkpoint on a labelled held-out test split."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from safe_drive.helmet import HELMET_CLASSES,HelmetInference
from safe_drive.helmet_dataset import validate_dataset
from safe_drive.vision import local_detector_weights


def class_metrics(box):
    indices=[int(v) for v in box.ap_class_index]
    result={}
    for cls,name in enumerate(HELMET_CLASSES):
        i=indices.index(cls) if cls in indices else None
        values={}
        for key,source in [('precision','p'),('recall','r'),('AP50','ap50'),('AP50_95','ap')]:
            value=float(getattr(box,source)[i]) if i is not None else None
            values[key]=value if value is not None and math.isfinite(value) else None
        result[name]=values
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True);parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--imgsz',type=int,default=960);parser.add_argument('--device',default='cpu')
    parser.add_argument('--report',type=Path,default=Path('evaluation-runs/helmet/evaluation.json'))
    args=parser.parse_args()
    if args.report.exists(): parser.error('use a new report path; evaluations are never overwritten')
    dataset=validate_dataset(args.data);weights=local_detector_weights(args.model)
    os.environ.update(YOLO_AUTOINSTALL='false',YOLO_OFFLINE='true')
    from ultralytics import YOLO
    model=YOLO(str(weights),task='detect');HelmetInference(model)
    metrics=model.val(data=str(args.data.resolve()),split='test',imgsz=args.imgsz,device=args.device,
                      project=str(args.report.parent),name='held-out',plots=True,verbose=True)
    report={'task':'detect','taxonomy':list(HELMET_CLASSES),'dataset':dataset,'model_sha256':hashlib.sha256(weights.read_bytes()).hexdigest(),
            'split':'test','image_size':args.imgsz,'device':args.device,'metrics':class_metrics(metrics.box),
            'note':'Head-box accuracy only. Rider association, abstention and temporal events need separate labelled sequence evaluation.'}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps(report,indent=2,allow_nan=False))

if __name__=='__main__': main()
