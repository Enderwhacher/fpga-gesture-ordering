"""Real-model numeric checks with CPU formula substitute for PL; no board speed claim."""
from pathlib import Path
import ast
import importlib.util
import json
import sys
import time
import types

APP=Path(__file__).resolve().parents[1]
ROOT=APP.parent
sys.path.insert(0,str(APP))
import cv2 as cv
import numpy as np
from v4_runtime import CONFIGS, StageVision
from validate_v4 import numeric_checks, compare


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


class ReferenceAccelerator:
    def __init__(self,path):
        self.net=cv.dnn.readNetFromONNX(str(path));self.last_timing=None
    def run(self,value):
        began=time.perf_counter();self.net.setInput(value);result=self.net.forward()
        self.last_timing={'total_ms':(time.perf_counter()-began)*1000}
        return result


def make_base():
    model=ROOT/'gesture_block_accel_v2';root=ROOT/'tmp/v3_local_root'
    palm=load(APP/'tests/mp_palmdet_reference.py','local_palm_reference')
    hagrid=load(model/'source/hagrid_runtime.py','local_hagrid_reference')
    classifier=hagrid.HagridClassifier(model/'source')
    accelerator=ReferenceAccelerator(model/'export/models/blocks.onnx')
    prefix=cv.dnn.readNetFromONNX(str(model/'export/models/prefix.onnx'))
    suffix=cv.dnn.readNetFromONNX(str(model/'export/models/suffix.onnx'))
    meta=json.loads((model/'export/block_params.json').read_text(encoding='utf-8'))
    classifier.fpga_completed_frames=0;classifier.last_split_timing={}
    def logits(blob):
        prefix.setInput(blob);value=accelerator.run(prefix.forward())
        suffix.setInput(value,meta['output_tensor']);result=suffix.forward().reshape(-1)
        classifier.fpga_completed_frames+=1
        return result
    classifier.logits=logits
    base=types.SimpleNamespace(cv=cv,classifier=classifier,accelerator=accelerator,
        detector=palm.MPPalmDet(str(root/'gesture_assets/palm_detection_mediapipe_2023feb.onnx'),scoreThreshold=.6),
        meta={'name':'PL formula substitute','model_sha256':classifier.meta['model_sha256']})
    return base,root,model


if __name__=='__main__':
    import gc,onnxruntime as ort
    base,root,model=make_base();rows=[]
    for config in CONFIGS:
        print('Checking real models',config,flush=True)
        rows.extend(numeric_checks(base,root,model,config))
        vision=StageVision(base,root,model,config)
        result=vision.infer(cv.imread(str(APP/'samples/fixed_hand.png')))
        assert result['detected']
        assert (result['fpga_call_ms'] is not None)==(not config.startswith('cpu_'))
        del vision;gc.collect()
    def definitions(path):
        return {node.name:ast.dump(node) for node in ast.parse(path.read_text(encoding='utf-8')).body
                if isinstance(node,(ast.FunctionDef,ast.ClassDef))}
    original=definitions(ROOT/'gesture_order_accel_v3/board_server.py')
    current=definitions(APP/'board_server.py')
    for key in ('BoardRuntime','make_handler','VisionBackend','check_camera_unused'):
        assert original[key]==current[key],key
    assert (APP/'order_core.py').read_bytes()==(ROOT/'gesture_order_accel_v3/order_core.py').read_bytes()
    report=dict(passed=True,board_tested=False,onnxruntime=ort.__version__,comparisons=len(rows),
        scope='Windows real FP32-model comparisons; CPU block formula in place of FPGA; no ARM performance claim.',
        preserved_original_protocol_gate_and_serial_runtime=True,checks=rows)
    (APP/'local_model_checks.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('V4_REAL_MODEL_CHECKS_PASS',len(rows),'maxlogit',max(row['logits_max_abs'] for row in rows))
