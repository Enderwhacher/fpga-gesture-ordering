"""FP32 engine alternatives. Every image is detected; FPGA ownership stays serial."""
import copy
import hashlib
import json
from pathlib import Path
import time
import numpy as np

PALM_HASH = '78ff51c38496b7fc8b8ebdb6cc8c1abb02fa6c38427c6848254cdaba57fcce7c'
PALM_CODE_HASH = 'f06ce44a9b77e12b49d72416388829fd1a481ffe7a516d914e5a8c6ca50710be'
ROUTES = ('baseline', 'palm_ort2', 'palm_ort4', 'hybrid_ort1', 'hybrid_ort2', 'hybrid_ort3', 'hybrid_ort4',
          'cpu_ort1', 'cpu_ort2', 'cpu_ort3', 'cpu_ort4', 'cpu_cv')


def session(path, threads):
    import onnxruntime as ort
    if threads not in (1, 2, 3, 4):
        raise ValueError('One to four CPU threads required')
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    options.log_severity_level = 3
    result = ort.InferenceSession(str(path), options, providers=['CPUExecutionProvider'])
    if result.get_providers() != ['CPUExecutionProvider']:
        raise RuntimeError('Unexpected execution provider')
    return result


class OrtPalmNet:
    """Keep the original detector's input, output order, anchors and NMS."""
    def __init__(self, path, output_names, threads):
        self.session = session(path, threads)
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = list(output_names)
        if set(self.output_names) != {o.name for o in self.session.get_outputs()}:
            raise RuntimeError('Palm output names differ')
        self.blob = None

    def getUnconnectedOutLayersNames(self):
        return self.output_names

    def setInput(self, value):
        self.blob = np.ascontiguousarray(value, dtype=np.float32)

    def forward(self, names=None):
        if self.blob is None:
            raise RuntimeError('Missing palm input')
        names = self.output_names if names is None else list(names)
        if names != self.output_names:
            raise RuntimeError('Palm output order changed')
        return self.session.run(names, {self.input_name: self.blob})


class OrtSplit:
    def __init__(self, accelerator, directory, threads):
        directory = Path(directory)
        self.accelerator = accelerator
        self.prefix = session(directory/'export/models/prefix.onnx', threads)
        self.suffix = session(directory/'export/models/suffix.onnx', threads)
        self.pin = self.prefix.get_inputs()[0].name
        self.sin = self.suffix.get_inputs()[0].name
        self.last_timing = None

    def forward(self, blob):
        start = time.perf_counter()
        x = np.ascontiguousarray(self.prefix.run(None, {self.pin: blob})[0], dtype=np.float32)
        prefix = time.perf_counter()
        y = self.accelerator.run(x)
        hardware = time.perf_counter()
        if y.shape != (1, 40, 28, 28) or not np.isfinite(y).all():
            raise RuntimeError('Invalid FPGA block output')
        result = self.suffix.run(None, {self.sin: y})[0].reshape(-1)
        end = time.perf_counter()
        if result.shape != (4,) or not np.isfinite(result).all():
            raise RuntimeError('Invalid classifier output')
        self.last_timing = dict(prefix_ms=(prefix-start)*1000, fpga_wall_ms=(hardware-prefix)*1000,
                                suffix_check_ms=(end-hardware)*1000, logits_total_ms=(end-start)*1000)
        return result


class Vision:
    def __init__(self, base, root, accel, route, own_base=False):
        if route not in ROUTES:
            raise ValueError('Unknown route: '+route)
        self.base = base
        self.own_base = own_base
        self.cv = base.cv
        self.accelerator = None if route.startswith('cpu_') else base.accelerator
        self.classifier = base.classifier
        self.detector = base.detector
        self.route = route
        self.meta = dict(base.meta, app_release='gesture_order_accel_v3', ps_route=route,
                         capture_process=False, fpga_enabled=self.accelerator is not None)
        self._sessions = []
        if route in ('baseline',):
            return
        threads = int(route[-1]) if route[-1] in '1234' else 4
        if route != 'cpu_cv':
            self.detector = copy.copy(base.detector)
            self.detector.model = OrtPalmNet(Path(root)/'gesture_assets/palm_detection_mediapipe_2023feb.onnx',
                                            base.detector.model.getUnconnectedOutLayersNames(), threads)
            self.meta.update(palm_engine='ONNX Runtime FP32', ort_threads=threads)
        if route.startswith('hybrid_') or route.startswith('cpu_'):
            self.classifier = copy.copy(base.classifier)
            self.classifier.fpga_completed_frames = 0
            self.classifier.last_split_timing = None
            if route.startswith('hybrid_'):
                network = OrtSplit(self.accelerator, accel, threads)
                def logits(blob):
                    result = network.forward(blob)
                    self.classifier.fpga_completed_frames += 1
                    self.classifier.last_split_timing = dict(network.last_timing)
                    return result
                self.classifier.logits = logits
                self._sessions.append(network)
                self.meta['classifier_engine'] = 'ORT prefix -> FPGA v2 blocks 5+6 -> ORT suffix'
            elif route.startswith('cpu_ort'):
                network = session(Path(root)/'gesture4_model_v2/hagrid_mobilenetv3_large.onnx', threads)
                name = network.get_inputs()[0].name
                self.classifier.logits = lambda blob: network.run(None, {name: blob})[0].reshape(-1)
                self._sessions.append(network)
            else:
                self.classifier.logits = lambda blob: self._cv_logits(blob)
            if self.accelerator is None:
                self.meta.update(name='CPU palm + CPU classifier (comparison only)', hardware_release=None,
                                 classifier_engine='ORT FP32' if route.startswith('cpu_ort') else 'OpenCV FP32')

    def _cv_logits(self, blob):
        net = self.base.classifier.net
        net.setInput(blob)
        return net.forward().reshape(-1)

    def infer(self, frame):
        from board_server import VisionBackend
        return VisionBackend.infer(self, frame)

    def close(self):
        if self.own_base:
            self.base.close()
            self.own_base = False
        self.accelerator = None


def verify_models(root):
    root = Path(root)
    for relative, expected in (
        ('gesture_assets/palm_detection_mediapipe_2023feb.onnx', PALM_HASH),
        ('gesture_assets/mp_palmdet.py', PALM_CODE_HASH),
        ('gesture4_model_v2/hagrid_mobilenetv3_large.onnx', '568660b57f4cd01cacae40d64df9124e9194c7fbcc42f8245839eb691badf741'),
        ('gesture4_model_v2/hagrid_runtime.py', '065f0ba1f30908b223d148178a22bd29c7eeaae58ff58a2b1611b529a298d24f'),
        ('gesture4_model_v2/model_meta.json', 'eb1bb16df09fb57d8a29e98b6789a482fa4e292e98a5febb6afea8e03ae6b15c'),
    ):
        if hashlib.sha256((root/relative).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Model or preprocessing differs: '+relative)


def factory(route):
    if route not in ROUTES or route.startswith('cpu_'):
        raise ValueError('The live demo must use a validated FPGA route')
    def create(root, model_dir, accel_dir, backend):
        verify_models(root)
        from board_server import VisionBackend
        base = VisionBackend(root, model_dir, accel_dir, 'fpga_v2', cv_threads=4)
        try:
            return Vision(base, root, accel_dir, route, own_base=True)
        except BaseException:
            base.close()
            raise
    return create
