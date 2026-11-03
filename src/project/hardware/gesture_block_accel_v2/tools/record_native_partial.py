"""Keep incomplete native-model simulation separate from passing evidence."""
from pathlib import Path
import hashlib
import json
ROOT=Path(__file__).resolve().parents[1]
work=ROOT/'build/axis_rtl_test'
files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in work.glob('*xsim*.log')}
result={'completed':False,'passed':False,'counted_as_rtl_pass':False,
    'reason':'Full-design vendor-model runs stopped because of simulation cost. No end-to-end native-model pass is claimed.',
    'replacement_evidence':'direct_rtl.json records generated control/RAM/pipeline RTL with separately vendor-checked FP32 primitive functional bindings',
    'partial_logs_sha256':files,'board_tested':False}
(ROOT/'hls/reports/vendor_full_design_incomplete.json').write_text(json.dumps(result,indent=2)+'\n')
print('Recorded incomplete native-model status separately')
