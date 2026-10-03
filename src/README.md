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
