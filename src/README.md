# Source

- `simulation/`：SOFA接口、场景、驱动输入和轨迹采集；
- `modeling/`：数据处理、动力学模型和训练；
- `control/`：控制器和闭环实验；
- `evaluation/`：指标、曲线和可视化；
- `experiment/`：受控实验注册表、配置步数推导、运行 manifest、SOFA 执行内核和执行入口。

本项目采用扁平源码结构，不额外创建项目名称二级目录。

轨迹跟踪实验通过 `control/tracking_contracts.py`、`simulation/trajectory.py`、
`simulation/tracking_pipeline.py` 和 `evaluation/recording.py` 的纯 Python 接口解耦轨迹、
控制器、仿真后端和记录器。SOFA 场景作为后端适配器接入，不应把通用实验编排重新写入
具体场景。

`simulation/scenes/trunk_trajectory_tracking.py` 将上述合同适配到官方 SoftRobots 逆向
QP 场景；`evaluation/tracking_metrics.py` 在仿真结束后统一写出 `trajectory.csv` 和
`performance.json`。控制循环只记录内存数据，不通过 CSV 驱动实时控制或绘图。

远端 batch 可通过 `scripts/experiment/run_tracking.py` 选择受支持的 tracking 输入和算法；
该入口既可在本地 Mac 发起 SSH 任务，也可在远端工作区直接调用 SOFA batch。受控规格会生成
`requested_config.json`、`effective_config.json` 与 `metadata.json`，由同一内核处理 batch/GUI 的
命令构建、日志、产物验证和完成状态。未带参数时默认运行 `line + reference_goal`，输出名称自动使用
UTC 时间戳。步数由配置推导，用户不能通过命令行传入任意场景或配置路径。

当前注册轨迹包括 `line`、`ellipse`、`circle`、`rounded_triangle` 和
`rounded_square`。圆角三角形与圆角正方形由闭合 Catmull–Rom 曲线生成，在控制点处保持
位置和速度连续；它们使用等时分段，不承诺严格恒定弧长速度。

在远端 XFCE 桌面中增加 `--mode gui --target server` 即打开可视化窗口；不带该选项时只运行 batch
并生成结果包。
