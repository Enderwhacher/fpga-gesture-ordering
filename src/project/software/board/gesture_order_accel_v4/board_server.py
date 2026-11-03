"""Camera + CPU palm detector + cached FPGA classifier; no board HDMI loading."""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import urlsplit
import uuid

from order_core import LABELS, MENU

HERE=Path(__file__).resolve().parent
_active_runtime=None


def load_cv(root):
    runtime=Path(root)/'gesture_runtime_cv410'
    if not runtime.is_dir(): raise RuntimeError('Missing existing OpenCV runtime: '+str(runtime))
    if str(runtime) not in sys.path: sys.path.insert(0,str(runtime))
    import cv2
    numbers=re.findall(r'\d+',cv2.__version__)
    if tuple(map(int,numbers[:2]))<(4,10): raise RuntimeError('Restart this Notebook kernel and run from the first cell (OpenCV 4.10 required)')
    return cv2


def prepare_cv(root,cv_threads=4):
    if type(cv_threads) is not int or cv_threads not in (2,4): raise ValueError("cv_threads must be 2 or 4")
    cv=load_cv(root); cv.setNumThreads(cv_threads)
    return cv


def check_camera_unused(device):
    executable=shutil.which('fuser')
    if executable:
        checked=subprocess.run([executable,str(device)],capture_output=True,text=True,timeout=3)
        if checked.returncode==0 and checked.stdout.strip():
            raise RuntimeError('Camera is still in use by PID(s) '+checked.stdout.strip()+
                '; stop the original camera/HDMI program before loading the computation overlay')


class VisionBackend:
    def __init__(self,root,model_dir,accel_dir,backend='fpga',cv_threads=4):
        root=Path(root); model_dir=Path(model_dir); accel_dir=Path(accel_dir)
        self.cv=prepare_cv(root,cv_threads); self.accelerator=None
        assets=root/'gesture_assets'
        required=[assets/'mp_palmdet.py',assets/'palm_detection_mediapipe_2023feb.onnx',
                  model_dir/'hagrid_runtime.py',model_dir/'model_meta.json',model_dir/'hagrid_mobilenetv3_large.onnx']
        for path in required:
            if not path.is_file(): raise FileNotFoundError('Missing existing deployment file: '+str(path))
        if str(assets) not in sys.path: sys.path.insert(0,str(assets))
        loaded=sys.modules.get('mp_palmdet')
        if loaded is not None and Path(loaded.__file__).resolve()!=required[0].resolve():
            raise RuntimeError('A different palm detector module is cached; restart the Notebook kernel')
        from mp_palmdet import MPPalmDet
        self.detector=MPPalmDet(str(required[1]),scoreThreshold=.6,
            backendId=self.cv.dnn.DNN_BACKEND_OPENCV,targetId=self.cv.dnn.DNN_TARGET_CPU)
        requested=json.loads((model_dir/'model_meta.json').read_text(encoding='utf-8'))
        if hashlib.sha256((model_dir/'hagrid_mobilenetv3_large.onnx').read_bytes()).hexdigest()!=requested['model_sha256']:
            raise RuntimeError('Requested model file failed SHA256 verification')
        if backend in ('fpga','fpga_v2'):
            runtime_name='blocks16_runtime' if backend=='fpga_v2' else 'blocks_runtime'
            loaded=sys.modules.get(runtime_name)
            if loaded is not None and Path(loaded.__file__).resolve()!=(accel_dir/(runtime_name+'.py')).resolve():
                raise RuntimeError('A different FPGA runtime is cached; restart the Notebook kernel')
            if str(accel_dir) not in sys.path: sys.path.insert(0,str(accel_dir))
            factory=importlib.import_module(runtime_name).make_fpga_classifier
            self.classifier,self.accelerator=factory(accel_dir)
            if requested['model_sha256']!=self.classifier.meta['model_sha256']:
                self.close(); raise RuntimeError('Requested model does not match the verified FPGA split')
        elif backend=='cpu':
            spec=importlib.util.spec_from_file_location('remote_order_cpu_classifier',model_dir/'hagrid_runtime.py')
            module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            self.classifier=module.HagridClassifier(model_dir)
        else: raise ValueError('backend must be fpga, fpga_v2 or cpu')
        if tuple(self.classifier.labels)!=LABELS:
            self.close(); raise RuntimeError('Unexpected gesture class order')
        self.meta={'name':'CPU palm + FPGA complete blocks 5+6' if backend!='cpu' else 'CPU palm + CPU classifier',
            'app_release':'gesture_order_blocks56_process_v4','cv_threads':int(self.cv.getNumThreads()),
            'hardware_release':('gesture_blocks56_fp32_pw16_v2' if backend=='fpga_v2' else 'gesture_blocks56_fp32_v1') if backend!='cpu' else None,
            'fpga_enabled':backend!='cpu','model_sha256':self.classifier.meta['model_sha256'],
            'labels':list(self.classifier.labels),'opencv':self.cv.__version__,'detector_score_threshold':.6,
            'classifier_input':'full corrected BGR frame, not a detected-box crop'}

    def infer(self,frame):
        import numpy as np
        start=time.monotonic()
        hands=np.asarray(self.detector.infer(frame)).reshape(-1,19)
        detector_ms=(time.monotonic()-start)*1000
        predictions=[]; classifier_ms=0.0; fpga_call_ms=None
        if len(hands):
            start=time.monotonic()
            c=self.classifier
            predictions=c.topk(c.logits(c.preprocess(frame)),k=3)
            classifier_ms=(time.monotonic()-start)*1000
            if self.accelerator is not None:
                fpga_call_ms=float(self.accelerator.last_timing['total_ms'])
        return {'detected':bool(len(hands)),'detected_hands':int(len(hands)),
            'label':str(predictions[0][0]) if predictions else None,
            'score':float(predictions[0][1]) if predictions else 0.0,
            'predictions':[(str(label),float(score)) for label,score in predictions],
            'detector_ms':float(detector_ms),'classifier_ms':float(classifier_ms),
            'fpga_call_ms':fpga_call_ms,
            'split_timing':dict(self.classifier.last_split_timing) if fpga_call_ms is not None else None,
            'fpga_completed_frames':int(getattr(self.classifier,'fpga_completed_frames',0))}

    def close(self):
        if self.accelerator is not None:
            self.accelerator.close(); self.accelerator=None


def food_thumbnails(directory,cv):
    import numpy as np
    result={}
    for item in MENU:
        path=Path(directory)/item['image']
        if not path.is_file(): continue
        photo=cv.imdecode(np.fromfile(str(path),np.uint8),cv.IMREAD_COLOR)
        if photo is None: continue
        ok,data=cv.imencode('.png',cv.resize(photo,(136,136),interpolation=cv.INTER_AREA))
        if ok: result[item['image']]=data.tobytes()
    return result


class BoardRuntime:
    def __init__(self,backend,cv,camera_device='/dev/video0',rotate_180=False,mirror=False,
                 startup_timeout=30.0,stall_timeout=3.0,camera_factory=None,assets=None):
        self.backend=backend; self.cv=cv; self.camera_device=camera_device
        self.rotate_180=rotate_180; self.mirror=mirror
        self.startup_timeout=startup_timeout; self.stall_timeout=stall_timeout
        self.camera_factory=camera_factory or (lambda device:cv.VideoCapture(device,cv.CAP_V4L2))
        self.assets=assets or {}; self.session_id=uuid.uuid4().hex
        self.stop_event=threading.Event(); self.lock=threading.Lock(); self.threads=[]
        self.begin=time.monotonic(); self.frame=None; self.captured_at=0.0; self.seq=0
        self.last_result=None; self.last_result_source=0.0; self.preview=None
        self.camera_stage='STARTING'; self.error=None; self.status='STARTING'
        self.capture_count=0; self.inference_count=0; self.classification_count=0
        self.records=[]; self.backend_closed=False
        self.inference_started=0.0; self.inference_active=False
        # Preview has its own cadence and sequence; never reuse it for gesture confirmation.
        self.preview_stream=None; self.preview_stream_seq=0; self.preview_stream_source=0.0
        self.preview_encoded_count=0; self.preview_encode_ms=0.0; self.preview_stream_error=None
        self.preview_interval=.05

    def fail(self,where,error):
        message=f'{where}: {type(error).__name__}: {error}'
        with self.lock:
            if self.error is None: self.error=message
            self.status='ERROR'
        print(message,flush=True); self.stop_event.set()

    def capture_loop(self):
        cap=None
        try:
            with self.lock: self.camera_stage='OPENING '+str(self.camera_device)
            cap=self.camera_factory(self.camera_device)
            if not cap.isOpened(): raise RuntimeError('Cannot open camera; stop the previous camera program')
            for prop,value in ((self.cv.CAP_PROP_FOURCC,self.cv.VideoWriter_fourcc(*'MJPG')),
                               (self.cv.CAP_PROP_FRAME_WIDTH,640),(self.cv.CAP_PROP_FRAME_HEIGHT,480),(self.cv.CAP_PROP_FPS,30)):
                cap.set(prop,value)
            first=True
            with self.lock: self.camera_stage='WAITING FOR FIRST FRAME'
            while not self.stop_event.is_set():
                ok,frame=cap.read(); captured=time.monotonic()
                if self.stop_event.is_set(): break
                if not ok or frame is None:
                    if first and captured-self.begin<self.startup_timeout:
                        self.stop_event.wait(.1); continue
                    raise RuntimeError('Camera read failed')
                frame=self.cv.resize(frame,(640,480))
                if self.rotate_180: frame=self.cv.rotate(frame,self.cv.ROTATE_180)
                if self.mirror: frame=self.cv.flip(frame,1)
                with self.lock:
                    self.frame=frame; self.captured_at=captured; self.seq+=1; self.capture_count+=1
                    self.camera_stage='STREAMING'
                first=False
        except BaseException as error: self.fail('capture',error)
        finally:
            if cap is not None: cap.release()

    def preview_loop(self):
        last=-1
        try:
            while not self.stop_event.is_set():
                started=time.monotonic()
                with self.lock: seq,frame,captured=self.seq,self.frame,self.captured_at
                if frame is None or seq==last:
                    self.stop_event.wait(.005); continue
                last=seq
                # Capture publishes a fresh array; inference receives a copy.
                thumbnail=self.cv.resize(frame,(160,120),interpolation=self.cv.INTER_AREA)
                ok,data=self.cv.imencode('.jpg',thumbnail,[self.cv.IMWRITE_JPEG_QUALITY,75])
                if not ok: raise RuntimeError('Cannot encode camera preview')
                encoded=base64.b64encode(data.tobytes()).decode('ascii')
                with self.lock:
                    self.preview_stream=encoded; self.preview_stream_seq=seq
                    self.preview_stream_source=captured; self.preview_encoded_count+=1
                    self.preview_encode_ms=(time.monotonic()-started)*1000
                self.stop_event.wait(max(.001,self.preview_interval-(time.monotonic()-started)))
        except Exception as error:
            # Display failure must not reconfigure hardware or fabricate AI observations.
            with self.lock: self.preview_stream_error=f'{type(error).__name__}: {error}'
            print('Preview stream failed:',self.preview_stream_error,flush=True)

    def preview_snapshot(self):
        with self.lock:
            now=time.monotonic()
            return {'protocol':1,'session_id':self.session_id,'status':self.status,
                'error':self.error or self.preview_stream_error,
                'seq':self.preview_stream_seq,
                'age_seconds':max(0.0,now-self.preview_stream_source) if self.preview_stream is not None else None,
                'preview_jpeg':self.preview_stream,
                'preview_hz':self.preview_encoded_count/max(.001,now-self.begin),
                'encode_ms':self.preview_encode_ms}

    def inference_loop(self):
        last=-1
        try:
            while not self.stop_event.is_set():
                with self.lock: seq,frame,captured=self.seq,self.frame,self.captured_at
                if frame is None or seq==last:
                    self.stop_event.wait(.003); continue
                last=seq
                with self.lock:
                    self.inference_started=time.monotonic(); self.inference_active=True
                result=self.backend.infer(frame.copy())
                with self.lock: self.inference_active=False
                if self.stop_event.is_set(): break
                thumbnail=self.cv.resize(frame,(160,120),interpolation=self.cv.INTER_AREA)
                ok,data=self.cv.imencode('.jpg',thumbnail,[self.cv.IMWRITE_JPEG_QUALITY,75])
                with self.lock:
                    self.last_result=dict(result,seq=seq); self.last_result_source=captured
                    self.preview=base64.b64encode(data.tobytes()).decode('ascii') if ok else None
                    self.inference_count+=1; self.classification_count+=int(result['detected'])
                    self.status='RUNNING'
                    self.records.append(dict(result,seq=seq,source_offset=captured-self.begin,
                        completed_offset=time.monotonic()-self.begin))
                    if len(self.records)>2000: self.records.pop(0)
        except BaseException as error: self.fail('inference',error)
        finally:
            # Only the inference owner closes the accelerator, after it returns.
            try: self.backend.close(); self.backend_closed=True
            except BaseException as error: self.fail('backend close',error)

    def start(self):
        if self.threads: raise RuntimeError('Runtime already started')
        self.begin=time.monotonic()
        self.threads=[threading.Thread(target=self.capture_loop,name='order-capture',daemon=True),
                      threading.Thread(target=self.preview_loop,name='order-preview',daemon=True),
                      threading.Thread(target=self.inference_loop,name='order-inference',daemon=True)]
        for worker in self.threads: worker.start()

    def check_health(self):
        now=time.monotonic()
        with self.lock:
            frame,captured,stage=self.frame,self.captured_at,self.camera_stage
            active,started=self.inference_active,self.inference_started
        if frame is None and now-self.begin>self.startup_timeout:
            self.fail('watchdog',RuntimeError('Camera startup timeout: '+stage))
        elif frame is not None and now-captured>self.stall_timeout:
            self.fail('watchdog',RuntimeError('Camera stream stalled'))
        elif active and now-started>15:
            self.fail('watchdog',RuntimeError('Inference exceeded 15 seconds; restart kernel if the worker cannot exit'))

    def snapshot(self):
        with self.lock:
            now=time.monotonic(); elapsed=max(now-self.begin,.001)
            observation=None
            if self.last_result is not None:
                observation=dict(self.last_result,age_seconds=max(0.0,now-self.last_result_source),preview_jpeg=self.preview)
            return {'protocol':1,'session_id':self.session_id,'status':self.status,'error':self.error,
                'backend':dict(self.backend.meta),'camera_stage':self.camera_stage,
                'observation':observation,'metrics':{'capture_hz':self.capture_count/elapsed,
                'ai_hz':self.inference_count/elapsed,'classification_hz':self.classification_count/elapsed}}

    def stop(self,timeout=8.0):
        self.stop_event.set()
        for worker in self.threads: worker.join(timeout=timeout)
        alive=[worker.name for worker in self.threads if worker.is_alive()]
        with self.lock:
            if self.status!='ERROR': self.status='STOPPED'
        return alive

    def save_log(self,directory,reason,alive):
        directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
        with self.lock: records=list(self.records)
        final_status=self.snapshot()
        preview_metrics=self.preview_snapshot()
        preview_metrics.pop('preview_jpeg',None)
        if final_status['observation'] is not None: final_status['observation'].pop('preview_jpeg',None)
        record={'session_id':self.session_id,'reason':reason,'backend':self.backend.meta,
            'rotate_180':self.rotate_180,'mirror':self.mirror,'camera_device':self.camera_device,
            'workers_still_alive':alive,'backend_closed':self.backend_closed,
            'final_status':final_status,'records':records,'preview_metrics':preview_metrics,
            'note':'Live acquisition/inference log. Ordering runs on laptop. No board HDMI or real payment.'}
        path=directory/('board_session_'+self.session_id+'.json')
        path.write_text(json.dumps(record,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')
        return path


def make_handler(runtime):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            path=urlsplit(self.path).path
            if path in ('/health','/api/status'):
                data=json.dumps(runtime.snapshot(),ensure_ascii=False,allow_nan=False).encode('utf-8')
                mime='application/json; charset=utf-8'
            elif path=='/api/preview':
                data=json.dumps(runtime.preview_snapshot(),ensure_ascii=False,allow_nan=False).encode('utf-8')
                mime='application/json; charset=utf-8'
            elif path.startswith('/assets/') and path[len('/assets/'):] in runtime.assets:
                data=runtime.assets[path[len('/assets/'):]]; mime='image/png'
            else:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError): pass
    return Handler


def run_board_server(root='/home/xilinx/jupyter_notebooks',model_dir=None,accel_dir=None,
                     asset_dir=None,host='0.0.0.0',port=8765,backend='fpga',
                     camera_device='/dev/video0',rotate_180=False,mirror=False,seconds=0,vision_factory=None,runtime_factory=None):
    global _active_runtime
    if _active_runtime is not None and any(t.is_alive() for t in _active_runtime.threads):
        raise RuntimeError('Previous camera/inference thread is still alive; restart this kernel')
    root=Path(root); model_dir=Path(model_dir or root/'gesture4_model_v2')
    accel_dir=Path(accel_dir or root/'gesture_block_accel_v1')
    asset_dir=Path(asset_dir or root/'gesture_order_demo_v2/assets')
    vision=None; server=None; runtime=None; serving=None; reason='finished'
    try:
        check_camera_unused(camera_device)
        # Reserve the port before downloading a bitstream; a second server must
        # fail before it can reconfigure hardware belonging to the first one.
        server=ThreadingHTTPServer((host,port),BaseHTTPRequestHandler)
        server.daemon_threads=True
        print('Loading CPU palm detector and '+backend+' classifier...',flush=True)
        vision=(vision_factory or VisionBackend)(root,model_dir,accel_dir,backend)
        thumbnails=food_thumbnails(asset_dir,vision.cv)
        runtime=(runtime_factory or BoardRuntime)(vision,vision.cv,camera_device,rotate_180,mirror,assets=thumbnails)
        server.RequestHandlerClass=make_handler(runtime)
        runtime.start(); _active_runtime=runtime
        serving=threading.Thread(target=server.serve_forever,name='order-http',daemon=True); serving.start()
        print('ORDER_BOARD_SERVER_READY port='+str(server.server_port),flush=True)
        print('Backend:',vision.meta['name'],'| No board HDMI download',flush=True)
        while not runtime.stop_event.wait(.2):
            runtime.check_health()
            if seconds and time.monotonic()-runtime.begin>=seconds: break
        if runtime.error: reason='error'; raise RuntimeError(runtime.error)
    except KeyboardInterrupt:
        reason='interrupted'; print('Stopping camera/inference and saving logs...',flush=True)
    except BaseException:
        reason='error'; raise
    finally:
        if runtime is not None: runtime.stop_event.set()
        if server is not None:
            if serving is not None: server.shutdown()
            server.server_close()
        if serving is not None: serving.join(timeout=2)
        if runtime is not None and runtime.threads:
            alive=runtime.stop()
            try: print('BOARD_LOG:',runtime.save_log(HERE/'logs',reason,alive),flush=True)
            except OSError as error: print('Cannot save board log:',error,flush=True)
            if alive: print('Threads still alive; restart kernel before retrying:',alive,flush=True)
            else: print('ORDER_BOARD_SERVER_STOPPED',flush=True)
        elif vision is not None: vision.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='/home/xilinx/jupyter_notebooks')
    parser.add_argument('--model-dir'); parser.add_argument('--accel-dir'); parser.add_argument('--asset-dir')
    parser.add_argument('--host',default='0.0.0.0'); parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--backend',choices=['fpga','cpu'],default='fpga')
    parser.add_argument('--camera-device',default='/dev/video0')
    parser.add_argument('--rotate-180',action='store_true'); parser.add_argument('--mirror',action='store_true')
    parser.add_argument('--seconds',type=float,default=0)
    return run_board_server(**vars(parser.parse_args(argv)))

if __name__=='__main__': main()
