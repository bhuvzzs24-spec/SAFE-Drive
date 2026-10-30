"""Cheap, honest configuration inspection. Never loads a model on a page request."""
import importlib.util
from pathlib import Path


def model_status(configured, dependencies, private=True):
    text=str(configured or '').strip()
    path=Path(text).expanduser() if text and '://' not in text else None
    try:
        exists=bool(path and path.is_file() and path.stat().st_size>0)
    except OSError:
        exists=False
    found={}
    for name in dependencies:
        try: found[name]=importlib.util.find_spec(name) is not None
        except (ValueError,ImportError,AttributeError): found[name]=False
    return {'configured':str(path) if private and path else path.name if path else 'Not configured',
            'file_exists':exists,'supported_format':bool(path and path.suffix.lower()=='.pt'),
            'dependencies_discoverable':all(found.values()),'missing_dependencies':[name for name,present in found.items() if not present],
            'load_status':'Not verified — checked when an analysis starts',
            'inference_status':'Not verified — requires a successful real-video run'}
