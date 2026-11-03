---
name: pynq-board-workflow
description: 通用 PYNQ 板卡开发与排错，涵盖环境盘点、Overlay 与 HWH 核对、PS/PL 接口、DMA、Notebook 资源管理和显示链路。适用于新建或接手 PYNQ 项目；板型、地址和时钟必须来自当前工程。
---

# 通用 PYNQ 开发技能

目标是让当前板卡上的软件、硬件工件和运行环境对应起来，再逐层定位故障。不要从某个演示项目复制地址、时钟或 PS 配置来试错。

## 先确定工作层级

收集板卡型号/修订号、FPGA 完整器件号、系统镜像来源、Python/PYNQ 版本、当前 bit/hwh、目标现象及错误原文。能从现有工程读取的先读，不要求用户重复提供。区分：

- 只排查 Python、依赖、路径或网络：通常无需下载 bitstream。
- 部署已生成 Overlay：先验证工件和兼容性，再访问硬件。
- 修改 RTL/HLS 或 BD：需对应 Vivado/Vitis 工具链和新一轮软硬件验证。
- 换板：重新核对 PS、DDR、MIO、接口和约束，不以 PYNQ 名称相同推断兼容。

## 按任务读取

- 新板/换内核/缺模块：[环境与生命周期](references/environment.md)。可运行 `scripts/inspect_pynq.py` 输出只读盘点；它不导入 PYNQ、不打开设备、不加载 Overlay。
- 加载硬件、寄存器或 DMA：[Overlay 与 DMA](references/overlay-dma.md)。地址从当前 HWH 和驱动契约读取。
- USB 相机、HDMI、网页显示：[输入输出与网络](references/io-network.md)。区分显示刷新、识别频率及结果年龄。
- 卡住、断连或重复运行失败：[故障定位](references/troubleshooting.md)。先保存状态，再选择与故障层级匹配的恢复方式。
- 需要报告/交接：[交付检查](references/delivery.md)。本次没做的上板测试不写为通过。

## 操作边界

1. 保留当前可用工件和环境快照，在候选副本修改。
2. 一个硬件资源只由一个明确所有者管理。换 Overlay 前结束相关 DMA、视频与工作线程；不要让多个 Notebook 同时操作同一核。
3. 先静态校验、软件参考、最小硬件事务，再完整应用。寄存器访问也可能因时钟/复位错误挂起，不能把任意 MMIO 读写当成安全探测。
4. 超时后先确认事务是否真正停止，再释放 buffer。Python 线程超时或 Kernel 停止不证明 PL 停止；驱动无法恢复时报告需重启的状态，不循环重试。
5. 用户任务的授权范围不因本技能扩大；不顺带升级系统、改网络配置或控制其他外设。

输出应包含：确认的环境、工件标识、问题所在层、最小改动、实际验证结果和待板测项。用户只问概念时不执行硬件操作。

## 依据与适用版本

参考 [PYNQ Overlay](https://pynq.readthedocs.io/en/latest/pynq_libraries/overlay.html)、[DMA](https://pynq.readthedocs.io/en/latest/pynq_libraries/dma.html)、[allocate](https://pynq.readthedocs.io/en/latest/pynq_libraries/allocate.html)。这些是 latest 文档入口；实际 API 和驱动行为应对照目标板已安装版本。

本技能提炼自 PYNQ-ZU 项目的实际问题，但不依赖其模型、IP 名称、地址或 100 MHz 配置。附带脚本只有主机侧验证，不代表已在所有 PYNQ 板型验证。
