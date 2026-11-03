"""One detector producer, one classification/FPGA owner; latest pending frame only."""
import base64
import threading
import time
from board_server import BoardRuntime


class PipelineRuntime(BoardRuntime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.latest_detection = None
        self.detection_event = threading.Event()
        self.detection_active = False
        self.detection_started = 0.
        self.detected_frame_count = 0
        self.pending_replaced_count = 0
        self.last_consumed_detection = -1
        self.overlapped_detections = 0
        self.overlapped_classifications = 0

    def detection_loop(self):
        last = -1
        try:
            while not self.stop_event.is_set():
                with self.lock:
                    seq, frame, captured = self.seq, self.frame, self.captured_at
                if frame is None or seq == last:
                    self.stop_event.wait(.003)
                    continue
                last = seq
                # Capture publishes new arrays; this snapshot belongs to this exact frame.
                owned = frame.copy()
                with self.lock:
                    self.detection_active = True
                    self.detection_started = time.monotonic()
                    self.overlapped_detections += int(self.inference_active)
                hands, detector_ms = self.backend.detect(owned)
                done = time.monotonic()
                with self.lock:
                    self.detection_active = False
                    if self.stop_event.is_set():
                        break
                    if self.latest_detection is not None:
                        self.pending_replaced_count += 1
                    self.latest_detection = (seq, captured, owned, hands, detector_ms, done)
                    self.detected_frame_count += 1
                    self.detection_event.set()
        except BaseException as error:
            self.fail('detector-stage', error)
        finally:
            with self.lock:
                self.detection_active = False
            self.detection_event.set()

    def inference_loop(self):
        try:
            while not self.stop_event.is_set():
                self.detection_event.wait(.05)
                with self.lock:
                    if self.stop_event.is_set():
                        break
                    packet = self.latest_detection
                    self.latest_detection = None
                    self.detection_event.clear()
                if packet is None:
                    continue
                seq, captured, frame, hands, detector_ms, detector_done = packet
                if self.stop_event.is_set():
                    break
                if seq <= self.last_consumed_detection:
                    raise RuntimeError('Non-monotonic detection packet')
                self.last_consumed_detection = seq
                with self.lock:
                    self.inference_active = True
                    self.inference_started = time.monotonic()
                    self.overlapped_classifications += int(self.detection_active)
                started = time.monotonic()
                result = self.backend.classify(frame, hands, detector_ms)
                with self.lock:
                    self.inference_active = False
                if self.stop_event.is_set():
                    break
                # Keep the original transport and original-frame preview semantics.
                thumbnail = self.cv.resize(frame, (160, 120), interpolation=self.cv.INTER_AREA)
                ok, data = self.cv.imencode('.jpg', thumbnail, [self.cv.IMWRITE_JPEG_QUALITY, 75])
                with self.lock:
                    completed = time.monotonic()
                    self.last_result = dict(result, seq=seq)
                    self.last_result_source = captured
                    self.preview = base64.b64encode(data.tobytes()).decode('ascii') if ok else None
                    self.inference_count += 1
                    self.classification_count += int(result['detected'])
                    self.status = 'RUNNING'
                    self.records.append(dict(result, seq=seq, source_offset=captured-self.begin,
                        completed_offset=completed-self.begin, detector_done_offset=detector_done-self.begin,
                        classification_started_offset=started-self.begin,
                        detector_to_classifier_wait_ms=(started-detector_done)*1000))
                    if len(self.records) > 2000:
                        self.records.pop(0)
        except BaseException as error:
            self.fail('classification-stage', error)
        finally:
            with self.lock:
                self.inference_active = False
                self.latest_detection = None
            # This is the only thread that runs or closes FPGA/DMA, after its call returns.
            try:
                self.backend.close()
                self.backend_closed = True
            except BaseException as error:
                self.fail('backend close', error)

    def start(self):
        if self.threads:
            raise RuntimeError('Runtime already started')
        self.begin = time.monotonic()
        self.threads = [threading.Thread(target=self.capture_loop, name='order-capture', daemon=True),
                        threading.Thread(target=self.preview_loop, name='order-preview', daemon=True),
                        threading.Thread(target=self.detection_loop, name='order-detector', daemon=True),
                        threading.Thread(target=self.inference_loop, name='order-classifier-fpga', daemon=True)]
        for thread in self.threads:
            thread.start()

    def check_health(self):
        super().check_health()
        with self.lock:
            active, started = self.detection_active, self.detection_started
        if active and time.monotonic()-started > 15:
            self.fail('watchdog', RuntimeError('Detector exceeded 15 seconds; stop and inspect logs'))

    def save_log(self, directory, reason, alive):
        path = super().save_log(directory, reason, alive)
        import json
        record = json.loads(path.read_text(encoding='utf-8'))
        record['pipeline_metrics'] = self.pipeline_metrics()
        path.write_text(json.dumps(record, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        return path

    def pipeline_metrics(self):
        with self.lock:
            return dict(detector_frames=self.detected_frame_count, pending_replaced=self.pending_replaced_count,
                        overlap_detector_starts=self.overlapped_detections,
                        overlap_classifier_starts=self.overlapped_classifications,
                        pending_slots=1, fpga_owners=1, dma_cross_frame_double_buffering=False,
                        note='CPU detector/classifier overlap; each result uses one exact source frame. '
                             'Latest pending detection replaces older pending work; FPGA calls remain serial.')
