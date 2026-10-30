"""Reproducible local fine-tuning of the three-class SAFE-Drive head detector."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
from safe_drive.helmet_dataset import validate_dataset
from safe_drive.vision import local_detector_weights


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--base-model',required=True,help='trusted local Ultralytics detection .pt; never a download name')
    parser.add_argument('--epochs',type=int,default=100)
    parser.add_argument('--imgsz',type=int,default=960)
    parser.add_argument('--batch',type=int,default=8)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--device',default='cpu')
    parser.add_argument('--project',type=Path,default=Path('training-runs/helmet'))
    parser.add_argument('--name',default='helmet-three-class-v1')
    args=parser.parse_args()
    if args.epochs<1 or args.imgsz<32 or args.batch<1: parser.error('epochs, image size and batch must be positive')
    dataset=validate_dataset(args.data);base=local_detector_weights(args.base_model)
    os.environ.update(YOLO_AUTOINSTALL='false',YOLO_OFFLINE='true')
    from ultralytics import YOLO
    model=YOLO(str(base),task='detect')
    if model.task!='detect': parser.error('base checkpoint must be a detection model')
    model.train(data=str(args.data.resolve()),epochs=args.epochs,imgsz=args.imgsz,batch=args.batch,
                device=args.device,project=str(args.project),name=args.name,plots=True,
                seed=args.seed,deterministic=True,workers=0,exist_ok=False)
    folder=Path(model.trainer.save_dir);best=folder/'weights/best.pt'
    if not best.is_file(): raise RuntimeError('training returned without a best checkpoint; no success is recorded')
    record={'dataset':dataset,'arguments':{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
            'base_sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'checkpoint_sha256':hashlib.sha256(best.read_bytes()).hexdigest(),
            'versions':{n:importlib.metadata.version(n) for n in ('ultralytics','torch','numpy')},
            'held_out_evaluation':'not_run'}
    (folder/'training-manifest.json').write_text(json.dumps(record,indent=2,allow_nan=False)+'\n')
    print('Training produced:',best)
    print('Run held-out evaluation before enabling experimental inference. Determinism across hardware is not guaranteed.')

if __name__=='__main__': main()
