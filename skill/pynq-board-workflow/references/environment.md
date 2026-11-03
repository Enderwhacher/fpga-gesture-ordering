# 环境与资源生命周期

## 只读盘点

在实际执行项目的 Notebook 内核查看 `sys.executable`、Python 版本以及依赖来源；终端中的 Python 不一定是同一个环境。记录 PYNQ、NumPy、OpenCV、ONNX Runtime 版本与目标 CPU 架构。wheel 的 Python ABI、架构和系统库要求必须匹配；Windows x64 包不能拿到 Linux ARM 上使用。

配套脚本：

```text
python scripts/inspect_pynq.py --output environment.json
python scripts/inspect_pynq.py --bit /absolute/path/design.bit --output overlay_inventory.json
```

路径相对于本技能目录。脚本只读系统信息与指定 bit/hwh，写入一个新 JSON，不连接网络、不安装依赖、不访问 MMIO。已有输出不会覆盖；重复采集使用新文件名。没有提供 bit 时不会搜索整个磁盘。

版本号相同不等于构建相同：OpenCV 后端、优化选项和共享库可能不同。复现当前性能时保存构建信息与依赖清单，不直接升级现用环境来修复一个缺包问题。候选环境变化后重新验证数值和计时。

## Notebook 状态

ROOT、模型路径等在启动单元显式初始化，以当前部署结构解析，避免依赖旧内核变量。区分导入失败、路径不存在、模型契约错误和硬件失败；不能用宽泛 except 隐藏后续的失败。

摄像头/推理/显示启动前，确认旧服务已停止且旧工作线程已退出。使用 stop 事件、有限等待和 finally 回收资源。记录仍存活线程；不要仅打印“已释放”就当成完成。

线程仍运行或底层设备调用未返回时，不同时重开相机或重新下载 Overlay。内核重启只能清除 Python 状态；硬件恢复方式取决于具体 IP/驱动。重启前保存日志，不把强制退出当正常清理。

## 迁移清单

板型号/修订、器件、镜像来源、Python ABI、PYNQ 版本、依赖构建、外设连接、当前 bit/hwh 哈希、启动入口与工作目录。缺少项标为未知，不通过文件名推断镜像的 SHA 或授权状态。
