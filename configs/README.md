# Configs

存放可复现的仿真、数据生成、建模和控制配置。初期保持扁平；只有在配置数量明显增加后再按主题拆分。

正式实验必须把实际使用的配置快照保存到对应的 `outputs/<run_id>/` 中。

- `trunk_inverse_tracking.json`：25 Hz 单目标逆向跟踪；
- `trunk_inverse_periodic_random.json`：固定种子生成三个受约束随机点，并循环跟踪两轮。
- `trunk_trajectory_tracking_line.json`：轨迹评估 Pipeline 的 25 Hz 定时直线轨迹；先稳定
  1 秒，再用 5 秒移动到终点，最后保持 2 秒。
- `trunk_trajectory_tracking_ellipse.json`：相同 Pipeline 的 25 Hz 三维闭合椭圆轨迹；
  稳定 1 秒，用 12 秒完成一圈，再在起终点保持 1 秒。

随机多目标配置保存种子、工作空间边界、点间距和距基座范围。实际生成坐标会随运行结果
写入 `generated_waypoints.json`，保证实验可复现。

轨迹评估配置通过 `trajectory.type`、`controller.type` 和 `backend.type` 选择可替换组件。
当前轨迹为 `timed_linear` 和 `periodic_ellipse`，控制器为 `reference_goal`，仿真后端为
`sofa_inverse_qp`。控制器负责生成任务空间目标，后端负责通过官方逆向 QP 求解绳索驱动，
二者不能混为同一组件。正式指标排除 `benchmark_warmup_steps`，同时在
`performance.json` 的 `tracking.all_steps` 保留全程指标。
