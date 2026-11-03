# 主机回归复现

直接部署板卡不需要这些PC测试。若要复现本地数值/线程回归，先安装requirements_host.txt所列依赖，再创建独立副本工作区：

```text
python tools/prepare_host_workspace.py --destination D:/gesture_v4_host_check
```

该工具不覆盖非空目录，复原测试期目录布局，包含原模型、原手掌代码、旧版AST对照和当前硬件分段。

在新工作区运行gesture_order_accel_v4/tests/test_pipeline.py（线程/规则10项）、check_models.py（51图×14配置数值检查）、check_benchmark.py（编排）、check_complete_flow.py（完整流程异常导出）。check_order_transport.py使用127.0.0.1真实HTTP和原客户端，需本机允许回环网络。

这些PC测试的相机/FPGA有替身，不是上板或识别准确率证据。原本地主机使用Python3.12、OpenCV4.10.0、ORT1.31.1；实际板测ORT1.23.2。requirements_host给API最低依赖范围，不代表锁定原本地主机全部环境；关键性能结论以板测文件为准。硬件HLS重建使用2025.2，另见hardware_rebuild.md。
