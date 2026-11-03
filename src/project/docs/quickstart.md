# 代码包部署说明

## 已运行第四版的板卡

按根目录 START_HERE.md 操作，只新增 02_restart_v4.ipynb 即可；模型、FPGA 和已有报告无需重装。

## 需要恢复至新目录

本精简代码包去掉重复的四个安装 ZIP，因此 deployment/install_* 原脚本不能在缺少原 ZIP 时直接执行。
这些安装脚本保留为源码参考；如使用完整项目包，可继续原安装流程。
若从本包恢复，在匹配 PYNQ-ZU 镜像的板卡上，将以下目录按完整结构复制到 /home/xilinx/jupyter_notebooks/：

| 本包来源 | 板端目录名 |
|---|---|
| software/board/gesture_order_accel_v4 | gesture_order_accel_v4 |
| hardware/gesture_block_accel_v2 | gesture_block_accel_v2 |
| board_assets/gesture_assets | gesture_assets |
| board_assets/gesture4_model_v2 | gesture4_model_v2 |
| board_assets/gesture_order_demo_v2 | gesture_order_demo_v2 |

已有同名目录时先保留原目录与日志，不直接覆盖不一致文件。
目录应包含原 manifest 校验需要的全部文件；不要只复制 bit/hwh 或几个 .py。
完整应用目录已附离线 ORT wheels；本机未持有现板 gesture_runtime_cv410 完整目录，仍需从原板采集运行环境。
deployment/repair_v4_runtime.py 和 collect_board_dependencies.py 为原修复/采集工具；细节见 docs/environment_and_versions.md。

同一块板、同一镜像恢复且无现有报告时，可按原 restore_validation_report.py 使用保留的 validated_report_v4.zip 恢复历史报告。
换板或换环境用 01_one_run_v4.ipynb 重新完整验证；不要把历史通过报告当作新环境的测试结果。
完成环境与验证后，新内核运行 02_restart_v4.ipynb 第1、2部分；最新报告失败时不能绕过。

## 笔记本

保留 software/laptop 整个目录。新电脑安装匹配的 Python，进入该目录执行：

```text
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-laptop.txt
```

板端 READY 后运行 start_laptop_portable.bat。原电脑可继续原 start_laptop.bat。
显示器接笔记本 HDMI；不运行 BaseOverlay，不用 start_demo.bat 证明 FPGA 功能。
