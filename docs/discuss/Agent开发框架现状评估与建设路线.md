# Agent 开发框架现状评估与建设路线

> 日期：2026-09-30  
> 范围：当前工作区、项目内 Agent 资产、测试与远程实验流程  
> 定位：跨日期维护的建设建议，不代表已经完成实现

## 1. 执行摘要

本项目已经有一套不错的 Agent 治理骨架：项目边界清晰，本地源码是唯一可信来源，远程只执行；`AGENTS.md`、远程 SOP、不可覆盖的 run ID、SHA-256 同步校验和实验元数据规范也已经建立。更重要的是，项目已经明确把科研软件资产和 Agent 资产共同纳入 Git 管理。

当前真正缺少的不是更多角色名称或更长的提示词，而是从“规则和计划”走到“可执行、可评测、可追踪、可发布”的闭环：

1. `agent/` 仍是空骨架，没有实际 workflow、Skill、registry 条目或部署入口；
2. 没有 Agent 评测任务、运行器、trace、基线和发布门禁；
3. 稳定操作尚未封装成结构化接口，远程脚本之间仍存在实验产物合同不完全一致的问题；
4. 本地开发环境不可复现，当前系统 Python 为 3.9.6，且未安装 pytest，而项目规则要求 Python 3.11；
5. 科研接口本身尚未稳定，自有 SOFA 场景、轨迹数据合同、建模和控制都未实现，因此不适合现在就扩展大量领域 Skill；
6. 实验元数据尚未记录 Agent harness、模型、Skill/workflow 版本、权限和工具调用，无法重放“Agent 如何产生这次改动或实验”。

因此，推荐的第一阶段目标是：

```text
一个通用开发 Agent
  + 简洁的 AGENTS.md 全局边界
  + 三条项目工作流
  + 三个渐进式 Skill
  + 一套 Agent eval / trace / registry
  + 现有确定性脚本作为工具层
```

暂不建设复杂多 Agent 编排。现有四个角色更适合作为职责视角和评审清单，而不是四个长期自治进程。

## 2. 当前项目已经具备的好基础

### 2.1 项目和科研目标清晰

项目已经定义最小科研闭环：SOFA 仿真、轨迹数据、动力学建模、闭环控制和可视化。当前文档也诚实地区分了“工程基础设施闭环已经完成”和“科研闭环尚未完成”。这种边界非常适合 Agent 工作，因为 Agent 的任务可以围绕阶段门禁定义，而不是围绕模糊的“帮我做研究”定义。

### 2.2 全局规则足够简洁

现有 `AGENTS.md` 主要描述目录、语言、远程安全、Git 授权和环境边界，没有塞入具体仿真流程。这一方向正确。OpenAI 当前建议定期清理全局规则，按任务需要指向具体文档，而不是要求每个小改动都加载整个仓库；Skill 也应采用渐进披露，避免上下文膨胀。[OpenAI：Rethinking skills and prompts](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)

### 2.3 远程实验流程具有良好的安全基础

当前流程已经具备以下重要性质：

- 本地是唯一代码源，远端只执行；
- 同步前检查远端漂移；
- 每次实验使用唯一 run ID，并拒绝覆盖；
- 保存退出码、日志、版本与元数据；
- 成功标记和业务验收分离；
- 凭据与项目工作区分离；
- 正式结论要求超出“进程退出码为 0”的数值和物理验证。

这些不是外围细节，而是 Agent 安全执行远程实验时最重要的工具层不变量。

### 2.4 Agent 资产已有正确的版本化原则

项目已经明确 `agent/` 是 workflow 和 Skill 的权威源码，全局安装目录只是部署副本；计划也列出了首批三个 Skill 和初步回归检查。这说明方向没有问题，主要问题是还没有实现和验证。

## 3. 现状证据与缺口

### 3.1 Agent 资产仍停留在设计层

当前 `agent/registry.yaml` 只有：

```yaml
schema_version: 1
workflows: []
skills: []
```

`agent/skills/README.md` 和 `agent/workflows/README.md` 也只有未来计划。仓库中没有任何 `SKILL.md`、workflow 规范、Agent eval case、registry schema 或安装脚本。

影响：

- Agent 不知道何时触发哪个项目工作流；
- 无法保证不同会话或模型遵循同一产物合同；
- Skill 修改无法做回归比较；
- “项目中的权威版本”尚不能部署到实际 Agent 环境。

### 3.2 计划有质量门禁，但没有评测基础设施

`docs/plan.md` 已要求验证正确目录、run ID 不覆盖、凭据保护、完整元数据、NaN/错误识别和 Skill 升级后的结构一致性，但当前只有一个上游 Trunk 资产校验测试，没有 Agent 任务集、模拟环境、trace 或 grader。

Agent 评测至少应区分：

- 最终状态是否正确；
- Agent 是否选择了正确的 workflow/Skill；
- 是否遵守权限、目录和审批边界；
- 是否以合理成本完成，而非反复尝试；
- 多次运行是否稳定。

OpenAI 的 Skill 评测建议把结果、过程、风格和效率分别评分，并同时加入应触发和不应触发的样例。[OpenAI：Testing Agent Skills Systematically with Evals](https://developers.openai.com/blog/eval-skills) Anthropic 进一步区分 task、trial、grader、trace、outcome 和 harness，并强调多次 trial 以及对最终环境状态的判定。[Anthropic：Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

### 3.3 本地测试入口当前不可执行

检查结果：

- 当前 `python3` 是 3.9.6；
- `python3 -m pytest -q` 报告没有安装 pytest；
- `pyproject.toml` 声明 `>=3.10,<3.12`，项目规则指定 Python 3.11；
- 远端实际存在 PyTorch Python 3.11 与 SOFA Python 3.10 两套运行时；
- 仓库没有 Conda environment 文件、依赖锁文件或 CI 配置。

Shell 语法检查通过，但这不足以形成 Agent 开发的本地反馈回路。

影响：Agent 每次更改后无法在标准环境中执行同一组检查，也无法区分“代码失败”和“环境缺失”。双 Python 运行时是合理的现实约束，但需要显式建模成兼容矩阵，而不是只靠 SOP 文字说明。

### 3.4 稳定流程写在文档和脚本里，但尚未形成统一工具合同

现有远程脚本已经实现许多正确行为，但不同任务的产物还不完全一致。例如正式规范要求配置快照、完整 metadata、指标和 Agent/代码版本；当前历史输出中，GPU smoke 与 SOFA demo 的文件集合并不统一，通用正式实验启动器也被明确标记为“尚未实现”。

影响：Skill 如果直接编排这些脚本，会继承不一致的输入输出，grader 也很难使用统一规则。应先统一 run manifest 与 verifier，再让 Agent 调用。

### 3.5 科研领域合同尚未成为机器可检查的不变量

目前仍未实现自有 SOFA 场景、`reset/step/save_trajectory` 接口、轨迹 schema、单位与坐标系定义、数据切分和闭环控制。对科学软件 Agent 而言，普通代码测试不够：还需要检查单位、坐标系、数值稳定性、物理对称性、数据格式和实验溯源。

SWE-bench Science 的设计也把这些 scientific contracts 视为科学代码 Agent 的核心，并使用固定基线、按 digest 固定的环境、独立 verifier 和干净重建进行验收。[SWE-bench Science](https://github.com/OpenMOSS/SWE-bench-Science)

### 3.6 缺少 Agent 运行溯源

当前实验元数据记录 Git commit、工作区状态、Python/SOFA/GPU 和时间，但还没有：

- Agent harness 与版本；
- 模型标识和关键推理配置；
- `AGENTS.md` / workflow / Skill 的版本或哈希；
- 工具调用与审批记录；
- 修改前后 diff；
- token、耗时、失败重试；
- Agent 任务 ID 与科研 run ID 的关联。

因此，即使代码和实验结果可追踪，也无法回答“这次 Agent 行为为什么和上次不同”。

### 3.7 安全边界存在，但没有对抗性测试

现有项目规则已经限制凭据、覆盖、远程漂移和删除，这是正确的；但没有测试 Agent 如何处理来自 README、日志、下载资料或远端输出中的恶意指令。AgentDojo 的研究指出，工具返回的不可信文本可通过间接 prompt injection 劫持 Agent 行为，并主张用环境最终状态和安全属性做动态评测，而不是只检查文字回答。[AgentDojo, NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/97091a5177d8dc64b1da8bf3e1f6fb54-Paper-Datasets_and_Benchmarks_Track.pdf)

本项目后续会读取论文、日志、配置和远端输出，这些都应被视为数据，而不是高优先级指令。

## 4. 一个好的 Agent 开发项目应是什么样

一个成熟的 Agent 项目不是“提示词仓库”，而是以下闭环：

```text
用户目标与风险边界
        ↓
任务合同（输入、输出、完成定义）
        ↓
路由：普通请求 / 固定 workflow / 自主 Agent
        ↓
Skill 提供领域流程，脚本提供确定性工具
        ↓
沙箱、权限、审批和远程执行边界
        ↓
trace + 最终产物 + 环境状态
        ↓
确定性 grader + 模型 grader + 人工科研审核
        ↓
registry、版本、发布门禁、回滚和真实失败回灌
```

### 4.1 从任务合同开始，而不是从角色开始

每个 Agent 能力先写清楚：

- 用户意图与典型输入；
- 前置条件；
- 可调用工具；
- 允许修改的路径与外部系统；
- 输出 schema；
- 完成条件；
- 失败条件与停止条件；
- 哪些决策必须由人确认。

“Research Planner”“Simulation Engineer”等角色可以保留为责任视角，但不应自动等价为多个自治 Agent。角色解决的是责任分工，task contract 解决的是可执行性。

### 4.2 固定流程优先使用 workflow，自主性只用于不确定部分

远程同步、run ID 校验、启动、状态检查、回传和审计是确定路径，应该由代码化 workflow 控制；文献调研、故障诊断和方案比较才需要更高自由度。Anthropic 对 workflow 和 agent 的区分也是：前者使用预定义路径以获得一致性，后者让模型动态决定步骤；应从最简单可用结构开始，因为自主性会增加延迟、成本和错误面。[Anthropic：Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)

### 4.3 指令、Skill 和工具分层

- `AGENTS.md`：只放全项目长期稳定的不变量和文档路由；
- workflow：定义跨工具的操作序列、审批点、失败恢复和产物；
- Skill：说明何时采用某领域工作法，复用模板、参考资料和必要脚本；
- scripts/tools：执行确定性动作，负责真实权限与数据校验；
- docs：保存架构决策、领域知识和实验结论；
- task prompt：只描述本次目标和本次完成定义。

OpenAI 对 Skill 的定义也是：Skill 是可复用工作流的说明层，工具或 MCP 提供实时数据、认证、授权和受控动作；模型先根据简短 metadata 决定是否加载完整指令。[OpenAI：Skills](https://developers.openai.com/plugins/concepts/skills)

### 4.4 验收最终世界状态，而不是只看回答

例如“远程实验成功”不能由 Agent 最终说“已完成”来判定，而要检查：

- 指定 run 目录是否新建且未覆盖；
- commit/config/环境是否记录；
- `COMPLETE`、退出码和必需产物是否一致；
- 轨迹是否有限、单位正确并满足物理阈值；
- 回传哈希是否一致；
- 没有访问禁止路径或泄露凭据。

模型输出只是 trace 的一部分，文件系统、远端状态和数值产物才是 outcome。

### 4.5 可复现、可观测、可回滚

每次 Agent trial 至少保存：任务、环境基线、模型/harness、加载的规则与 Skill、工具调用、审批、文件 diff、grader 结果、耗时和最终状态。Agent 版本发布后必须能回退到上一版，并能在同一 eval suite 上比较。

### 4.6 科研判断保留人工门禁

Agent 可以检查数据、生成图表、复现实验和形成候选解释，但以下事项应保留人工确认：

- 研究问题和对照组变更；
- 物理参数解释；
- 数据排除规则；
- 是否支持论文结论；
- 向外发布的科研声明；
- 删除或覆盖不可再生数据。

## 5. 推荐的项目内架构

```text
agent/
├── README.md
├── registry.yaml
├── schemas/
│   ├── registry.schema.json
│   ├── task.schema.json
│   └── trace.schema.json
├── workflows/
│   ├── remote-experiment.md
│   ├── sofa-validation.md
│   └── result-audit.md
├── skills/
│   ├── experiment-result-auditor/
│   │   ├── SKILL.md
│   │   ├── references/
│   │   └── templates/
│   ├── remote-experiment-operator/
│   │   └── SKILL.md
│   └── sofa-scene-validator/
│       └── SKILL.md
├── evals/
│   ├── cases/
│   ├── fixtures/
│   ├── rubrics/
│   └── baselines/
└── templates/
    ├── exec-plan.md
    └── agent-run-manifest.json

scripts/agent/
├── validate_registry.py
├── install_skills.sh
├── run_evals.py
└── summarize_trace.py

tests/
├── agent/
│   ├── test_registry.py
│   ├── test_skill_metadata.py
│   └── test_security_boundaries.py
└── integration/
    ├── test_remote_experiment_workflow.py
    ├── test_result_audit_workflow.py
    └── test_sofa_validation_workflow.py
```

`agent/` 保存声明性资产和评测数据；`scripts/agent/` 保存通用运行、校验和部署入口；`tests/` 保存可由标准测试命令执行的检查。Skill 自身专用的小脚本仍放在对应 Skill 目录，避免和通用基础设施混淆。

### 5.1 registry 建议字段

每个条目至少记录：

```yaml
id: experiment-result-auditor
kind: skill
version: 0.1.0
status: draft
owner: project
entrypoint: agent/skills/experiment-result-auditor/SKILL.md
triggers: []
inputs: []
outputs: []
risk_level: R0
permissions: []
dependencies: []
eval_suite: agent/evals/cases/experiment-result-auditor.yaml
compatible_harnesses: []
change_log: []
```

状态建议使用 `draft → active → deprecated → retired`。所有 `active` 条目必须存在、通过 schema、拥有 eval suite，并在部署后能验证哈希。

### 5.2 风险级别建议

- `R0`：只读、本地分析；可自动执行；
- `R1`：本地工作区可恢复写入；执行后报告 diff；
- `R2`：启动远程计算、使用显著资源或写入远端新 run；需要明确任务授权和预算边界；
- `R3`：删除、覆盖、push、对外发布或其他不可逆动作；沿用项目现有人工审批规则。

风险级别必须在工具层强制，而不是只写在 Skill 提示里。

## 6. 首批能力的正确落地顺序

### 6.1 第一项：`experiment-result-auditor`

建议把它作为第一个真正落地的 Skill，而不是先做最复杂的远程执行 Agent，原因是它只读、已有历史输出可做 fixture、输入输出容易固定，也能顺便建立 registry、eval、trace 和发布全链路。

首版只做确定性检查：

- 必需文件和状态标记；
- JSON/CSV schema；
- commit、config、环境和退出码完整性；
- NaN/Inf、时间单调、样本数和哈希；
- 禁止 train/test 相邻 transition 泄漏的证据检查；
- 生成机器可读 `audit.json` 和中文摘要。

### 6.2 第二项：`remote-experiment-operator`

先把它实现成 workflow，再在上面加薄 Skill：

```text
preflight
→ 本地检查
→ 远端漂移检查
→ 同步并验证
→ 生成新 run manifest
→ 启动
→ 监控
→ verifier
→ 回传
→ result auditor
```

每个步骤输出结构化状态，并支持 `--dry-run` 或 fake remote fixture。Skill 只负责理解用户意图、选择配置和解释失败，不能绕过脚本直接拼接任意 SSH 命令。

### 6.3 第三项：`sofa-scene-validator`

等自有场景和轨迹 schema 完成后再激活。首版 grader 应优先检查：

- RequiredPlugin 和资源存在；
- 输入边界与单位；
- 零输入平衡和确定性；
- 单绳方向、对称性和时间步稳定性；
- 轨迹字段、NaN/Inf 和求解器错误；
- 上游固定资产未被修改。

在此之前只把它保留为 `draft` workflow，不要把未稳定的方法固化为 Skill。

## 7. Agent eval 体系

### 7.1 三层评测

第一层是静态检查：

- registry/schema；
- Skill metadata 与引用路径；
- 禁止路径、凭据模式、危险命令；
- 文档和脚本入口存在。

第二层是隔离集成评测：

- 临时工作区和 fake remote；
- 固定 baseline 与 fixture；
- 测试文件变化、命令调用和最终状态；
- 使用确定性 grader；
- 测试成功、失败、超时、重复 run ID、远端漂移和脏工作区。

第三层是真实端到端 canary：

- 小型、低成本、唯一 run ID；
- 只在前两层通过后执行；
- 记录完整 trace；
- 不删除历史结果；
- 科研结果仍由人审核。

### 7.2 每个 Skill 的最小任务集

建议初期每个 Skill 10～20 个 case：

- 3 个明确触发；
- 3 个自然语言隐式触发；
- 2 个相邻但不应触发；
- 3～5 个错误/缺失输入；
- 2～3 个安全与权限攻击；
- 2 个历史真实失败回归。

每个 case 至少运行 3 次，关键安全 case 必须全部通过。模型具有随机性，单次通过不足以说明稳定。

### 7.3 核心指标

- 任务成功率和关键 case 通过率；
- Skill 触发 precision / recall；
- 禁止动作率，目标为 0；
- 完整元数据率，目标为 100%；
- 结果可复现率或数值容差内一致率；
- 人工接管次数；
- 中位工具调用数、耗时和 token；
- 与上一 active 版本相比的回归数量。

### 7.4 发布门禁

一个 Skill 从 `draft` 变为 `active` 前，应满足：

- registry 与引用完整；
- 确定性检查 100% 通过；
- 高风险和安全 case 100% 通过；
- 任务成功率达到预设阈值；
- 至少人工审阅若干完整 trace；
- 有变更记录和回滚版本；
- 安装副本哈希与 `agent/` 权威源码一致。

## 8. 建议的四阶段路线

### 阶段 A：建立可运行的开发脊柱（1～2 天）

目标：任何人或 Agent 都能用一个命令得到一致反馈。

1. 明确双运行时矩阵：本地/训练 Python 3.11，SOFA adapter Python 3.10；
2. 增加可重建环境和 dev/test 依赖；
3. 增加统一 `check` 入口，至少执行 shell 语法、Python 单测、ruff 和 registry 校验；
4. 建立最小 CI，默认不连接远端；
5. 修复本地 Python 3.9 与缺失 pytest 的问题。

验收：新环境中一个命令完成全部本地检查，失败能明确归因。

### 阶段 B：实现第一个垂直闭环（2～4 天）

目标：以 `experiment-result-auditor` 验证框架设计。

1. 定义 registry schema、run manifest 和 audit 输出 schema；
2. 从现有历史输出制作脱敏小 fixture；
3. 实现 Skill、确定性 auditor 和 10～20 个 eval case；
4. 记录 trace、成本和最终 grader 结果；
5. 完成安装、哈希验证和回滚演练。

验收：Skill 从源码到部署、触发、执行、评测和回滚全部跑通。

### 阶段 C：工作流化远程实验（3～5 天）

目标：把已有 SOP 变成机器可执行状态机。

1. 统一 run manifest 和产物合同；
2. 建立 preflight、start、status、verify、fetch、audit 的结构化接口；
3. 加入 fake remote、dry-run、超时、重入和恢复测试；
4. 接入 `remote-experiment-operator` 薄 Skill；
5. 把 Agent 版本和 trace ID 写入实验 metadata。

验收：在不访问真实远端的情况下覆盖主要分支；真实 canary 可完整执行且不可覆盖。

### 阶段 D：接入科研闭环（随 G2/G3 推进）

目标：让 Agent 评测真正覆盖连续体机器人领域不变量。

1. 固定轨迹 schema、单位、坐标系和误差定义；
2. 实现 SOFA 数值与物理 invariant tests；
3. 激活 `sofa-scene-validator`；
4. 增加数据泄漏、重复性、多 seed、消融和基线检查；
5. 将真实失败持续回灌到 eval suite。

验收：Agent 不只是生成代码，还能在干净环境中证明科研产物满足预定义合同。

## 9. 现在不建议做的事情

- 不要先引入复杂的多 Agent orchestration 框架；
- 不要把四个职责角色直接实现为四个常驻自治 Agent；
- 不要把整个 SOP 复制进 `AGENTS.md`；
- 不要为尚未稳定的建模、控制和论文写作流程创建大量 Skill；
- 不要用 LLM judge 代替所有确定性数值检查；
- 不要让 Skill 直接持有凭据或绕过 `scripts/remote/`；
- 不要把 Agent 最终回答当作任务成功证据；
- 不要让 eval 使用会被待测 Agent看到的参考答案或敏感 verifier 数据。

## 10. 下一步建议

按投入产出比，下一次实施建议只做一个小里程碑：

> 建立本地可运行的 Agent 框架最小脊柱，并完成 `experiment-result-auditor` 的第一个端到端版本。

该里程碑应包含：环境、registry schema、run/audit schema、一个 Skill、一个确定性 auditor、10～20 个 eval case、统一检查命令和部署哈希验证。完成它之后，再判断 registry 字段、目录和 eval harness 是否合适，然后复制模式到远程实验和 SOFA 验证，而不是一次性搭建一个庞大的 Agent 平台。

## 11. 参考资料

- [OpenAI：Rethinking skills and prompts for GPT-6 Astra](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra)
- [OpenAI：Testing Agent Skills Systematically with Evals](https://developers.openai.com/blog/eval-skills)
- [OpenAI：Skills](https://developers.openai.com/plugins/concepts/skills)
- [OpenAI：Using PLANS.md for multi-hour problem solving](https://developers.openai.com/cookbook/articles/codex_exec_plans)
- [Anthropic：Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic：Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [AgentDojo, NeurIPS 2024](https://proceedings.neurips.cc/paper_files/paper/2024/file/97091a5177d8dc64b1da8bf3e1f6fb54-Paper-Datasets_and_Benchmarks_Track.pdf)
- [SWE-bench Science](https://github.com/OpenMOSS/SWE-bench-Science)
- [AstaBench](https://allenai.org/asta/bench)
