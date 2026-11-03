# 两个残差块 FPGA 加速 v2：PW16

这是 `gesture_blocks56_fp32_pw16_v2`，使用原 HaGRID MobileNetV3 模型及 FP32 参数，仍替换 features.5 和 features.6，未加速 CPU 手掌检测网络。

- 点卷积：8 输出通道 ×16 输入通道并行；原版为 8×8。
- 深度卷积：保留 2 通道并行。
- 权重布局：片内 BRAM，40/120 输入通道分别按48/128补零计算；外部传输参数和张量格式不变。
- 参数：两个驻留参数区，初始化加载一次。每次 RUN 输入125456字节、输出125440字节。
- 独立命名空间：`blocks16_runtime.py`、`blocks16_driver`；IP VLNV 版本2.0。
- 硬件：PS＋DMA＋卷积核，100 MHz 目标，不含板卡 HDMI。

请与 `gesture_order_blocks56_process_v4` 一起安装，使用该目录下 `00_process_v4.ipynb` 完成新旧硬件对照、分进程对照和实际点餐。不要用本目录旧名称的临时开发文件启动程序。正式包仅发布新版运行入口。

本地验证包括六组 C 数值向量、零参数恒等与恢复参数、生成 RTL 的实际控制/存储/AXIS 握手，以及3组完整输出。RTL 仅浮点仿真绑定替换为单独与原 AMD IP 做过3567次逐位/逐周期检查的模型；未完成全设计原厂模型端到端仿真。

相同 AXIS 背压测试条件下，RUN 从573941周期降至472233周期，减少17.7%，约1.22倍。这不是板上完整分类或系统速度结论。新旧两版的详细证据由打包清单与 `hls/reports`、`vivado/reports` 保存。板测前 `board_tested` 保持 false。

复现：Vitis 2025.2 执行 `hls/run_hls.tcl`，`tools/prepare_vivado.py` 提取独立 b3w IP 仓库；按 `hls/setup_rtl.tcl` 与 `tools/fast_rtl.py` 完成仿真；`tools/build_local.py` 执行 Vivado 独立工程、HWH 审计和带门槛的发布。完整硬件构建、时序及哈希通过后才允许发布。
