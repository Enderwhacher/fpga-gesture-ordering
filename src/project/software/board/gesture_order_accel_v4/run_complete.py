"""One validated board run, selected live demo, then automatic stopped-only export."""
from pathlib import Path
import json
import time

HERE=Path(__file__).resolve().parent


def display_archive(archive,root):
    from IPython.display import HTML,display
    from urllib.parse import quote
    href='/files/'+quote(Path(archive).relative_to(Path(root)).as_posix(),safe='/')
    display(HTML('<a href="'+href+'" download>下载 gesture_order_accel_v4_results.zip</a>'))


def run(root='/home/xilinx/jupyter_notebooks',samples=12):
    from validate_v4 import run as validate,export_results
    from start_v4 import run_selected
    report=None
    live_begin=None
    stage='validation'
    status=dict(passed=False,stage=stage,board_live_test_started=False,live_order_verified=False)
    try:
        report=validate(root,samples=samples)
        status.update(validation_passed=report['passed'],selected_config=report.get('selected_config'),
            processing_25percent_vs_v2_met=report.get('processing_25percent_vs_v2_met'),
            latency_25percent_vs_v2_met=report.get('latency_25percent_vs_v2_met'),
            latency_25percent_vs_v3_met=report.get('latency_25percent_vs_v3_met'),
            throughput_25percent_vs_v3_met=report.get('throughput_25percent_vs_v3_met'))
        print('V4_GOALS:',json.dumps({key:value for key,value in status.items() if key.endswith('_met')}),flush=True)
        print('处理耗时相对第二版下降:',report.get('processing_reduction_vs_v2_percent'),'%',flush=True)
        print('每帧延迟相对第三版下降:',report.get('frame_age_reduction_vs_v3_percent'),'%',flush=True)
        print('结果间隔相对第三版下降:',report.get('output_interval_reduction_vs_v3_percent'),'%',flush=True)
        stage='live_demo';status['stage']=stage
        # start_v4 still checks all report/build/model/FPGA identities and CPU exclusions.
        live_begin=time.monotonic()
        status['live_start_requested']=True
        run_selected(report,root)
        stage='stopped';status['stage']=stage;status['passed']=True
    except KeyboardInterrupt:
        status.update(stage=stage,interrupted=True)
        print('V4_RUN_INTERRUPTED: exporting completed evidence; this does not mark an interrupted benchmark passed.',flush=True)
        raise
    except BaseException as error:
        status.update(stage=stage,error=repr(error))
        raise
    finally:
        if live_begin is not None:
            import board_server
            runtime=board_server._active_runtime
            started=runtime is not None and runtime.begin>=live_begin
            status['board_live_test_started']=started
            if started:
                status.update(live_results=runtime.inference_count,live_classifications=runtime.classification_count,
                              live_error=runtime.error,
                              workers_still_alive=[thread.name for thread in runtime.threads if thread.is_alive()])
                status['passed']=bool(status['passed'] and runtime.inference_count>0 and not runtime.error and not status['workers_still_alive'])
            else:
                status['passed']=False
        # The live server stops its compute worker before returning. Refuse to pack
        # if any worker remains; never load another overlay to work around a fault.
        (HERE/'logs').mkdir(exist_ok=True)
        (HERE/'logs/complete_run.json').write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8')
        try:
            archive=export_results()
            print('V4_RESULTS_READY:',archive,flush=True)
            display_archive(archive,root)
        except BaseException as error:
            print('V4_EXPORT_NEEDS_ATTENTION:',repr(error),flush=True)
            print('Do not reload FPGA while workers remain. Preserve the error and the results/logs directories.',flush=True)
    return report
