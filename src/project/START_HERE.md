# FPGA 非接触式手势点餐系统 第四版代码提交包

本包以第四版 r1 与启动补充为基础，面向 200 MB 以内代码提交。
保留运行源码、HLS C++/测试台、生成 RTL/IP、Vivado Tcl/BD/IP 源配置、bit/hwh、完整模型与分段模型、
训练脚本与 best.pth、测试向量、菜单资源、离线 ORT wheels、关键报告和 02_restart_v4.ipynb。

移除完整 Vivado 归档中的综合/布线缓存、大型重复安装 ZIP、旧 OpenCV 恢复包与演示 PPT。
原完整项目保留独立副本。本代码包不包含布线 DCP，也不包含现场板卡完整 OpenCV 环境。
已提取 Vivado 源工程至 hardware/vivado_sources；重建说明见 docs/hardware_rebuild.md。

## 当前板卡启动

1. 停止旧笔记本服务；板端停止旧 Notebook，等待 ORDER_BOARD_SERVER_STOPPED，关闭旧内核。
2. 上传 deployment/02_restart_v4.ipynb 到 /home/xilinx/jupyter_notebooks/gesture_order_accel_v4/。
3. 新 Python 3 内核运行第1、2部分，依次确认 V4_PREFLIGHT_OK 和 ORDER_BOARD_SERVER_READY。
4. 笔记本进入 software/laptop，原电脑使用 start_laptop.bat；换电脑配置依赖后使用 start_laptop_portable.bat。
5. 浏览器 http://127.0.0.1:8080；板端默认 http://192.168.3.1:8765。显示器接笔记本 HDMI。
6. 停止后运行新 Notebook 第3部分导出日志。不重新测速，不加载 BaseOverlay。

## 查阅与校验

- 执行 python tools/verify_project_v4.py，全部一致时输出 PROJECT_V4_OK。
- project_manifest.json 是本精简包的文件清单；handoff_manifest.json 是历史原包记录。
- software/board、software/laptop：板端与电脑程序；training：训练代码、配置、权重和结果。
- hardware/gesture_block_accel_v2：HLS、驱动、Tcl、模型分段、参数、向量、bit/hwh。
- hardware/generated_ip：生成 RTL/IP；hardware/vivado_sources：源工程摘录。
- board_assets：最终分类/检测模型和菜图；evidence/final：原第四版实测证据。
- packaging/omitted_files.json：移除清单；packaging/source_snapshot.json：源工程提取记录。

整包打包与入口整理不构成新的板测或性能提升；原核心程序、模型、硬件文件不改写。
部署至新环境前阅读 docs/quickstart.md；旧说明存于 docs/full_package_reference，仅作完整包参考。
推荐解压至较短路径，例如 D:/gesture_v4_code，避免 Windows 自动生成 IP 路径过长。

## 新增可复用技能

本次补充9个独立技能，重点是可单独迁移的[通用PYNQ技能](skill/pynq-board-workflow/SKILL.md)。完整索引与使用方法见[技能目录](skill/readme.md)。新增内容不改变原运行代码、模型、硬件与实测结果。
