# 第四版日常启动更新

本更新解决新内核缺少 ROOT 变量、跳过初始化导致无法启动的问题。
不是新硬件或性能版本；保持第四版 r1、serial_cv1_t3、FPGA v2。

## 已经能运行的板卡（不重装）

1. 笔记本旧服务 Ctrl+C；板端旧 Notebook 停止一次，等待 ORDER_BOARD_SERVER_STOPPED，再关闭旧内核。
2. 上传 deployment/02_restart_v4.ipynb 至 /home/xilinx/jupyter_notebooks/gesture_order_accel_v4/。
3. 打开该文件，选择新的 Python 3 内核，运行第1部分，等待 V4_PREFLIGHT_OK。
4. 运行第2部分，等待 ORDER_BOARD_SERVER_READY port=8765。这个单元保持 [*] 是正常状态。
5. 原电脑继续双击已运行过的 start_laptop.bat；换电脑按 quickstart.md 配置依赖后使用 start_laptop_portable.bat。
6. 浏览器 http://127.0.0.1:8080；板端默认 http://192.168.3.1:8765。显示器连接笔记本 HDMI。
7. 停止时先笔记本 Ctrl+C，再板端停止一次，等待 STOPPED，运行新 Notebook 第3部分下载日志。

不要加载 BaseOverlay，不必重跑原长测，不必改模型或 bit/hwh。
若提示没有报告、最新报告失败、文件校验不符或内核缓存旧模块，按报错修复；不能删除失败报告或绕过校验。
新安装环境仍按 quickstart.md 安装硬件、应用、模型、运行库并验证；本入口不是完整安装器。
原安装器最后可能仍提示 01_one_run_v4.ipynb（完整验证入口）；日常启动用本新增入口。

## 给队友的项目更新方式

- 完整新版：直接解压 gesture_order_project_v4_startup.zip 到新目录，执行 python tools/verify_handoff.py。
- 小更新包：解压 gesture_order_v4_startup_update.zip，将其中 gesture_order_project_v4 下的内容复制到此前完整项目根目录；它包含更新后的文档、校验工具与 project_manifest.json。
- 板卡只需上传一个 02_restart_v4.ipynb，其他整合文件留在电脑交接目录。
- 原 R1 安装 ZIP、原应用 manifest、核心 Python、模型、bit/hwh 与历史证据逐字节保留。
- 新增入口是原补充包中的文件原样整合；补充包也保存在 deployment/，原核对记录保存在 evidence/startup/。
- 当前项目清单是 project_manifest.json；handoff_manifest.json 是历史原包清单，不代表修改后的说明文件。

## 验证范围

本机验证 Notebook JSON、Python 3.10 语法、初始化门禁、启动函数引用、原文件哈希与整合包文件清单。
本机未连接板卡，没有启动摄像头、下载比特流或产生新的性能测量。最终仍需在板端确认 READY 与实际点餐。
