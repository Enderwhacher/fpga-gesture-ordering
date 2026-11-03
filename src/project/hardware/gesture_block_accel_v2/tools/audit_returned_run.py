"""Independently audit saved board arrays and paired benchmark statistics."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import statistics
import sys
import zipfile
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent
archive=Path('E:/gesture_blocks56_board_results.zip');sha=hashlib.sha256(archive.read_bytes()).hexdigest()
snapshot=WS/'board_returns'/('blocks56_'+sha[:12]);snapshot.mkdir(parents=True,exist_ok=True)
shutil.copyfile(archive,snapshot/'returned_results.zip')
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    names=[n for n in z.namelist() if n.endswith('/report.json')];assert len(names)==1
    name=names[0];folder=name.rsplit('/',1)[0];report=json.loads(z.read(name))
    assert report['passed'] and report['fpga_tested'] and report['board_tested'] and report['error'] is None
    assert report['script_sha256']==hashlib.sha256((ROOT/'board/validate_hardware.py').read_bytes()).hexdigest()
    for n in ('package_manifest.json','overlay/build_manifest.json','export/block_params.json'):
        assert z.read(n)==(ROOT/n).read_bytes(),n
    assert report['fpga_completed_frames']==72 and report['hardware_signature_after_test']=='0xa5010300'
    assert len(report['cases'])==6 and len(report['network_cases'])==4
    assert report['zero_parameters_identity']['passed'] and report['restored_parameters']['passed']
    checks=[]
    def compare(filename,reference):
        actual=np.load(io.BytesIO(z.read(folder+'/'+filename)),allow_pickle=False)
        expected=np.load(reference,allow_pickle=False)
        if filename.endswith('_logits.npy'):expected=expected.reshape(-1)
        assert actual.shape==expected.shape and np.isfinite(actual).all()
        error=np.abs(actual.astype(np.float64)-expected.astype(np.float64))
        bad=error>1e-4+1e-4*np.abs(expected.astype(np.float64));assert not bad.any(),filename
        checks.append({'file':filename,'elements':int(actual.size),'max_abs_error':float(error.max()),'passed':True})
    for case in report['cases']:
        compare(case['name']+'_blocks.npy',ROOT/'export/cases'/case['name']/'golden_output.npy')
    for case in report['network_cases']:
        for backend in ('cpu_full','fpga_split'):
            compare(case['name']+'_'+backend+'_logits.npy',ROOT/'export/cases'/case['name']/'model_logits.npy')
    benchmarks={}
    for threads,groups in report['benchmark'].items():
        benchmarks[threads]={}
        for group,data in groups.items():
            cpu=data['samples_ms']['cpu'];fpga=data['samples_ms']['fpga'];assert len(cpu)==len(fpga)==12
            assert all(np.isfinite(v) and v>0 for v in cpu+fpga)
            c,f=statistics.median(cpu),statistics.median(fpga)
            assert abs(c-data['median_ms']['cpu'])<1e-8 and abs(f-data['median_ms']['fpga'])<1e-8
            wins=sum(b<a for a,b in zip(cpu,fpga));assert wins==data['fpga_faster_pairs']
            benchmarks[threads][group]={'cpu_median_ms':c,'fpga_median_ms':f,'ratio_of_medians':c/f,
                'latency_reduction_percent':100*(c-f)/c,'fpga_faster_pairs':wins,'pairs':12}
    result={'passed':True,'board_tested':True,'archive_sha256':sha,'run':folder,
        'verified_saved_arrays':checks,'verified_saved_array_count':len(checks),'fpga_completed_frames':72,
        'parameter_reload_and_restore_passed':True,'benchmark':benchmarks,
        'scope':'One returned standalone board run, fixed saved real-frame input. Excludes live camera, palm detection, ordering UI and long-duration stability.',
        'conclusion':'Two-block offload correctness confirmed. Local block speedup clear at both thread counts; full classifier benefit clear at 2 threads, small and order-sensitive at 4 threads (6/12 wins). Real ordering integration still required.'}
    out=WS/'output/gesture_blocks56_board_review.json';out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    text='''# 两个残差块 FPGA 加速：板测复核

本次独立加速器板测通过。复核了 14 个保存的输出数组，六组残差块输出和四组 CPU/FPGA 完整分类输出均与本地黄金数据一致；参数清零与恢复通过。记录了 72 次 FPGA 完成事件。

| OpenCV线程数 | 比较范围 | CPU中位耗时(ms) | FPGA路径中位耗时(ms) | 中位数之比 | FPGA更快轮次 |
|---|---|---:|---:|---:|---:|
'''
    for t,g in benchmarks.items():
        for label,b in g.items():text+=f"| {t} | {'两个残差块' if label=='blocks' else '完整分类器'} | {b['cpu_median_ms']:.3f} | {b['fpga_median_ms']:.3f} | {b['ratio_of_medians']:.3f}× | {b['fpga_faster_pairs']}/12 |\n"
    text+='''
FPGA路径包含数据打包、DMA、等待和输出复制。局部算子段加速比不能当成完整网络或完整点餐系统加速比。

2线程完整分类器中位耗时下降约9.9%，12/12对照轮次更快。4线程下降约2.0%，仅6/12轮次更快，样本存在明显的执行顺序相关差异；这份记录不足以确认4线程下有稳定整网收益。实际原因尚未单独验证。

实际运行耗时仍以4线程更低，不应为了展示较大的加速比而默认改回2线程。

下一步：冻结当前硬件与结果证据，保持现有采集、菜单和交互规则，接入新的分类器工厂 `blocks_runtime.make_fpga_classifier()`，只加载新加速Overlay一次，然后做摄像头与点餐联调、连续运行和CPU/FPGA同场景对照。当前记录不包含实时手势准确率、手掌检测、网络界面或长时间运行稳定性验证。

构建包的 `board_tested=false` 是发布时状态，保持原文件不变。本次板测状态单独保存在复核结果中。
'''
    (WS/'output/两个残差块FPGA加速_板测复核.md').write_text(text,encoding='utf-8')
    print(json.dumps({'passed':True,'saved_arrays_checked':len(checks),'fpga_completed_frames':72,'benchmark':benchmarks,'review':str(out)},ensure_ascii=False,indent=2))
