# 第四版R1最终候选操作说明

推荐使用01_one_run_v4.ipynb的3个代码框完成整轮；原00分步Notebook保留作排查入口。

本版保留原始FP32模型、预处理、手势类别、置信度与保持/移手解锁规则，复用已验证的FPGA v2及DMA。改进CPU线程配置，并尝试检测/分类跨帧流水线。它是协同系统第四版，不是新PL比特流；不把CPU收益算成新增FPGA核收益。

## 上传与安装

1. 笔记本点餐命令行Ctrl+C。
2. 板端原服务器Notebook顶部■一次，等待ORDER_BOARD_SERVER_STOPPED；关闭旧内核，不只关闭标签页。
3. 下载gesture_order_accel_v4_r1.zip和install_gesture_order_accel_v4_r1.py，上传到/home/xilinx/jupyter_notebooks根目录。不要先解压，不放进旧应用目录。
4. 新建Python 3 Notebook，运行：

```python
import runpy
runpy.run_path('/home/xilinx/jupyter_notebooks/install_gesture_order_accel_v4_r1.py',run_name='__main__')
```

正常出现V4_APP_INSTALLED。它只写新目录，不加载硬件，不覆盖第二/三版，不安装系统包。若同名第四版目录存在但不可变文件不同，先改名留存，再重新安装；不要覆盖有用日志。

## 首次验证

打开gesture_order_accel_v4/00_final_candidate_v4.ipynb，使用新的Python 3内核。保持原摄像头朝向，逐个代码框运行，不运行全部。

| 部分 | 操作 | 正常结果 |
|---|---|---|
| 1 | 离线解压运行库到本程序vendor | V4_RUNTIME_READY |
| 2 | 核对模型、原FPGA v2、摄像头和端口 | V4_PREFLIGHT_OK，不下载硬件 |
| 3 | 同图数值＋性能对照 | V4_VALIDATION_OK、选定配置和分别计量的指标 |
| 4 | 实际点餐联调 | ORDER_BOARD_SERVER_READY port=8765，持续[*]正常 |
| 5 | 停止后打包 | 蓝色链接下载gesture_order_accel_v4_results.zip |
| 6 | 后续读取已保存的通过报告启动 | 首次跳过；后续内核重启后运行1、2、6即可 |

第3部分覆盖48张实拍图及黑图、灰图、固定噪声图，逐配置校验；性能用同一张已检出手的固定图，真实摄像头和预览同时后台运行。14种配置，正反顺序28组，每组2次预热＋12个结果。通常按15—30分钟预留，实际依板速。输出会持续更新。任何检查失败，先第5部分导出，不删除检查。不用摆手，不发送点餐动作。

可以先只运行1、2、3，再5导出给开发者检查。若进入4：笔记本继续原start_laptop.bat，界面、菜品和笔记本HDMI不改。三菜各一份33元模拟订单提交后，重做：V返回/取消退出、点赞保持5秒只加一次、移手后握拳减一份、断线不操作且重连保留购物车并移手解锁。流水线改变时序，本轮需要重新回归。

结束顺序：笔记本Ctrl+C → 板端■一次 → ORDER_BOARD_SERVER_STOPPED → 第5部分下载。发回板端ZIP和笔记本本次logs。数据及回归都确认后才能定版。

## 架构与衡量方式

- v2_reference：第二版，原线程OpenCV检测＋OpenCV分类前后段＋FPGA v2。
- v3_reference：第三版已采用的hybrid_ort2，OpenCV全局4线程、ORT检测/分类前后段2线程、同一FPGA v2。
- serial_cv1_t1/2/3/4：OpenCV后台全局1线程，ORT采用1/2/4线程，串行检测和分类。
- pipe_cv1_d2_c2、pipe_cv1_d1_c2、pipe_cv1_d2_c1、pipe_cv1_d3_c1：同一帧先检测再分类，跨不同帧重叠检测与分类。最新待分类槽只有1个，忙时新检测结果替换旧待处理帧，不积压。检测/分类各自单线程所有者；DMA与FPGA只有分类线程调用，调用保持串行。
- cpu_serial_cv1_t2/3、cpu_pipe_cv1_t2、cpu_pipe_cv1_d3_c1：匹配的ORT纯CPU对照，不参与FPGA点餐路径选择。

每个发布结果都来自同一张有源序号/采集时间的图，检测与分类不混帧；不缓存旧检测代替新检测。流水线可能丢弃尚未开始分类的过时检测帧，此计数保存在pending_replaced中；不会重发旧分类来假装提高识别帧率。

三类指标分别记录：
1. detector_plus_classifier_ms：同帧检测＋分类处理耗时，便于与第二/三版比较；FPGA调用已经包含在分类时间内。
2. frame_age_ms：源图发布到结果完成的延迟，包含调度等待；不含摄像头曝光/USB传输、网络、界面与保持确认。
3. result_interval_ms：相邻新结果的间隔，衡量吞吐。流水线吞吐变高不代表单帧延迟变低，25%目标分别标记，不混用。

选择要求：数值全通过、采集>=10fps、预览>=8fps；相对本轮第三版参考，中位每帧延迟不恶化超过5%、P95不恶化超过10%，并有至少5%延迟下降或15%结果间隔下降，且正反两轮都满足收益与延迟条件。合格候选中，优先满足相对第二版25%延迟/处理耗时目标，再优先低延迟，在与最佳延迟接近的候选中选择较短结果间隔。无稳健收益时明确选v3_reference，不假装第四版达标。纯CPU比较如实保留。

所有不可变源码、样本、依赖均哈希检查。Notebook和输出目录明确允许变化。原始模型和FPGA bit/hwh核对固定SHA。错误时不会自动切纯CPU。

## 为什么保留FP32

本地探索过检测及分类前后段INT8候选。检测坐标出现较大偏差，分类置信度偏差也超过预设范围，因此没有打包这些模型，不降低阈值强行通过。保留原FP32识别链路，避免临近提交引入量化识别波动。

CPU/FPGA协同收益必须与新增PL核收益区分；本版PL仍是gesture_blocks56_fp32_pw16_v2。已有两块FPGA相对CPU的局部提速证据保留；本版新增的是线程调度/流水线实验。不能把流水线结果间隔减少写成整机延迟等比例减少。

## 重现与回退

板端依赖原gesture_block_accel_v2、gesture_assets、gesture4_model_v2、gesture_runtime_cv410、gesture_order_demo_v2/assets；不加载HDMI BaseOverlay。离线ORT1.23.2及依赖随包保留许可/元数据，沿用板上NumPy。目标Linux ARM64、Python3.10、glibc>=2.27。电脑本地测试使用不同ORT版本时会记录，不能替代ARM板测。

每轮原始报告在results/v4_*/report.json；实际日志在logs/。停止本版并关闭内核后，可回到第三版已验证的启动方式。第四版重启时运行Notebook 1、2、6，复用最近一次通过报告；若源码或硬件变化、最近一次失败，不会自动绕过。

交接时保留本包及原FPGA v2 HLS/Vivado源工程、构建脚本、IP、bit/hwh、模型来源/许可和板测报告。验证包本身不是赛事全部材料；设计报告、AI协作记录、skill包等仍需汇总。

参考：https://onnxruntime.ai/docs/performance/tune-performance/threading.html


## R1推荐的一次完整运行入口

本次推荐打开01_one_run_v4.ipynb。只有3个代码框：路径/离线库、预检查、完整运行。第三个框会自动完成数值检查和28组对照，再启动选中的FPGA服务器；停止后自动导出。看到ORDER_BOARD_SERVER_READY才去笔记本运行原start_laptop.bat，[*]正常。完成点餐后笔记本Ctrl+C、板端■一次，等待下载链接。

R1专用上传文件为gesture_order_accel_v4_r1.zip及install_gesture_order_accel_v4_r1.py，在根目录用runpy运行后者。旧第四版文件不用混装。如果已经安装旧第四版，停止其内核后将gesture_order_accel_v4文件夹改名留存，再运行新安装脚本；第三版不动。

新增3线程串行、检测2/分类1及检测3/分类1配置，并增加相匹配的CPU对照。原笔记本RemoteOrderState/GestureGate/OrderStore通过本机HTTP与真实流水线线程联调：包含5秒持续保持、减一份、V返回/取消、断线状态和重连锁定、33元模拟订单保存、重复轮询抑制及独立预览。摄像头和神经网络在该联调中为测试替身，不等于真实板卡或识别精度验证。

输出V4_GOALS明确区分处理耗时/每帧延迟/吞吐目标。只有本轮板测和实际点餐都确认，才定最终版。自动运行结束不等于订单验收通过，也不保证板上一定达到25%目标。
