# 第四版整合记录

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
