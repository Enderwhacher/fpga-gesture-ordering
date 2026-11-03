"""Verify deployed app code; notebook outputs/settings and logs remain editable."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'app_manifest.json').read_text(encoding='utf-8'))
for name,expected in manifest['critical_sha256'].items():
    path=(ROOT/name).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file(): raise RuntimeError('Missing app file: '+name)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise RuntimeError('App file changed: '+name)
print('REMOTE_ORDER_APP_OK:',manifest['package'],len(manifest['critical_sha256']),'immutable app files')
