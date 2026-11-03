# Vivado/HLS工程与复建

## 精简包中的 Vivado 源工程

hardware/vivado_sources 保留原工程 XPR、BD、IP 仓库与 wrapper，未包含 gblock.runs、缓存和大型自动生成输出产品。
该副本仅作源码查看与重建起点，本次未在 Vivado 重新打开/综合；不要认为它带有原已布线设计。
原完整工程的重新打开与布线检查记录属于历史完整包，仍在 evidence 中，不代表本精简目录测试通过。
当前已验证 bit/hwh 原样保留在 hardware/gesture_block_accel_v2/overlay。
从源码重建优先使用下述配套 Tcl/工具；需要查看原布线 DCP 时使用另存的完整项目包。

## C/C++、Verilog在哪里

- HLS可综合C++：hardware/gesture_block_accel_v2/hls/src/blocks56_axis.cpp及blocks56_axis.h。
- C测试台：hls/tb/test_blocks.cpp，六组向量、参数重载/零参数恒等检查。
- 生成Verilog：hardware/generated_ip/hdl/verilog；VHDL/XCI/component.xml及约束保留原结构。其来源ZIP在hls/ip/gesture_blocks56_axis.zip，不能只复制顶层.v而丢子模块/IP元数据。
- AXI/驱动：blocks16_driver及blocks16_runtime.py；PS主程序是Python，无需虚构一个C主程序。
- Tcl：hls/run_hls.tcl、hls/setup_rtl.tcl、vivado/build.tcl、vivado/restore_ps.tcl；板卡PS源参数在board_baseline/ps_2022_1_parameters.tsv。
- 生成系统顶层HDL、BD、各IP配置和实现约束可从 hardware/vivado_sources 的源配置查看，生成产品需重新构建。

## 从源码重新生成（在副本工作区进行）

保持目录名gesture_block_accel_v2，在其父目录留出b3w作为构建目录，不混用旧b2w。Python需要NumPy/OpenCV/ONNX/ORT等，工具需安装2025.2并支持xczu5eg器件。旧工具默认路径E:/AMDDesignTools/2025.2，不同安装位置需要在工作副本调整或传入参数，不能修改冻结证据后仍声称原SHA未变。

1. 先用现有导出的模型、参数和golden向量复建；无需重新训练，也不要先跑export覆盖冻结数据。
2. Vitis运行HLS：

```text
E:\AMDDesignTools\2025.2\Vitis\bin\vitis-run.bat --mode hls --tcl hls/run_hls.tcl
```

3. `python tools/prepare_vivado.py`准备b3w/ip_repo与HLS汇总。它会将RTL通过状态重置为False，提醒尚需重新验证，属于预期行为。
4. `vitis-run.bat --mode hls --tcl hls/setup_rtl.tcl`生成RTL仿真准备文件。现有快速RTL路线为`python tools/fast_rtl.py prepare`，再用Vivado XSIM编译/运行生成的build/fast_rtl_test/fast_rtl.prj及fp_equivalence.prj，最后`python tools/fast_rtl.py verify`。此路径的浮点primitive使用单独与原厂模型比较的功能绑定；不是全设计原厂端到端cosim。具体命令与已有run.tcl、prj由工具生成，原运行日志和结果在hls/reports中，不能把旧结果当本次新运行。
5. 运行hardware包内driver/runtime/source测试后，可执行：

```text
python tools/build_local.py --vivado E:/AMDDesignTools/2025.2/Vivado/bin/vivado.bat --jobs 4
```

脚本会创建/恢复Vivado工程、实现、导出bit/hwh并审计。发布门槛还依赖真实完成的C/RTL/驱动/数值检查；没有新运行就不应手工改passed。

## 原始验证范围

当前冻结硬件的C仿真、HLS综合、生成RTL接口/控制与3组完整输出、3567次浮点primitive逐位/逐周期检查、Vivado实现/时序/HWH、板上新旧数值与计时、第四版真实订单均有证据。全设计原厂模型端到端cosim未完成，不作为已通过项目。

布局布线资源：LUT84,062，FF103,062，BRAM36 Tile126，URAM32，DSP973；目标100MHz，setup slack0.767ns、hold slack0.010ns。使用最终实现报告，不能拿HLS估算资源冒充布局布线值，不根据slack直接宣称另一个Fmax。

部署当前演示直接使用已验证bit/hwh，不需要队友重新构建硬件，更不需要重建HDMI TX或购买HDMI授权。
