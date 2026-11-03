"""Independent numerical, latency and output-interval measurements; real background camera."""
import gc
import hashlib
import json
from pathlib import Path
import platform
import statistics
import threading
import time
import traceback
import types
import uuid
import zipfile
import numpy as np

HERE = Path(__file__).resolve().parent


def compare(actual, expected, atol=1e-4, rtol=1e-4):
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape or not np.isfinite(actual).all() or not np.isfinite(expected).all():
        raise RuntimeError('Numeric shape/finite mismatch')
    delta = np.abs(actual.astype(np.float64)-expected.astype(np.float64))
    if np.any(delta > atol+rtol*np.abs(expected)):
        raise RuntimeError('Numeric mismatch: '+str(float(delta.max())))
    return float(delta.max()) if delta.size else 0.


def compare_hands(actual, expected):
    actual, expected = np.asarray(actual), np.asarray(expected)
    if actual.shape != expected.shape:
        raise RuntimeError('Palm detection count changed')
    if not actual.size:
        return 0.
    error = compare(actual[:, :18], expected[:, :18], atol=.02, rtol=0.)
    compare(actual[:, 18], expected[:, 18], atol=1e-5, rtol=0.)
    return error


def system_snapshot():
    import glob
    result = {}
    for pattern in ('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq',
                    '/sys/class/thermal/thermal_zone*/temp'):
        for name in glob.glob(pattern):
            try:
                result[name] = int(Path(name).read_text().strip())
            except (ValueError, OSError):
                pass
    return result


class Background:
    def __init__(self, cv):
        from board_server import BoardRuntime
        self.runtime = BoardRuntime(types.SimpleNamespace(meta={'name': 'Benchmark background'}), cv)

    def start(self):
        r = self.runtime
        r.begin = time.monotonic()
        r.threads = [threading.Thread(target=r.capture_loop, daemon=True),
                     threading.Thread(target=r.preview_loop, daemon=True)]
        for thread in r.threads:
            thread.start()
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            if r.error or r.preview_stream_error:
                raise RuntimeError(r.error or r.preview_stream_error)
            if r.capture_count >= 3 and r.preview_encoded_count >= 2:
                return
            time.sleep(.03)
        raise RuntimeError('Camera startup timeout')

    def snapshot(self):
        r = self.runtime
        with r.lock:
            return dict(capture=r.capture_count, preview=r.preview_encoded_count,
                        error=r.error or r.preview_stream_error)

    def stop(self):
        r = self.runtime
        r.stop_event.set()
        for thread in r.threads:
            thread.join(timeout=5)
        status = self.snapshot()
        status['workers_still_alive'] = [t.name for t in r.threads if t.is_alive()]
        return status


def numeric_checks(base, root, accel, config):
    from v4_runtime import StageVision
    vision = StageVision(base, root, accel, config)
    rows = []
    frames = [(p.name, base.cv.imread(str(p))) for p in sorted((HERE/'samples').glob('*.png'))]
    frames += [('black', np.zeros((480, 640, 3), np.uint8)),
               ('gray', np.full((480, 640, 3), 127, np.uint8)),
               ('noise', np.random.default_rng(20261101).integers(0, 256, (480, 640, 3), dtype=np.uint8))]
    for image_index, (name, frame) in enumerate(frames):
        if frame is None:
            raise RuntimeError('Invalid sample: '+name)
        raw_input, _ = base.detector._preprocess(frame)
        names = base.detector.model.getUnconnectedOutLayersNames()
        base.detector.model.setInput(raw_input)
        raw = base.detector.model.forward(names)
        vision.detector.model.setInput(raw_input)
        outputs = vision.detector.model.forward(names)
        raw_error = max(compare(a, b, atol=1e-3, rtol=1e-4) for a, b in zip(outputs, raw))
        hand_error = compare_hands(vision.detector.infer(frame), base.detector.infer(frame))
        blob = base.classifier.preprocess(frame)
        base.classifier.net.setInput(blob)
        expected = base.classifier.net.forward().reshape(-1)
        actual = vision.classifier.logits(blob)
        logit_error = compare(actual, expected)
        if int(actual.argmax()) != int(expected.argmax()):
            raise RuntimeError('Class changed: '+name+' '+config)
        def softmax(value):
            result = np.exp(value-value.max())
            return result/result.sum()
        compare(softmax(actual), softmax(expected))
        rows.append(dict(config=config, image=name, raw_max_abs=raw_error,
                         coordinates_max_abs=hand_error, logits_max_abs=logit_error))
        if (image_index+1)%10==0 or image_index+1==len(frames):
            print(' ',config,'numeric images',image_index+1,'/',len(frames),flush=True)
    # Do not close the borrowed accelerator. Release the engine sessions only.
    return rows


def fixed_source(runtime, frame):
    while not runtime.stop_event.is_set():
        with runtime.lock:
            runtime.seq += 1
            runtime.frame = frame
            runtime.captured_at = time.monotonic()
            runtime.camera_stage = 'FIXED_INPUT_SOURCE'
            runtime.capture_count += 1
        runtime.stop_event.wait(1/30)


def benchmark_block(base, root, accel, config, fixed, expected_predictions, samples=12):
    from board_server import BoardRuntime
    from pipeline_runtime import PipelineRuntime
    from v4_runtime import StageVision, CONFIGS
    vision = StageVision(base, root, accel, config)
    runtime = (PipelineRuntime if CONFIGS[config]['mode']=='pipeline' else BoardRuntime)(vision, vision.cv)
    background = Background(vision.cv)
    block = dict(config=config, system_before=system_snapshot(), records=[])
    try:
        background.start()
        runtime.begin = time.monotonic()
        runtime.threads = [threading.Thread(target=fixed_source, args=(runtime, fixed), daemon=True,
                                             name='benchmark-fixed-source')]
        if isinstance(runtime, PipelineRuntime):
            runtime.threads.append(threading.Thread(target=runtime.detection_loop, daemon=True,
                                                    name='benchmark-detector'))
        runtime.threads.append(threading.Thread(target=runtime.inference_loop, daemon=True,
                                                name='benchmark-classifier-fpga'))
        for thread in runtime.threads:
            thread.start()
        deadline = time.monotonic()+120
        before = began = None
        last_count = -1
        while time.monotonic() < deadline:
            runtime.check_health()
            if runtime.error:
                raise RuntimeError(runtime.error)
            with runtime.lock:
                count = len(runtime.records)
            if count >= 2 and before is None:
                before = background.snapshot()
                began = time.perf_counter()
            if count != last_count:
                print(' ', config, 'results', count, '/', samples+2, flush=True)
                last_count = count
            if count >= samples+2:
                break
            time.sleep(.02)
        else:
            raise RuntimeError('Benchmark timed out: '+config)
        duration = time.perf_counter()-began
        after = background.snapshot()
        block.update(capture_hz=(after['capture']-before['capture'])/duration,
                     preview_hz=(after['preview']-before['preview'])/duration)
        with runtime.lock:
            all_rows = list(runtime.records)
        selected = all_rows[2:samples+2]
        previous = all_rows[1]
        for row in selected:
            if not row['detected'] or row['label'] != expected_predictions[0][0]:
                raise RuntimeError('Same-frame decision changed')
            compare([p for _, p in row['predictions']], [p for _, p in expected_predictions])
            if row['seq'] <= previous['seq'] or row['source_offset'] <= previous['source_offset']:
                raise RuntimeError('Reused or out-of-order input')
            if vision.accelerator is not None and row['fpga_completed_frames'] != previous['fpga_completed_frames']+1:
                raise RuntimeError('FPGA completion missing')
            row = dict(row, result_interval_ms=(row['completed_offset']-previous['completed_offset'])*1000,
                       frame_age_ms=(row['completed_offset']-row['source_offset'])*1000)
            block['records'].append(row)
            previous = row
        if isinstance(runtime, PipelineRuntime):
            block['pipeline_metrics'] = runtime.pipeline_metrics()
        block['system_after'] = system_snapshot()
    finally:
        # Stop/join both computation owners before any next configuration changes
        # OpenCV's process-global thread count or reloads model sessions.
        alive = runtime.stop()
        block['inference_workers_still_alive'] = alive
        status = background.stop()
        block['camera_cleanup'] = status
        if not runtime.threads:
            vision.close()
        if alive or status['workers_still_alive'] or status['error']:
            raise RuntimeError('Workers did not stop cleanly: '+str(block))
    return block


def summarize(blocks):
    from v4_runtime import CONFIGS
    summary = {}
    for config in CONFIGS:
        selected = [b for b in blocks if b['config']==config]
        if len(selected) != 2:
            raise RuntimeError('Incomplete balanced comparison')
        rows = [r for b in selected for r in b['records']]
        summary[config] = {key: statistics.median(r[key] for r in rows)
                           for key in ('frame_age_ms', 'result_interval_ms', 'detector_ms', 'classifier_ms')}
        summary[config].update(frame_age_p95_ms=float(np.percentile([r['frame_age_ms'] for r in rows],95)),
            detector_plus_classifier_ms=statistics.median(r['detector_ms']+r['classifier_ms'] for r in rows),
            results=len(rows), background_ok=all(b['capture_hz']>=10 and b['preview_hz']>=8 for b in selected),
            rounds=[{key: statistics.median(r[key] for r in b['records'])
                     for key in ('frame_age_ms','result_interval_ms')} for b in selected])
    return summary


def choose(summary):
    reference = summary['v3_reference']
    if not reference['background_ok']:
        return None
    candidates = []
    for name, row in summary.items():
        if name.startswith('cpu_') or name in ('v2_reference','v3_reference') or not row['background_ok']:
            continue
        age_ok = row['frame_age_ms'] <= reference['frame_age_ms']*1.05
        tail_ok = row['frame_age_p95_ms'] <= reference['frame_age_p95_ms']*1.10
        gain = row['frame_age_ms'] <= reference['frame_age_ms']*.95 or row['result_interval_ms'] <= reference['result_interval_ms']*.85
        consistent = all(new['frame_age_ms'] <= old['frame_age_ms']*1.05 and
                         (new['frame_age_ms'] <= old['frame_age_ms']*.95 or
                          new['result_interval_ms'] <= old['result_interval_ms']*.85)
                         for new, old in zip(row['rounds'], reference['rounds']))
        if age_ok and tail_ok and gain and consistent:
            candidates.append(name)
    if not candidates:
        return 'v3_reference'
    # Prefer candidates that actually meet the latency/processing goal. A pipeline
    # with a shorter result interval must not displace a candidate that meets the
    # promised 25% processing target merely by publishing more often.
    v2=summary.get('v2_reference')
    if v2 is not None:
        def priority(name):
            row=summary[name]
            latency=row['frame_age_ms']<=v2['frame_age_ms']*.75
            processing=(row.get('detector_plus_classifier_ms') is not None and
                        v2.get('detector_plus_classifier_ms') is not None and
                        row['detector_plus_classifier_ms']<=v2['detector_plus_classifier_ms']*.75)
            return 0 if latency and processing else 1 if latency else 2 if processing else 3
        best_priority=min(priority(name) for name in candidates)
        candidates=[name for name in candidates if priority(name)==best_priority]
    best_age = min(summary[name]['frame_age_ms'] for name in candidates)
    near = [name for name in candidates if summary[name]['frame_age_ms'] <= best_age*1.05]
    return min(near, key=lambda name: summary[name]['result_interval_ms'])


def run(root='/home/xilinx/jupyter_notebooks', samples=12):
    if platform.system() != 'Linux' or platform.machine().lower() not in ('aarch64','arm64'):
        raise RuntimeError('Run on PYNQ-ZU')
    if samples < 12:
        raise ValueError('Use at least 12 results per balanced round')
    from start_v4 import preflight
    versions = preflight(root)
    root = Path(root)
    folder = HERE/'results'/('v4_'+uuid.uuid4().hex[:12])
    folder.mkdir(parents=True)
    report = dict(passed=False, board_tested=True, error=None, cleanup_errors=[], kernel_restart_required=False,
        numeric_checks=[], blocks=[], versions=versions,
        scope='Same FP32 model and fixed image. Real capture+preview background. '
              'Separate source-to-result frame age and result interval; no HTTP/UI/gesture hold time. '
              'V2/V3 serial controls plus matched ORT CPU controls. No quantization or new PL bitstream.')
    base = cv = None
    previous_threads = None
    caught = None
    def save():
        (folder/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    from session_guard import exclusive_board_test
    with exclusive_board_test():
        try:
            from board_server import VisionBackend, load_cv
            from v4_runtime import CONFIGS
            cv = load_cv(root)
            previous_threads = cv.getNumThreads()
            accel = root/'gesture_block_accel_v2'
            base = VisionBackend(root,root/'gesture4_model_v2',accel,'fpga_v2',cv_threads=4)
            report.update(package_manifest_sha256=hashlib.sha256((HERE/'manifest.json').read_bytes()).hexdigest(),
                          bit_sha256=hashlib.sha256((accel/'overlay/gesture_blocks56.bit').read_bytes()).hexdigest(),
                          model_sha256=base.meta['model_sha256'])
            for config in CONFIGS:
                print('NUMERIC:',config,flush=True)
                report['numeric_checks'].extend(numeric_checks(base,root,accel,config))
                gc.collect()
                save()
            fixed = cv.imread(str(HERE/'samples/fixed_hand.png'))
            blob = base.classifier.preprocess(fixed)
            base.classifier.net.setInput(blob)
            expected = base.classifier.topk(base.classifier.net.forward().reshape(-1),3)
            report['fixed_frame_sha256'] = hashlib.sha256(fixed.tobytes()).hexdigest()
            order = list(CONFIGS)
            for index, config in enumerate(order+list(reversed(order))):
                print('BENCHMARK',index+1,'/',len(order)*2,config,flush=True)
                block = benchmark_block(base,root,accel,config,fixed,expected,samples)
                block['index'] = index+1
                report['blocks'].append(block)
                gc.collect()
                save()
            summary = summarize(report['blocks'])
            chosen = choose(summary)
            report.update(summary=summary,selected_config=chosen)
            if chosen is not None:
                new, v2, v3 = summary[chosen], summary['v2_reference'], summary['v3_reference']
                report.update(frame_age_reduction_vs_v2_percent=100*(1-new['frame_age_ms']/v2['frame_age_ms']),
                    frame_age_reduction_vs_v3_percent=100*(1-new['frame_age_ms']/v3['frame_age_ms']),
                    output_interval_reduction_vs_v3_percent=100*(1-new['result_interval_ms']/v3['result_interval_ms']),
                    latency_25percent_vs_v2_met=new['frame_age_ms']<=v2['frame_age_ms']*.75,
                    latency_25percent_vs_v3_met=new['frame_age_ms']<=v3['frame_age_ms']*.75,
                    throughput_25percent_vs_v3_met=new['result_interval_ms']<=v3['result_interval_ms']/1.25)
                report.update(processing_reduction_vs_v2_percent=100*(1-new['detector_plus_classifier_ms']/v2['detector_plus_classifier_ms']),
                    processing_reduction_vs_v3_percent=100*(1-new['detector_plus_classifier_ms']/v3['detector_plus_classifier_ms']),
                    processing_25percent_vs_v2_met=new['detector_plus_classifier_ms']<=v2['detector_plus_classifier_ms']*.75)
                best_cpu = min((name for name in summary if name.startswith('cpu_') and summary[name]['background_ok']),
                               key=lambda name: summary[name]['result_interval_ms'],default=None)
                report['fastest_cpu_config'] = best_cpu
                report['fpga_vs_cpu_interval_speedup'] = summary[best_cpu]['result_interval_ms']/new['result_interval_ms'] if best_cpu else None
            report['passed'] = True
        except BaseException as error:
            caught = error
            report['error'] = dict(message=repr(error),traceback=traceback.format_exc())
            if 'stop cleanly' in str(error):
                report['kernel_restart_required'] = True
        finally:
            if base is not None:
                try:
                    base.close()
                except BaseException as error:
                    report['cleanup_errors'].append(repr(error))
                    report['kernel_restart_required'] = True
            if cv is not None and previous_threads is not None and not report['kernel_restart_required']:
                cv.setNumThreads(previous_threads)
            gc.collect()
            report['passed'] = bool(report['passed'] and not report['cleanup_errors'] and report['error'] is None)
            save()
            print('V4_VALIDATION_OK' if report['passed'] else 'V4_VALIDATION_FAILED',flush=True)
    if caught is not None:
        raise caught
    print(json.dumps(report.get('summary',{}),indent=2),flush=True)
    print('SELECTED FPGA CONFIG:',report.get('selected_config'),flush=True)
    return report


def export_results():
    import board_server
    runtime = board_server._active_runtime
    if runtime is not None and any(t.is_alive() for t in runtime.threads):
        raise RuntimeError('Stop server before exporting')
    target = HERE/'gesture_order_accel_v4_results.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for directory in ('results','logs'):
            for path in sorted((HERE/directory).rglob('*')):
                if path.is_file():
                    archive.write(path,path.relative_to(HERE).as_posix())
        for path in sorted(HERE.glob('*.py')):
            archive.write(path,'source/'+path.name)
        for name in ('manifest.json','00_final_candidate_v4.ipynb'):
            archive.write(HERE/name,'source/'+name)
    return target
