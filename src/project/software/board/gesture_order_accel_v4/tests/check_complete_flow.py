"""One-run control flow: success, validation failure and failed startup preserve export."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import time
import types
from unittest.mock import patch

APP=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('v4_complete_fixture',APP/'run_complete.py')
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
checks=[]
with tempfile.TemporaryDirectory(prefix='v4_complete_',dir=APP.parent/'tmp') as directory:
    runner.HERE=Path(directory)
    displayed=[]
    runner.display_archive=lambda archive,root:displayed.append(str(archive))
    report=dict(passed=True,selected_config='pipe_cv1_d3_c1',processing_25percent_vs_v2_met=True)
    board=types.SimpleNamespace(_active_runtime=None)
    def export():
        target=runner.HERE/'fixture_results.zip';target.write_bytes(b'fixture only');return target
    def live(report,root):
        board._active_runtime=types.SimpleNamespace(begin=time.monotonic(),inference_count=3,
            classification_count=2,error=None,threads=[])
    modules=dict(validate_v4=types.SimpleNamespace(run=lambda *a,**kw:dict(report),export_results=export),
                 start_v4=types.SimpleNamespace(run_selected=live),board_server=board)
    with patch.dict(sys.modules,modules):
        result=runner.run(directory)
        status=json.loads((runner.HERE/'logs/complete_run.json').read_text(encoding='utf-8'))
        assert result['passed'] and status['passed'] and status['board_live_test_started']
        assert not status['live_order_verified'] and displayed
        checks.append('validated live run exports after clean stop without claiming order verification')
        def bad(*args,**kwargs):raise RuntimeError('fixture validation error')
        modules['validate_v4'].run=bad
        try:runner.run(directory);raise AssertionError('validation error hidden')
        except RuntimeError as error:assert 'validation error' in str(error)
        status=json.loads((runner.HERE/'logs/complete_run.json').read_text(encoding='utf-8'))
        assert not status['passed'] and not status['board_live_test_started'] and len(displayed)==2
        checks.append('validation failure still exports and is not marked passed')
        modules['validate_v4'].run=lambda *a,**kw:dict(report)
        board._active_runtime=None
        modules['start_v4'].run_selected=bad
        try:runner.run(directory);raise AssertionError('startup error hidden')
        except RuntimeError:pass
        status=json.loads((runner.HERE/'logs/complete_run.json').read_text(encoding='utf-8'))
        assert not status['passed'] and not status['board_live_test_started'] and len(displayed)==3
        checks.append('startup failure cannot be misreported as a running board service')
(APP/'local_complete_flow_checks.json').write_text(json.dumps(dict(passed=True,board_tested=False,
    checks=checks,scope='Control-flow fixtures; no board, model or performance test'),indent=2)+'\n',encoding='utf-8')
print('V4_COMPLETE_FLOW_PASS',len(checks))
