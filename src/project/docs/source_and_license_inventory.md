# 来源与许可证清点

本包是内部交接，没有替用户决定公开发布许可证，也没有将AMD或模型/数据集自动改成MIT/Apache。

| 材料 | 可核对来源 | 状态 |
|---|---|---|
| 第四版应用与驱动/HLS自写代码 | 当前协作工作区及已验证R1发布包，SHA清单 | 团队应确认整体开源许可与作者标注 |
| 最终分类模型3文件 | 队友gesture4_model_v2_handoff.zip，ONNX SHA568660... | 权重已打包；训练代码/数据/预训练来源及许可由模型方补 |
| 手掌ONNX、mp_palmdet.py | 队友原PYNQ_ZU_PL_handoff_v1(2).zip中board/gesture_assets；SHA见环境表 | 不擅自推断数据集/模型分发许可；队友补原始来源链接/声明 |
| cola/fries图片 | 队友点餐源包及当前笔记本assets | 图片来源/使用权待队友核对 |
| burger图片 | 当前笔记本download_cache中由板端服务下载的136×136缩略图 | 保留为补充；现板采集原始菜图；来源许可待核对 |
| Vivado/HLS生成IP、原厂primitive | Vivado/Vitis2025.2生成结果 | 保留AMD原始版权/许可标记，使用安装工具及许可条件 |
| ORT1.23.2及依赖wheel | PyPI原始wheel，包内METADATA/许可原样保留 | 可检查wheel，不剥离第三方声明 |
| OpenCV实际ARM运行库 | 当前板卡gesture_runtime_cv410 | 尚待只读采集，不冒充其他构建 |
| PYNQ与SD镜像 | 用户报告pynq_zu_2022_10_07.img | 不打包整镜像；记录版本，建议保存实际镜像来源与校验值 |
| 竞赛/板卡PDF | 用户提供，仅供本队核对要求 | 正式公开仓库可改为来源链接或按权利方授权处理 |

模型元数据中的board_tested:false/runtime:CPU baseline是模型方原始描述，已保留不篡改；当前硬件及系统验证证据独立存档。不能因此选错旧模型，也不能把本包测试写成模型方原始声明。

新笔记本电脑可按requirements-laptop.txt安装依赖；对应包自身许可证由发行包保留。公开前尤其核对模型/训练集和菜图，不以代码许可证覆盖它们。
