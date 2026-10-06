# Koopman 模型基线与预测评价

> 日期：2026-10-06  
> 状态：v2 受保护选择与最终评估已完成；M2 自动预测门槛通过

## 目标

在固定的 `koopman_v1` 审计数据集上建立可比较的动力学预测基线。模型只学习 episode 内的离散转移：

```text
x[t-1] + u[t] → x[t]
```

其中 `x` 为 79 维状态，`u` 为 8 维实际施加绳索命令。该阶段检验模型预测能力，不将模型直接接入
SOFA 控制闭环。

## 受控输入与隔离

- 训练入口只接受注册的 `koopman_v1` 和一个已通过审计的规范 dataset release ID；
- 训练器重新核验 release 的 schema、状态/动作合同、transition NPZ 哈希和来源审计哈希，拒绝被改动的数据；
- 均值和尺度只由 train 的 7,996 条转移拟合；
- validation 的 3,998 条转移仅用于候选模型选择；
- test 的 3,998 条转移仅输出最终一次报告，不能反向调整配置。

## 第一版模型

`configs/koopman_model_v1.json` 固定两项候选：

| 名称 | 动力学形式 | 作用 |
|---|---|---|
| `linear_affine` | `x[t+1] = A x[t] + B u[t] + c` | 最小线性对照 |
| `edmd_rff` | 固定随机 Fourier 升维后的 EDMD with control | 标准固定升维 Koopman 候选 |

两者均以岭回归拟合。`edmd_rff` 的随机频率与相位由固定种子生成，输出中会持久化全部参数；它不是
端到端可学习 lift，后者在固定升维基线稳定后再单独引入。

第二轮的 `configs/koopman_model_v2.json` 在运行前登记三个 RFF 特征数、带宽与随机种子组合。其 validation
阶段只能读取 train 与 validation 转移，写出带配置和数据集哈希的 `selection.json`；final 阶段必须引用
该文件，且只对线性基线与所选 Koopman 候选计算一次 test 指标。这样后续候选比较不会再次把 test 用作调参
信号。

## 评价口径

对每个 split 保持动作序列为真实记录值，以真实起点进行开环多步滚动，绝不跨 episode。输出：

- 一步预测，以及 1、10、50、100 步滚动；
- 归一化状态 RMSE；
- 末端位置 RMSE（mm）；
- 中心线位置 RMSE（mm）；
- 每个 horizon 的实际样本数。

验证集依据 100 步归一化状态 RMSE 选择候选。输出目录保存 `models.npz`、`normalization.json`、
`dataset_provenance.json`、验证/测试指标、`summary.json` 及 `COMPLETE`，使模型和结果可复跑。

## 执行

```bash
PYTHONPATH=src python scripts/experiment/train_koopman.py \
  --model koopman_v2_rff_candidates \
  --dataset koopman_v1 \
  --dataset-release 20261005_koopman_v1_v1 \
  --output <validation_output_id> \
  --stage validation
```

该计算不涉及机器人运动，因此当前阶段的验收以数据隔离、数值指标、结果文件完整性和可复跑性为准。
模型通过独立测试的多步稳定性门槛后，再开始设计 Koopman 环境与模型强化学习接口。最终测试还必须使用
`--stage final --selection <validation_output_id>`，不能省略选择来源。

## 首次结果与结论

首次固定配置运行输出为 `20261006_koopman_v1_fixed_lift_v1`。其来源审计为
`20261005_koopman_v1_dataset_audit_v1`，并已物化为规范 release `20261005_koopman_v1_v1`；结果包包含
完整的来源哈希、模型参数和 `COMPLETE` 状态。

验证集以 100 步归一化状态 RMSE 选择 `edmd_rff`（0.7305），优于线性基线（0.7766）。独立测试集上，
100 步时 `edmd_rff` 仍略优于线性基线：状态 RMSE 为 0.7346 vs 0.7419，末端 RMSE 为 10.90 mm vs
11.48 mm，中心线位置 RMSE 为 5.51 mm vs 5.83 mm；整个 100 步滚动没有出现非有限数值。

但在线性更容易处理的短时域中，`edmd_rff` 暂未取胜：测试集一步归一化状态 RMSE 为 0.1105（线性
0.0914），10 步为 0.5272（线性 0.4748），50 步为 0.6066（线性 0.5796）。因此该结果只证明固定升维
Koopman 基线和评价链路成立，不宣称当前模型已具备支撑模型强化学习的精度。后续改进只能以训练/验证
split 进行选择；当前 test 结果作为 v1 基准冻结，不用于调参。

## v2 受保护选择与最终评估

v2 的候选选择输出为 `20261006_koopman_v2_selection_v1`。它只计算 validation 指标，并选择
`edmd_rff_48_b1`。训练器随后使用该选择输出、相同数据集哈希和相同配置哈希生成唯一的 final 结果
`20261006_koopman_v2_final_v1`。

独立 test 上，所选模型在 50 和 100 步优于线性基线：

| Horizon | `edmd_rff_48_b1` 状态 NRMSE | 线性状态 NRMSE | Koopman 末端 RMSE | 线性末端 RMSE |
|---:|---:|---:|---:|---:|
| 1 | 0.0946 | 0.0914 | 0.046 mm | 0.045 mm |
| 10 | 0.4800 | 0.4748 | 1.900 mm | 1.886 mm |
| 50 | 0.5756 | 0.5796 | 6.742 mm | 6.793 mm |
| 100 | 0.7311 | 0.7419 | 11.104 mm | 11.485 mm |

模型在所有评价 horizon 保持有限值，且主评价口径（100 步）由验证选择和独立测试一致地优于基线。短时域
未优于线性模型这一限制必须保留在后续结论中；在不改用新的独立测试集前，不再调整或重新报告 v2 的 test
指标。
