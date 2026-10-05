# Datasets

存放SOFA生成的轨迹、外部数据以及清洗和切分后的训练数据。

数据集大文件默认不进入Git；每个正式数据集应记录生成配置、随机种子、轨迹级划分、数据校验结果和来源代码的Git提交。

`koopman_v1` 的原始 episode 仍回传到 `outputs/trunk_forward_data/<run_id>/`，不直接复制到本目录。
通过 `scripts/experiment/audit_koopman_dataset.py` 审计后，数据集来源清单和质量报告写入
`outputs/koopman_datasets/<dataset_audit_id>/`。训练只能读取审计通过的 manifest，不能按 CSV 行随机切分。
