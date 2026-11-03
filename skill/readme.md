# 技能目录与使用方法

本包新增9个独立SKILL.md。首选通用主技能 `pynq-board-workflow`，它不依赖本点餐项目，可单独复制使用；其余8个聚焦项目中可复用的工作流程，并链接本包代码作为案例依据。

| 技能 | 适用任务 |
|---|---|
| [pynq-board-workflow](pynq-board-workflow/SKILL.md) | 通用环境、Overlay、DMA、资源生命周期、相机/显示/网络及排错 |
| [gesture-model-training](gesture-model-training/SKILL.md) | 会话隔离、左右手评估、全网微调、ONNX与预处理一致性 |
| [fpga-model-partition](fpga-model-partition/SKILL.md) | 瓶颈分析、连续子图融合、参数驻留与收益上限 |
| [pynq-accelerator-bringup](pynq-accelerator-bringup/SKILL.md) | HLS包协议、DMA、黄金向量与数值检查 |
| [pynq-notebook-deploy](pynq-notebook-deploy/SKILL.md) | 新内核可重复启动、报告恢复和资源清理 |
| [edge-preview-latency](edge-preview-latency/SKILL.md) | 网络预览、结果年龄与网页卡顿排查 |
| [gesture-action-gate](gesture-action-gate/SKILL.md) | 新帧确认、保持一次、移手释放及断线锁定 |
| [fpga-fair-benchmark](fpga-fair-benchmark/SKILL.md) | 同配置CPU对照、逐阶段指标与公平性能结论 |
| [fpga-project-handoff](fpga-project-handoff/SKILL.md) | 体积受限打包、源码/工件/证据追溯与解压校验 |

## 使用方式

可直接让助手读取对应SKILL.md并按本次任务使用。例如：“使用 skill/pynq-board-workflow/SKILL.md，先只读检查我的板卡环境和bit/hwh，不下载硬件。”

若使用支持本地技能发现的Codex，可将通用技能整个目录复制到个人 skills 目录（例如 ~/.codex/skills/pynq-board-workflow），再通过 `$pynq-board-workflow` 调用。本次只加入交接包，没有自动安装或修改个人工具设置。安装后以实际工具发现结果为准。

通用技能所需参考和脚本都在其目录内。其余8个技能的案例链接依赖本包目录结构；移到个人技能目录后，应提供项目根路径并按包内原相对路径查阅案例，不能声称案例也已安装。

## 检查与证据边界

[validation_report.json](validation_report.json)记录9个技能格式、链接和环境盘点脚本的主机检查。没有新训练、板测或Vivado重建；技能数量增加不代表系统加速幅度增加。

原golden_check.py、提示词和故障清单继续保留。以下为原项目技能总结，其中版本整体优化与纯PL贡献应按新增公平测量技能区分。

---

# 可复用PS/PL协同验证技能包

此目录是竞赛技能包，不会安装到个人工具或替用户执行外部操作。可用于其他PYNQ/SoC加速题目，核心方法不依赖手势类别和本板型号；具体PS/DDR/时钟参数仍须由新设计提供。

## 1 使用范围

适用：模型/算子从CPU迁往PL，需核对输入输出、驻留参数、DMA及整机收益；跨设备经网络展示，需要区分预览、识别与交互延迟。输入是原模型/黄金张量/设计接口、硬件工件和计时样本。

不适用：没有原始参考结果却要求证明数值正确；换板直接套用本项目PS配置；硬件未知时钟/复位状态仍尝试任意PL MMIO；用吞吐冒充单帧延迟。

## 2 可复用流程

1. 建立不可变模型/预处理/类别/bit+hwh哈希，先确认测的是同一对象。
2. 在硬件访问前核对器件、PS配置、复位极性和名义/实际时钟。合法范围来自设计及平台，不能为消除报错盲目放宽。
3. HLS C参考与host侧包格式先通过；用零/边界/随机/真实输入及参数重载测试功能。
4. 输入输出buffer明确所有权，缓存维护与复制时间纳入调用计时；每帧结果关联源序号与模型，只有一个DMA所有者。
5. 比较同一固定输入，预热、正反顺序、真实后台负载，保留每次样本，不只报最好一次。
6. 分别计算算子/完整网络/整帧处理/源图年龄/结果间隔；图像显示帧率不能作为识别吞吐。
7. 真实应用用session+seq去重，断线/过期锁定，不用预览或旧结果触发动作。
8. 对没有收益的候选明确否决，保留回退和失败证据；打包源码/参数/IP/构建脚本/版本/原始测量。

## 3 工具使用

golden_check.py只读取NumPy数组，不访问板卡：

```text
python skill/golden_check.py --reference reference.npy --actual accelerator_output.npy --atol 1e-4 --rtol 1e-4
```

应使用同一输入得到的真实输出，不用黄金文件复制冒充板上结果。文件名、形状、误差阈值由新任务配置；allow_pickle=False，非有限/形状不符直接失败。对分类还需核对top-1及概率，对检测需核对NMS后的数量、坐标和分数，不能只看一个卷积张量。

prompt_templates.md给出可复用提示词；troubleshooting.md说明触发条件、观察、排查和边界。

## 4 来源和已验证效果

来自本队复位/时钟断连、参数驻留、局部加速整机无收益、Notebook输出误入哈希、vendor部分解压、CPU线程争抢和流水线延迟变高等观察。现版同图714比较、真实订单、硬件独立对照以及本地失败注入有证据。第四版最终配置处理耗时相对第二版下降35.7%，不是对任意模型/板卡的保证。

泛化边界：DMA地址、器件、时钟范围、模型维度/阈值不可原样套用。可迁移的是验证顺序、来源锁定、所有权和测量口径。
