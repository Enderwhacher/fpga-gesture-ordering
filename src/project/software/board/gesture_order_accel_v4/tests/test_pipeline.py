"""Real worker threads and original gate: ownership, stale backlog, release, errors."""
from pathlib import Path
import sys
import threading
import time
import unittest
import numpy as np
import cv2 as cv

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from pipeline_runtime import PipelineRuntime
from order_core import GestureGate
from validate_v4 import choose


class Engine:
    meta={'name':'pipeline ownership fixture'}
    def __init__(self,fail=None):
        self.fail=fail;self.count=0;self.active=0;self.owner=None;self.closed=False
    def detect(self,frame):
        if self.fail=='detect':raise RuntimeError('fixture detector error')
        marker=int(frame[0,0,0]);time.sleep(.005)
        return (np.full((1,19),marker) if marker else np.empty((0,19))),5.
    def classify(self,frame,hands,elapsed):
        ident=threading.get_ident()
        if self.owner is None:self.owner=ident
        assert self.owner==ident and self.active==0
        self.active+=1
        try:
            if self.fail=='classify':raise RuntimeError('fixture classifier error')
            marker=int(frame[0,0,0])
            assert bool(marker)==bool(len(hands))
            if marker:assert (hands==marker).all()
            time.sleep(.02)
            self.count+=int(bool(marker))
            return dict(detected=bool(marker),detected_hands=int(bool(marker)),label='thumbs_up' if marker else None,
                score=.9 if marker else 0.,predictions=[('thumbs_up',.9)] if marker else [],
                detector_ms=elapsed,classifier_ms=20. if marker else 0.,
                fpga_call_ms=1. if marker else None,split_timing={},fpga_completed_frames=self.count)
        finally:self.active-=1
    def close(self):
        assert self.active==0
        if self.owner is not None:assert self.owner==threading.get_ident()
        self.closed=True


class PipelineTests(unittest.TestCase):
    def runtime(self,engine):
        r=PipelineRuntime(engine,cv);r.begin=time.monotonic()
        r.threads=[threading.Thread(target=r.detection_loop,daemon=True),
                   threading.Thread(target=r.inference_loop,daemon=True)]
        for worker in r.threads:worker.start()
        return r
    def publish(self,r,marker,duration):
        until=time.monotonic()+duration
        while time.monotonic()<until and not r.stop_event.is_set():
            with r.lock:
                r.seq+=1;r.frame=np.full((24,32,3),marker,np.uint8);r.captured_at=time.monotonic()
            time.sleep(.002)
    def test_owned_frames_bounded_queue_and_single_fpga_owner(self):
        engine=Engine();r=self.runtime(engine)
        try:
            for marker in range(1,8):self.publish(r,marker,.04)
        finally:alive=r.stop()
        self.assertFalse(alive);self.assertIsNone(r.error);self.assertTrue(engine.closed)
        self.assertGreater(len(r.records),3)
        self.assertGreater(r.pending_replaced_count,0)
        self.assertGreater(r.overlapped_detections+r.overlapped_classifications,0)
        seq=[x['seq'] for x in r.records]
        self.assertEqual(seq,sorted(set(seq)))
        self.assertTrue(all(x['completed_offset']>=x['source_offset'] for x in r.records))
        self.assertEqual(r.pipeline_metrics()['pending_slots'],1)
    def test_hold_once_explicit_nohand_releases(self):
        engine=Engine();r=self.runtime(engine)
        try:
            self.publish(r,1,.30);self.publish(r,0,.20);self.publish(r,1,.30)
        finally:alive=r.stop()
        self.assertFalse(alive);self.assertIsNone(r.error)
        gate=GestureGate(required=2,hold_seconds=.03,release_seconds=.03)
        fired=[]
        for row in r.records:
            action=gate.update(row['label'],row['score'],row['detected'],row['source_offset'],row['completed_offset'])
            if action:fired.append(action)
        self.assertEqual(fired,['thumbs_up','thumbs_up'])
    def test_stage_failures_stop_and_close(self):
        for where in ('detect','classify'):
            with self.subTest(stage=where):
                engine=Engine(fail=where);r=self.runtime(engine)
                try:self.publish(r,1,.2);time.sleep(.04)
                finally:alive=r.stop()
                self.assertFalse(alive);self.assertIsNotNone(r.error);self.assertTrue(engine.closed)
                self.assertFalse(r.records)
    def test_stop_discards_pending_work_without_an_extra_fpga_call(self):
        engine=Engine();r=PipelineRuntime(engine,cv)
        worker=threading.Thread(target=r.inference_loop,daemon=True)
        r.threads=[worker];worker.start();time.sleep(.01)
        with r.lock:
            r.latest_detection=(1,time.monotonic(),np.ones((24,32,3),np.uint8),np.ones((1,19)),5.,time.monotonic())
            r.stop_event.set();r.detection_event.set()
        alive=r.stop()
        self.assertFalse(alive);self.assertEqual(engine.count,0);self.assertTrue(engine.closed)
        self.assertIsNone(r.latest_detection);self.assertFalse(r.records)


class ChoiceTests(unittest.TestCase):
    def row(self,age,interval,quality=True):
        return dict(frame_age_ms=age,result_interval_ms=interval,frame_age_p95_ms=age*1.1,background_ok=quality,
                    rounds=[dict(frame_age_ms=age,result_interval_ms=interval)]*2)
    def test_rejects_faster_but_stale_pipeline(self):
        self.assertEqual(choose({'v3_reference':self.row(400,400),'pipe':self.row(600,200)}),'v3_reference')
    def test_never_chooses_cpu(self):
        self.assertEqual(choose({'v3_reference':self.row(400,400),'serial':self.row(320,320),
                                 'cpu_fast':self.row(100,100)}),'serial')
    def test_accepts_overlap_without_latency_regression(self):
        self.assertEqual(choose({'v3_reference':self.row(400,400),'pipe':self.row(400,280)}),'pipe')
    def test_rejects_single_round_lucky_gain(self):
        row=self.row(320,320);row['rounds']=[dict(frame_age_ms=280,result_interval_ms=280),dict(frame_age_ms=420,result_interval_ms=420)]
        self.assertEqual(choose({'v3_reference':self.row(400,400),'serial':row}),'v3_reference')
    def test_rejects_preview_starvation(self):
        self.assertEqual(choose({'v3_reference':self.row(400,400),'serial':self.row(200,200,False)}),'v3_reference')
    def test_prefers_real_goal_over_publish_rate(self):
        v2=self.row(450,450);v2['detector_plus_classifier_ms']=400
        serial=self.row(295,295);serial['detector_plus_classifier_ms']=260
        pipe=self.row(305,180);pipe['detector_plus_classifier_ms']=390
        self.assertEqual(choose({'v2_reference':v2,'v3_reference':self.row(383,383),
                                 'serial':serial,'pipe':pipe}),'serial')


if __name__=='__main__':
    cv.setNumThreads(1)
    import json
    suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result=unittest.TextTestRunner().run(suite)
    (APP/'local_concurrency_checks.json').write_text(json.dumps(dict(passed=result.wasSuccessful(),
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),board_tested=False,
        scope='Real Python worker threads; fixture engine, original GestureGate and selection rules; not hardware performance.'),indent=2)+'\n',encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() else 1)
