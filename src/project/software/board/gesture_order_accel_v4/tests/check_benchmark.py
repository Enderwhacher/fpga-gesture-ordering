"""Exercise actual serial/pipeline benchmark orchestration with real model data."""
from pathlib import Path
import json
import sys
import time
APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP));sys.path.insert(0,str(APP/'tests'))
from check_models import make_base
import validate_v4
import cv2 as cv


class FixtureBackground:
    def __init__(self,cv):self.begin=time.monotonic()
    def start(self):pass
    def snapshot(self):
        elapsed=time.monotonic()-self.begin
        return dict(capture=int(elapsed*30),preview=int(elapsed*20),error=None)
    def stop(self):return dict(workers_still_alive=[],error=None)


if __name__=='__main__':
    validate_v4.Background=FixtureBackground
    base,root,accel=make_base()
    fixed=cv.imread(str(APP/'samples/fixed_hand.png'))
    base.classifier.net.setInput(base.classifier.preprocess(fixed))
    expected=base.classifier.topk(base.classifier.net.forward().reshape(-1),3)
    blocks=[]
    for config in ('v3_reference','serial_cv1_t3','pipe_cv1_d2_c2','pipe_cv1_d3_c1'):
        block=validate_v4.benchmark_block(base,root,accel,config,fixed,expected,samples=12)
        assert len(block['records'])==12
        assert not block['inference_workers_still_alive']
        # Windows monotonic() can have ~15 ms granularity; Linux board timing is finer.
        assert all(r['frame_age_ms']>=0 and r['result_interval_ms']>0 for r in block['records'])
        blocks.append(dict(config=config,records=len(block['records']),workers_closed=True))
    report=dict(passed=True,board_tested=False,scope='Real models with CPU PL substitute, simulated background counters; orchestration only, not performance evidence',blocks=blocks)
    (APP/'local_benchmark_checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('V4_BENCHMARK_ORCHESTRATION_PASS')
