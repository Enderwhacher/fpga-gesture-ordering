"""Replace complete features.5+features.6 with one PL command per inference."""
import hashlib
import importlib.util
import json
from pathlib import Path
import runpy
import time

import cv2
import numpy as np

ROOT=Path(__file__).resolve().parent


class SplitBlocksNetwork:
    def __init__(self,compute,directory=ROOT):
        directory=Path(directory)
        info=json.loads((directory/'export/export_manifest.json').read_text(encoding='utf-8'))
        for name,expected in info['sha256'].items():
            if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=expected: raise RuntimeError('Export file changed: '+name)
        self.meta=json.loads((directory/'export/block_params.json').read_text(encoding='utf-8'))
        self.prefix=cv2.dnn.readNetFromONNX(str(directory/'export/models/prefix.onnx'))
        self.suffix=cv2.dnn.readNetFromONNX(str(directory/'export/models/suffix.onnx'))
        for net in (self.prefix,self.suffix):
            net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV); net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.compute=compute; self.last_timing=None

    def forward(self,blob):
        self.last_timing=None; started=time.perf_counter()
        self.prefix.setInput(blob); x=np.ascontiguousarray(self.prefix.forward(),dtype=np.float32)
        prefix=time.perf_counter(); y=self.compute(x); hardware=time.perf_counter()
        if y.shape!=(1,40,28,28) or y.dtype!=np.float32 or not np.isfinite(y).all(): raise RuntimeError('Invalid two-block output')
        self.suffix.setInput(y,self.meta['output_tensor']); result=self.suffix.forward().reshape(-1)
        if result.shape!=(4,) or not np.isfinite(result).all(): raise RuntimeError('Invalid classifier logits')
        end=time.perf_counter()
        self.last_timing={'prefix_ms':(prefix-started)*1000,'fpga_wall_ms':(hardware-prefix)*1000,
                          'suffix_check_ms':(end-hardware)*1000,'logits_total_ms':(end-started)*1000}
        return result


def make_fpga_classifier(directory=ROOT):
    directory=Path(directory).resolve()
    runpy.run_path(str(directory/'board/verify_package.py'),run_name='blocks56_verify')
    spec=importlib.util.spec_from_file_location('blocks16_cpu_model',directory/'source/hagrid_runtime.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    classifier=module.HagridClassifier(directory/'source')
    from blocks16_driver import BlocksAccelerator
    parameters=[np.fromfile(directory/f'export/params/block{bank}.bin',dtype='<f4') for bank in (0,1)]
    accelerator=BlocksAccelerator(directory/'overlay/gesture_blocks56.bit',parameters)
    try:
        network=SplitBlocksNetwork(accelerator.run,directory)
        if network.meta['source_model_sha256']!=classifier.meta['model_sha256']: raise RuntimeError('Split model SHA differs')
        classifier.fpga_completed_frames=0; classifier.last_split_timing=None; classifier.last_fpga_timing=None
        def logits(blob):
            classifier.last_split_timing=None; classifier.last_fpga_timing=None
            result=network.forward(blob)
            classifier.fpga_completed_frames+=1
            classifier.last_split_timing=dict(network.last_timing)
            classifier.last_fpga_timing=dict(accelerator.last_timing)
            return result
        classifier.logits=logits; classifier.close=accelerator.close
        classifier.acceleration_backend='CPU prefix -> FPGA PW16 complete features.5+6 -> CPU suffix; FP32 resident coefficients'
        return classifier,accelerator
    except BaseException:
        accelerator.close(); raise
