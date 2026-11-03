"""Verify the frozen working release remains available for rollback."""
from pathlib import Path
import hashlib
import json
ROOT=Path(__file__).resolve().parents[1]
baseline=ROOT.parent/'output/validated_round2_functional_v1'
manifest=baseline/'baseline_manifest.json'
if not manifest.exists():
    print('Original frozen baseline is not in this workspace; no change made')
else:
    info=json.loads(manifest.read_text(encoding='utf-8'));checked=[]
    for entry in info['files']:
        path=baseline/entry['name']
        assert path.stat().st_size==entry['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest()==entry['sha256'],path.name
        checked.append(entry['name'])
    result={'passed':True,'files':len(checked),'scope':'Frozen previous functional release archives remain byte-identical; this does not validate the new board hardware',
        'baseline_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}
    (ROOT/'reports/stable_baseline_intact.json').write_text(json.dumps(result,indent=2)+'\n')
    print('Stable baseline verified:',len(checked),'unchanged files')
