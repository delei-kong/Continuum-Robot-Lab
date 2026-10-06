# Tests

- `smoke/`：SSH、GPU、Python和SOFA等基础设施检查；
- `integration/`：仿真、数据、建模和控制链路测试。

与研究代码无关的小型测试数据可放在 `fixtures/` 并提交Git。

`test_tracking_pipeline.py` 使用确定性假后端验证轨迹、控制器和记录器可以独立替换组合，
不依赖 SOFA 环境；同时覆盖定时直线轨迹的稳定、移动、保持阶段，参考轨迹折线采样及
预热前后指标口径。闭合椭圆轨迹测试覆盖稳定、周期跟踪、保持阶段以及解析速度和加速度。
闭合 Catmull–Rom 测试覆盖控制点插值、跨周期位置/速度连续性、工厂解析和控制点数量校验。
`test_trajectory_cli.py` 验证轨迹/控制器注册表、别名解析和输出名称安全校验。

`test_forward_data.py` 验证正向数据采集的动作限幅与速率限制、固定 seed 多绳激励、时间语义和配置边界，
不依赖 SOFA。

`test_koopman_dataset.py` 验证 Koopman 数据集的 episode 时序、状态—动作—下一状态对齐、数值质量、
动作覆盖和 train/validation/test 内容隔离；同样不依赖 SOFA。

`test_koopman_model.py` 验证线性与固定升维 Koopman 模型的状态/动作维度、固定随机种子、一步预测及
episode 内多步滚动评价；不读取正式数据集，也不依赖 SOFA。
