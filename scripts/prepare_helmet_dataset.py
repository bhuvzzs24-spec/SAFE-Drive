"""Prepare a user-labelled, group-split dataset; never creates labels or downloads data."""
import argparse
import json
from pathlib import Path
import shutil
from safe_drive.helmet import HELMET_CLASSES
from safe_drive.helmet_dataset import SPLITS,manifest_rows,validate_dataset


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True,help='existing flat images/ and labels/ export')
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); rows=manifest_rows(args.manifest)
    if args.output.exists(): parser.error('output must be a new directory; existing data is never overwritten')
    for row in rows:
        for sub,name in [('images',row['image']),('labels',str(Path(row['image']).with_suffix('.txt')))]:
            source=args.source/sub/name
            if not source.is_file() or source.is_symlink() or not source.resolve().is_relative_to(args.source.resolve()):
                parser.error('missing or unsafe labelled source file: '+name)
    args.output.mkdir(parents=True)
    for split in SPLITS:
        for sub in ['images','labels']: (args.output/sub/split).mkdir(parents=True)
    for row in rows:
        for sub,name in [('images',row['image']),('labels',str(Path(row['image']).with_suffix('.txt')))]:
            shutil.copyfile(args.source/sub/name,args.output/sub/row['split']/name)
    shutil.copyfile(args.manifest,args.output/'manifest.csv')
    config={'path':str(args.output.resolve()),**{s:f'images/{s}' for s in SPLITS},'names':list(HELMET_CLASSES)}
    (args.output/'data.yaml').write_text(json.dumps(config,indent=2)+'\n')
    print(json.dumps(validate_dataset(args.output/'data.yaml'),indent=2))

if __name__=='__main__': main()
