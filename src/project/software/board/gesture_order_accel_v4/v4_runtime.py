"""Final-candidate FP32 routes; no quantization, model resize or reused detection."""
import time
from pathlib import Path
import numpy as np
from v3_runtime import Vision, OrtPalmNet, verify_models

CONFIGS = {
    'v2_reference': dict(route='baseline', cv=4, mode='serial'),
    'v3_reference': dict(route='hybrid_ort2', cv=4, mode='serial'),
    'serial_cv1_t1': dict(route='hybrid_ort1', cv=1, mode='serial'),
    'serial_cv1_t2': dict(route='hybrid_ort2', cv=1, mode='serial'),
    'serial_cv1_t3': dict(route='hybrid_ort3', cv=1, mode='serial'),
    'serial_cv1_t4': dict(route='hybrid_ort4', cv=1, mode='serial'),
    'pipe_cv1_d2_c2': dict(route='hybrid_ort2', cv=1, mode='pipeline'),
    'pipe_cv1_d1_c2': dict(route='hybrid_ort2', cv=1, mode='pipeline', detector_threads=1),
    'pipe_cv1_d2_c1': dict(route='hybrid_ort1', cv=1, mode='pipeline', detector_threads=2),
    'pipe_cv1_d3_c1': dict(route='hybrid_ort1', cv=1, mode='pipeline', detector_threads=3),
    'cpu_serial_cv1_t2': dict(route='cpu_ort2', cv=1, mode='serial'),
    'cpu_serial_cv1_t3': dict(route='cpu_ort3', cv=1, mode='serial'),
    'cpu_pipe_cv1_t2': dict(route='cpu_ort2', cv=1, mode='pipeline'),
    'cpu_pipe_cv1_d3_c1': dict(route='cpu_ort1', cv=1, mode='pipeline', detector_threads=3),
}


class StageVision(Vision):
    def __init__(self, base, root, accel, config, own_base=False):
        settings = CONFIGS[config]
        super().__init__(base, root, accel, settings['route'], own_base)
        if 'detector_threads' in settings:
            self.detector.model = OrtPalmNet(Path(root)/'gesture_assets/palm_detection_mediapipe_2023feb.onnx',
                base.detector.model.getUnconnectedOutLayersNames(), settings['detector_threads'])
        self.cv.setNumThreads(settings['cv'])
        self.meta.update(app_release='gesture_order_accel_v4', ps_config=config,
                         build_revision='r1',
                         cv_threads=settings['cv'], scheduling=settings['mode'],
                         classifier_threads=1 if settings['route']=='hybrid_ort1' else
                                            4 if settings['route']=='hybrid_ort4' else 2,
                         detector_threads=settings.get('detector_threads',
                                            1 if settings['route']=='hybrid_ort1' else
                                            4 if settings['route']=='hybrid_ort4' else 2),
                         quantized=False, detection_reused=False)
        if settings['route'] == 'baseline':
            self.meta.update(classifier_threads=4, detector_threads=4)
        else:
            count=int(settings['route'][-1])
            self.meta.update(classifier_threads=count,detector_threads=settings.get('detector_threads',count))

    def detect(self, frame):
        began = time.monotonic()
        hands = np.asarray(self.detector.infer(frame)).reshape(-1, 19)
        return hands, (time.monotonic()-began)*1000

    def classify(self, frame, hands, detector_ms):
        predictions = []
        classifier_ms = 0.
        fpga_ms = None
        if len(hands):
            began = time.monotonic()
            c = self.classifier
            predictions = c.topk(c.logits(c.preprocess(frame)), k=3)
            classifier_ms = (time.monotonic()-began)*1000
            if self.accelerator is not None:
                fpga_ms = float(self.accelerator.last_timing['total_ms'])
        return dict(detected=bool(len(hands)), detected_hands=int(len(hands)),
                    label=str(predictions[0][0]) if predictions else None,
                    score=float(predictions[0][1]) if predictions else 0.,
                    predictions=[(str(label), float(score)) for label, score in predictions],
                    detector_ms=float(detector_ms), classifier_ms=float(classifier_ms), fpga_call_ms=fpga_ms,
                    split_timing=dict(self.classifier.last_split_timing) if fpga_ms is not None else None,
                    fpga_completed_frames=int(getattr(self.classifier, 'fpga_completed_frames', 0)))

    def infer(self, frame):
        hands, elapsed = self.detect(frame)
        return self.classify(frame, hands, elapsed)


def factory(config):
    if config not in CONFIGS or config.startswith('cpu_'):
        raise ValueError('Unknown FPGA demo configuration')
    def create(root, model_dir, accel_dir, backend):
        verify_models(root)
        from board_server import VisionBackend
        base = VisionBackend(root, model_dir, accel_dir, 'fpga_v2', cv_threads=4)
        try:
            return StageVision(base, root, accel_dir, config, own_base=True)
        except BaseException:
            base.close()
            raise
    return create
