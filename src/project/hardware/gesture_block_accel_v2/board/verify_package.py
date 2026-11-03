"""Verify the deployment package before any overlay or DMA access."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def verify(directory=ROOT):
    root=Path(directory).resolve()
    info=json.loads((root/'package_manifest.json').read_text(encoding='utf-8'))
    if info.get('release')!='gesture_blocks56_fp32_pw16_v2':raise RuntimeError('Wrong package release')
    for name,expected in info['sha256'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Package hash mismatch: '+name)
    build=json.loads((root/'overlay/build_manifest.json').read_text(encoding='utf-8'))
    if not all(build.get(k) for k in ('implementation_passed','rtl_simulation_passed','csim_passed')):
        raise RuntimeError('Hardware checks not complete')
    print('BLOCKS56_PACKAGE_OK:',len(info['sha256']),'verified files',flush=True)
    return {'passed':True,'files':len(info['sha256']),'release':info['release']}

PACKAGE_STATUS=verify()
