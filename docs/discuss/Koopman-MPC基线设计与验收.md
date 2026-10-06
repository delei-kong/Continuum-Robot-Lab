# Koopman-MPC 基线设计与验收

> 状态：直线 K-MPC 基线已完成原始 SOFA batch 与 GUI 人工验收；复杂轨迹待独立验证

## 目的

K-MPC 是模型强化学习之前的模型控制基线，用于回答“已冻结 Koopman 模型是否能在约束下驱动原始 SOFA
机器人跟踪参考末端轨迹”。它不是强化学习的替代物，也不允许以模型内部 rollout 成绩代替 SOFA 闭环结果。

## 固定输入

- 模型：`outputs/koopman_models/20261006_koopman_v2_final_v1/` 的 validation 选择模型
  `edmd_rff_48_b1`；加载器要求 `COMPLETE`、`evaluation_stage=final`、`test_evaluated=true`，并核对
  `selection.json` 与 `summary.json` 的选择一致。
- 状态：与数据集完全相同的 79 维状态，包含 8 路绳索位移/力、末端位置和 10 个中心线点的位置/速度。
- 动作：8 路实际施加的绳索位移（mm）。
- 动作上界：训练 split 的已覆盖范围 `[10, 10, 10, 10, 5, 5, 5, 5] mm`，而非机器人更宽的物理
  限位；这样首个闭环基线不会把预测模型外推到未采集的大动作区间。
- 已登记任务：`line`、`ellipse`、`circle`、`triangle` 与 `square`；控制周期与模型数据一致，均为
  100 Hz。闭环轨迹按正式数据集的末端位置覆盖范围设计为中等幅值任务：椭圆主轴约 36 mm、圆直径
  28 mm、等边三角形边长 18 mm、正方形边长 16 mm。椭圆和圆形是解析周期轨迹，三角形和正方形是
  闭合 Catmull–Rom 的圆角轮廓。
- 首个 1 秒严格施加零动作，使 Trunk 自然下垂到训练集覆盖的状态区域；该段步数必须与参考轨迹的
  `settle_duration_s` 一致，且不调用 MPC。参考起点取该自然平衡附近，而不是未稳定的几何初始位姿。

## 控制形式

冻结模型在 lift 空间写为：

```text
z[k+1] = A z[k] + B u[k] + c
tip[k] = C z[k] + d
```

每个 SOFA 步只使用当前真实观测构造 `z[0]`，在 10 步预测域内求解：

```text
sum ||tip[k] - reference[k]||_Q^2
  + lambda_u ||u[k]||^2
  + lambda_du ||u[k] - u[k-1]||^2
```

并施加硬约束：

```text
0 <= u_i[k] <= cable_max_i
|u_i[k] - u_i[k-1]| <= max_command_delta
```

实现使用固定次数的投影梯度法；每轮投影按时间顺序同时满足幅值和相邻动作变化率。执行时仅下发第一步，
下一帧重新读 SOFA 的完整状态并再次优化。场景外仍有同一套 `CableActionSafetyLayer`，作为最终硬保护；
控制器只将实际施加动作写回其 warm start。

## 运行与产物

查看受支持输入：

```bash
python scripts/experiment/run_koopman_mpc.py --list
```

从本地发起首个远端 batch：

```bash
python scripts/experiment/run_koopman_mpc.py \
  --input line \
  --output <run_id> \
  --mode batch
```

回传并核验：

```bash
scripts/remote/fetch_run.sh koopman_mpc_tracking <run_id>
```

运行目录必须包含标准 `trajectory.csv`、`performance.json`、`model_provenance.json`、配置快照和完成标记。
`model_provenance.json` 固化引用的 final 模型输出、所选模型名和 lift 维度；其缺失会使运行验收失败。

## 门禁

自动门禁：

- 800 行轨迹记录、`COMPLETE`、`exit_code=0`，日志无 `[ERROR]`；
- 控制器诊断、状态、动作和跟踪误差均为有限值；
- 记录的索长动作满足幅值和相邻步变化率约束；
- 模型来源为冻结的 final 输出，而非临时候选或任意 NPZ 文件；
- `performance.json` 同时报告全程与去除预热后的跟踪、控制耗时与 deadline 指标。

### 当前 batch 证据

`20261006_koopman_mpc_line_canary_v4` 已通过上述自动门禁，回传目录为
`outputs/koopman_mpc_tracking/20261006_koopman_mpc_line_canary_v4/`。去除 1 秒物理稳定段后，直线任务的
RMSE 为 3.019 mm、P95 误差为 5.379 mm、最终误差为 3.190 mm；控制周期 P99 为 37.395 ms，小于 50 ms
deadline，且无 deadline miss。所有 800 个记录均使用冻结的 `edmd_rff_48_b1` 模型，动作约束检查通过。

开发中曾发现实时中心线状态被错写为 `x,vx,y,vy,z,vz`，而数据集合同定义为
`x,y,z,vx,vy,vz`；这会导致模型收到畸形状态并产生饱和动作。现已将状态组装收敛到带单元测试的纯函数，
canary v4 是修复后的首个有效 batch 证据。

其余四种轨迹已作为受控配置登记，但尚无各自的 SOFA batch 与 GUI 验收结果；它们不能借用直线任务的
通过结论。后续复杂轨迹比较应保持相同的模型、动作范围、控制频率和物理稳定段，仅切换注册输入。

人工 GUI 门禁：

```bash
cd /root/gpufree-share/Continuum-Robot-Lab/workspace
python scripts/experiment/run_koopman_mpc.py \
  --input <line|ellipse|circle|triangle|square> \
  --output <gui_run_id> \
  --mode gui --target server
```

预期现象：绿线/绿点为参考，红点为实时末端，橙线为实际末端路径；稳定段内动作应平滑，移动与保持阶段不应
发生明显跳变、穿透、无界振荡或非有限状态。直线基线已由用户确认 GUI 通过；其余登记轨迹仍须分别通过同一
人工门禁，不能借用该结论。

橙线复用已验收的 SofaValidation `Monitor`：它直接监听映射后的真实末端 `TipObservation/dofs`，不使用
模型预测，也不参与 MPC 优化或性能指标计算。场景在 1 秒物理稳定段结束时，以当前末端位置设置绿色起点
标记并开启 `tipTrajectory.listening`；因此轨迹只记录控制开始后的真实运动，不包含初始自然下垂过程。
`trajectory_precision_s` 和 `trajectory_color_rgba` 是该统一显示机制的配置接口。

此前 K-MPC 另行实现动态 `OglModel` 管状/折线网格；它在 batch 中可运行但 GUI 中不可见，故已删除，不能
作为可视化验收证据。`20261006_koopman_mpc_line_monitor_canary_v1` 已验证 Monitor 路径：800 步完成，日志在
`t=1.00 s` 输出 `actual trajectory visualization started`，RMSE 6.040 mm、P95 9.202 mm、控制周期 P99
36.214 ms，50 ms deadline 下无 miss。该数值是放大后约 23 mm 直线的独立基线，不能与旧小幅值直线的
3.019 mm 混用。用户已确认 Monitor 在 GUI 中可见且随真实末端更新，故直线 K-MPC 基线验收通过；复杂轨迹
的独立控制效果与可视化验收仍保留到 M4。
