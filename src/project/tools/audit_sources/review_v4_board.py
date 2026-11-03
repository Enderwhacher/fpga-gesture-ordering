"""Audit exact V4 deployment, balanced benchmark, live counter and saved laptop order."""
from pathlib import Path
import hashlib
import json
import runpy
import statistics
import zipfile

ROOT=Path(__file__).resolve().parent
BOARD=Path('E:/gesture_order_accel_v4_results.zip')
LAPTOP=ROOT/'output/gesture_order_laptop_v1/gesture_order_laptop_v1/logs (4).zip'
OUT=ROOT/'output/validated_v4_review'
OUT.mkdir(exist_ok=True)


def sha(data):return hashlib.sha256(data).hexdigest()
def write(name,value):(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


with zipfile.ZipFile(BOARD) as bz,zipfile.ZipFile(LAPTOP) as lz:
    report_name='results/v4_95d5373fa6ae/report.json'
    report=json.loads(bz.read(report_name))
    board_name='logs/board_session_5789afd2bf4549819084467a54836a07.json'
    board=json.loads(bz.read(board_name))
    manifest=json.loads(bz.read('source/manifest.json'))
    assert sha(bz.read('source/manifest.json'))==report['package_manifest_sha256']
    for name in ('board_server.py','order_core.py','pipeline_runtime.py','run_complete.py','session_guard.py',
                 'setup_runtime.py','start_v4.py','v3_runtime.py','v4_runtime.py','validate_v4.py'):
        assert sha(bz.read('source/'+name))==manifest['files'][name],name
    # Tie evidence to the actual previously delivered app archive, not a newly rebuilt app.
    release=ROOT/'output/gesture_order_accel_v4_r1.zip'
    with zipfile.ZipFile(release) as archive:
        assert archive.read('gesture_order_accel_v4/manifest.json')==bz.read('source/manifest.json')
    assert report['passed'] and report['error'] is None and not report['cleanup_errors']
    assert len(report['numeric_checks'])==714
    assert report['selected_config']==board['backend']['ps_config']=='serial_cv1_t3'
    assert len(report['blocks'])==28 and all(len(b['records'])==12 for b in report['blocks'])
    assert board['backend']['fpga_enabled'] and not board['backend']['quantized']
    assert board['backend']['hardware_release']=='gesture_blocks56_fp32_pw16_v2'
    assert sha((ROOT/'gesture_block_accel_v2/overlay/gesture_blocks56.bit').read_bytes())==report['bit_sha256']
    assert not board['workers_still_alive'] and board['backend_closed'] and board['final_status']['error'] is None
    assert board['final_status']['status']=='STOPPED'
    rows=board['records'];byseq={r['seq']:r for r in rows}
    assert len(byseq)==len(rows)
    previous=0
    for row in rows:
        previous+=int(row['detected'])
        assert row['fpga_completed_frames']==previous
    assert previous==171
    matched=[]
    for name in lz.namelist():
        if 'laptop_session_' in name:
            data=json.loads(lz.read(name))
            if data.get('transport',{}).get('session_id')==board['session_id']:matched.append((name,data))
    assert len(matched)==1
    laptop_name,laptop=matched[0]
    order_name='logs/orders/order_'+laptop['laptop_session']+'_001.json'
    order=json.loads(lz.read(order_name))
    assert laptop['backend']==board['backend'] and laptop['storage_error'] is None
    core=runpy.run_path(str(ROOT/'gesture_order_accel_v4/order_core.py'))['OrderController']()
    actions=laptop['all_actions'];trace=[]
    assert len({a['seq'] for a in actions})==len(actions)
    for action in actions:
        observation=byseq[action['seq']]
        assert observation['label']==action['gesture'] and observation['score']>=.6
        actual=core.handle(action['gesture'],observation['completed_offset'])
        assert actual==action['action'] and core.page==action['page']
        trace.append(dict(seq=action['seq'],action=actual,page=core.page,cart=list(core.cart),total_fen=core.total_fen))
    for key in ('page','selected','review_selected','cart','total_fen','message','order_count'):
        assert core.snapshot()[key]==laptop['state'][key],key
    for key,value in laptop['state']['last_order'].items():assert order[key]==value
    assert order['total_fen']==3300 and order['simulated'] and not order['paid']
    assert [item['quantity'] for item in order['items']]==[1,1,1]
    detected=[r for r in rows if r['detected']]
    summary=report['summary'];chosen=summary['serial_cv1_t3'];cpu=summary['cpu_serial_cv1_t3']
    # Recalculate, rather than trusting the pre-computed target flag.
    drop=100*(1-chosen['detector_plus_classifier_ms']/summary['v2_reference']['detector_plus_classifier_ms'])
    assert abs(drop-report['processing_reduction_vs_v2_percent'])<1e-8 and drop>=25
    review=dict(passed=True,board_session=board['session_id'],laptop_session=laptop['laptop_session'],
        selected_config='serial_cv1_t3',scheduling='serial',cv_threads=1,ort_threads=3,
        numeric_comparisons=714,balanced_blocks=28,samples_per_configuration=24,
        processing_reduction_vs_v2_percent=drop,
        processing_reduction_vs_v3_percent=report['processing_reduction_vs_v3_percent'],
        frame_age_reduction_vs_v2_percent=report['frame_age_reduction_vs_v2_percent'],
        frame_age_reduction_vs_v3_percent=report['frame_age_reduction_vs_v3_percent'],
        latency_25percent_vs_v3_met=report['latency_25percent_vs_v3_met'],
        processing_25percent_vs_v2_met=True,summary=summary,
        matched_serial_cpu_processing_reduction_percent=100*(1-chosen['detector_plus_classifier_ms']/cpu['detector_plus_classifier_ms']),
        matched_serial_cpu_interval_speedup=cpu['result_interval_ms']/chosen['result_interval_ms'],
        live_results=len(rows),live_fpga_classifications=171,
        live_detected_medians={key:statistics.median(r[key] for r in detected) for key in ('detector_ms','classifier_ms','fpga_call_ms')},
        live_detected_processing_median_ms=statistics.median(r['detector_ms']+r['classifier_ms'] for r in detected),
        capture_hz=board['final_status']['metrics']['capture_hz'],preview_hz=board['preview_metrics']['preview_hz'],
        verified_action_count=len(actions),action_trace=trace,order_saved=True,total_fen=3300,
        simulated=True,paid=False,workers_closed=True,board_error=None,
        model_sha256=report['model_sha256'],bit_sha256=report['bit_sha256'],
        package_manifest_sha256=report['package_manifest_sha256'],
        limitations=[
            'Target met versus V2; reduction versus V3 is 22.86%, below 25%.',
            'V4 retains the V2 PL bitstream. Main end-to-end improvement is PS execution and thread configuration.',
            'Matched tuned serial CPU differs by about 1.1% processing time; no statistically significant whole-system FPGA advantage established.',
            'Best CPU result-interval control is a high-latency pipeline; raw fpga_vs_cpu_interval_speedup is not a matched latency comparison.',
            'Fixed-image benchmark excludes HTTP, display, gesture hold, camera exposure and USB transfer latency.',
            'Live labels are not an independently labelled accuracy dataset.',
            'No cancel_exit event or transport-fault history in the matching laptop session. Hold/exit-cancel/offline recovery require separate user confirmation.',
        ],source_archives=[dict(path=str(p),sha256=sha(p.read_bytes())) for p in (BOARD,LAPTOP)],
        deployment_archive_sha256=sha(release.read_bytes()))
    write('review.json',review)
    for name,data in (
        ('benchmark_report.json',bz.read(report_name)),('board_session.json',bz.read(board_name)),
        ('laptop_session.json',lz.read(laptop_name)),('saved_order.json',lz.read(order_name)),
        ('installed_manifest.json',bz.read('source/manifest.json'))):
        (OUT/name).write_bytes(data)

readme='''# 第四版R1板上性能与完整订单核对

选中serial_cv1_t3：原线程串行调度、OpenCV全局1线程、ORT检测和分类前后段3线程，PL为已验证的FPGA v2两个完整块。保持FP32模型、预处理、相机朝向及原手势确认规则。流水线候选因较高单帧延迟未采用。

同图、真实采集预览后台、正反顺序各12个结果：第二版处理耗时470.460615ms，第三版392.168825ms，第四版302.501480ms。相对第二版下降35.700998%，相对第三版下降22.864476%。相对第二版25%目标通过；相对第三版25%延迟下降未通过。每帧源图到结果完成的延迟由487.196055ms到319.025650ms，下降34.518%；不包含曝光、USB、HTTP、界面、保持确认。

714组数值检查通过。实际运行1736次检测，其中171次分类均逐次对应FPGA完成计数递增；有手时同帧检测+分类中位312.70ms，其中FPGA调用约6.65ms（已计入分类，不重复相加）。板端采集约26.99fps、预览约19.54fps，不能当成完整识别帧率。

笔记本匹配同一板端会话，23次动作与摄像头记录对应，并回放订单状态机一致；保存汉堡、可乐、薯条各一份33元模拟订单，未支付。服务器正常停止，线程/加速器关闭。V返回、减份、完整提交有直接日志证据；持续保持、取消退出和断线恢复的本轮完整过程仍需用户确认，不能用旧会话替代。

公平对照：匹配三线程串行纯CPU处理耗时305.841260ms，FPGA协同302.501480ms，仅约1.09%差异，不能宣称显著整机FPGA优势。35.7%主要是PS执行和线程配置收益，不能写成PL硬件核自身提速。最高吞吐CPU候选为高延迟流水线，与低延迟选中配置不宜只比输出间隔。

建议冻结此配置用于提交前验收，保留第三版回退，不继续改模型。后续可运行R1 Notebook前两步，再用分步Notebook第6部分读取已保存的同版板测报告启动，不必重复长测。需要归档的实际report.json请从原板端results/v4_95d5373fa6ae保留，勿覆盖。

此目录是验证证据，不是完整部署包。对应部署包仍为gesture_order_accel_v4_r1.zip，硬件源工程/bit/hwh来自gesture_block_accel_v2；运行库恢复脚本只恢复vendor，不改应用哈希。原始ZIP与部署包SHA记在review.json。
'''
(OUT/'readme.md').write_text(readme,encoding='utf-8')
write('evidence_manifest.json',{p.name:sha(p.read_bytes()) for p in sorted(OUT.iterdir()) if p.is_file() and p.name!='evidence_manifest.json'})
target=ROOT/'output/validated_v4_evidence.zip'
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for p in sorted(OUT.iterdir()):
        if p.is_file():archive.write(p,'validated_v4_review/'+p.name)
with zipfile.ZipFile(target) as archive:assert archive.testzip() is None
print('V4_AUDIT_PASS',len(actions),'actions; 171 hardware classifications; target',round(drop,3),'percent')
print('EVIDENCE',target)
