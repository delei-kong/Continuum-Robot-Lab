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

控制器注册表包含 `reference_goal` 基线和 `task_space_pid` 任务空间外环原型；PID 已为五种
已验收轨迹登记保守低增益预设，但当前结果不代表 PID 优于 inverse QP 基线。

在远端 XFCE 桌面中增加 `--mode gui --target server` 即打开可视化窗口；不带该选项时只运行 batch
并生成结果包。

需要比较已批准的基线轨迹时，使用 `--batch baseline_trajectories --output <batch_id>`。批量矩阵由
代码注册，当前固定为 line 与 ellipse；每个 case 仍委托给同一单 case 执行内核，并在
`outputs/tracking_batches/<batch_id>/` 写入 `batch_manifest.json`、`summary.json` 和 `summary.csv`。

Koopman 阶段的正向数据采集由 `simulation/forward_data.py` 定义无 SOFA 依赖的动作安全、时间和激励
合同，并由 `scenes/trunk_forward_data.py` 将其接入直接绳驱 Trunk。每步记录实际执行绳索动作、绳索
位移与力、末端位置及中心线位置/速度；该链路不经过 inverse QP。

正向数据实验与 tracking 一样通过受控 Python 入口运行：

```bash
python scripts/experiment/run_forward_data.py \
  --input multisine_pilot --output <run_id> --mode batch
```

正式 `koopman_v1` 数据集通过 `--batch koopman_v1_train|koopman_v1_validation|koopman_v1_test`
选择固定的 episode 矩阵。`modeling/koopman_dataset.py` 定义 79 维状态、8 维动作、episode 内时序对齐和
质量审计；`scripts/experiment/audit_koopman_dataset.py` 只从已回传的受控 batch 组装数据集，不接受任意
CSV 路径。

审计通过的正式数据会物化到 `datasets/<dataset_id>/<release_id>/`，其 `transitions/<split>.npz` 固化
`state/action/next_state`、episode 边界和来源哈希；模型训练不再读取 `outputs/` 中的原始 run。
`modeling/koopman_model.py` 只读取这一规范数据集 release，使用训练 split 拟合归一化、线性仿射动力学
基线和固定随机 Fourier 升维的 EDMDc/Koopman 模型。验证 split 选择模型；测试 split 仅报告一次。
`scripts/experiment/train_koopman.py` 只接受受控数据集 ID、release ID 与新的模型输出 ID，不接受任意 CSV、
配置或模型路径。每个模型结果写入 `outputs/koopman_models/<output_id>/`，包含模型参数、归一化、数据来源
哈希、验证/测试的一步与多步指标以及标准完成状态。

`control/koopman_mpc_controller.py` 以验证选择后冻结的 Koopman 模型构造 10 步受约束滚动优化：末端位置
误差、动作幅值和动作变化率共同构成目标，8 路索长的非负、上界与单步变化率为硬约束。
`scripts/experiment/run_koopman_mpc.py` 是其独立受控入口；场景每步采集完整 79 维真实 SOFA 状态，输出
直接索长命令，并将模型来源、控制诊断和标准 tracking 指标写入运行产物。
