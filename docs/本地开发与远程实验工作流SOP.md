# 本地开发与远程实验工作流 SOP

> 版本：V1.2（2026-09-29）
> 适用范围：本地 Mac 开发 + 远程 Linux GPU 工作站实验
> 当前进度：SSH、工作区同步、PyTorch GPU 冒烟测试、SOFA/SoftRobots 安装及官方绳驱 demo 已验证

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
| 远端桌面 SOFA 可视化 demo | `scripts/server/run_sofa_gui_demo.sh`（在远端终端执行） |
| 远端桌面 Trunk 可视化 | `scripts/server/run_sofa_trunk_gui.sh`（在远端终端执行） |

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

验收通过后，结果分别位于：

- `outputs/remote_smoke/<run_id>/`
- `outputs/sofa_demo/<run_id>/`

正式实验至少要求：`exit_code=0`、无 `FAILED`、必需产物完整，且通过该实验的数值/物理验收条件。仅“程序无报错”不等于科研结论正确。

## 3. 首次配置或实例重建

1. 由 `scripts/remote/config.example.sh` 生成本地 `config.local.sh`，填写主机、端口、私钥和远程路径。
2. 执行 `scripts/remote/check_connection.sh` 确认 SSH 和 GPU。
3. 如 PyTorch 环境不存在，执行 `scripts/remote/setup_smoke_env.sh`。
4. 如 SOFA 环境不存在，执行：

   ```bash
   scripts/remote/install_sofa.sh /path/to/SOFA_v25.12.00_Linux-Python_3.10.zip
   scripts/remote/check_sofa.sh
   ```

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

当前已证明的是“本地开发 → 远程 GPU/SOFA 执行 → 结果回传”基础链路。尚未证明本课题的自有机器人模型、轨迹数据导出、参数标定或控制效果。

下一步按以下顺序推进：

1. 建立项目自有的最小绳驱连续体机器人 SOFA 场景。
2. 输出时间、控制量、末端位姿和状态轨迹 CSV。
3. 为该场景增加独立启动、状态、验收和回传脚本。
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
| 重要数据位于临时盘 | 立即复制到远程持久存储并拉回必要结果 |

当 SSH 明确返回 `Permission denied (publickey,password)`，且已确认远端实例、网络和端口正常时，在本机项目根目录恢复公钥授权：

```bash
source scripts/remote/config.local.sh
if [[ ! -f "${REMOTE_IDENTITY}.pub" ]]; then
  ssh-keygen -y -f "$REMOTE_IDENTITY" > "${REMOTE_IDENTITY}.pub"
  chmod 644 "${REMOTE_IDENTITY}.pub"
fi
ssh-copy-id -i "${REMOTE_IDENTITY}.pub" -p "$REMOTE_PORT" "$REMOTE_HOST"
scripts/remote/check_connection.sh
```

`ssh-copy-id` 的远端密码由用户交互式输入，不记录到命令、项目文件或日志。只安装 `.pub` 公钥，不得复制或上传私钥。连接恢复后仍需正常执行远端漂移检查和工作区同步。

不直接删除或覆盖远程数据，不使用未经路径确认的 `rsync --delete`。更详细的验收和恢复规则见[远程工作流技术规范](./远程工作流技术规范.md)。

## 7. 修订记录

| 版本 | 日期 | 变化 |
|---|---|---|
| V1.5 | 2026-09-30 | 增加 SSH 公钥授权丢失后的 `ssh-copy-id` 恢复流程与凭据边界 |
| V1.4 | 2026-09-29 | 将 SoftRobots v25.12 Trunk 源码和必要网格固定到本地工作区 |
| V1.3 | 2026-09-29 | 增加 SoftRobots 官方 Trunk 场景的 batch 和远端桌面启动入口 |
| V1.2 | 2026-09-29 | 增加进入项目时自动启动的源码监控、单实例保护和远端漂移阻断 |
| V1.1 | 2026-09-28 | 增加远端 XFCE 桌面的 SofaImGui 可视化启动与 OpenGL 自检脚本 |
| V1.0 | 2026-09-28 | 将 SOP 收敛为主操作流程；技术规范与验收历史拆分为独立文档 |
| V0.9 | 2026-09-28 | 完成 SOFA/SoftRobots 环境及官方 CableConstraint demo 验证 |

更早的修订历史见[远程工作流验收记录](./远程工作流验收记录.md)。
