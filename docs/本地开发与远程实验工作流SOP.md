# 本地开发与远程实验工作流 SOP

> 版本：V1.17（2026-10-03）
> 适用范围：本地 Mac 开发 + 远程 Linux GPU 工作站实验
> 当前进度：SSH、工作区同步、PyTorch GPU、SOFA/SoftRobots、Trunk 周期控制、25 Hz 逆向点位跟踪、末端轨迹和实时控制曲线已验证；通用轨迹评估 Pipeline 的直线、椭圆、圆形、圆角三角形和圆角正方形均已通过自动和人工可视化验收

## 1. 核心原则

- **本地是唯一代码源**：代码、配置和文档在本地维护；远程只作为执行镜像。
- **远程只做重任务**：运行 SOFA 仿真、数据生成和模型训练，不日常编辑源码。
- **代码与数据分离**：代码单向上传；结果按需拉回；大型数据和可重建环境留在远程。
- **每次运行可追溯**：使用唯一 `run_id`，保存配置、日志、版本、随机种子和退出码，不覆盖旧结果。

详细路径、同步边界、运行元数据和安全规则见[远程工作流技术规范](./远程工作流技术规范.md)。

## 2. 一次实验的完整流程

```text
本地修改代码
  → 本地语法检查/轻量测试
  → 同步整个 workspace 并通过 SHA-256 校验
  → 以新 run_id 启动远程任务
  → 检查 COMPLETE、exit_code 和业务验收结果
  → 拉回必要产物
  → 本地分析并进入下一轮
```

### Step 0：进入本地项目

```bash
cd /Users/tory/Desktop/workspace/Continuum-Robot-Lab/workspace
```

本机 `.zshrc` 会在终端启动于本项目或进入本项目目录时调用自动同步启动器。启动器具有进程去重机制，不会为多个终端重复创建监控进程；如果监控进程结束，下次进入项目目录时会自动补启。

```bash
scripts/remote/status_auto_sync.sh
scripts/remote/stop_auto_sync.sh
scripts/remote/start_auto_sync.sh
```

监控器只在可同步源码的内容指纹变化并稳定后上传，不会自动执行 Git commit 或 push。`datasets/`、`outputs/`、本机配置和缓存不会触发源码同步。
修改 `config.local.sh` 中的主机、端口或密钥后，应执行一次
`stop_auto_sync.sh` 和 `start_auto_sync.sh`，让长期运行的监控器重新读取连接参数。SSH
和 SCP 默认启用保活及失联检测，避免实例切换时留下长期半开连接。

### Step 1：完成本地检查

根据本次改动运行最小必要检查：

```bash
for file in scripts/remote/*.sh; do bash -n "$file"; done
PYTHONPYCACHEPREFIX=.remote/pycache python3 -m py_compile tests/smoke/remote_gpu/*.py
```

项目后续引入测试框架后，在此步增加对应的单元测试。

### Step 2：确认连接与同步状态

```bash
scripts/remote/check_connection.sh
scripts/remote/status_auto_sync.sh
```

自动同步正常时无需重复手动上传。需要立即同步或诊断时仍可运行：

```bash
scripts/remote/sync_workspace.sh
```

每次同步在应用新文件前都会验证远端源码是否仍与上次成功清单一致。发现远端修改、新增或删除时会返回 `REMOTE_SOURCE_DRIFT` 并停止，不覆盖远端。只有最近一次日志包含 `workspace_sync_verification=passed` 才能启动远程实验。

### Step 3：启动远程任务

`run_id` 建议使用 `YYYYMMDD_任务_版本_seed` 格式。当前已实现的入口如下：

| 用途 | 命令 |
|---|---|
| PyTorch GPU 链路冒烟测试 | `scripts/remote/run_smoke.sh <run_id>` |
| 官方 SOFA CableConstraint demo | `scripts/remote/run_sofa_demo.sh <run_id>` |
| 官方 SoftRobots Trunk demo | `scripts/remote/run_sofa_trunk_demo.sh <run_id>` |
| 项目 Trunk 单绳周期控制 | `scripts/remote/run_trunk_cycle.sh <run_id>` |
| 项目 Trunk 25 Hz 逆向点位跟踪 | `scripts/remote/run_trunk_inverse_tracking.sh <run_id>` |
| 项目 Trunk 25 Hz 周期随机多目标跟踪 | `scripts/remote/run_trunk_inverse_periodic_random.sh <run_id>` |
| 项目 Trunk 25 Hz 直线轨迹评估 Pipeline | `scripts/remote/run_trunk_trajectory_tracking.sh <run_id>` |
| 项目 Trunk 25 Hz 椭圆轨迹评估 Pipeline | `scripts/remote/run_trunk_trajectory_tracking_ellipse.sh <run_id>` |
| 参数化 Trunk 轨迹评估入口 | `python scripts/remote/run_trunk_trajectory_tracking.py <trajectory> <controller> <run_id>` |
| 远端桌面 SOFA 可视化 demo | `scripts/server/run_sofa_gui_demo.sh`（在远端终端执行） |
| 远端桌面 Trunk 可视化 | `scripts/server/run_sofa_trunk_gui.sh`（在远端终端执行） |
| 远端桌面 Trunk 周期控制 | `scripts/server/run_trunk_cycle_gui.sh [run_id]`（在远端终端执行） |
| 远端桌面 Trunk 逆向点位跟踪 | `scripts/server/run_trunk_inverse_tracking_gui.sh [run_id]`（在远端终端执行） |
| 远端桌面 Trunk 周期随机多目标跟踪 | `scripts/server/run_trunk_inverse_periodic_random_gui.sh [run_id]`（在远端终端执行） |
| 远端桌面 Trunk 直线轨迹评估 Pipeline | `scripts/server/run_trunk_trajectory_tracking_gui.sh [run_id]`（在远端终端执行） |
| 远端桌面 Trunk 椭圆轨迹评估 Pipeline | `scripts/server/run_trunk_trajectory_tracking_ellipse_gui.sh [run_id]`（在远端终端执行） |

PyTorch 冒烟任务由 `tmux` 后台运行；当前 SOFA demo 是带超时限制的同步短任务。正式长任务必须使用 `tmux` 或调度器，不能依赖 SSH 会话存活。

如果已进入远端 XFCE 桌面，在远端终端直接启动可视化场景：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_sofa_gui_demo.sh
```

打开 SoftRobots 官方 Trunk 教程场景：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_sofa_trunk_gui.sh
```

Trunk 场景已以上游 commit、许可证和校验值固定到 `src/simulation/examples/softrobots_trunk/`。该基线默认使用正向求解，但绳索驱动动画被注释；直接运行主要验证多绳、网格、FEM 和求解器链路。后续控制器通过新增项目自有文件实现，不直接修改固定上游基线。

观察项目自有的 `cableL0` 周期控制场景：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_trunk_cycle_gui.sh
```

场景先稳定 1 秒，再开始周期控制和轨迹采样。蓝色模型为 Trunk，红点为实时末端，
绿色点为轨迹起点，橙色线为末端历史轨迹。场景使用独立安装的 SofaValidation
`Monitor`；`Trunk Control Plot` 窗口实时显示 `cableL0` 位移指令。启动脚本会按固定的
插件 `ACTIVE_ROOT` 显式加载动态库，并自动打开项目自有曲线窗口。曲线插件直接读取
场景中的 `cableL0/cable.value` 并在进程内保存绘图样本；CSV 仅用于实验结果持久化，
不再承担实时绘图通信。

观察 25 Hz 官方逆向点位跟踪场景：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_trunk_inverse_tracking_gui.sh
```

蓝色模型为 Trunk，黄色固定标记为最终目标，绿色点为当前参考，红色点为映射末端，
橙色线为末端历史轨迹。场景在初始目标保持 1 秒，用 5 秒移动至
`[65, -25, 145] mm`，再固定保持 2 秒。

观察周期随机多目标跟踪场景：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_trunk_inverse_periodic_random_gui.sh [run_id]
```

场景使用固定种子生成三个受约束随机目标，并依次循环两轮。黄色、品红和青色固定标记
分别表示 P0、P1 和 P2；每段用 5 秒移动并保持 1 秒。实际点位写入运行目录中的
`generated_waypoints.json`，控制与误差记录写入 `trajectory.csv` 和 `performance.json`。

观察通用轨迹评估 Pipeline 的第一条定时直线轨迹：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_trunk_trajectory_tracking_gui.sh [run_id]
```

场景先在 `[0, -5, 185] mm` 保持 1 秒，再用 5 秒沿绿色参考直线移动到
`[65, -25, 145] mm`，最后保持 2 秒。黄色标记为终点，绿色点为当前时刻参考，红色点
为实际末端，橙色线为实际轨迹。运行结束后输出标准 `trajectory.csv` 和
`performance.json`；后者同时保留排除预热后的正式指标、全程指标和分阶段指标。

观察同一 Pipeline 的三维闭合椭圆轨迹：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_trunk_trajectory_tracking_ellipse_gui.sh [run_id]
```

场景先在 `[0, -5, 185] mm` 保持 1 秒，再用 12 秒完成一圈三维椭圆，最后回到同一
起终点保持 1 秒。绿色半透明实体管状闭环为参考轨迹，黄色标记为椭圆中心，绿色点为
当前参考，红色点为实际末端，较粗的橙色线为实际轨迹；半透明参考管允许观察其内部近乎
重合的实际轨迹。参考管和轨迹显示参数只作用于渲染，不进入逆向求解和控制链路。

只检查 X11、OpenGL、RTX 4090 渲染和 SOFA 路径，不打开窗口：

```bash
bash /root/gpufree-share/Continuum-Robot-Lab/workspace/scripts/server/run_sofa_gui_demo.sh --check-only
```

### Step 4：验收并拉回结果

PyTorch 冒烟测试：

```bash
scripts/remote/status_smoke.sh <run_id>
scripts/remote/verify_run.sh <run_id>
scripts/remote/fetch_smoke.sh <run_id>
```

SOFA demo：

```bash
scripts/remote/fetch_sofa_demo.sh <run_id>
```

Trunk 周期控制：

```bash
scripts/remote/fetch_trunk_cycle.sh <run_id>
```

Trunk 25 Hz 逆向点位跟踪：

```bash
scripts/remote/fetch_trunk_inverse_tracking.sh <run_id>
```

Trunk 25 Hz 轨迹评估 Pipeline：

```bash
scripts/remote/fetch_trunk_trajectory_tracking.sh <run_id>
```

参数化批处理入口可在本地或远端工作区直接执行，当前注册了 `line`/`timed_linear`、
`ellipse`/`periodic_ellipse`、`circle`、`rounded_triangle`/`triangle` 和
`rounded_square`/`square`，以及 `reference_goal`（也可写作 `reference`）控制器。省略参数时默认使用
`line + reference_goal`，输出名称自动生成。例如：

```bash
# 默认直线轨迹、默认控制器、自动输出名称
python scripts/remote/run_trunk_trajectory_tracking.py

# 只切换轨迹，控制器和输出名称仍使用默认值
python scripts/remote/run_trunk_trajectory_tracking.py ellipse

# 显式指定全部参数
python scripts/remote/run_trunk_trajectory_tracking.py \
  ellipse reference_goal 20261003_ellipse_reference_cli_v1

# 在远端 XFCE 桌面打开同一实验的可视化窗口
python scripts/remote/run_trunk_trajectory_tracking.py \
  ellipse reference_goal 20261003_ellipse_reference_gui_v1 --gui

# 查看所有已经注册的组合
python scripts/remote/run_trunk_trajectory_tracking.py --list
```

输出名称只允许字母、数字、点、下划线和短横线，并直接作为远端 `run_id`；配置、场景和
步数由注册表选择，不接受任意本地路径。不带 `--gui` 时为无窗口 batch；带 `--gui` 时
必须在远端 XFCE 工作区执行并打开 SOFA 窗口。新增控制器或轨迹时，先在注册表中增加明确
组合，再补充相应配置和测试。

验收通过后，结果分别位于：

- `outputs/remote_smoke/<run_id>/`
- `outputs/sofa_demo/<run_id>/`
- `outputs/trunk_cycle/<run_id>/`
- `outputs/trunk_inverse_tracking/<run_id>/`
- `outputs/trajectory_tracking/<run_id>/`

正式实验至少要求：`exit_code=0`、无 `FAILED`、必需产物完整，且通过该实验的数值/物理验收条件。仅“程序无报错”不等于科研结论正确。
涉及机器人运动、控制效果或场景显示的阶段，还必须提供准确命令、预期现象和通过判据，
由用户完成人工可视化验收；用户明确确认以前不得进入下一阶段。

## 3. 首次配置或实例重建

1. 由 `scripts/remote/config.example.sh` 生成本地 `config.local.sh`，填写主机、端口、私钥和远程路径。
2. 执行 `scripts/remote/check_connection.sh` 确认 SSH 和 GPU。
3. 如 PyTorch 环境不存在，执行 `scripts/remote/setup_smoke_env.sh`。
4. 如 SOFA 环境不存在，执行：

   ```bash
   scripts/remote/install_sofa.sh /path/to/SOFA_v25.12.00_Linux-Python_3.10.zip
   scripts/remote/check_sofa.sh
   ```

5. 如项目需要末端轨迹显示，安装固定版本的 SofaValidation，再复查完整环境：

   ```bash
   scripts/remote/install_sofa_validation.sh
   scripts/remote/check_sofa.sh
   ```

   安装脚本在本机下载并校验约 26 KB 的官方固定 commit 源码包，再上传到远端构建；
   插件进入 `$REMOTE_RUNTIME_ROOT/plugins/SofaValidation/` 的独立版本目录，不覆盖
   SOFA 主安装。远端构建依赖为 `libboost1.74-dev` 和 `libeigen3-dev`，缺失时通过
   Ubuntu apt 镜像安装。

6. 如项目需要 SofaImGui 实时控制曲线，安装项目自有可视化插件：

   ```bash
   scripts/remote/install_continuum_viz.sh
   scripts/remote/check_sofa.sh
   ```

   插件固定匹配 SOFA 25.12 自带的 Dear ImGui 1.91.8 和 ImPlot 0.16。安装目录包含
   项目插件源码哈希；源码变化时生成新版本目录，不覆盖旧库。插件只读当前场景中的
   `cableL0/cable.value`，采样留在 C++ 内存中，不进入控制或力学求解链路。
   `trajectory.csv` 由控制器独立记录并按配置的间隔批量 flush，结束及异常时强制落盘。

`config.local.sh`、SSH 私钥和密码不得上传或提交。完整环境版本和重建说明见[远程工作流技术规范](./远程工作流技术规范.md)。

## 4. 设备配置

| | 最低配置（最小场景/小样本） | 推荐配置（批量正式实验） |
|---|---|---|
| CPU | 4～8 核 | 24～32 个高性能物理核心 |
| 内存 | 16 GB | 128 GB |
| GPU | 支持 CUDA 的 NVIDIA GPU；仅 SOFA 基础验证可暂无 GPU | RTX 4090 24 GB（独占）或 L40S 48 GB（共享） |
| 项目盘 | 100 GB 可用空间 | 2 TB NVMe，可选 4 TB 归档空间 |
| 系统 | Ubuntu 22.04 LTS、可 SSH | Ubuntu 22.04 LTS、稳定 SSH、可用任务队列 |

只在出现明确的内存不足、显存不足、吞吐量不足或磁盘使用率超过 80% 时，才根据监控数据升级对应资源。

## 5. 当前开发边界与下一步

当前已证明“本地开发 → 远程 GPU/SOFA 执行 → 结果回传”基础链路，以及基于固定
SoftRobots Trunk 模型的单绳周期控制、末端轨迹显示、控制量内存实时绘图、单目标与
周期随机多目标跟踪。通用轨迹、控制器、SOFA 后端、内存记录器和离线指标已通过标准
接口组合；定时直线和闭合椭圆轨迹均已通过远端自动验证和人工可视化验收。
圆形、圆角三角形和圆角正方形已接入相同入口，并通过远端 batch 与人工可视化验收。
组件职责、时间语义、配置约定、标准产物和扩展规则见
[轨迹跟踪实验 Pipeline 设计](./discuss/轨迹跟踪实验Pipeline设计.md)。

下一步按以下顺序推进：

1. 补充参数扫描入口，验证 Pipeline 的批量组合能力。
2. 将末端三轴或目标误差接入同一只读绘图链路。
3. 接入新的闭环控制器，并在相同轨迹和指标口径下与逆向 QP 基线比较。
4. 在进入正式实验前，补齐 Git commit、配置快照和资源监控元数据。

已完成验证的数据和已知问题见[远程工作流验收记录](./远程工作流验收记录.md)。

## 6. 故障处理

| 现象 | 处理 |
|---|---|
| SSH 失败 | 检查 `config.local.sh`、网络、端口和私钥权限 |
| 自动同步未运行 | 执行 `scripts/remote/status_auto_sync.sh`，必要时重新启动 |
| `REMOTE_SOURCE_DRIFT` | 停止同步，核对远端修改并通过Git分支回收，不强制覆盖 |
| 同步校验失败 | 停止启动实验，重新同步并核对失败文件 |
| 任务无结果 | 检查 `stdout.log`、`exit_code`、`FAILED` 和远程磁盘空间 |
| SOFA 不可用 | 运行 `scripts/remote/check_sofa.sh`；实例重建后重新安装 |
| SofaValidation 不可用 | 运行 `scripts/remote/install_sofa_validation.sh`，再执行 `scripts/remote/check_sofa.sh` |
| 实时曲线窗口不存在 | 运行 `scripts/remote/install_continuum_viz.sh`，确认启动日志含 `Registered GUI "Trunk Control Plot"` |
| 重要数据位于临时盘 | 立即复制到远程持久存储并拉回必要结果 |

当 SSH 明确返回 `Permission denied (publickey,password)`，且已确认远端实例、网络和端口正常时，在本机项目根目录恢复公钥授权：

```bash
scripts/remote/authorize_ssh_key.sh
```

脚本读取 `config.local.sh`，必要时从已有私钥生成对应 `.pub` 文件，然后调用
`ssh-copy-id` 并执行连接检查。远端密码仍由用户在 `ssh-copy-id` 提示中交互式输入，脚本
不接收、不记录密码。只安装 `.pub` 公钥，不得复制或上传私钥。连接恢复后仍需正常执行
远端漂移检查和工作区同步。

不直接删除或覆盖远程数据，不使用未经路径确认的 `rsync --delete`。更详细的验收和恢复规则见[远程工作流技术规范](./远程工作流技术规范.md)。

## 7. 修订记录

| 版本 | 日期 | 变化 |
|---|---|---|
| V1.17 | 2026-10-03 | 参数化入口新增圆形、圆角三角形和圆角正方形，并完成 batch 与 GUI 验收 |
| V1.16 | 2026-10-03 | 增加轨迹与控制器参数化单实验入口及默认参数 |
| V1.15 | 2026-10-03 | 增加通用轨迹跟踪 Pipeline、定时直线与三维闭合椭圆验收流程 |
| V1.14 | 2026-10-03 | 增加 25 Hz 周期随机多目标跟踪的 batch 与 GUI 工作流 |
| V1.13 | 2026-10-03 | 增加人工可视化验收门禁，用户确认后方可进入下一阶段 |
| V1.12 | 2026-10-02 | 增加 Trunk 25 Hz 官方逆向点位跟踪、性能统计与 GUI 入口 |
| V1.11 | 2026-10-02 | 修复同步监控停止信号与 SSH 半开连接检测 |
| V1.10 | 2026-10-02 | 增加交互式 SSH 公钥授权恢复脚本，统一端口变更后的恢复入口 |
| V1.9 | 2026-09-30 | 实时曲线改为直接读取 SOFA Data，CSV 改为批量 flush 的独立持久化通道 |
| V1.8 | 2026-09-30 | 增加项目自有 SofaImGui/ImPlot 插件与实时 `cableL0` 控制曲线 |
| V1.7 | 2026-09-30 | 固定安装 SofaValidation，并增加 Trunk 末端轨迹显示及插件检查流程 |
| V1.6 | 2026-09-30 | 增加项目 Trunk 周期控制的 batch、GUI 和结果回传入口 |
| V1.5 | 2026-09-30 | 增加 SSH 公钥授权丢失后的 `ssh-copy-id` 恢复流程与凭据边界 |
| V1.4 | 2026-09-29 | 将 SoftRobots v25.12 Trunk 源码和必要网格固定到本地工作区 |
| V1.3 | 2026-09-29 | 增加 SoftRobots 官方 Trunk 场景的 batch 和远端桌面启动入口 |
| V1.2 | 2026-09-29 | 增加进入项目时自动启动的源码监控、单实例保护和远端漂移阻断 |
| V1.1 | 2026-09-28 | 增加远端 XFCE 桌面的 SofaImGui 可视化启动与 OpenGL 自检脚本 |
| V1.0 | 2026-09-28 | 将 SOP 收敛为主操作流程；技术规范与验收历史拆分为独立文档 |
| V0.9 | 2026-09-28 | 完成 SOFA/SoftRobots 环境及官方 CableConstraint demo 验证 |

更早的修订历史见[远程工作流验收记录](./远程工作流验收记录.md)。
