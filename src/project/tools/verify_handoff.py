"""Verify the extracted handoff using only Python standard library."""
from pathlib import Path
import hashlib
import json
import os

ROOT=Path(__file__).resolve().parents[1]


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def verify(root=ROOT):
    root=Path(root).resolve()
    if os.name == 'nt':
        sep = chr(92)
        prefix = sep * 2 + '?' + sep
        value = str(root)
        if not value.startswith(prefix):
            value = prefix + ('UNC' + sep + value[2:] if value.startswith(sep * 2) else value)
        root = Path(value)
    manifest_path=root/'project_manifest.json'
    if not manifest_path.is_file():manifest_path=root/'handoff_manifest.json'
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    failures=[]
    for index,(name,record) in enumerate(manifest['files'].items(),1):
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size!=record['bytes'] or digest(path)!=record['sha256']:
            failures.append(name)
        if index%100==0:print('Verified',index,'/',len(manifest['files']),flush=True)
    if failures:raise RuntimeError('Handoff mismatch: '+', '.join(failures))
    print('HANDOFF_OK:',len(manifest['files']),'files | final config serial_cv1_t3',flush=True)
    return dict(passed=True,files=len(manifest['files']))


if __name__=='__main__':verify()
