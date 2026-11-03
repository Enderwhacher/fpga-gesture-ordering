from pathlib import Path
import hashlib,json,shutil,runpy,statistics,ast,zipfile
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'outputs/gesture_order_project_v4'
def long(p): return Path('\\\\?\\'+str(p.resolve()))
def sha(p):
    with long(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(rel,text):
    p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
def cp(src,rel):
    p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,p)
def read(rel):return json.loads((OUT/rel).read_text(encoding='utf-8'))
manifest=read('handoff_manifest.json')
for name,rec in manifest['files'].items():
    p=OUT/name
    assert long(p).stat().st_size==rec['bytes'] and sha(p)==rec['sha256'],name
print('HANDOFF_OK',len(manifest['files']),flush=True)
b=read('evidence/final/board_session.json');l=read('evidence/final/laptop_session.json');r=read('evidence/final/benchmark_report.json');o=read('evidence/final/saved_order.json')
assert l['transport']['session_id']==b['session_id']
assert r['passed'] and len(r['numeric_checks'])==714 and len(r['blocks'])==28
assert b['backend']['ps_config']==r['selected_config']=='serial_cv1_t3'
assert b['backend']['hardware_release']=='gesture_blocks56_fp32_pw16_v2'
prev=0
for row in b['records']:
    prev+=int(row['detected']);assert row['fpga_completed_frames']==prev
assert prev==171 and not b['workers_still_alive'] and b['backend_closed']
core=runpy.run_path(str(OUT/'software/laptop/order_core.py'))['OrderController']()
byseq={x['seq']:x for x in b['records']}
for a in l['all_actions']:
    obs=byseq[a['seq']];assert obs['label']==a['gesture'] and obs['score']>=.6
    assert core.handle(a['gesture'],obs['completed_offset'])==a['action']
    assert core.page==a['page']
assert core.total_fen==o['total_fen']==3300 and o['simulated'] and not o['paid']
assert len(l['all_actions'])==23
model=OUT/'board_assets/gesture4_model_v2/hagrid_mobilenetv3_large.onnx'
if not model.exists():model=next((OUT/'board_assets').rglob('hagrid_mobilenetv3_large.onnx'))
assert sha(model)==r['model_sha256']
assert sha(OUT/'hardware/gesture_block_accel_v2/overlay/gesture_blocks56.bit')==r['bit_sha256']
assert sha(OUT/'software/board/gesture_order_accel_v4/manifest.json')==r['package_manifest_sha256']
for directory,mname,key in [('software/board/gesture_order_accel_v4','manifest.json','files'),('software/laptop','app_manifest.json','critical_sha256')]:
    m=read(directory+'/'+mname)
    for name,digest in m[key].items():
        if isinstance(digest,str): assert sha(OUT/directory/name)==digest,(directory,name)
for p in (OUT/'software').rglob('*.py'):ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p))
for name in ['train_gesture4_full.py','train_gesture4.py','export_gesture4_full.py','package_gesture4_full.py']:
    cp(ROOT/'outputs'/name,'training/scripts/'+name)
for name in ['best.pth','config.json','report.json','history.json','export_verification.json','validation_predictions.csv','validation_logits.npy','model_meta.json']:
    cp(ROOT/'outputs/gesture4_full_run02'/name,'training/run02/'+name)
training=json.loads((OUT/'training/run02/report.json').read_text(encoding='utf-8'))
assert abs(training['validation']['accuracy']-364/384)<1e-10
old=ROOT/'outputs/gesture_order_project_v2/board/jupyter_notebooks/gesture_runtime_cv410'
cvout=OUT/'recovery/previous_board_opencv.zip';cvout.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(cvout,'w',zipfile.ZIP_DEFLATED) as z:
    for p in old.rglob('*'):
        if p.is_file():z.write(p,'gesture_runtime_cv410/'+p.relative_to(old).as_posix())
write('recovery/readme.md','''# 旧板端 OpenCV 恢复参考

previous_board_opencv.zip 来自此前 gesture_order_project_v2 实际板端提取目录。
它不是本轮第四版现板依赖快照，不能据此认定二进制构建完全一致。不要自动覆盖现板环境。
请使用 tools/collect_board_dependencies.py 获取现板 v4_board_dependencies.zip，再比较内容。
本次未连接板卡，未加载 FPGA，未修改板端运行库。
''')
write('training/readme.md','''# 最终四类模型的训练证据

原始训练脚本保存在 scripts，训练配置、best.pth、逐轮历史、验证预测与导出检查在 run02。
最终分类模型沿用 board_assets 中的原文件，与 FPGA 分段源模型 SHA256 一致。

338 张训练图，384 张验证图，按采集会话分开；验证集参与最佳轮次选择，因此不是独立测试集。
原 HaGRID MobileNetV3-Large 初始化，新分类头预热 3 轮、全网络微调 24 轮，选择第 21 轮。
所有网络参数参与后期训练，BatchNorm 运行统计冻结，仿射参数可训练。输入保持整帧，不裁检测框。
验证正确 364/384，94.79%；旧模型同验证集 344/384，89.58%。不代表跨人群、跨场景准确率。
每类召回：张手 90/96，握拳 94/96，V 92/96，点赞 88/96。
左手点赞相对旧版退步，详见原 report.json，后续应增加独立场景测试。
数值等价 714 组是软硬件计算检查，不是识别准确率测试。

脚本按原始字节保存，重训前需要恢复原输入布局：scripts 同级放 gesture_round01_02_reviewed.zip、
gesture_round03_validation.zip、hagrid_conversion/MobileNetV3_large.pth，以及导出使用的原 runtime。
数据 ZIP 和预训练权重没有重复放入此工程包，输入 SHA 见 run02/config.json。
原训练环境 torch 2.7.1+cpu、torchvision 0.22.1+cpu，导出 ONNX 1.18；具体以配置和脚本为准。
本次不重训，不替换原模型，不声称仅凭本包已具备全部训练输入。
''')
write('docs/integration_v4.md','''# 第四版整合记录

## 当前入口

本项目以本次 gesture_order_v4_teammate_handoff 为运行基线，原始 445 项清单文件保持字节不变。
PS 为 gesture_order_accel_v4 R1，配置 serial_cv1_t3；硬件目录 gesture_block_accel_v2，PW16 双残差块。
笔记本使用 software/laptop 全目录。此前工程 v2 保留为回退档案，不把旧 board_server.py 或旧 bit 覆盖进第四版。

本次补入 training 训练证据、recovery 旧 OpenCV 恢复参考、presentation 演示材料和本整合说明。
原 docs/submission_checklist.md 的训练资料缺项现已部分补足，独立测试集和完整训练输入仍缺。
原 readme/report 和 manifest 保留为来源记录，优先阅读 START_HERE.md 与本说明。
原笔记本 app_manifest.compute_release 是旧标签，不选择硬件；不改校验过的应用字节。
实际选型以板端 backend.hardware_release / ps_config 和当前 bit SHA 为准。

## 已核对

原交接文件 SHA、模型与切分来源 SHA、部署 bit SHA、应用清单、Python 语法。
独立重放本轮 23 次动作，与原板端帧号对应；33 元模拟订单一致，171 次分类对应 FPGA 完成计数。
这些是对提供证据的复核和本机测试，不是新增上板实测或 Vivado 重建。

## 尚需现场完成

保留第四版现板 OpenCV 构建快照。启动后核对 serial_cv1_t3、PW16 v2 和递增的 FPGA 完成计数。
验证保持只触发一次、取消退出、断线恢复并保存新日志。演示前确认相机朝向和光照。
当前通过以太网 HTTP 连接 192.168.3.1，接口既可能是 USB 网络也可能是网线，按实际网络配置连接。
显示器接笔记本 HDMI，板卡不加载 BaseOverlay，避免覆盖当前卷积硬件。
''')
write('START_HERE.md','''# FPGA 非接触式手势点餐系统 · 第四版整合

这是本次新的主工程包。已接入第四版 PS 程序、PW16 双残差块硬件、现用笔记本网页，并补入模型训练资料。
旧项目保持独立，第四版原始运行源码与硬件产物不改写。

## 现板已经运行第四版

1. 先停止旧电脑程序和板端 Notebook，等待后台线程退出。
2. 板端打开 /home/xilinx/jupyter_notebooks/gesture_order_accel_v4/00_final_candidate_v4.ipynb。
3. 新内核运行第 1、2 部分，再运行第 6 部分，读取本机已有通过报告。无需重新长测。
4. 电脑使用 software/laptop/start_laptop_portable.bat，浏览器 http://127.0.0.1:8080。
5. 板端地址默认 http://192.168.3.1:8765。显示器接笔记本 HDMI，不再加载 base.bit。

## 需要恢复或换电脑

严格按 docs/quickstart.md 的安装顺序。deployment 含原始已验证硬件、应用、资产安装 ZIP 与脚本。
硬件和应用目录名称保持不变；已有不同文件时安装器会停止，先备份旧目录。
新机器需配置依赖和网络，当前板端 OpenCV 快照仍需现场补存。recovery 中旧版本仅供比对恢复。

## 文件导航

- software/board：R1 程序和 Notebook；software/laptop：完整电脑界面。
- hardware：HLS、RTL、bit/hwh、分段模型和正式 Vivado 归档。
- board_assets：最终模型与菜单资源；training：训练配置、权重与验证结果。
- evidence/final：本轮匹配的板端日志、电脑日志和 33 元订单。
- presentation：3 分钟演示文稿、逐页讲稿及演示操作单。
- docs/integration_v4.md：整合边界和未完成现场项。

性能必须区分：两个块历史固定输入四线程对照 CPU 11.85ms / FPGA 6.54ms，局部约 1.81 倍。
系统同轮第二版参考 470.46ms / 第四版 302.50ms，耗时降 35.70%，主要来自 PS 调优。
同线程调优纯 CPU 305.84ms / 协同 302.50ms，仅约 1.09% 差异，未证明显著整机 FPGA 优势。

执行 python tools/verify_project_v4.py 校验整合包。原始交接校验器另保留 tools/verify_handoff.py。
建议解压到较短路径（例如 D:/gesture_v4），避免 Windows 自动生成 IP 文件路径过长。
''')
check={'handoff_files_verified':len(manifest['files']),'matched_session':b['session_id'],'replayed_actions':23,'fpga_classifications':prev,'numeric_checks':714,'saved_order_fen':3300,'model_sha256':sha(model),'new_board_test':False,'vivado_rebuilt':False,'original_runtime_files_unchanged':True}
write('evidence/integration_checks.json',json.dumps(check,ensure_ascii=False,indent=2))
print('INTEGRATION_AUDIT_OK',check,flush=True)
