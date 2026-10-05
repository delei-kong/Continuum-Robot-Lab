# 统一 tracking 入口阶段 B 人工验收指南

> 阶段：通用 SOFA 执行内核  
> 日期：2026-10-05  
> 前置条件：阶段 A 已验收并提交。

## 1. 验收目的

确认 manifest 驱动的通用 SOFA 执行内核在不改变场景、控制循环、轨迹数学或指标口径的前提下，能够通过
远端 GUI 运行椭圆 tracking，并产出与 batch 相同的标准运行合同。

已自动通过的配套回归：

- 本地→SSH 直线 batch：`20261005_line_runtime_core_canary_v1`，200 条轨迹；
- 远端工作区椭圆 batch：`20261005_ellipse_runtime_core_canary_v1`，350 条轨迹；
- 两者均包含 `requested_config.json`、`effective_config.json`、`metadata.json`、`exit_code`、
  `process_exit_code`、`trajectory.csv`、`performance.json` 与 `COMPLETE`。

## 2. GUI 验收命令

在远端 XFCE 桌面的终端中进入工作区，复制执行以下单行命令。实际验收中该 Run ID 已被其他历史运行占用，
最终使用 `20261005_ellipse_tracking_gui_v6`；下面保留的是原先为本阶段预留的命令格式。

```bash
cd /root/gpufree-share/Continuum-Robot-Lab/workspace
python scripts/experiment/run_tracking.py --input ellipse --algorithm reference_goal --output 20261005_ellipse_runtime_core_gui_v2 --mode gui --target server
```

关闭 SOFA 窗口时不要在终端按 `Ctrl+C`，也不要关闭启动命令的终端；等待命令输出
`experiment_status=complete` 后再检查产物。

## 3. 通过判据

- 绿色半透明椭圆为参考路径，绿色点连续沿路径运动；
- 红色实际末端持续跟随绿色参考点，橙色实际轨迹与参考闭环基本重合；
- 机器人运动无明显跳变、发散、异常抖动或不合理穿越；
- 终端无 Python exception、`[ERROR]` 或 non-finite 报错；
- 运行目录 `/root/gpufree-share/Continuum-Robot-Lab/workspace/runs/20261005_ellipse_runtime_core_gui_v2/`
  存在 `COMPLETE`，不存在 `FAILED`，`exit_code` 为 `0`；
- 本地回传后，`outputs/trajectory_tracking/20261005_ellipse_runtime_core_gui_v2/` 包含
  `requested_config.json`、`effective_config.json`、`metadata.json`、`trajectory.csv` 和
  `performance.json`，且轨迹为 350 条记录。

## 4. 结论规则

用户明确确认 GUI 视觉现象通过，且标准运行产物校验通过后，方可删除已被通用内核替代的旧 tracking
运行器并确认阶段 B 完成。失败时保留对应运行目录和日志，不覆盖、不删除历史结果。

## 5. 2026-10-05 验收记录与结论

阶段 B 已验收通过：

- 本地→SSH 直线 batch：`20261005_line_runtime_core_canary_v1`，200 条轨迹，manifest 与标准产物完整；
- 远端工作区椭圆 batch：`20261005_ellipse_runtime_core_canary_v1`，350 条轨迹，manifest 与标准产物完整；
- 远端椭圆 GUI：`20261005_ellipse_tracking_gui_v6`，用户确认参考/实际轨迹显示及运动连续性正常；本地回传后
  验证为 `COMPLETE=true`、`FAILED=false`、`exit_code=0`、`process_exit_code=0`、GUI manifest、350 条轨迹
  和无 artifact verifier 错误。

已删除被 `scripts/remote/run_experiment.sh` 和 `scripts/server/run_experiment.sh` 替代的三份旧 tracking
运行器。官方 demo、周期控制和 smoke 具有不同生命周期，未因脚本数量目标而在本阶段合并。
