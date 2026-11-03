"""Standalone two-block correctness, reload and paired CPU/FPGA timing."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import runpy
import statistics
import sys
import time
import traceback
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'board')]

def write_json(path,value):path.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n',encoding='utf-8')

def export_results():
    path=ROOT/'gesture_blocks56_board_results.zip'
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted((ROOT/'board/results').rglob('*')):
            if p.is_file():z.write(p,p.relative_to(ROOT).as_posix())
        for name in ('package_manifest.json','overlay/build_manifest.json','export/block_params.json'):
            if (ROOT/name).is_file():z.write(ROOT/name,name)
    print('DOWNLOAD:',path.name,flush=True);return path

def validate(repeats=12,thread_counts=(2,4)):
    if type(repeats) is not int or not 3<=repeats<=100:raise ValueError('repeats must be 3..100')
    if not thread_counts or any(type(v)is not int or v not in (2,4) for v in thread_counts):raise ValueError('threads must be 2 or 4')
    import numpy as np
    from environment import load_cv,exclusive_board
    folder=ROOT/'board/results'/('run_'+uuid.uuid4().hex[:10]);folder.mkdir(parents=True)
    report={'passed':False,'board_tested':False,'fpga_tested':False,'cases':[],'network_cases':[],'benchmark':{},'error':None,
        'scope':'Standalone complete features.5+6 acceleration, FP32, same-frame paired CPU/FPGA comparisons; excludes camera and UI',
        'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    def mark(stage):
        print(stage,flush=True)
        with (folder/'trace.jsonl').open('a',encoding='utf-8') as out:
            out.write(json.dumps({'stage':stage,'time_ns':time.time_ns()})+'\n');out.flush();os.fsync(out.fileno())
        write_json(folder/'report.json',report)
    def compare(actual,expected):
        if actual.shape!=expected.shape or not np.isfinite(actual).all():raise RuntimeError('Bad output shape/values')
        delta=np.abs(actual.astype(np.float64)-expected.astype(np.float64));bad=delta>1e-4+1e-4*np.abs(expected.astype(np.float64))
        check={'passed':not bool(bad.any()),'elements':int(actual.size),'max_abs_error':float(delta.max()),'bad_elements':int(bad.sum()),'atol':1e-4,'rtol':1e-4}
        if not check['passed']:raise RuntimeError('Numeric mismatch: '+json.dumps(check))
        return check
    cv=None;old_threads=None
    try:
        mark('00_verify_files_before_hardware')
        runpy.run_path(str(ROOT/'board/verify_package.py'),run_name='blocks56_verify')
        cv=load_cv();old_threads=cv.getNumThreads();cv.setNumThreads(2)
        report['environment']={'machine':platform.machine(),'python':sys.version,'opencv':cv.__version__,'opencv_path':cv.__file__,'numpy':np.__version__}
        from blocks16_driver import BlocksAccelerator
        from blocks16_runtime import SplitBlocksNetwork
        parameters=[np.fromfile(ROOT/f'export/params/block{b}.bin',dtype='<f4') for b in (0,1)]
        spec=importlib.util.spec_from_file_location('blocks56_cpu',ROOT/'source/hagrid_runtime.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        cpu=module.HagridClassifier(ROOT/'source')
        blocknet=cv.dnn.readNetFromONNX(str(ROOT/'export/models/blocks.onnx'))
        blocknet.setPreferableBackend(cv.dnn.DNN_BACKEND_OPENCV);blocknet.setPreferableTarget(cv.dnn.DNN_TARGET_CPU)
        def cpu_blocks(x):blocknet.setInput(x);return blocknet.forward()
        with exclusive_board():
            mark('10_download_blocks56_overlay_once_and_initialize_weights')
            with BlocksAccelerator(ROOT/'overlay/gesture_blocks56.bit',parameters) as accel:
                from pynq import Clocks
                report['pl0_clock_mhz']=float(Clocks.fclk0_mhz);report['hardware_loaded']=True
                expected_completed=0
                def hardware(x):
                    nonlocal expected_completed
                    result=accel.run(x);expected_completed+=1
                    if accel.completed_frames!=expected_completed:raise RuntimeError('FPGA completion counter mismatch')
                    return result
                mark('20_compare_six_full_tensors')
                for name in (ROOT/'export/case_list.txt').read_text().split():
                    case=ROOT/'export/cases'/name;x=np.load(case/'input.npy',allow_pickle=False);before=x.copy()
                    actual=hardware(x);np.save(folder/(name+'_blocks.npy'),actual,allow_pickle=False)
                    check=compare(actual,np.load(case/'golden_output.npy',allow_pickle=False))
                    if not np.array_equal(x,before):raise RuntimeError('Input modified')
                    report['cases'].append({'name':name,'check':check,'timing':dict(accel.last_timing)})
                    mark('PASS_BLOCKS '+name)
                report['fpga_tested']=report['board_tested']=True
                mark('30_verify_parameter_reload_and_restore')
                for bank in (0,1):accel.load_parameters(bank,np.zeros_like(parameters[bank]))
                x=np.load(ROOT/'export/cases/random/input.npy',allow_pickle=False)
                report['zero_parameters_identity']=compare(hardware(x),x)
                for bank in (0,1):accel.load_parameters(bank,parameters[bank])
                report['restored_parameters']=compare(hardware(x),np.load(ROOT/'export/cases/random/golden_output.npy',allow_pickle=False))
                split=SplitBlocksNetwork(hardware)
                mark('40_compare_complete_classifier_four_inputs')
                for name in ('black','gradient','seeded_noise','real_frame'):
                    case=ROOT/'export/cases'/name;blob=np.load(case/'model_input.npy',allow_pickle=False)
                    expected=np.load(case/'model_logits.npy',allow_pickle=False).reshape(-1)
                    checks={}
                    for label,method in (('cpu_full',cpu.logits),('fpga_split',split.forward)):
                        actual=method(blob);checks[label]=compare(actual,expected)
                        np.save(folder/(name+'_'+label+'_logits.npy'),actual,allow_pickle=False)
                    report['network_cases'].append({'name':name,'checks':checks})
                    mark('PASS_CLASSIFIER '+name)
                case=ROOT/'export/cases/real_frame';blob=np.load(case/'model_input.npy',allow_pickle=False)
                x=np.load(case/'input.npy',allow_pickle=False);block_expected=np.load(case/'golden_output.npy',allow_pickle=False)
                logits_expected=np.load(case/'model_logits.npy',allow_pickle=False).reshape(-1)
                for threads in thread_counts:
                    cv.setNumThreads(threads)
                    if cv.getNumThreads()!=threads:raise RuntimeError('OpenCV thread setting rejected')
                    mark('50_PAIRED_BENCHMARK_THREADS_'+str(threads))
                    group={}
                    for name,methods,target in (
                        ('blocks',{'cpu':lambda:cpu_blocks(x),'fpga':lambda:hardware(x)},block_expected),
                        ('classifier',{'cpu':lambda:cpu.logits(blob),'fpga':lambda:split.forward(blob)},logits_expected)):
                        for method in methods.values():
                            for _ in range(3):compare(method(),target)
                        samples={'cpu':[],'fpga':[]};hardware_times=[];split_times=[]
                        for i in range(repeats):
                            for key in (('cpu','fpga') if i%2==0 else ('fpga','cpu')):
                                started=time.perf_counter();actual=methods[key]();elapsed=(time.perf_counter()-started)*1000
                                compare(actual,target);samples[key].append(elapsed)
                                if key=='fpga':
                                    hardware_times.append(dict(accel.last_timing))
                                    if name=='classifier':split_times.append(dict(split.last_timing))
                            print('THREADS',threads,name,'ROUND',i+1,'/',repeats,flush=True)
                        medians={k:statistics.median(v) for k,v in samples.items()}
                        ratios=[c/f for c,f in zip(samples['cpu'],samples['fpga'])]
                        group[name]={'samples_ms':samples,'median_ms':medians,'speedup_ratio_of_medians':medians['cpu']/medians['fpga'],
                            'paired_speedup_ratios':ratios,'median_paired_speedup':statistics.median(ratios),
                            'fpga_faster_pairs':sum(f<c for c,f in zip(samples['cpu'],samples['fpga'])),'pairs':repeats,
                            'hardware_call_timings':hardware_times,'split_timings':split_times}
                    report['benchmark'][str(threads)]=group
                    mark('PASS_BENCHMARK_THREADS_'+str(threads))
                report['benchmark_input']='Same real captured frame saved before this test, preprocessed blob; no live acquisition'
                report['fpga_completed_frames']=accel.completed_frames
                signature=accel.ping();report['hardware_signature_after_test']=hex(signature)
                if signature!=0xA5010300:raise RuntimeError('Resident parameter flags changed unexpectedly')
                report['passed']=True;mark('BLOCKS56_HARDWARE_VALIDATION_OK')
                print(json.dumps({k:{n:v['median_ms'] for n,v in g.items()} for k,g in report['benchmark'].items()},indent=2),flush=True)
    except BaseException as error:
        report['passed']=False;report['error']={'message':repr(error),'traceback':traceback.format_exc()};mark('ERROR');raise
    finally:
        if cv is not None and old_threads is not None:cv.setNumThreads(old_threads)
        write_json(folder/'report.json',report);export_results()
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--repeats',type=int,default=12);parser.add_argument('--export-only',action='store_true')
    args=parser.parse_args()
    return export_results() if args.export_only else validate(args.repeats)
if __name__=='__main__':main()
