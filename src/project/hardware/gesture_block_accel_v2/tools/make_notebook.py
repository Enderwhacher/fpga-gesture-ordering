from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[1]
def cell(kind,text):return {'cell_type':kind,'metadata':{},'source':text.splitlines(keepends=True),**({'execution_count':None,'outputs':[]} if kind=='code' else {})}
cells=[
cell('markdown','''# 两个完整残差块 FPGA 加速验证

只做加速器验证，不启动摄像头和点餐界面。保留旧版本，解压到独立目录。

先停止原点餐服务器，确认输出 `ORDER_BOARD_SERVER_STOPPED`，并关闭笔记本端点餐窗口。若原程序停止失败或有线程未退出，重启板卡后再做本次验证。

选择 Python 3 内核，按顺序运行。不要点击“运行全部”。第 1 步不会下载硬件；第 2 步会下载新的独立加速 bitstream。
'''),
cell('code', '''from pathlib import Path
import runpy
import sys

ROOT = Path('/home/xilinx/jupyter_notebooks/gesture_block_accel_v1')
assert (ROOT / 'package_manifest.json').is_file(), '请检查解压目录，不能多套一层文件夹'
for folder in (ROOT, ROOT / 'board'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
runpy.run_path(str(ROOT / 'board/environment.py'), run_name='__main__')
'''),
cell('markdown','''## 第 2 步：下载并验证

正常会依次显示 `PASS_BLOCKS`、`PASS_CLASSIFIER`、两组线程测速，最后显示 `BLOCKS56_HARDWARE_VALIDATION_OK`。

测速时不运行其他识别程序、不加载 `base.bit`。耗时取决于板上环境；不要在单元仍为 `[*]` 时重复点击运行。
'''),
cell('code', '''validation = runpy.run_path(str(ROOT / 'board/validate_hardware.py'))
report = validation['validate'](repeats=12, thread_counts=(2, 4))
print('全部通过:', report['passed'])
print('实际 FPGA 完成次数:', report['fpga_completed_frames'])
for threads, group in report['benchmark'].items():
    print('OpenCV 线程数:', threads)
    for name, data in group.items():
        print(name, 'CPU/FPGA 中位耗时(ms):', data['median_ms'],
              '加速比:', data['speedup_ratio_of_medians'])
'''),
cell('markdown','''## 第 3 步：下载结果

等第 2 步结束，运行下面的单元并点击下载链接。即使第 2 步出现红色错误，只要内核仍能执行，也可运行此单元打包已经保存的日志。

如果网页断开，重新连接后先从第 1 步恢复路径，再只运行本单元导出日志。先保留错误信息，不要反复加载硬件。
'''),
cell('code', '''from IPython.display import FileLink, display
exporter = runpy.run_path(str(ROOT / 'board/validate_hardware.py'))
archive = exporter['export_results']()
display(FileLink(archive.name))
'''),
cell('markdown','''## 结果怎么看

- `passed=True` 表示本次板上数据一致性、参数重载、整网输出和测速流程通过。
- `blocks` 是 FPGA 覆盖的两个完整残差块，包含打包、DMA、等待和输出复制。
- `classifier` 是完整分类器，包含 CPU 前段、FPGA 两个残差块、CPU 后段；不含摄像头、手掌检测、网络和界面。
- 加速比为同一线程数下 CPU 中位耗时 / FPGA 中位耗时，大于 1 才有收益。必须分别看算子段和完整分类器。
- 当前仍使用原模型、原四类手势。该测试不会改变点餐逻辑。

把 `gesture_blocks56_board_results.zip` 发回后，再决定是否把它接入正在使用的点餐程序。恢复旧演示时，先结束本 Notebook 内核，然后按原版本启动流程重新加载旧加速 overlay。
''')]
notebook={'cells':cells,'metadata':{'kernelspec':{'display_name':'Python 3 (ipykernel)','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.10'}},'nbformat':4,'nbformat_minor':5}
for i,c in enumerate(cells):c['id']=f'blocks56-{i:02d}'
(ROOT/'00_validate_blocks56.ipynb').write_text(json.dumps(notebook,ensure_ascii=False,indent=1)+'\n',encoding='utf-8')
print('Notebook created')
