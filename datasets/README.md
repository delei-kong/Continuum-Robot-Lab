# Datasets

存放 SOFA 生成、外部引入及清洗后的正式训练数据。数据集大文件默认不进入 Git；每个 release 必须记录
生成配置、随机种子、轨迹级划分、质量审计和来源哈希。

## 规范格式

正式数据集统一使用 `continuum_dynamics_dataset_v1` 格式：

```text
datasets/<dataset_id>/<release_id>/
├── COMPLETE
├── dataset_manifest.json     # release、split、来源审计和文件哈希
├── schema.json               # 状态/动作列、单位、dt 和转移语义
├── episodes/<split>/*.csv    # 保留的逐 episode 原始观测
├── transitions/<split>.npz   # state、action、next_state、episode_index、episode_ids
└── provenance/
    ├── audit.json
    ├── source_manifest.json
    ├── effective_configs/
    └── run_metadata/
```

`transitions/<split>.npz` 是训练的统一输入；它保留完整 episode 边界，严禁按行跨 split 切分。`episodes/`
中的 CSV 是可读、可复核的原始记录，`provenance/` 使 release 不依赖 `outputs/` 仍可追溯来源。

原始 SOFA run 结果仍保留在 `outputs/trunk_forward_data/<run_id>/`，作为不可变运行证据，不再作为模型训练入口。
审计通过后，使用受控命令物化 release：

```bash
PYTHONPATH=src python scripts/experiment/audit_koopman_dataset.py \
  --dataset koopman_v1 \
  --materialize-from <dataset_audit_id> \
  --release <release_id>
```

当前正式 release 为 `datasets/koopman_v1/20261005_koopman_v1_v1/`。它和后续生成的数据均受 `.gitignore`
保护，不应提交到 Git。
