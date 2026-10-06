# Koopman 数据集设计与质量审计

> 状态：正式数据集已审计并物化为规范 release，供后续建模与控制使用
> 日期：2026-10-05

## 1. 目标

`koopman_v1` 是 M2 的首个正式数据集。它只使用正向绳驱 Trunk 数据，训练目标为：

```text
state[t-1] + applied_action[t] → state[t]
```

每个 episode 在 SOFA 中从相同物理初态独立开始；数据切分只能以完整 episode 为单位，不能按行随机拆分，
也不能复用相同 seed 的内容到不同 split。

## 2. 状态、动作与时序合同

原始 `episode.csv` 保留全部 92 列。Koopman v1 选择：

- 状态 `x`：8 根绳的实际位移和约束力（16）、末端位置（3）、10 个中心线点的位置与速度（60），共 79 维；
- 动作 `u`：8 根绳的实际施加位移命令，共 8 维；
- 目标：下一观测状态 `x_next`，共 79 维。

场景在步首写入 `u[t]`，在步末记录 `x[t]`。因此第一个 CSV 行没有被记录的初始状态，长度为 `N`
的 episode 只生成 `N-1` 条转移：`(x[t-1], u[t], x[t])`。任何转移均不得跨 episode 拼接。

## 3. 固定采集矩阵

每个 episode 使用 10 ms 步长、20 s 时长、1 s 静置，共 2000 行与 1999 条模型转移。

| Split | 已注册 batch | Episodes | 激励覆盖 | 预期转移数 |
|---|---|---:|---|---:|
| train | `koopman_v1_train` | 4 | 低、中、高幅值与较高频率 | 7996 |
| validation | `koopman_v1_validation` | 2 | 独立 seed 与未见频率/幅值组合 | 3998 |
| test | `koopman_v1_test` | 2 | 独立 seed 与未见频率/幅值组合 | 3998 |

8 个输入、seed、幅值和频率保存在本地 `configs/trunk_forward_koopman_v1_*.json`；这些文件由 Git
忽略，避免将大量逐 episode 实验参数提交到仓库。`scripts/remote/sync.include` 将它们纳入受保护的远端
源码同步，实际使用值也会写入 run 的 `effective_config.json`。batch 矩阵在
`src/experiment/forward_data_cli.py` 注册；操作者不能从命令行扫描物理或激励参数。

## 4. 质量门禁

`configs/koopman_dataset_v1.json` 与 `src/modeling/koopman_dataset.py` 强制以下条件：

1. 每个 episode 恰为连续时间序列，行号从零连续、时间步与 10 ms 合同一致；
2. 每个 episode 至少 2000 行，状态和动作字段完整、有限，且 `non_finite=0`；
3. 任一 episode 的命令限幅比例不超过 5%，每根绳的命令跨度至少为 1 mm；
4. train、validation、test 都非空，CSV 路径、episode ID 和内容 SHA-256 均不得重复；
5. 仅接受已回传的标准成功产物：`COMPLETE`、`exit_code=0`、有效配置、元数据和 `episode.csv`。

审计会将数据合同、各 episode SHA-256、每 split 行数/转移数和失败原因写入独立结果目录。归一化参数、
lift 函数和模型选择只能在 train split 拟合；validation 用于选择，test 只用于最终一次报告。

## 5. 标准执行顺序

先从本地运行三个已注册的采集 batch：

```bash
python scripts/experiment/run_forward_data.py \
  --batch koopman_v1_train --output <train_batch_id>
python scripts/experiment/run_forward_data.py \
  --batch koopman_v1_validation --output <validation_batch_id>
python scripts/experiment/run_forward_data.py \
  --batch koopman_v1_test --output <test_batch_id>
```

每个 case 具有 `<batch_id>__<input>` 的独立 run ID。按 `trunk_forward_data` profile 回传所有成功 case 后，
组装并审计数据集：

```bash
python scripts/experiment/audit_koopman_dataset.py \
  --dataset koopman_v1 \
  --train-batch <train_batch_id> \
  --validation-batch <validation_batch_id> \
  --test-batch <test_batch_id> \
  --output <dataset_audit_id>
```

该入口只接收注册的数据集 ID、batch 输出 ID 和审计输出 ID；原始文件路径不能由命令行指定。审计通过后，
必须进一步物化为 Git 忽略的规范数据集 release：

```bash
PYTHONPATH=src python scripts/experiment/audit_koopman_dataset.py \
  --dataset koopman_v1 \
  --materialize-from <dataset_audit_id> \
  --release <release_id>
```

release 固定写入 `datasets/<dataset_id>/<release_id>/`：它保留按 split 的 episode CSV、训练统一使用的
`transitions/<split>.npz`、schema、审计副本、有效配置、运行元数据与 SHA-256。`outputs/koopman_datasets/`
仅保留审计运行证据；Koopman 训练只允许读取规范 release。

## 6. 首次正式数据集记录

`20261005_koopman_v1_dataset_audit_v1` 已通过审计，对应 train、validation、test batch 分别为
`20261005_koopman_v1_train_v1`、`20261005_koopman_v1_validation_v1` 和
`20261005_koopman_v1_test_v1`。它包含 8 个独立 episode、16,000 行观测和 15,992 条转移；
所有数值有限、跨 split SHA-256 不重复，命令限幅比例为 0.35%–0.80%。后续模型训练必须引用这一审计
输出，不得以 M1 pilot 或 GUI canary 替换其中任一 split。

该审计结果已物化为 `datasets/koopman_v1/20261005_koopman_v1_v1/`，格式为
`continuum_dynamics_dataset_v1`。它包含 8 个 CSV episode、train/validation/test 三个 NPZ transition
文件和完整 provenance；文件由 `.gitignore` 忽略。
