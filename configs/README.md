# Configs

存放可复现的仿真、数据生成、建模和控制配置。初期保持扁平；只有在配置数量明显增加后再按主题拆分。

正式实验必须把实际使用的配置快照保存到对应的 `outputs/<run_id>/` 中。

- `trunk_inverse_tracking.json`：25 Hz 单目标逆向跟踪；
- `trunk_inverse_periodic_random.json`：固定种子生成三个受约束随机点，并循环跟踪两轮。

随机多目标配置保存种子、工作空间边界、点间距和距基座范围。实际生成坐标会随运行结果
写入 `generated_waypoints.json`，保证实验可复现。
