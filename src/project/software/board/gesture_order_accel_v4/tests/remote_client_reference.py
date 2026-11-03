"""Pure ordering/transport state; no PYNQ dependency and no cross-host clock comparison."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import threading
import uuid

from order_core import GestureGate, LABELS, OrderController

MAX_RESPONSE=128*1024


def finite_number(value,name,minimum=0,maximum=1e12):
    if isinstance(value,bool) or not isinstance(value,(int,float)):
        raise ValueError(name+' must be numeric')
    if not math.isfinite(value) or not minimum<=value<=maximum:
        raise ValueError(name+' out of range')
    return float(value)


def validate_packet(packet):
    if not isinstance(packet,dict) or type(packet.get('protocol')) is not int or packet['protocol']!=1:
        raise ValueError('Unknown board protocol')
    session=packet.get('session_id')
    if not isinstance(session,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,80}',session):
        raise ValueError('Invalid board session')
    if packet.get('status') not in ('STARTING','RUNNING','ERROR','STOPPED'):
        raise ValueError('Invalid board status')
    backend=packet.get('backend')
    if not isinstance(backend,dict) or type(backend.get('fpga_enabled')) is not bool:
        raise ValueError('Missing backend identity')
    if backend.get('labels')!=list(LABELS): raise ValueError('Wrong gesture class order')
    metrics=packet.get('metrics',{})
    if not isinstance(metrics,dict): raise ValueError('Invalid board metrics')
    for name in ('capture_hz','ai_hz','classification_hz'):
        if name in metrics: finite_number(metrics[name],name)
    if 'observation' not in packet: raise ValueError('Missing observation field')
    observation=packet.get('observation')
    if observation is None: return packet
    if not isinstance(observation,dict): raise ValueError('Invalid observation')
    seq=observation.get('seq')
    if type(seq) is not int or seq<1: raise ValueError('Invalid frame sequence')
    finite_number(observation.get('age_seconds'),'age_seconds')
    if type(observation.get('detected')) is not bool: raise ValueError('Missing hand presence')
    label=observation.get('label')
    if observation['detected'] and label not in LABELS: raise ValueError('Unknown gesture label')
    if not observation['detected'] and label is not None: raise ValueError('No-hand result contains gesture')
    finite_number(observation.get('score'),'score',maximum=1.000001)
    for name in ('detector_ms','classifier_ms'):
        finite_number(observation.get(name),name)
    if observation.get('fpga_call_ms') is not None:
        finite_number(observation['fpga_call_ms'],'fpga_call_ms')
    count=observation.get('fpga_completed_frames')
    if type(count) is not int or count<0: raise ValueError('Invalid FPGA completion counter')
    preview=observation.get('preview_jpeg')
    if preview is not None and (not isinstance(preview,str) or len(preview)>64*1024):
        raise ValueError('Preview too large')
    return packet


class OrderStore:
    def __init__(self,directory,session_id=None):
        self.directory=Path(directory); self.session_id=session_id or uuid.uuid4().hex

    def __call__(self,order):
        self.directory.mkdir(parents=True,exist_ok=True)
        record=dict(deepcopy(order),laptop_session=self.session_id,
            saved_at_utc=datetime.now(timezone.utc).isoformat())
        target=self.directory/f"order_{self.session_id}_{order['number']:03d}.json"
        temporary=target.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        temporary.replace(target)


class RemoteOrderState:
    def __init__(self,save_order=None,min_score=.60,demo=False):
        self.lock=threading.RLock()
        self.controller=OrderController(save_order=save_order)
        self.gate=GestureGate(min_score=min_score)
        self.session_id=None; self.last_seq=-1; self.last_contact=None
        self.source_time=None; self.latest=None; self.backend={}; self.board_metrics={}
        self.connected=False; self.connection_status='WAITING FOR BOARD'; self.last_error=None
        self.processed=0; self.duplicates=0; self.action_log=[]; self.demo=bool(demo)
        self.storage_error=None

    def fault(self,message='BOARD OFFLINE - REMOVE HAND'):
        with self.lock:
            self.connected=False; self.connection_status='DEMO' if self.demo else 'BOARD OFFLINE'
            self.last_error=str(message); self.gate.invalidate('BOARD OFFLINE - REMOVE HAND')

    def accept(self,packet,received_at,http_elapsed):
        packet=validate_packet(packet)
        finite_number(received_at,'received_at'); finite_number(http_elapsed,'http_elapsed',maximum=120)
        with self.lock:
            new_session=self.session_id is not None and self.session_id!=packet['session_id']
            if self.session_id!=packet['session_id']:
                self.session_id=packet['session_id']; self.last_seq=-1; self.source_time=None
                if new_session: self.gate.invalidate('BOARD RESTARTED - REMOVE HAND',reset_source=True)
            self.last_contact=received_at; self.backend=deepcopy(packet['backend'])
            self.board_metrics=deepcopy(packet.get('metrics') or {})
            observation=packet['observation']
            if packet['status']!='RUNNING' or observation is None:
                self.connected=False; self.connection_status=packet['status']
                if packet['status'] in ('ERROR','STOPPED'):
                    self.last_error=str(packet.get('error') or packet['status'])
                    self.gate.invalidate('BOARD STOPPED - REMOVE HAND')
                else:
                    self.gate.reset_candidate(); self.gate.status='WAITING FOR CAMERA'
                return False
            self.connected=True; self.last_error=None
            self.connection_status='DEMO' if self.demo else 'CONNECTED'
            # Account conservatively for the entire HTTP round trip. Never use a
            # board wall timestamp or compare its monotonic clock with ours.
            age=float(observation['age_seconds'])+http_elapsed
            if age>self.gate.max_age:
                self.connection_status='AI RESULT STALE'
                self.gate.invalidate('AI STALE - REMOVE HAND')
                return False
            if observation['seq']<=self.last_seq:
                self.duplicates+=1
                self.expire(received_at)
                return False
            self.last_seq=observation['seq']; self.source_time=received_at-age
            self.latest=deepcopy(observation); self.processed+=1
            gesture=self.gate.update(observation['label'],observation['score'],observation['detected'],
                source_time=self.source_time,now=received_at)
            if gesture is not None:
                try:
                    action=self.controller.handle(gesture,received_at)
                    self.storage_error=None
                    self.action_log.append({'seq':self.last_seq,'session_id':self.session_id,
                        'gesture':gesture,'action':action,'page':self.controller.page})
                    if len(self.action_log)>2000: self.action_log.pop(0)
                except OSError as error:
                    self.storage_error=str(error)
                    self.controller.message='SAVE FAILED - REMOVE HAND AND RETRY'
                    self.action_log.append({'seq':self.last_seq,'action':'save_failed','error':str(error)})
            return True

    def expire(self,now):
        with self.lock:
            if self.source_time is not None and now-self.source_time>self.gate.max_age:
                self.gate.invalidate('AI STALE - REMOVE HAND')
                self.connection_status='AI RESULT STALE'
            if self.last_contact is not None and now-self.last_contact>2.0:
                self.connected=False; self.connection_status='BOARD OFFLINE'
                self.gate.invalidate('BOARD OFFLINE - REMOVE HAND')

    def snapshot(self,now):
        with self.lock:
            self.expire(now)
            observation=deepcopy(self.latest)
            if observation:
                observation.pop('preview_jpeg',None)
                observation['current_age_seconds']=max(0,now-self.source_time)
            return {'state':self.controller.snapshot(),'gate':self.gate.snapshot(),
                'transport':{'connected':self.connected,'status':self.connection_status,
                    'session_id':self.session_id,'last_seq':self.last_seq,'processed_results':self.processed,
                    'duplicates_ignored':self.duplicates,'last_error':self.last_error},
                'mode':'DEMO' if self.demo else 'LIVE','backend':deepcopy(self.backend),
                'board_metrics':deepcopy(self.board_metrics),'observation':observation,
                'storage_error':self.storage_error,'actions':deepcopy(self.action_log[-30:])}
