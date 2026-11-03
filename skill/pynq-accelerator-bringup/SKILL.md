---
name: pynq-accelerator-bringup
description: 对已有自定义 PYNQ 加速器执行分层联调，核对 HLS 包协议、参数驻留、DMA 所有权与数值一致性。用于核已构建但运行超时或输出异常的项目。
---

# 自定义加速核联调

先读当前设计/驱动契约，再做硬件事务。若仅有环境或 Overlay 概念问题，可使用通用 PYNQ 技能；这里重点是已有核的协议与数值。

1. 配对 bit/hwh、IP源码、参数和模型，验证各自清单；校验哈希不等于已完成板测。
2. 静态核对时钟、复位、地址、接口宽度、长度和 packet header。按实际驱动确认 LOAD/RUN、bank编号、字节序和应答长度，不能另造简化协议。
3. 先做主机 packet/参考计算，再 HLS C 和适用的 RTL检查。记录仿真是否用了替身；快速功能绑定不等于完整原厂模型端到端 cosim。
4. 板上首次测试使用已有有界驱动、最小已知向量、唯一 DMA 所有者。输出完整接收后才递增成功计数，捕获异常时保存状态与本次输入身份。
5. 比较零、边界、随机和真实输入，检查首次LOAD、重复RUN、参数重载。输出与黄金参考逐元素比，之后检查整网 logits/top-1；不能只比最终标签。
6. 发生超时时停止新事务。确认核/通道停止后再释放buffer；无法可靠恢复就明确要求内核或设备恢复，禁止一边卡住一边重载核继续操作。

## 可直接查阅的本项目实现

- [包契约](../../src/project/hardware/gesture_block_accel_v2/blocks16_driver/packet.py)
- [驱动](../../src/project/hardware/gesture_block_accel_v2/blocks16_driver/accelerator.py)
- [硬件包验证](../../src/project/hardware/gesture_block_accel_v2/board/verify_package.py)
- [板上验证](../../src/project/hardware/gesture_block_accel_v2/board/validate_hardware.py)
- [通用数组比较工具](../golden_check.py)：从项目根运行 `python skill/golden_check.py --reference ref.npy --actual actual.npy --atol 1e-4 --rtol 1e-4`，容差应按当前设计约定设置。

不得把 ref.npy 复制成 actual.npy 冒充硬件结果。数组工具不验证时序、DMA完成或模型识别准确率。
