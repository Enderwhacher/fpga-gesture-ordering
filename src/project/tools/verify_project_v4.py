"""Verify the integrated project without camera, FPGA, or external dependencies."""
from pathlib import Path
import hashlib,json,os
ROOT=Path(__file__).resolve().parents[1]
def access(p):
    p=p.resolve()
    return Path('\\\\?\\'+str(p)) if os.name=='nt' and not str(p).startswith('\\\\?\\') else p
def digest(p):
    h=hashlib.sha256()
    with access(p).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    manifest=json.loads((ROOT/'project_manifest.json').read_text(encoding='utf-8'))
    for i,(name,record) in enumerate(manifest['files'].items(),1):
        p=(ROOT/name).resolve()
        if not p.is_relative_to(ROOT) or access(p).stat().st_size!=record['bytes'] or digest(p)!=record['sha256']:
            raise RuntimeError('Mismatch: '+name)
        if i%100==0:print('Verified',i,flush=True)
    print('PROJECT_V4_OK',len(manifest['files']),'files; no hardware test performed',flush=True)
if __name__=='__main__':main()
