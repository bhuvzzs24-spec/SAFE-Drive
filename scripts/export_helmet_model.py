"""Package a validated three-class .pt for the current adapter; optional ONNX research export."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from safe_drive.helmet import HelmetInference,HELMET_CLASSES
from safe_drive.vision import local_detector_weights

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--evaluation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='new .pt destination')
    args=parser.parse_args();source=local_detector_weights(args.model)
    record=json.loads(args.evaluation.read_text());digest=hashlib.sha256(source.read_bytes()).hexdigest()
    if record.get('model_sha256')!=digest or record.get('split')!='test' or record.get('taxonomy')!=list(HELMET_CLASSES):
        parser.error('evaluation must reference this checkpoint, taxonomy and held-out test split')
    if args.output.exists() or args.output.suffix!='.pt': parser.error('choose a new local .pt output path')
    HelmetInference.from_path(source)
    args.output.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,args.output)
    args.output.with_suffix('.evaluation.json').write_text(json.dumps(record,indent=2)+'\n')
    print('Packaged:',args.output,'SHA256:',digest)
    print('Evaluation presence is not an automatic quality approval; inspect class and sequence metrics.')
