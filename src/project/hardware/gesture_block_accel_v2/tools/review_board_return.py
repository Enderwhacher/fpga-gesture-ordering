"""Read returned evidence as data; do not execute any returned scripts."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.stdout.reconfigure(encoding='utf-8')
path=Path('E:/gesture_blocks56_board_results.zip')
sha=hashlib.sha256(path.read_bytes()).hexdigest()
with zipfile.ZipFile(path) as z:
    assert z.testzip() is None
    print('ARCHIVE',sha,len(z.namelist()))
    for name in z.namelist():
        if name.endswith('report.json') or name.endswith('build_manifest.json'):
            value=json.loads(z.read(name))
            if name.endswith('build_manifest.json'):
                print('BUILD',json.dumps(value,ensure_ascii=False))
                continue
            print('REPORT',name)
            print(json.dumps({k:v for k,v in value.items() if k!='benchmark'},ensure_ascii=False,indent=2))
            for threads,groups in value.get('benchmark',{}).items():
                for group,data in groups.items():
                    print('BENCHMARK',threads,group,json.dumps({k:v for k,v in data.items() if k not in ('hardware_call_timings','split_timings')},ensure_ascii=False))
                    for key in ('hardware_call_timings','split_timings'):
                        rows=data.get(key,[])
                        if rows:
                            import statistics
                            print(key,'medians',json.dumps({k:statistics.median(r[k] for r in rows) for k,v in rows[0].items() if isinstance(v,(int,float))}))
