---
name: gesture-model-training
description: 为手势分类项目整理会话隔离数据、微调 MobileNetV3 并核对 ONNX 导出与部署预处理。适用于训练精度、左右手偏差或替换分类模型问题。
---

# 手势模型训练与导出

先确认数据输入和部署输入是否相同。本项目是检测手是否存在后，对校正方向的整帧分类，不按检测框裁图；改成 ROI 应作为新的数据/模型方案验证。

## 流程

1. 为每张图保留标签、左右手、采集会话、背景/光照和质量记录。连续视频邻帧按会话整体划分，检查精确重复与近重复；新场景/新人员留作独立测试，验证集选择最佳轮次后不能再称其为独立测试集。
2. 针对误识别先核对方向、BGR/RGB、缩放/padding、mean/std、类别顺序；同图 CPU 与 FPGA 均错误时，先查这些条件和数据覆盖。分数 1.000 不等于泛化准确率。
3. 在独立训练输出目录工作，不覆盖现板模型。当前标签顺序为 open_palm、fist、victory、thumbs_up；shape=1×3×224×224，最长边224，居中填充144，参数读取 model_meta.json。不要从常见 ImageNet 参数猜归一化。
4. 复现现有全网训练时先按脚本恢复输入布局。原始数据 ZIP、HaGRID 预训练权重未包含在代码包；缺少时列清单，不宣称一键可重训。旧脚本还有硬编码相对路径，先审查再执行。
5. 比较每类召回、混淆矩阵、左右手分组和同一验证集上的旧模型；不要只报总体平均。当前配置的冻结 BN 统计是小样本方案，不作为所有数据集的默认规则。
6. 导出后核对 ONNX 图、shape、标签和逐图 logits/top-1 与 PyTorch 的一致性；整套交付 ONNX、runtime、meta、配置、权重、逐图结果和哈希。
7. 新模型先走 CPU 同图与实时验证。全网微调后，原 FPGA prefix/suffix、参数与黄金向量可能失效，不能仅替换完整 ONNX 而继续沿用旧切分参数。

## 项目依据

项目根目录是含 project_manifest.json 的目录；以下链接适用于本包，移出后改用用户给出的项目根路径。

- [训练输入、已有结果与缺项](../../src/project/training/readme.md)
- [全网训练脚本](../../src/project/training/scripts/train_gesture4_full.py)、[导出检查](../../src/project/training/scripts/export_gesture4_full.py)
- [配置](../../src/project/training/run02/config.json)、[部署元数据](../../src/project/training/run02/model_meta.json)

验收输出应将“数值等价”“验证准确率”“新场景测试”“板上延迟”分别列出。本技能不执行或宣称新的训练结果。
