# Configs

存放可复现的仿真、数据生成、建模和控制配置。初期保持扁平；只有在配置数量明显增加后再按主题拆分。

正式实验必须把实际使用的配置快照保存到对应的 `outputs/<run_id>/` 中。

- `trunk_inverse_tracking.json`：25 Hz 单目标逆向跟踪；
- `trunk_inverse_periodic_random.json`：固定种子生成三个受约束随机点，并循环跟踪两轮。
- `trunk_trajectory_tracking_line.json`：轨迹评估 Pipeline 的 25 Hz 定时直线轨迹；先稳定
  1 秒，再用 5 秒移动到终点，最后保持 2 秒。
- `trunk_trajectory_tracking_ellipse.json`：相同 Pipeline 的 25 Hz 三维闭合椭圆轨迹；
  稳定 1 秒，用 12 秒完成一圈，再在起终点保持 1 秒。
- `trunk_trajectory_tracking_circle.json`：使用等长正交轴定义的三维圆形轨迹，时间阶段与
  椭圆一致。
- `trunk_trajectory_tracking_rounded_triangle.json`：通过三个控制点的闭合 Catmull–Rom
  圆角三角形轨迹。
- `trunk_trajectory_tracking_rounded_square.json`：通过四个控制点的闭合 Catmull–Rom
  圆角正方形轨迹。
- `trunk_forward_multisine_pilot.json`：Koopman 阶段的正向多绳数据采集 pilot；固定 8 绳
  多正弦激励、安全动作上限和中心线采样点。
- `koopman_dataset_v1.json`：正式 Koopman v1 数据集的 split 及行数、动作覆盖和限幅比例质量门禁。
- `koopman_model_v1.json`：正式 Koopman v1 的线性仿射基线、固定随机 Fourier 升维 EDMDc、训练集归一化
  以及独立 split 上的一步/多步预测评价口径。
- `koopman_model_v2.json`：三个预注册的固定 RFF 升维候选；仅允许在 validation 阶段选择，最终测试必须
  引用其冻结的选择输出。
- `trunk_koopman_mpc_line.json`：100 Hz 直驱 Koopman-MPC 基线；固定引用已完成最终评价的模型输出，
  并登记预测域、末端误差代价、动作/动作增量代价和 8 绳硬约束。
- `trunk_koopman_mpc_{ellipse,circle,triangle,square}.json`：同一 K-MPC 控制合同下、按正式数据集末端状态
  覆盖范围设计的中等幅值闭环轨迹集；椭圆、圆形采用解析周期轨迹，三角形、正方形采用平滑的闭合
  Catmull–Rom 轮廓。它们从自然下垂平衡点起步，避免在预热阶段人为制造模型外推。
- `trunk_forward_koopman_v1_*.json`：正式 Koopman v1 的逐 episode 本地参数文件；它们由 Git 忽略，
  但会通过 `scripts/remote/sync.include` 同步至远端执行镜像。实际使用的配置仍会快照进各 run 的
  `effective_config.json`，作为可追溯记录。

随机多目标配置保存种子、工作空间边界、点间距和距基座范围。实际生成坐标会随运行结果
写入 `generated_waypoints.json`，保证实验可复现。

轨迹评估配置通过 `trajectory.type`、`controller.type` 和 `backend.type` 选择可替换组件。
当前轨迹类型为 `timed_linear`、`periodic_ellipse` 和 `periodic_catmull_rom`，控制器为
`reference_goal` 和任务空间外环原型 `task_space_pid`，仿真后端为 `sofa_inverse_qp`。
`trunk_trajectory_tracking_*_pid.json` 是五种已验收轨迹的保守低增益 PID 初始预设。圆形复用椭圆解析模型的等长正交轴特例；
圆角多边形复用闭合 Catmull–Rom 模型。控制器负责生成任务空间目标，后端负责通过官方
逆向 QP 求解绳索驱动，二者不能混为同一组件。正式指标排除 `benchmark_warmup_steps`，同时在
`performance.json` 的 `tracking.all_steps` 保留全程指标。

Koopman-MPC 不使用 inverse QP：它直接对 8 路索长位移做滚动优化，模型状态严格复用训练数据的 79 维
状态合同。控制配置只能引用一个已完成 final 评价的模型输出；运行时会校验其 `COMPLETE`、最终评价状态和
validation 选择记录，拒绝从模型包中任意挑选候选。每个 K-MPC 配置复用 SofaValidation `Monitor` 显示橙色
实际末端轨迹，`trajectory_precision_s` 与 `trajectory_color_rgba` 只影响 GUI 显示，不改变控制或记录的数据合同。
