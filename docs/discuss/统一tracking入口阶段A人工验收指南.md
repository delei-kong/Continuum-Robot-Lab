# 统一 tracking 入口阶段 A 人工验收指南

> 日期：2026-10-05  
> 适用版本：统一 tracking 入口与脚本收敛阶段 A  
> 验收对象：`scripts/experiment/run_tracking.py` 与 `scripts/remote/fetch_run.sh`

## 1. 验收目标

确认新的统一 tracking 入口在不改变既有 SOFA 场景、控制循环和评估口径的前提下，能够：

1. 从本地通过 SSH 启动已注册的 batch 实验；
2. 从远端 XFCE 工作区启动相同注册表对应的 GUI 实验；
3. 生成、回传并验证标准实验产物；
4. 保持轨迹显示和机器人运动的既有可视化效果。

本轮不验收新的控制算法、物理模型或科学结论，只验收执行入口与脚本收敛后的功能等价性。

## 2. 前置条件

在本地项目根目录执行以下检查：

```bash
cd /Users/tory/Desktop/workspace/Continuum-Robot-Lab/workspace
scripts/remote/check_connection.sh
scripts/remote/check_sofa.sh
scripts/remote/sync_workspace.sh
```

通过判据：连接脚本能显示远端用户和 GPU；SOFA 检查无缺失插件；同步输出
`workspace_sync_verification=passed`。若同步报告远端源码漂移，停止验收，不得覆盖远端源码。

## 3. Batch 回归验收

### 3.1 直线 canary

在本地项目根目录执行：

```bash
python scripts/experiment/run_tracking.py \
  --input line \
  --algorithm reference_goal \
  --output 20261005_line_tracking_canary_v1

scripts/remote/fetch_run.sh trajectory_tracking \
  20261005_line_tracking_canary_v1

python scripts/experiment/run_tracking.py --input ellipse --algorithm reference_goal --output 20261005_ellipse_tracking_gui_v2 --mode gui --target server
```

预期现象：远端 batch 完成 200 步；回传命令成功；本地生成：

```text
outputs/trajectory_tracking/20261005_line_tracking_canary_v1/
├── COMPLETE
├── config.json
├── metadata.json
├── trajectory.csv
├── performance.json
├── stdout.log
└── exit_code
```

通过判据：

- 存在 `COMPLETE`，不存在 `FAILED`；
- `exit_code` 内容为 `0`；
- `trajectory.csv` 恰有 200 条数据记录，不含表头；
- `performance.json` 非空，且包含 `tracking` 与 `timing`；
- `stdout.log` 不含 `[ERROR]`、Python exception 或 non-finite 报错；
- `performance.json` 中的完成步数为 200。

失败判据：命令非零退出、回传失败、产物缺失、步数不匹配、日志含致命错误，或数值出现 NaN/Inf。

### 3.2 椭圆 canary

在本地项目根目录执行：

```bash
python scripts/experiment/run_tracking.py \
  --input ellipse \
  --algorithm reference_goal \
  --output 20261005_ellipse_tracking_canary_v1

scripts/remote/fetch_run.sh trajectory_tracking \
  20261005_ellipse_tracking_canary_v1
```

预期现象：远端 batch 完成 350 步，回传到：

```text
outputs/trajectory_tracking/20261005_ellipse_tracking_canary_v1/
```

通过判据与直线 canary 相同，但 `trajectory.csv` 与 `performance.json` 的完成步数应为 350。

这一步用于确认非直线轨迹同样通过新入口、注册表、配置步数推导和统一回传链路运行。

## 4. GUI 人工可视化验收

进入远端 XFCE 桌面，在远端终端执行。优先复制下面的**单行命令**，避免续行符被终端或复制过程拆开；
`--mode gui` 与 `--target server` 必须和 `python` 命令处于同一条命令中。`v5` 是本次验收专用的未使用
Run ID；已有同名目录时改用一个新的、未使用的 Run ID，保留历史目录不覆盖。

```bash
cd /root/gpufree-share/Continuum-Robot-Lab/workspace
python scripts/experiment/run_tracking.py --input ellipse --algorithm reference_goal --output 20261005_ellipse_tracking_gui_v5 --mode gui --target server
```

预期现象：

- 绿色半透明闭环是椭圆参考路径；
- 绿色点连续沿参考路径完成一圈；
- 红色点为实际末端，连续跟随绿色点；
- 橙色轨迹与绿色参考闭环基本重合；
- 机器人运动连续，无明显跳变、发散、异常抖动或不合理穿越；
- 终端不出现 `[ERROR]`、Python exception 或 non-finite 报错。

关闭 SOFA 窗口时不要在终端按 `Ctrl+C`，也不要关闭启动该命令的终端；等待终端输出
`GUI experiment completed: ...` 后，再检查远端运行目录：

```bash
RUN_ID=20261005_ellipse_tracking_gui_v5
RUN_DIR="/root/gpufree-share/Continuum-Robot-Lab/workspace/runs/$RUN_ID"
test -f "$RUN_DIR/COMPLETE"
test ! -e "$RUN_DIR/FAILED"
test "$(tr -d '[:space:]' <"$RUN_DIR/exit_code")" = "0"
test -s "$RUN_DIR/trajectory.csv"
test -s "$RUN_DIR/performance.json"
```

GUI 通过判据：视觉现象全部满足，且上述检查全部成功。

## 5. 验收回报模板

请按下列格式回报结果：

```text
统一 tracking 入口阶段 A 验收

- 直线 batch：通过 / 失败
  - run ID：
  - 输出目录：
  - 完成步数：
  - 主要报错（如有）：

- 椭圆 batch：通过 / 失败
  - run ID：
  - 输出目录：
  - 完成步数：
  - 主要报错（如有）：

- 椭圆 GUI 人工可视化：通过 / 失败
  - 参考与实际轨迹显示：正常 / 异常
  - 运动连续性：正常 / 异常
  - 终端或日志报错：无 / 有（附摘要）
```

## 6. 阶段结论规则

只有直线 batch、椭圆 batch 和椭圆 GUI 人工可视化均通过后，才能确认阶段 A 的统一 tracking
入口功能验收通过，并开始通用 SOFA 执行内核的阶段 B。任一项失败时，保留失败运行目录和日志，
先定位问题，不覆盖、不删除历史产物。

## 7. 2026-10-05 验收记录

阶段 A 已验收通过：

- 直线 batch：`20261005_line_tracking_canary_v1`，200/200 步，已回传并通过标准产物校验；
- 椭圆 batch：`20261005_ellipse_tracking_canary_v1`，350/350 步，已回传并通过标准产物校验；
- 椭圆 GUI：`20261005_ellipse_tracking_gui_v5`，人工确认参考/实际轨迹显示及运动连续性正常；远端与本地
  均验证为 `COMPLETE=true`、`FAILED=false`、`exit_code=0`、`process_exit_code=0`，并包含 350 条轨迹和
  非空 `performance.json`。

结果保存在本地 `outputs/trajectory_tracking/` 对应 Run ID 目录；旧的 `v1` 至 `v4` 目录作为执行和修复过程
记录保留，不覆盖、不删除。
