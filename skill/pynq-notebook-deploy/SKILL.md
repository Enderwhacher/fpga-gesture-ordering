---
name: pynq-notebook-deploy
description: 维护 PYNQ Notebook 项目的可重复启动、依赖路径、预检查、结果报告恢复和服务退出。用于 ROOT 丢失、缺模型、资源占用或部署入口交接。
---

# Notebook 可重复启动

启动应从新内核成立，不依赖上一次留下的 ROOT、模型对象或服务器实例。先定位缺的是变量、文件、依赖还是硬件工件，不用重新跑全部训练来修复路径。

1. 检查部署目录和必需文件，输出缺失路径。用实际 Notebook 内核的解释器确认依赖，不把系统 pip 成功当当前内核已可用。
2. 停旧服务、等待线程退出并关闭旧内核。摄像头/Overlay/DMA有占用时不要同时启动新实例。
3. 将纯静态预检查与硬件下载/启动分开；预检查通过不代表加速核已运行。
4. 若复用历史验证报告，检查当前应用、模型和 bit 身份与报告匹配，检查报告 passed 与重启要求。最新失败不能被悄悄跳过成“使用旧成功”。缺失报告时按项目恢复/验证流程处理，不手写 passed。
5. 观察服务 READY、后端身份、实际配置和成功完成计数，客户端连接后再测试新帧。日志必须能说明本次启动选择了哪个硬件版本。
6. finally中停止各资源并报告仍存活线程；正常停止和强制退出分别记录。

## 第四版入口实例

- [02_restart_v4.ipynb](../../src/project/software/board/gesture_order_accel_v4/02_restart_v4.ipynb)
- [启动校验与报告选择](../../src/project/software/board/gesture_order_accel_v4/start_v4.py)
- [部署说明](../../src/project/docs/quickstart.md)、[版本与依赖缺项](../../src/project/docs/environment_and_versions.md)

本项目板端常用根目录 `/home/xilinx/jupyter_notebooks`，它是本项目约定而非所有 PYNQ 的固定路径。当前加速核不依赖板卡HDMI，不要在启动时追加 BaseOverlay 覆盖其硬件。此技能不将旧安装ZIP缺失解释为源码缺失。
