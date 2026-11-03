# 验证入口

先解压board/validated_runtime.rar，在运行包根目录安装requirements_host.txt对应依赖，再用tools/prepare_host_workspace.py创建独立测试副本。详见运行包docs/host_tests.md。

源码可在src/project/software/board/gesture_order_accel_v4/tests审阅。主机替身检查不等于板测；HLS/RTL重建参考build/readme.md。原始板测证据在data/evidence/final，不能将旧结果标为本次新运行。
