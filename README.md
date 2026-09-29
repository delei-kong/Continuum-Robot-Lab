# Continuum Robot Lab

融合物理先验的绳驱连续体机器人数据驱动建模与控制研究工作区。

当前目标是在2026年11月初中期答辩前跑通以下最小科研闭环：

```text
SOFA仿真 → 轨迹数据集 → 动力学建模 → 闭环控制 → 曲线与可视化
```

本地 `workspace/` 是项目唯一可信源码，远程GPU工作站仅作为同步后的实验执行平台。

## 目录

```text
src/       仿真、建模、控制和评价代码
configs/   可复现实验配置
tests/     冒烟测试和集成测试
scripts/   本地远程管理脚本及服务器执行脚本
agent/     项目级Agent工作流和Skill源码
docs/      计划、SOP、技术规范和报告
datasets/  科研数据集，默认不提交大文件
outputs/   日志、权重、指标、图表和视频，默认不提交
```

## 当前状态

- 本地到远端的工作区同步与SHA-256一致性验证已通过；
- 远端GPU最小训练实验已通过；
- SOFA、SofaPython3、SoftRobots和STLIB已安装；
- 官方CableConstraint示例的batch和GUI运行已验证；
- 自有绳驱连续体机器人场景、数据管线和控制算法尚待实现。

## 工作入口

- 研究推进计划：[docs/plan.md](docs/plan.md)
- 本地与远端SOP：[docs/本地开发与远程实验工作流SOP.md](docs/本地开发与远程实验工作流SOP.md)
- 技术规范：[docs/远程工作流技术规范.md](docs/远程工作流技术规范.md)
- 验收记录：[docs/远程工作流验收记录.md](docs/远程工作流验收记录.md)

任何密码、私钥、Token或机器专用配置都不得提交到本仓库。
