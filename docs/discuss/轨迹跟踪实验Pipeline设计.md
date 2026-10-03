# 轨迹跟踪实验 Pipeline 设计

> 日期：2026-10-03
> 状态：V1 基线完成；直线与三维闭合椭圆已通过自动和人工可视化验收

## 1. 目标与边界

Pipeline 用统一接口组合轨迹、控制器、仿真后端、内存记录器和离线指标，使后续实验可以
只替换一个组件或一组参数，而不复制 SOFA 场景和评估逻辑。

当前基线使用官方 SoftRobots.Inverse QP 后端验证链路，不代表已经实现课题最终的 PID、
MPC 或学习控制器，也不代表仿真模型已经完成实机参数标定。

## 2. 组件与数据流

```text
Trajectory.sample(t + dt)
        │ TrajectoryReference
        ▼
TrackingController.compute(observation, reference, dt)
        │ ControlCommand
        ▼
TrackingBackend / SOFA event adapter
        │ TrackingObservation at t + dt
        ▼
InMemoryTrackingRecorder
        │ tuple[TrackingStepRecord, ...]
        ▼
tracking_metrics → trajectory.csv + performance.json
```

V1 中的具体组合：

| 角色 | 当前实现 | 配置类型 |
|---|---|---|
| 轨迹 | 定时直线、三维周期椭圆 | `timed_linear`、`periodic_ellipse` |
| 控制器 | 将参考位置转换为任务空间目标 | `reference_goal` |
| 后端 | SOFA Trunk + 官方逆向 QP | `sofa_inverse_qp` |
| 记录器 | 控制循环内存记录 | `InMemoryTrackingRecorder` |
| 评估器 | 误差、分阶段指标和实时性统计 | `tracking_metrics.py` |

`reference_goal` 和 `sofa_inverse_qp` 必须保持为两个组件：前者决定发送什么命令，后者决定
命令如何作用到仿真对象。后续 PID 可以替换控制器；正向 SOFA、假后端或实机适配器可以
替换后端。

## 3. 代码布局

| 文件 | 职责 |
|---|---|
| `src/control/tracking_contracts.py` | 参考、观测、命令、控制器协议 |
| `src/control/reference_controller.py` | 基线控制器与控制器工厂 |
| `src/simulation/trajectory.py` | 轨迹协议、轨迹工厂及参考路径几何 |
| `src/simulation/tracking_pipeline.py` | 不依赖 SOFA 的同步实验编排器 |
| `src/simulation/sofa_tracking_backend.py` | SOFA 数据与统一合同之间的适配 |
| `src/simulation/scenes/trunk_inverse_common.py` | Trunk 逆向场景公共建图 |
| `src/simulation/scenes/trunk_trajectory_tracking.py` | SOFA 动画事件驱动的 Pipeline 场景 |
| `src/evaluation/recording.py` | 内存记录器和逐步记录结构 |
| `src/evaluation/tracking_metrics.py` | 结束后序列化与指标计算 |
| `tests/test_tracking_pipeline.py` | 无 SOFA 的组件替换和时间语义测试 |

同步 `TrackingExperimentRunner` 用于纯 Python 后端和快速测试；SOFA 必须由动画事件推进，
因此场景使用同一合同实现事件适配，而不是在回调内部再次启动同步 Runner。

## 4. 时间与记录语义

每个离散步按以下顺序处理：

1. 在步首生成 `t + dt` 的参考；
2. 控制器根据 `t` 时刻观测和 `t + dt` 参考生成命令；
3. 后端推进一个 `dt`；
4. 在步末读取 `t + dt` 观测；
5. 用相同时间戳的参考与观测计算误差。

SOFA 场景在 `AnimateBegin` 写目标，在 `AnimateEnd` 读取实际末端。控制周期耗时按相邻两个
`AnimateBegin` 的墙钟时间计算，最后一步没有下一次步首，因此其周期字段为空。

控制循环只向内存追加记录，不读写 CSV。`trajectory.csv` 和 `performance.json` 在运行结束
后统一生成，避免文件 I/O 干扰 25 Hz 控制和 GUI 刷新。

## 5. 配置约定

一个实验配置至少包含：

```json
{
  "dt": 0.04,
  "control_rate_hz": 25.0,
  "duration_s": 8.0,
  "seed": 20261003,
  "deadline_ms": 40.0,
  "benchmark_warmup_steps": 25,
  "trajectory": {"type": "timed_linear"},
  "controller": {"type": "reference_goal"},
  "backend": {"type": "sofa_inverse_qp"}
}
```

`duration_s / dt` 必须为整数，`dt * control_rate_hz` 必须为 1。轨迹总时长必须和实验时长
一致，轨迹起点必须和 SOFA 初始目标一致。随机轨迹和随机控制器必须只使用配置中的 seed。

## 6. 标准产物与指标

每个 run 目录至少包含：

```text
<run_id>/
├── config.json
├── metadata.json
├── trajectory.csv
├── performance.json
├── stdout.log
├── exit_code
└── COMPLETE 或 FAILED
```

`trajectory.csv` 保存同时间戳参考、实际末端、误差、控制命令、控制器诊断、8 根绳的位移
与力，以及 controller/backend/control-period 三类耗时。

`performance.json` 包含：

- 排除预热段后的 RMSE、平均值、P95、最大值、最终误差和三轴 RMSE；
- `tracking.all_steps` 全程指标，保留初始化瞬态；
- `tracking.by_phase` 分阶段指标；
- controller、backend 和完整控制周期的均值、P50/P95/P99、最大值和截止时间超限统计。

## 7. 已验收基线

| 轨迹 | 正式 RMSE | 最大误差 | 控制周期 P99 | 人工验收 |
|---|---:|---:|---:|---|
| 1 s 稳定 + 5 s 直线 + 2 s 保持 | 0.02284 mm | 0.07661 mm | 29.529 ms | 通过 |
| 1 s 稳定 + 12 s 三维椭圆 + 1 s 保持 | 0.04376 mm | 0.09425 mm | 31.800 ms | 通过 |

数值结果用于验证官方逆向 QP 基线和评估链路，不应直接解释为尚未实现的 PID 控制精度。

## 8. 扩展规则

新增轨迹时：实现 `Trajectory`，注册到 `trajectory_from_mapping`，提供解析参考和阶段名称，
先通过纯 Python 时间边界测试，再进行远端 batch 与人工 GUI 验收。

新增控制器时：实现 `TrackingController`，明确支持的 `ControlCommand` 类型，在工厂中注册，
并使用同一轨迹、seed、dt 和指标与基线比较。

新增后端时：实现其支持的命令类型和观测映射；同步后端可直接接入
`TrackingExperimentRunner`，事件驱动后端应保持相同时间和记录语义。

## 9. 下一阶段

下一阶段只增加批量实验能力：使用显式实验矩阵组合配置、为每个 case 生成独立 run 目录，
失败 case 不覆盖其他结果，最后输出聚合表。批量入口稳定并完成自动验证后，再开始 PID
控制器，以避免同时调试控制算法和实验调度器。
