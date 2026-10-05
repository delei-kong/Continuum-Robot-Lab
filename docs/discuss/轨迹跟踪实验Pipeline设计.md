# 轨迹跟踪实验 Pipeline 设计

> 日期：2026-10-03
> 状态：V1 基线完成；五条轨迹均已验收；PID 五轨迹 batch 已完成，圆形已完成 GUI 验收，其余四条待 GUI 验收

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
| 轨迹 | 定时直线、三维周期椭圆/圆形、闭合圆角多边形 | `timed_linear`、`periodic_ellipse`、`periodic_catmull_rom` |
| 控制器 | 参考目标基线、任务空间 PID 外环原型 | `reference_goal`、`task_space_pid` |
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
| `src/control/pid_controller.py` | 任务空间 PID 外环原型与限幅、分阶段状态管理 |
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
| 1 s 稳定 + 12 s 三维圆形 + 1 s 保持 | 0.05049 mm | 0.09556 mm | 31.052 ms | 通过 |
| 1 s 稳定 + 12 s 圆角三角形 + 1 s 保持 | 0.04114 mm | 0.09269 mm | 32.068 ms | 通过 |
| 1 s 稳定 + 12 s 圆角正方形 + 1 s 保持 | 0.04174 mm | 0.09291 mm | 34.029 ms | 通过 |

数值结果用于验证官方逆向 QP 基线和评估链路，不应直接解释为尚未实现的 PID 控制精度。
圆角三角形和圆角正方形 batch 各出现 1 次超过 40 ms 的控制周期，但 P99 均满足 40 ms
门限；保留该偶发抖动，待重复实验时继续观察。

任务空间 PID 保守预设的五轨迹 batch 结果：

| 轨迹 | 正式 RMSE | 最大误差 | 控制周期 P99 | 超期次数 | GUI 验收 |
|---|---:|---:|---:|---:|---|
| 直线 | 0.02617 mm | 0.08301 mm | 30.719 ms | 0 | 待验收 |
| 椭圆 | 0.04338 mm | 0.09059 mm | 31.658 ms | 0 | 待验收 |
| 圆形 | 0.04939 mm | 0.09118 mm | 34.365 ms | 0 | 通过 |
| 圆角三角形 | 0.04069 mm | 0.09065 mm | 31.142 ms | 0 | 待验收 |
| 圆角正方形 | 0.04132 mm | 0.09061 mm | 31.312 ms | 1 | 待验收 |

五个 case 均完成 350 步以内的统一产物验证；直线为 200 步，其余轨迹为 350 步。

## 8. 扩展规则

新增轨迹时：实现 `Trajectory`，注册到 `trajectory_from_mapping`，提供解析参考和阶段名称，
先通过纯 Python 时间边界测试，再进行远端 batch 与人工 GUI 验收。

闭合圆角多边形采用 uniform Catmull–Rom 插值，按控制点分段等时推进；曲线在控制点处位置
和速度连续，但当前版本没有做弧长重参数化，因此不能将其速度解释为严格恒定切向速度。

新增控制器时：实现 `TrackingController`，明确支持的 `ControlCommand` 类型，在工厂中注册，
并使用同一轨迹、seed、dt 和指标与基线比较。

新增后端时：实现其支持的命令类型和观测映射；同步后端可直接接入
`TrackingExperimentRunner`，事件驱动后端应保持相同时间和记录语义。

## 9. 下一阶段

下一阶段扩展控制器实验：固定当前保守增益，在椭圆及其他已验收轨迹上比较
`reference_goal` 与 `task_space_pid`，再进行受控增益扫描和批量汇总。每个新组合仍须完成
自动指标和人工 GUI 验收。

当前提供受控的单 case tracking 入口：

```bash
python scripts/experiment/run_tracking.py \
  --input <preset> --algorithm <algorithm> --output <run_id>
```

省略参数时默认使用 `line + reference_goal`，并生成带 UTC 时间戳的 run ID。输入可选择
`line`、`ellipse`、`circle`、`rounded_triangle`、`rounded_square`、`single_target` 和
`periodic_random`；`triangle`、`square`、`target` 和 `random` 是对应短别名。当前 `task_space_pid`
已登记五种轨迹预设，并通过 `pid_trajectories` 矩阵统一运行。入口通过安全注册表
映射到固定配置、场景和产物 profile，不允许用户参数直接构造远端路径。步数由配置推导，完整
实验矩阵和结果聚合仍属于下一阶段。

默认入口是 batch 模式；在远端 XFCE 工作区追加 `--mode gui --target server` 可以复用同一注册表
打开对应的 SOFA 可视化场景。batch 与 GUI 使用同一配置和控制循环，区别只在运行显示方式。

已批准的基线比较使用固定矩阵，而不是开放任意组合：

```bash
python scripts/experiment/run_tracking.py \
  --batch baseline_trajectories --output <batch_id>
```

当前矩阵固定执行 `line` 与 `ellipse`，case run ID 分别为 `<batch_id>__line` 和
`<batch_id>__ellipse`。某 case 失败会写入批次汇总但不会阻止后续 case；可用
`--list-batches` 查看可用矩阵。汇总文件保存在 `outputs/tracking_batches/<batch_id>/`。
