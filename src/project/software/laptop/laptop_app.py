"""Laptop ordering/display application. A local browser displays the existing UI."""
import argparse
import base64
import json
import math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import HTTPError
import uuid
import webbrowser

import cv2
import numpy as np

from order_core import LABELS, MENU
from order_ui import OrderUI
from remote_client import MAX_RESPONSE, OrderStore, RemoteOrderState

HERE=Path(__file__).resolve().parent


class LaptopRuntime:
    def __init__(self,board_url='http://192.168.3.1:8765',asset_dir=None,log_dir=None,
                 min_score=.60,demo=False,poll_interval=.10,cache_dir=None):
        parsed=urlsplit(board_url)
        if parsed.scheme!='http' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Board URL must be http://IP:port with no credentials or query')
        self.board_url=board_url.rstrip('/'); self.demo=bool(demo); self.poll_interval=poll_interval
        self.begin=time.monotonic(); self.session_id=uuid.uuid4().hex
        self.log_dir=Path(log_dir or HERE/'logs'); self.asset_dir=Path(asset_dir or HERE/'assets')
        self.cache_dir=Path(cache_dir or HERE/'download_cache')
        self.state=RemoteOrderState(OrderStore(self.log_dir/'orders',self.session_id),min_score,demo)
        self.ui=OrderUI(self.asset_dir); self.ui_lock=threading.Lock()
        self.stop_event=threading.Event(); self.condition=threading.Condition(); self.threads=[]
        self.jpeg=None; self.jpeg_seq=0; self.rendered_frames=0
        self.preview=None; self.preview_lock=threading.Lock()
        self.preview_transport='starting'; self.preview_last_key=None
        self.preview_received=0.0; self.preview_source_age=0.0; self.preview_frames=0
        self.preview_error=None; self.preview_rtt_ms=None; self.preview_first_received=None
        self.opener=build_opener(ProxyHandler({}))
        self.preview_opener=build_opener(ProxyHandler({}))
        self.demo_label=None; self.demo_lock=threading.Lock(); self.failure=None
        self.image_downloads=set()
        for index,item in enumerate(MENU):
            cached=self.cache_dir/item['image']
            if cached.is_file() and not (self.asset_dir/item['image']).is_file():
                image=cv2.imdecode(np.fromfile(str(cached),np.uint8),cv2.IMREAD_COLOR)
                if image is not None and image.shape[:2]==(136,136): self.ui.set_photo(index,image)
        cv2.setNumThreads(2)

    def read_url(self,path,limit=MAX_RESPONSE,opener=None):
        request=Request(self.board_url+path,headers={'Cache-Control':'no-cache'})
        with (opener or self.opener).open(request,timeout=1.0) as response:
            data=response.read(limit+1)
        if len(data)>limit: raise ValueError('Board response exceeds configured limit')
        return data

    def fetch_assets(self):
        for index,item in enumerate(MENU):
            if self.stop_event.is_set(): return
            if item['image'] in self.image_downloads: continue
            # Existing collected photos already render; fetch only missing originals.
            if (self.asset_dir/item['image']).is_file():
                self.image_downloads.add(item['image']); continue
            try:
                data=self.read_url('/assets/'+item['image'],512*1024)
                image=cv2.imdecode(np.frombuffer(data,np.uint8),cv2.IMREAD_COLOR)
                if image is None or image.shape[:2]!=(136,136): raise ValueError('Invalid food thumbnail')
                with self.ui_lock: self.ui.set_photo(index,image)
                self.cache_dir.mkdir(parents=True,exist_ok=True)
                (self.cache_dir/item['image']).write_bytes(data)
                self.image_downloads.add(item['image'])
            except Exception as error:
                # A missing photo does not convert a real recognition into a demo result.
                print('Food thumbnail not available:',item['image'],str(error),flush=True)

    def decode_preview(self,observation,source_age=0.0,received=None):
        encoded=observation.get('preview_jpeg')
        if not encoded: return
        try:
            image=cv2.imdecode(np.frombuffer(base64.b64decode(encoded,validate=True),np.uint8),cv2.IMREAD_COLOR)
            if image is None or image.shape[:2]!=(120,160): return
            with self.preview_lock:
                self.preview=image; self.preview_received=time.monotonic() if received is None else received
                self.preview_source_age=source_age; self.preview_frames+=1
                if self.preview_first_received is None: self.preview_first_received=self.preview_received
            return True
        except (ValueError,cv2.error): pass
        return False

    def accept_preview(self,packet,received,rtt):
        # This endpoint is display-only. Do not call state.accept or advance the gesture gate.
        if not isinstance(packet,dict) or packet.get('protocol')!=1:
            raise ValueError('Invalid preview protocol')
        session=packet.get('session_id'); seq=packet.get('seq'); age=packet.get('age_seconds')
        if not isinstance(session,str) or not session or type(seq) is not int or seq<0:
            raise ValueError('Invalid preview identity')
        self.preview_transport='independent'; self.preview_rtt_ms=rtt*1000
        if packet.get('error') or packet.get('status') in ('ERROR','STOPPED'):
            with self.preview_lock: self.preview=None
            self.preview_error=str(packet.get('error') or packet.get('status'))
            return False
        if not packet.get('preview_jpeg'):
            with self.preview_lock: self.preview=None
            return False
        if not isinstance(age,(int,float)) or not math.isfinite(age) or age<0:
            raise ValueError('Invalid preview age')
        if age+rtt>1.0:
            with self.preview_lock: self.preview=None
            self.preview_error='STALE CAMERA PREVIEW'
            return False
        key=(session,seq)
        if key==self.preview_last_key: return False
        if self.preview_last_key and session==self.preview_last_key[0] and seq<self.preview_last_key[1]:
            return False
        if not self.decode_preview(packet,age+rtt,received):
            raise ValueError('Invalid preview JPEG')
        self.preview_last_key=key; self.preview_error=None
        return True

    def preview_loop(self):
        while not self.stop_event.is_set():
            began=time.monotonic(); delay=.05
            try:
                packet=json.loads(self.read_url('/api/preview',opener=self.preview_opener).decode('utf-8'))
                received=time.monotonic()
                if self.stop_event.is_set(): break
                self.accept_preview(packet,received,received-began)
            except HTTPError as error:
                if error.code==404:
                    self.preview_transport='legacy'; delay=2.0
                    self.preview_error='Board needs preview patch; using inference-rate preview'
                else: self.preview_error=f'HTTP {error.code}'
            except Exception as error:
                self.preview_error=f'{type(error).__name__}: {error}'
            self.stop_event.wait(max(.005,delay-(time.monotonic()-began)))

    def poll_loop(self):
        next_assets=0.0
        while not self.stop_event.is_set():
            begin=time.monotonic()
            try:
                packet=json.loads(self.read_url('/api/status').decode('utf-8'))
                received=time.monotonic()
                if self.stop_event.is_set(): break
                processed=self.state.accept(packet,received,received-begin)
                if processed and self.preview_transport!='independent':
                    observation=packet['observation']
                    self.decode_preview(observation,observation.get('age_seconds',0)+received-begin,received)
                if received>=next_assets and packet.get('status')=='RUNNING':
                    self.fetch_assets(); next_assets=time.monotonic()+10
            except Exception as error:
                self.state.fault(f'{type(error).__name__}: {error}')
            self.stop_event.wait(max(.005,self.poll_interval-(time.monotonic()-begin)))

    def demo_loop(self):
        seq=0
        while not self.stop_event.is_set():
            with self.demo_lock: label=self.demo_label
            seq+=1; now=time.monotonic()
            packet={'protocol':1,'session_id':'demo_'+self.session_id,'status':'RUNNING','error':None,
                'backend':{'name':'DEMO INPUT - NO CAMERA OR FPGA','fpga_enabled':False,'labels':list(LABELS)},
                'metrics':{'capture_hz':0,'ai_hz':0,'classification_hz':0},
                'observation':{'seq':seq,'age_seconds':0,'detected':label is not None,'label':label,
                    'score':1.0 if label else 0.0,'detector_ms':0.0,'classifier_ms':0.0,
                    'fpga_call_ms':None,'fpga_completed_frames':0,'preview_jpeg':None}}
            self.state.accept(packet,now,0)
            self.stop_event.wait(.1)

    def set_demo_gesture(self,label):
        if not self.demo: raise PermissionError('Manual gesture injection is disabled in live mode')
        if label is not None and label not in LABELS: raise ValueError('Unknown gesture')
        with self.demo_lock: self.demo_label=label

    def metrics(self,snapshot):
        observation=snapshot.get('observation') or {}; elapsed=max(.001,time.monotonic()-self.begin)
        label='DEMO / NO FPGA' if self.demo else ('CPU + FPGA' if snapshot['backend'].get('fpga_enabled') else 'CPU ONLY')
        if not snapshot['backend']: label='WAITING FOR AI'
        with self.preview_lock:
            preview_age=max(0,time.monotonic()-self.preview_received)+self.preview_source_age if self.preview is not None else None
            preview_fps=max(0,self.preview_frames-1)/max(.001,time.monotonic()-self.preview_first_received) if self.preview_first_received is not None else 0
        return {'backend_label':label,'display_fps':self.rendered_frames/elapsed,
            'preview_fps':preview_fps,'preview_transport':self.preview_transport,
            'preview_age_ms':preview_age*1000 if preview_age is not None else None,
            'preview_rtt_ms':self.preview_rtt_ms,'preview_error':self.preview_error,
            'ai_hz':snapshot['board_metrics'].get('ai_hz',0),
            'detector_ms':observation.get('detector_ms'),'classifier_ms':observation.get('classifier_ms'),
            'fpga_call_ms':observation.get('fpga_call_ms')}

    def render_loop(self):
        try:
            while not self.stop_event.is_set():
                start=time.monotonic(); snapshot=self.state.snapshot(start)
                with self.preview_lock:
                    camera=self.preview if start-self.preview_received+self.preview_source_age<=1.0 else None
                with self.ui_lock:
                    canvas=self.ui.render(snapshot['state'],snapshot['gate'],camera,self.metrics(snapshot))
                ok,data=cv2.imencode('.jpg',canvas,[cv2.IMWRITE_JPEG_QUALITY,88])
                if not ok: raise RuntimeError('Cannot encode laptop display frame')
                with self.condition:
                    self.jpeg=data.tobytes(); self.jpeg_seq+=1; self.rendered_frames+=1
                    self.condition.notify_all()
                self.stop_event.wait(max(.001,.05-(time.monotonic()-start)))
        except BaseException as error:
            self.failure=f'{type(error).__name__}: {error}'
            print('Laptop renderer failed:',self.failure,flush=True); self.stop_event.set()

    def snapshot(self):
        snapshot=self.state.snapshot(time.monotonic())
        snapshot['display']=self.metrics(snapshot); snapshot['laptop_session']=self.session_id
        snapshot['food_thumbnails_ready']=sorted(self.image_downloads)
        return snapshot

    def start(self):
        if self.threads: raise RuntimeError('Laptop runtime already started')
        self.threads=[threading.Thread(target=self.demo_loop if self.demo else self.poll_loop,name='order-receiver',daemon=True),
                      threading.Thread(target=self.render_loop,name='order-renderer',daemon=True)]
        if not self.demo:
            self.threads.append(threading.Thread(target=self.preview_loop,name='order-preview-receiver',daemon=True))
        for thread in self.threads: thread.start()

    def stop(self):
        self.stop_event.set()
        with self.condition: self.condition.notify_all()
        for worker in self.threads: worker.join(timeout=3)
        self.log_dir.mkdir(parents=True,exist_ok=True)
        record=self.snapshot()
        with self.state.lock: record['all_actions']=list(self.state.action_log)
        path=self.log_dir/('laptop_session_'+self.session_id+'.json')
        path.write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        return path


def make_handler(runtime):
    html=(HERE/'web/index.html').read_bytes()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def send_bytes(self,data,mime,status=200):
            self.send_response(status); self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store')
            self.end_headers()
            try: self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass

        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/': self.send_bytes(html,'text/html; charset=utf-8')
            elif path in ('/api/state','/health'):
                self.send_bytes(json.dumps(runtime.snapshot(),ensure_ascii=False,allow_nan=False).encode('utf-8'),
                    'application/json; charset=utf-8')
            elif path=='/frame.jpg':
                with runtime.condition: data=runtime.jpeg
                if data is None: self.send_error(503,'Renderer starting')
                else: self.send_bytes(data,'image/jpeg')
            elif path=='/stream.mjpg':
                self.send_response(200); self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')
                self.send_header('Cache-Control','no-store'); self.end_headers()
                last=-1
                try:
                    while not runtime.stop_event.is_set():
                        with runtime.condition:
                            runtime.condition.wait_for(lambda:runtime.jpeg_seq!=last or runtime.stop_event.is_set(),timeout=1)
                            data,seq=runtime.jpeg,runtime.jpeg_seq
                        if data is None or seq==last: continue
                        last=seq
                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: '+str(len(data)).encode()+b'\r\n\r\n'+data+b'\r\n')
                        self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,TimeoutError): pass
            else: self.send_error(404)

        def do_POST(self):
            # Live operation has no HTTP endpoint that injects manual gestures.
            if urlsplit(self.path).path!='/api/demo' or not runtime.demo:
                self.send_error(403); return
            origin=self.headers.get('Origin')
            if origin is not None and origin!='http://'+self.headers.get('Host',''):
                self.send_error(403); return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 1<=length<=256: raise ValueError('Invalid request size')
                packet=json.loads(self.rfile.read(length).decode('utf-8'))
                if not isinstance(packet,dict) or set(packet)!={'label'}: raise ValueError('Invalid gesture request')
                runtime.set_demo_gesture(packet['label'])
            except (ValueError,KeyError,TypeError): self.send_error(400); return
            self.send_bytes(b'{"ok":true}','application/json')
    return Handler


def run_laptop(board='http://192.168.3.1:8765',port=8080,open_browser=False,demo=False,min_score=.60):
    runtime=LaptopRuntime(board,min_score=min_score,demo=demo)
    server=ThreadingHTTPServer(('127.0.0.1',port),make_handler(runtime)); server.daemon_threads=True
    url='http://127.0.0.1:'+str(server.server_port)+'/'
    thread=None
    try:
        runtime.start()
        thread=threading.Thread(target=server.serve_forever,name='order-local-http',daemon=True); thread.start()
        print(('DEMO - NO FPGA' if demo else 'LIVE - BOARD: '+board)+'\nOpen '+url+'\nCtrl+C stops the laptop application.',flush=True)
        if open_browser: webbrowser.open(url)
        while not runtime.stop_event.wait(.2): pass
    except KeyboardInterrupt: print('Stopping laptop application...',flush=True)
    finally:
        runtime.stop_event.set()
        if thread is not None: server.shutdown()
        server.server_close()
        if thread is not None: thread.join(timeout=2)
        print('LAPTOP_LOG:',runtime.stop(),flush=True)
    if runtime.failure: raise RuntimeError(runtime.failure)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board',default='http://192.168.3.1:8765')
    parser.add_argument('--port',type=int,default=8080)
    parser.add_argument('--open-browser',action='store_true'); parser.add_argument('--demo',action='store_true')
    parser.add_argument('--min-score',type=float,default=.60)
    args=vars(parser.parse_args(argv)); return run_laptop(**args)

if __name__=='__main__': main()
