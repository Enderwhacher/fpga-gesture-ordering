"""Explicit validated startup; only FPGA routes can become the final demo."""
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
BIT_SHA = 'a7732997d677c89e16f6981625c796d4d9e5e34fe235dfbbb95328f03b91f89a'
HWH_SHA = '8ed7017eb013a49bdb08b0150f4c625106dada999220d38ae8dd64c7d8e3be3f'


def preflight(root='/home/xilinx/jupyter_notebooks'):
    from setup_runtime import prepare
    versions = prepare(root)
    from v3_runtime import verify_models
    verify_models(root)
    root = Path(root)
    accel = root/'gesture_block_accel_v2'
    for name, expected in (('gesture_blocks56.bit',BIT_SHA),('gesture_blocks56.hwh',HWH_SHA)):
        if hashlib.sha256((accel/'overlay'/name).read_bytes()).hexdigest()!=expected:
            raise RuntimeError('Expected verified FPGA v2 '+name)
    runpy.run_path(str(accel/'board/verify_package.py'),run_name='v4_verify_pl')
    from board_server import check_camera_unused
    from session_guard import exclusive_board_test
    with exclusive_board_test():
        check_camera_unused('/dev/video0')
    print('V4_PREFLIGHT_OK | no bitstream downloaded',flush=True)
    return versions


def run_selected(report,root='/home/xilinx/jupyter_notebooks'):
    if not isinstance(report,dict) or not report.get('passed') or report.get('kernel_restart_required'):
        raise RuntimeError('Complete numeric/benchmark validation first')
    config = report.get('selected_config')
    from v4_runtime import CONFIGS, factory
    if config not in CONFIGS or config.startswith('cpu_'):
        raise RuntimeError('No accepted FPGA route. Export logs; keep V3.')
    if report.get('package_manifest_sha256')!=hashlib.sha256((HERE/'manifest.json').read_bytes()).hexdigest():
        raise RuntimeError('Benchmark came from another app build')
    if report.get('bit_sha256')!=BIT_SHA:
        raise RuntimeError('Benchmark bitstream differs')
    preflight(root)
    print('V4 FINAL CANDIDATE:',config,'| real FPGA v2 |',CONFIGS[config]['mode'],flush=True)
    if config=='v3_reference':
        print('No robust gain accepted: explicitly retaining V3 scheduling in the isolated V4 app.',flush=True)
    (HERE/'logs').mkdir(exist_ok=True)
    (HERE/'logs/selection.json').write_text(json.dumps({key:report.get(key) for key in (
        'selected_config','frame_age_reduction_vs_v2_percent','frame_age_reduction_vs_v3_percent',
        'output_interval_reduction_vs_v3_percent','latency_25percent_vs_v2_met',
        'processing_reduction_vs_v2_percent','processing_reduction_vs_v3_percent','processing_25percent_vs_v2_met',
        'latency_25percent_vs_v3_met','throughput_25percent_vs_v3_met','fastest_cpu_config',
        'fpga_vs_cpu_interval_speedup','package_manifest_sha256')},indent=2)+'\n',encoding='utf-8')
    from board_server import run_board_server, BoardRuntime
    from pipeline_runtime import PipelineRuntime
    root = Path(root)
    return run_board_server(root=root,accel_dir=root/'gesture_block_accel_v2',backend='fpga_v2',
        camera_device='/dev/video0',rotate_180=False,mirror=False,vision_factory=factory(config),
        runtime_factory=PipelineRuntime if CONFIGS[config]['mode']=='pipeline' else BoardRuntime)


def load_last_report():
    reports=sorted((HERE/'results').glob('v4_*/report.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    if not reports:
        raise RuntimeError('No V4 report; run validation first')
    report=json.loads(reports[0].read_text(encoding='utf-8'))
    if not report.get('passed'):
        raise RuntimeError('Latest run did not pass. Export logs before restarting.')
    print('Using saved V4 validation:',reports[0],flush=True)
    return report
