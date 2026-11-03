# 构建入口

HLS C++和Tcl可在src/project/hardware/gesture_block_accel_v2查看。generated_ip.zip与vivado_sources.zip保持原生成文件名/内容。需要重建时先解压board/validated_runtime.rar，在完整目录副本按docs/hardware_rebuild.md操作。

使用原工具链Vivado/Vitis 2025.2与目标器件xczu5eg-sfvc784-1-e；工具安装位置需按本机调整。源配置摘录没有已布线DCP或构建缓存，需重新生成产品；本次未新执行Vivado或仿真。现有已校验bit/hwh在部署归档。
