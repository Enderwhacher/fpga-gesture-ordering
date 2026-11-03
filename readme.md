# FPGA 非接触式手势点餐系统

基于 PYNQ-ZU RevB（XCZU5EG）的四类手势点餐演示。USB相机由板卡采集，PS执行手掌检测及分类前后段，PL加速MobileNetV3的两个连续残差块；笔记本通过HTTP接收结果与预览，并通过浏览器/HDMI显示菜单。

菜单包含汉堡、可乐、薯条，支持浏览、加入购物车、核对、取消与保存模拟订单。类别为张手、握拳、V和点赞；新结果保持确认后触发一次，明确移手后解锁。

## 仓库导航

|目录|内容|
|---|---|
|src/project|可浏览的PS Python、网页、HLS C++、Tcl、训练与导出代码及相关元数据|
|sim|主机验证、数值对照与仿真复现入口|
|build|生成RTL/IP与Vivado源配置归档、构建说明|
|board|包含模型、bit/hwh、离线依赖和9个Skill的已校验部署RAR|
|data/evidence|原始板测、同图性能报告、订单与复核证据|
|skill|通用PYNQ主技能和8个专项技能|
|report|设计报告来源、大模型协作记录|

## 复现与启动

1. 将 `board/validated_runtime.rar` 解压至短路径，例如 `D:/gesture_v4`。该归档保留完整运行目录及原文件名；仓库的src/project是供审阅的源码视图，不是可直接部署目录。
2. 阅读解压目录的START_HERE.md和docs/quickstart.md，按目录映射部署板端程序、模型与硬件。原始训练数据ZIP、预训练初始化权重及现场特定OpenCV构建未全部随包提供，详见运行包说明。
3. 在解压目录运行 `python tools/verify_project_v4.py` 核对647项清单。主机校验不访问板卡。
4. 已运行第四版的板卡上传02_restart_v4.ipynb至gesture_order_accel_v4，停止旧内核后运行第1、2部分，依次确认V4_PREFLIGHT_OK、ORDER_BOARD_SERVER_READY。
5. 笔记本运行software/laptop/start_laptop.bat；新电脑先配置依赖并使用portable入口。浏览器默认127.0.0.1:8080，板端默认192.168.3.1:8765，以现场配置为准。
6. 停止并导出日志。当前加速Overlay不含HDMI链路，显示器连接笔记本；不要另加载base覆盖加速核。

## 性能证据及范围

第四版检测+分类处理耗时中位数302.50ms；同配置CPU305.84ms，耗时降低约1.09%。第二版470.46ms至第四版的35.7%属于版本整体优化，不能全部归因于PL。局部核、整网、结果年龄、结果间隔和预览FPS分别统计，原始依据见data/evidence/final。

训练验证364/384（94.79%）来自参与最佳轮次选择的验证集，不是独立场景测试准确率。714组同图计算检查用于数值等价，不代表识别准确率。新增技能和本仓库整理未产生新训练、上板测量或硬件重建结果。

## 命名与归档

仓库目录和文件名均为ASCII英文，不含中文和空格。README/SKILL.md及生成IP的标准大小写按工具要求保留；厂商生成树置于build归档，避免修改大小写破坏IP引用。原硬件中文说明在源码视图改为operation_guide.md，映射见source_map.json；原始部署归档保持不变。

源码视图中的历史清单/路径仅用于审阅；运行时必须使用board归档内的原目录与清单。仓库自己的submission_manifest.json记录当前发布文件。

第三方模型/运行库/IP权利分别归原权利人；本仓库没有用一个统一新许可证覆盖第三方内容。来源及许可范围见src/project/docs/source_and_license_inventory.md。
