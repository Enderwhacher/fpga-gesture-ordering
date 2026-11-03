"""Create deployable/reproducible artifacts only after training and export checks."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
run = ROOT/'gesture4_full_run02'
report = json.loads((run/'report.json').read_text(encoding='utf-8'))
verification = json.loads((run/'export_verification.json').read_text(encoding='utf-8'))
assert verification['images'] == verification['matched_top1'] == 384
assert report['selected_stage'] == 'full_finetune'
assert report['validation_accuracy_delta'] > 0
labels_cn = {'open_palm':'张手', 'fist':'握拳', 'victory':'V 手势', 'thumbs_up':'点赞'}
new, old = report['validation'], report['old_model_validation']
table = '\n'.join(f"| {labels_cn[k]} | {old['per_class_recall'][k]:.2%} | {new['per_class_recall'][k]:.2%} |" for k in labels_cn)
hands = '\n'.join(f"| {h} | {old['by_hand'][h]['accuracy']:.2%} | {new['by_hand'][h]['accuracy']:.2%} |" for h in ('left','right'))
details = '\n'.join(f"| {h} {labels_cn[k]} | {old['by_hand'][h]['per_class_recall'][k]:.2%} | {new['by_hand'][h]['per_class_recall'][k]:.2%} |"
                    for h in ('left','right') for k in labels_cn)
readme = f'''# 四手势全网络微调版 V2

本模型已在电脑上训练和导出验证，尚未在 PYNQ-ZU 上实测。

## 上板替换步骤

1. 解压本 ZIP，将整个 `gesture4_model_v2` 文件夹上传到 `/home/xilinx/jupyter_notebooks/`。
2. 保留旧 `gesture4_model` 或 `gesture4` 文件夹，不覆盖它。
3. 停止点餐程序并重启其 Notebook 内核；先运行第一个设置单元，再按顺序运行后续单元。
4. 在点餐 Notebook 第一个单元只修改模型目录：

```python
ROOT = Path('/home/xilinx/jupyter_notebooks')
MODEL_DIR = ROOT / 'gesture4_model_v2'
```

现有点餐 v1/v2 的 `CPUBackend(ROOT, MODEL_DIR)` 接口不变。摄像头方向保持已经确认正确的设置；不要因为换模型重新旋转画面。继续保留手部检测、确认、移开手再触发规则。初次对照保持原分类筛选阈值 0.60，不要同时改多个变量。

## 训练实际做了什么

- 从原始 HaGRID MobileNetV3-Large 34 类预训练权重重新开始，新建四分类层。
- 分类层预热 3 轮，随后开放整个网络参数进行微调；BatchNorm 运行统计保持预训练值，仿射参数参与微调。
- 网络共有 4,207,156 个参数。导出时检查了特征提取部分 {verification['feature_parameter_tensors_total']} 个参数张量，全部相对原预训练权重发生变化。
- 仍是 338 张训练原图、384 张验证原图，16 次采集。原始 ZIP、旧模型未修改。
- 增强：随机水平翻转、小角度旋转/平移/缩放、亮度/对比度/饱和度；增强图不算额外独立样本。
- 按验证宏平均召回率选最佳模型，同分时选较低验证损失。实际共训练 {report['epochs_run']} 轮（含预热），采用第 {report['selected_epoch']} 轮。
- 固定随机种子 2026，CPU 4 线程，batch 16。详细学习率、损失、每轮结果见 config/history。

## 与旧模型同一验证集对照

总体：旧版 **{old['accuracy']:.2%}** → 新版 **{new['accuracy']:.2%}**。

| 类别 | 旧模型 | 新模型 |
|---|---:|---:|
{table}

| 手别 | 旧模型 | 新模型 |
|---|---:|---:|
{hands}

| 手别与类别 | 旧模型 | 新模型 |
|---|---:|---:|
{details}

总体提高不表示每个子组都提高：左手点赞从 47/48 降至 43/48，右手 V 从 48/48 降至 47/48；现场测试应重点复查。左手 V 从 31/48 提升至 45/48，右手点赞从 40/48 提升至 45/48。

这些是用于选模型的验证数据，不是独立测试成绩。相邻帧有相关性，也缺少充分的不同人、背景、光照。因此不能将表格解释为实际点餐准确率。

## 导出及接口

- 文件名仍为 `hagrid_mobilenetv3_large.onnx`，ONNX opset 13。
- 输入 float32 `[1,3,224,224]`，输出 logits `[1,4]`。
- 类别顺序 open_palm、fist、victory、thumbs_up。
- 整帧 BGR 转 RGB，最长边缩放到 224，居中填充 144，归一化保持旧版约定。不是手部 ROI 裁剪分类。
- 384/384 张验证图的 PyTorch 与 OpenCV ONNX 第一名预测一致，最大 logit 绝对误差 {verification['max_abs_logit_error']:.8f}。
- 元数据包含模型 SHA256，加载器会检查文件完整性。

## 现场验证建议

另行拍摄左右手四种手势，各做 10 次独立摆手，每次保持约 3 秒、移开后再做；覆盖正面、轻微侧转、近远、不同背景。新旧模型使用同一组新图片/录像比较。分别记录：有手检测成功率、检测成功后的分类正确率、实际点餐动作是否正确触发、无手误触发数。不要用识别分数代替准确率。

本轮只重训四分类网络，手掌检测模型未改变。没有空画面/其他手势类别；未识别到手的问题需单独检查检测器。没有实测开发板性能，也没有接入 FPGA 神经网络加速。

## 恢复旧模型

停止程序并重启内核，把 MODEL_DIR 改回原来的 `gesture4_model`（或你原先的 `gesture4`），从第一个单元重新执行。
'''
(run/'使用说明.md').write_text(readme, encoding='utf-8')
repro = '''# 复现训练

在原项目目录内运行，使用原有 hagrid_conversion/.venv Python。四分类训练依赖 torch 2.7.1+cpu、torchvision 0.22.1+cpu、numpy、Pillow、OpenCV 4.10。导出另需 ONNX 1.18。

```powershell
& "outputs/hagrid_conversion/.venv/Scripts/python.exe" "outputs/train_gesture4_full.py" --out "outputs/gesture4_full_reproduce"
& "outputs/hagrid_conversion/.venv/Scripts/python.exe" "outputs/export_gesture4_full.py" --run "outputs/gesture4_full_reproduce"
```

脚本 train_gesture4.py 是原有数据读取/预处理辅助代码，需与新训练脚本同目录。导出依赖目录使用 outputs/gesture4_export_deps02。训练脚本默认从同目录读取：

- gesture_round01_02_reviewed.zip
- gesture_round03_validation.zip
- hagrid_conversion/MobileNetV3_large.pth（原始 HaGRID 权重）
- gesture4_training_run01/best.pth（旧模型，仅用于对照，不用于初始化）
- gesture4_training_run01/model_meta.json
- gesture4_training_run01/gesture4_model/hagrid_runtime.py（导出加载器）

本结果包未重复包含数百 MB 的数据及原始预训练权重；上列依赖保留在原项目 outputs 内。输入文件哈希与会话划分记录在 config.json。输出目录必须不存在，防止覆盖既有模型。代码中保留了训练/验证无重叠断言和预处理一致性检查。
'''
(run/'复现训练.md').write_text(repro, encoding='utf-8')

def package(dest, files):
    manifest = {name: hashlib.sha256(path.read_bytes()).hexdigest() for path, name in files}
    with zipfile.ZipFile(dest, 'w', zipfile.ZIP_DEFLATED) as z:
        for path, name in files:
            z.write(path, name)
        z.writestr('SHA256.json', json.dumps(manifest, indent=2))
    with zipfile.ZipFile(dest) as z:
        assert z.testzip() is None
        for name, digest in manifest.items():
            assert hashlib.sha256(z.read(name)).hexdigest() == digest
    print(dest.name, dest.stat().st_size, 'bytes; verified', len(files), 'files')

board_files = [(run/'gesture4_model_v2'/name, 'gesture4_model_v2/'+name)
               for name in ('hagrid_mobilenetv3_large.onnx','model_meta.json','hagrid_runtime.py')]
reports = [(run/name, name) for name in ('使用说明.md','report.json','config.json','export_verification.json')]
package(ROOT/'gesture4_full_finetuned_board_v2.zip', board_files+reports)
training_files = [(run/name, name) for name in ('best.pth','model_meta.json','history.json','validation_predictions.csv','validation_logits.npy','复现训练.md')]
scripts = [(ROOT/name, 'scripts/'+name) for name in ('train_gesture4_full.py','train_gesture4.py','export_gesture4_full.py','package_gesture4_full.py')]
package(ROOT/'gesture4_full_training_results_v2.zip', training_files+reports+scripts)
