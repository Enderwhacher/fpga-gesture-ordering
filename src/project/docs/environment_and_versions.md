# 环境、版本与依赖边界

冻结设备：PYNQ-ZU XCZU5EG-sfvc784-1-e。用户报告SD镜像文件pynq_zu_2022_10_07.img；本包不含镜像本体，不把该文件名当成镜像校验值。实际板上Python3.10.4、PYNQ3.0；第四版板测报告记录ORT1.23.2、NumPy1.21.5、OpenCV4.10.0。板上CPU采样频率约1.2GHz，不能假定其他配置性能相同。

工具：Vivado/Vitis2025.2；器件xczu5eg-sfvc784-1-e；设计目标PL时钟100MHz。实际分频允许与名义值略有差异，由已验证驱动95—105MHz门槛保护，不能为绕过未知错误任意放宽。

| 文件 | SHA256 |
|---|---|
| 最终分类ONNX | 568660b57f4cd01cacae40d64df9124e9194c7fbcc42f8245839eb691badf741 |
| hagrid_runtime.py | 065f0ba1f30908b223d148178a22bd29c7eeaae58ff58a2b1611b529a298d24f |
| model_meta.json | eb1bb16df09fb57d8a29e98b6789a482fa4e292e98a5febb6afea8e03ae6b15c |
| 手掌检测ONNX | 78ff51c38496b7fc8b8ebdb6cc8c1abb02fa6c38427c6848254cdaba57fcce7c |
| mp_palmdet.py | f06ce44a9b77e12b49d72416388829fd1a481ffe7a516d914e5a8c6ca50710be |
| FPGA bit | a7732997d677c89e16f6981625c796d4d9e5e34fe235dfbbb95328f03b91f89a |
| FPGA hwh | 8ed7017eb013a49bdb08b0150f4c625106dada999220d38ae8dd64c7d8e3be3f |
| HLS IP ZIP | f975b911df9d06c48bf33fd04f2596e2bebd7ed5fb185d0530cb5698c80904d7 |
| R1应用清单 | c7bddd586b7a310b749256f0cf35ab8c8180ee4067c4fe95531e888eee906a74 |

ORT运行库随software/board/.../wheels和R1 ZIP提供，Linux ARM64 Python3.10、glibc>=2.27，8个wheel保持原许可。NumPy沿用板上版本；本轮实测1.21.5可加载运行，ORT wheel包元数据声明numpy>=1.21.6，属于实际环境与包要求的差异，不能把现板直接pip升级而假定结果仍等价。正式复现优先保存现用环境；若升级依赖，另跑数值/性能回归。

## 唯一尚未从板上取回的关键运行快照

本机没有/home/xilinx/jupyter_notebooks/gesture_runtime_cv410目录及其准确构建内容。不能用一个同版本号wheel冒充该构建。工具collect_board_dependencies.py只读取相关目录和版本，不访问摄像头/Overlay/DMA。

上传该脚本到根目录，新的Python 3代码框运行：

```python
import runpy
runpy.run_path('/home/xilinx/jupyter_notebooks/collect_board_dependencies.py',run_name='__main__')
```

下载v4_board_dependencies.zip，和本交接包一起保存/给队友。它包含现用OpenCV目录、原模型/代码/菜图的快照、版本JSON、OpenCV构建信息及文件哈希，不包含整张SD镜像、登录凭据或其他项目目录。与本包板端模型对照哈希后再合并。

PYNQ系统、Linux共享库和板卡镜像仍是运行前提，不要在其他型号板卡仅复制PS配置并认为可用。预先生成的bit/hwh足够当前演示；工具安装环境仅用于复建硬件。

笔记本原app_manifest.json中的compute_release仍是早期单层核标签，它不负责选择硬件；当前实际后端由板端/API日志的hardware_release与ps_config确认。本包保留原验证字节，勿据该历史标签误换回旧核。
