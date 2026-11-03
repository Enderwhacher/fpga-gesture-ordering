from pathlib import Path
import sys
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')
root = Path(__file__).resolve().parents[1]
print('Host local time',datetime.now().isoformat(timespec='seconds'))
for rel in ('vivado/reports/build_result.tsv', 'build/fast_rtl_test/fast_xsim_resident.log'):
    p = root / rel
    print('\nFILE', p)
    if p.exists():
        content=p.read_text(errors='replace')
        print('\n'.join(content.splitlines()[-12:]))
    else:print('missing')
for p in (root.parent/'b2w/gblock/gblock.runs').glob('*/runme.log'):
    content=p.read_text(errors='replace')
    if (p.parent/'.vivado.end.rst').exists():continue
    else:
        print('\nACTIVE RUN',p.parent.name,'updated',datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec='seconds'))
        print('\n'.join(content.splitlines()[-8:]))
