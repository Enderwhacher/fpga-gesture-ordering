"""Review the supplied v2 live session without changing deployment packages."""
import hashlib
import json
from pathlib import Path
import runpy
import statistics
import zipfile


ROOT = Path(__file__).resolve().parent
BOARD = Path('E:/gesture_order_blocks56_process_v4_results (1).zip')
LAPTOP = ROOT / 'output/gesture_order_laptop_v1/gesture_order_laptop_v1/logs (3).zip'
OUT = ROOT / 'output/validated_pw16_thread_live_v2'
OUT.mkdir(exist_ok=True)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_json(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


with zipfile.ZipFile(BOARD) as bz, zipfile.ZipFile(LAPTOP) as lz:
    board_name = next(n for n in bz.namelist() if 'board_session_' in n)
    board = json.loads(bz.read(board_name))
    matching = []
    for name in lz.namelist():
        if 'laptop_session_' in name:
            data = json.loads(lz.read(name))
            if data.get('transport', {}).get('session_id') == board['session_id']:
                matching.append((name, data))
    assert len(matching) == 1
    laptop_name, laptop = matching[0]
    order_name = 'logs/orders/order_' + laptop['laptop_session'] + '_001.json'
    order = json.loads(lz.read(order_name))
    hardware = json.loads(bz.read('results/pw16_6239eb6c418e/report.json'))
    scheduling = json.loads(bz.read('results/ab_0a38a8a7cb3e/report.json'))

    manifest = json.loads(bz.read('source/app_manifest.json'))
    for relative, expected in manifest['critical_sha256'].items():
        member = relative if relative.startswith('inputs/') else 'source/' + relative
        assert sha(bz.read(member)) == expected, relative
    assert bz.read('source/order_core.py') == (ROOT / 'gesture_order_blocks56_process_v4/order_core.py').read_bytes()
    notebook = json.loads(bz.read('source/00_process_v4.ipynb'))
    launcher = next(''.join(c['source']) for c in notebook['cells']
                    if c['cell_type'] == 'code' and 'run_board_server(' in ''.join(c['source']))
    assert 'board_server.run_board_server(' in launcher
    assert "backend='fpga_v2'" in launcher and "accel_dir=ROOT/'gesture_block_accel_v2'" in launcher
    assert 'from process_server import run_board_server' not in launcher
    assert board['backend']['hardware_release'] == 'gesture_blocks56_fp32_pw16_v2'
    assert board['backend'] == laptop['backend']
    assert board['backend']['fpga_enabled'] and hardware['passed'] and hardware['recommend_new_hardware']
    assert not hardware['cleanup_errors'] and hardware['error'] is None

    rows = board['records']
    detected = [r for r in rows if r['detected']]
    byseq = {r['seq']: r for r in rows}
    assert len(byseq) == len(rows)
    completed = 0
    for row in rows:
        completed += int(bool(row['detected']))
        assert row['fpga_completed_frames'] == completed
    assert completed == len(detected) == 152
    assert not board['workers_still_alive'] and board['backend_closed']
    assert board['final_status']['status'] == 'STOPPED' and board['final_status']['error'] is None
    assert laptop['storage_error'] is None

    core = runpy.run_path(str(ROOT / 'gesture_order_blocks56_process_v4/order_core.py'))['OrderController']()
    actions = laptop['all_actions']
    assert len({a['seq'] for a in actions}) == len(actions)
    trace = []
    for action in actions:
        row = byseq[action['seq']]
        assert row['label'] == action['gesture'] and row['score'] >= .6
        assert action['session_id'] == board['session_id']
        actual = core.handle(action['gesture'], row['completed_offset'])
        assert actual == action['action'] and core.page == action['page']
        trace.append(dict(seq=action['seq'], action=actual, page=core.page,
                          cart=list(core.cart), total_fen=core.total_fen))
    for key in ('page', 'selected', 'cart', 'review_selected', 'total_fen', 'message', 'order_count'):
        assert core.snapshot()[key] == laptop['state'][key], key
    for key, value in laptop['state']['last_order'].items():
        assert order[key] == value
    assert order['total_fen'] == 3300 and order['simulated'] and not order['paid']
    assert [i['quantity'] for i in order['items']] == [1, 1, 1]

    metrics = {key: statistics.median(r[key] for r in detected)
               for key in ('detector_ms', 'classifier_ms', 'fpga_call_ms')}
    metrics['same_frame_detector_plus_classifier_ms'] = statistics.median(
        r['detector_ms'] + r['classifier_ms'] for r in detected)
    review = dict(
        passed=True,
        scope='Threaded capture plus FPGA v2, live order integration; not a paired whole-system speed comparison.',
        board_session=board['session_id'], laptop_session=laptop['laptop_session'],
        source_manifest_verified=True, launcher_verified_thread_capture=True,
        model_sha256=board['backend']['model_sha256'], hardware_release=board['backend']['hardware_release'],
        detector_results=len(rows), classification_and_fpga_completions=completed,
        live_detected_frame_medians=metrics,
        board_capture_hz=board['final_status']['metrics']['capture_hz'],
        board_preview_hz=board['preview_metrics']['preview_hz'],
        laptop_display_snapshot=laptop['display'],
        verified_action_count=len(actions), verified_state_replay=trace,
        saved_order_total_fen=3300, simulated=True, paid=False,
        workers_closed=True, accelerator_closed=True,
        isolated_hardware_summary=hardware['summary'],
        isolated_fpga_call_reduction_percent=hardware['fpga_call_reduction_percent'],
        scheduling_reduction_percent=scheduling['process_reduction_percent'],
        recommend_process_mode=False,
        limits=[
            'No paired v1/v2 live whole-system comparison; no substantial end-to-end speedup established.',
            'No per-poll transport history: offline/reconnect behavior cannot be revalidated from this session snapshot.',
            'No cancel_exit action in this session. Previous v1 user regression confirmation is separate evidence.',
            'Hold duration and true-label recognition accuracy require dedicated observations; actions alone do not establish accuracy.',
            'FPGA accelerates classifier blocks 5 and 6; palm detection and other classifier layers remain on CPU.',
        ],
        source_archives=[dict(path=str(p), sha256=sha(p.read_bytes())) for p in (BOARD, LAPTOP)],
    )
    save_json('review.json', review)
    save_json('hardware_report.json', hardware)
    save_json('scheduling_report.json', scheduling)
    # Keep only this matched live session in the evidence set, not historical laptop sessions.
    for destination, data in (
        ('board_session.json', bz.read(board_name)),
        ('laptop_session.json', lz.read(laptop_name)),
        ('saved_order.json', lz.read(order_name)),
        ('tested_notebook.ipynb', bz.read('source/00_process_v4.ipynb')),
    ):
        (OUT / destination).write_bytes(data)

readme = '''# 新版 FPGA v2＋原线程采集：板上联调记录

2026-11-01 收到并核对。完整33元模拟订单已保存，20次动作均按同一板端会话和摄像头序号匹配，重放原订单状态机后最终购物车一致。152次分类均对应FPGA完成计数递增。服务器正常停止，线程及加速器关闭。

实际配置：gesture_order_blocks56_process_v4 目录中的 board_server.run_board_server；backend='fpga_v2'；accel_dir=/home/xilinx/jupyter_notebooks/gesture_block_accel_v2。使用原线程采集，不调用 process_server。相机保持已验证的物理朝向；rotate_180=False，mirror=False。笔记本和HDMI显示方式不变。app_release仍含process_v4字样，不能仅据目录或版本名判断是否启用了分进程。

独立同图硬件对照：v1调用7.54183ms，v2调用6.542385ms（含传输），耗时下降13.252%，提速1.153倍。v2两个网络块相对四线程CPU约1.811倍。完整分类由75.075875ms到73.922005ms，仅下降约1.54%。数值/参数重载及完整分类对照通过。

本次真实交互有手帧中位耗时：检测323.31ms，分类146.96ms，其中FPGA调用6.667ms；同帧检测＋分类之和的中位数469.90ms。FPGA时间已经包含在分类时间内，不要重复相加。采集约25.96fps、板端预览约19.21fps；笔记本结束快照显示界面约17.80fps、预览约16.70fps。这些帧率不是手势识别帧率。

分进程对照仅下降0.212%，不采用。整机明显加速目标尚未达成，不能将1.811倍块级提速写成整机提速；本次真实交互也不是新旧版严格同图配对性能测试。

此包是验证证据补充，不是完整部署/源码交接包。原v1冻结版保持不动。原优化包中的gesture_block_accel_v2为本次硬件；实际启动使用tested_notebook.ipynb中第5单元的线程版代码，不使用原分进程启动代码。若重启内核，要从第1单元依次运行；第3、4单元确认数值/资源退出通过后，再使用线程版第5单元。

本次已直接验证V返回、购物车保留、减一份、完整订单保存。持续保持和断线恢复仍需按专门步骤回归；本份笔记本日志只有最终连接快照，不能证明完整断线过程。没有cancel_exit事件，不据此声称本轮退出取消已验证。

原始文件存于用户提供的两份ZIP，路径与SHA256记在review.json；此包只选取匹配本次会话的笔记本记录，避免把旧会话当作本次证据。没有修改模型、硬件、板端或笔记本部署文件。
'''
(OUT / 'readme.md').write_text(readme, encoding='utf-8')
files = sorted(p for p in OUT.iterdir() if p.is_file() and p.name != 'manifest.json')
save_json('manifest.json', {p.name: sha(p.read_bytes()) for p in files})
archive = ROOT / 'output/validated_pw16_thread_live_v2_evidence.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    for path in sorted(OUT.iterdir()):
        if path.is_file():
            z.write(path, 'validated_pw16_thread_live_v2/' + path.name)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
print(json.dumps(dict(passed=True, report=str(OUT / 'review.json'), evidence=str(archive),
                      archive_sha256=sha(archive.read_bytes()), metrics=metrics), indent=2))
