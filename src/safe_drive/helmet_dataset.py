"""Validate local YOLO head annotations and camera/session-disjoint provenance."""
from pathlib import Path
import csv
import hashlib
import json
import math
from .helmet import HELMET_CLASSES

SPLITS = ('train','val','test')


def label_rows(path):
    rows=[]
    for number,line in enumerate(path.read_text().splitlines(),1):
        if not line.strip(): continue
        values=line.split()
        if len(values)!=5: raise ValueError(f'{path.name}:{number}: expected class cx cy width height')
        try: cls=int(values[0]);cx,cy,w,h=map(float,values[1:])
        except ValueError: raise ValueError(f'{path.name}:{number}: invalid numeric annotation') from None
        if str(cls)!=values[0] or cls not in range(3) or not all(math.isfinite(v) for v in (cx,cy,w,h)):
            raise ValueError(f'{path.name}:{number}: use only class IDs 0,1,2 and finite coordinates')
        if not 0<w<=1 or not 0<h<=1 or min(cx-w/2,cy-h/2)<-1e-7 or max(cx+w/2,cy+h/2)>1+1e-7:
            raise ValueError(f'{path.name}:{number}: normalized box lies outside image')
        rows.append((cls,cx,cy,w,h))
    return rows


def manifest_rows(path):
    with path.open(newline='') as file:
        reader=csv.DictReader(file)
        if not {'image','split','group_id','license'}.issubset(reader.fieldnames or []):
            raise ValueError('manifest.csv needs image,split,group_id,license columns')
        rows=list(reader)
    seen=set();groups={}
    for row in rows:
        name=Path(row['image'])
        if name.is_absolute() or '..' in name.parts or len(name.parts)!=1 or name.name in seen:
            raise ValueError('manifest image names must be unique basenames without traversal')
        seen.add(name.name)
        if row['split'] not in SPLITS or not row['group_id'].strip() or not row['license'].strip():
            raise ValueError('each image needs train/val/test, a capture-group ID and a real permission/license reference')
        if row['group_id'] in groups and groups[row['group_id']]!=row['split']:
            raise ValueError('capture-group leakage between dataset splits')
        groups[row['group_id']]=row['split']
    if not rows: raise ValueError('dataset manifest is empty')
    return rows


def validate_dataset(config_path):
    config_path=Path(config_path).resolve()
    text=config_path.read_text()
    try: config=json.loads(text)
    except json.JSONDecodeError:
        import yaml
        config=yaml.safe_load(text)
    if not isinstance(config,dict) or config.get('names') not in (list(HELMET_CLASSES),dict(enumerate(HELMET_CLASSES))):
        raise ValueError(f'dataset names must be exactly {list(HELMET_CLASSES)}')
    if 'download' in config: raise ValueError('automatic dataset download directives are not allowed')
    root=Path(config.get('path','.')).expanduser()
    if not root.is_absolute(): root=config_path.parent/root
    root=root.resolve(); rows=manifest_rows(root/'manifest.csv')
    counts={split:[0,0,0] for split in SPLITS};hashes={};images={split:0 for split in SPLITS};listed=set()
    for row in rows:
        split=row['split']
        if config.get(split)!=f'images/{split}': raise ValueError('use images/train, images/val and images/test split directories')
        image=root/'images'/split/row['image'];label=root/'labels'/split/Path(row['image']).with_suffix('.txt')
        if not image.resolve().is_relative_to(root) or image.is_symlink() or label.is_symlink():
            raise ValueError('dataset symlinks and out-of-root paths are not allowed')
        if not image.is_file() or not label.is_file(): raise ValueError(f'image or explicit label missing: {row["image"]}')
        if image.suffix.lower() not in {'.jpg','.jpeg','.png'}: raise ValueError('dataset images must be JPEG or PNG')
        payload=image.read_bytes()
        if not (payload.startswith(b'\xff\xd8') or payload.startswith(b'\x89PNG\r\n\x1a\n')): raise ValueError('image header does not match JPEG/PNG')
        digest=hashlib.sha256(payload).hexdigest()
        if digest in hashes: raise ValueError('duplicate image content across dataset; deduplicate before training')
        hashes[digest]=split;listed.add(image.resolve());images[split]+=1
        annotation_digest=hashlib.sha256(label.read_bytes()).hexdigest()
        hashes[digest]=split+":"+annotation_digest
        for cls,*_ in label_rows(label): counts[split][cls]+=1
    actual={p.resolve() for split in SPLITS for p in (root/'images'/split).glob('*') if p.is_file()}
    if actual!=listed: raise ValueError('manifest must account for every image in all splits')
    for split in SPLITS:
        if not images[split] or not all(counts[split]): raise ValueError(f'{split} requires labelled examples for each of the three classes')
    return {'taxonomy':list(HELMET_CLASSES),'images':images,'objects':counts,
            'manifest_sha256':hashlib.sha256((root/'manifest.csv').read_bytes()).hexdigest(),
            'dataset_sha256':hashlib.sha256(json.dumps(sorted(hashes.items())).encode()).hexdigest()}
