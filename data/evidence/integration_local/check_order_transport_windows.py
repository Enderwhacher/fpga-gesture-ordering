"""Loopback HTTP, real original laptop state/gate/store, pipeline fixture inference."""
from pathlib import Path
import hashlib
from http.server import ThreadingHTTPServer
import importlib.util
import json
import sys
import tempfile
import threading
import time
import urllib.request
import numpy as np
import cv2 as cv

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
from board_server import make_handler
from pipeline_runtime import PipelineRuntime
from order_core import LABELS


def load_client():
    path=APP/'tests/remote_client_reference.py'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='e26b66cac02a9861a1b66262bf9622c3b72244764d18cb1b269bd1b36a725a24'
    spec=importlib.util.spec_from_file_location('original_laptop_client',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class Camera:
    def __init__(self):self.marker=0;self.released=False
    def isOpened(self):return True
    def set(self,*args):return True
    def read(self):time.sleep(.025);return True,np.full((24,32,3),self.marker,np.uint8)
    def release(self):self.released=True


class Engine:
    meta=dict(name='FPGA protocol fixture',fpga_enabled=True,labels=list(LABELS))
    def __init__(self):self.owner=None;self.frames=0;self.closed=False
    def detect(self,frame):
        marker=int(frame[0,0,0]);time.sleep(.008)
        return np.full((1,19),marker) if marker else np.empty((0,19)),8.
    def classify(self,frame,hands,detector_ms):
        tid=threading.get_ident()
        if self.owner is None:self.owner=tid
        assert tid==self.owner
        marker=int(frame[0,0,0]);assert bool(marker)==bool(len(hands))
        if marker:assert (hands==marker).all()
        time.sleep(.02)
        label=LABELS[marker-1] if marker else None
        self.frames+=int(bool(marker))
        return dict(detected=bool(marker),detected_hands=int(bool(marker)),label=label,
            score=.99 if marker else 0.,predictions=[(label,.99)] if marker else [],
            detector_ms=detector_ms,classifier_ms=20. if marker else 0.,fpga_call_ms=1. if marker else None,
            split_timing={},fpga_completed_frames=self.frames)
    def close(self):
        if self.owner is not None:assert threading.get_ident()==self.owner
        self.closed=True


def main():
    client=load_client();cv.setNumThreads(1)
    camera=Camera();engine=Engine()
    runtime=PipelineRuntime(engine,cv,camera_factory=lambda device:camera)
    stop=threading.Event();online=threading.Event();online.set();errors=[]
    checks=[]
    with tempfile.TemporaryDirectory(prefix='v4_http_',dir=APP.parent/'tmp') as directory:
        state=client.RemoteOrderState(save_order=client.OrderStore(directory,'v4_local_test'))
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(runtime));server.daemon_threads=True
        url='http://127.0.0.1:'+str(server.server_port)
        serving=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True)
        def poll():
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while not stop.is_set():
                if not online.is_set():
                    stop.wait(.02);continue
                try:
                    start=time.monotonic()
                    with opener.open(url+'/api/status',timeout=2) as response:
                        packet=json.load(response)
                    now=time.monotonic()
                    state.accept(packet,now,now-start)
                    # Deterministic duplicate delivery: original 25 ms poll/camera
                    # periods can phase-lock on Windows and produce no duplicates.
                    state.accept(packet,now,now-start)
                except BaseException as error:
                    errors.append(repr(error));stop.set();break
                stop.wait(.025)
        polling=threading.Thread(target=poll,daemon=True)
        def show(marker,duration=.85):
            camera.marker=marker;time.sleep(duration)
            if errors:raise RuntimeError(errors)
        def release():show(0,.65)
        def gesture(marker):release();show(marker)
        try:
            runtime.start();serving.start();polling.start()
            show(0,.7);gesture(1)
            assert state.controller.page=='MENU'
            # A real 5-second hold with the unchanged original gate.
            release();show(4,5.0)
            assert state.controller.cart==[1,0,0]
            checks.append('continuous thumbs-up 5 seconds adds once')
            gesture(4);assert state.controller.cart==[2,0,0]
            gesture(2);assert state.controller.page=='REVIEW'
            gesture(2);assert state.controller.cart==[1,0,0]
            checks.append('two burgers minus one via released fist')
            gesture(3);assert state.controller.page=='MENU' and state.controller.cart==[1,0,0]
            gesture(3);assert state.controller.page=='EXIT_CONFIRM'
            gesture(3);assert state.controller.page=='MENU' and state.controller.cart==[1,0,0]
            checks.append('V returns and cancels exit preserving cart')
            release();online.clear();time.sleep(.1);state.fault('fixture cable unplugged')
            show(4,.9);assert state.controller.cart==[1,0,0]
            online.set();show(4,.9);assert state.controller.cart==[1,0,0]
            checks.append('offline input ignored and reconnect-held hand cannot fire')
            release();gesture(1);assert state.controller.selected==1
            gesture(4);assert state.controller.cart==[1,1,0]
            gesture(1);gesture(4);assert state.controller.cart==[1,1,1]
            gesture(2);assert state.controller.page=='REVIEW'
            gesture(4);assert state.controller.page=='DONE'
            files=list(Path(directory).glob('order_*.json'));assert len(files)==1
            order=json.loads(files[0].read_text(encoding='utf-8'))
            assert order['total_fen']==3300 and order['simulated'] and not order['paid']
            checks.append('complete 33-yuan simulated order saved through original OrderStore')
            snapshot=state.snapshot(time.monotonic())
            assert snapshot['transport']['duplicates_ignored']>0
            assert not snapshot['storage_error'] and not runtime.error
            seq=[a['seq'] for a in state.action_log];assert seq==sorted(set(seq))
            checks.append('duplicate polls never become duplicate actions')
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url+'/api/preview',timeout=2) as response:
                preview=json.load(response)
            assert preview['preview_jpeg'] and preview['seq']>0
            checks.append('independent preview endpoint remains functional')
        finally:
            stop.set()
            if polling.ident:polling.join(timeout=3)
            if serving.ident:server.shutdown();serving.join(timeout=3)
            server.server_close()
            alive=runtime.stop()
        assert not alive and engine.closed and camera.released and not errors
        result=dict(passed=True,board_tested=False,checks=checks,workers_closed=True,
            scope='Actual loopback HTTP, original laptop client/gate/order store, real pipeline threads; camera and inference are fixtures. Not board performance or recognition accuracy.',
            runtime_metrics=runtime.pipeline_metrics(),actions=state.action_log)
        (APP/'local_order_transport_checks.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('V4_ORDER_TRANSPORT_PASS',len(checks),flush=True)


if __name__=='__main__':main()
