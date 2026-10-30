"""Fail-closed local dataset validation; output is a manifest, never model metrics."""
import argparse
import json
from pathlib import Path
from safe_drive.helmet_dataset import validate_dataset

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(validate_dataset(args.data),indent=2))
