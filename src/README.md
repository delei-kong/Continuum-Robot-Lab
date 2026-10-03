# Source

- `simulation/`：SOFA接口、场景、驱动输入和轨迹采集；
- `modeling/`：数据处理、动力学模型和训练；
- `control/`：控制器和闭环实验；
- `evaluation/`：指标、曲线和可视化。

本项目采用扁平源码结构，不额外创建项目名称二级目录。

轨迹跟踪实验通过 `control/tracking_contracts.py`、`simulation/trajectory.py`、
`simulation/tracking_pipeline.py` 和 `evaluation/recording.py` 的纯 Python 接口解耦轨迹、
控制器、仿真后端和记录器。SOFA 场景作为后端适配器接入，不应把通用实验编排重新写入
具体场景。

`simulation/scenes/trunk_trajectory_tracking.py` 将上述合同适配到官方 SoftRobots 逆向
QP 场景；`evaluation/tracking_metrics.py` 在仿真结束后统一写出 `trajectory.csv` 和
`performance.json`。控制循环只记录内存数据，不通过 CSV 驱动实时控制或绘图。

远端批处理可通过 `scripts/remote/run_trunk_trajectory_tracking.py` 选择已注册的轨迹和
控制器；该入口既可在本地 Mac 发起 SSH 任务，也可在远端工作区直接调用 SOFA batch。未带
参数时默认运行 `line + reference_goal`，输出名称自动使用 UTC 时间戳。

当前注册轨迹包括 `line`、`ellipse`、`circle`、`rounded_triangle` 和
`rounded_square`。圆角三角形与圆角正方形由闭合 Catmull–Rom 曲线生成，在控制点处保持
位置和速度连续；它们使用等时分段，不承诺严格恒定弧长速度。

在远端 XFCE 桌面中增加 `--gui` 即打开可视化窗口；不带该选项时只运行 batch 并生成结果包。
