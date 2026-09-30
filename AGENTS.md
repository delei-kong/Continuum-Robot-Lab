# 连续体机器人实验室项目规则

## 适用范围

- 本文件适用于当前目录及其所有子目录。
- 当前目录是项目根目录，也是源码的唯一可信来源。

## 语言

- 面向用户的分析、说明、文档和回复使用中文；代码、命令及技术标识符可以保留英文。

## 目录

- 源代码放在 `src/`，采用扁平布局。
- 测试放在 `tests/`，基础设施检查放在 `tests/smoke/`。
- 运维脚本放在 `scripts/`，可复用数据放在 `datasets/`，运行结果放在 `outputs/`。
- Agent 工作流和 Skill 源文件放在 `agent/`，其中的版本是权威版本。
- 未经用户明确要求，不得将新实现放到项目根目录之外，也不得移动根目录之外的资料。
- 未经用户明确要求，不得提交大型数据、检查点、缓存或生成结果。

## 文档

- 项目文档保存在 `docs/`。
- 工作过程中，按当天日期创建 `docs/logs/YYYY-MM-DD/` 目录，记录当日有价值的对话与讨论、计划、参考资料和开发文档。
- 需要跨日期长期维护的专题讨论保存在 `docs/discuss/`，包括架构决策、方案比较、实验结论、重要问题分析和未决事项。
- 远程工作流程发生变化时，同步更新 `docs/本地开发与远程实验工作流SOP.md`。

## 本地与远程

- 所有源码修改在本地完成；远程工作站仅用于执行。
- 远程操作使用 `scripts/remote/` 中的脚本，并遵循远程工作流 SOP。
- 发现本地与远程源码不一致时，立即停止同步；未经用户明确授权，不得覆盖或删除远程数据。
- 不得在项目目录中保存密码、私钥、访问令牌或其他凭据。

### SSH 公钥授权恢复

- 当连接或自动同步返回 `Permission denied (publickey,password)` 时，先检查网络、实例状态和 `scripts/remote/config.local.sh`；确认是公钥授权丢失后，由用户在本机项目根目录执行以下流程：

  ```bash
  source scripts/remote/config.local.sh
  if [[ ! -f "${REMOTE_IDENTITY}.pub" ]]; then
    ssh-keygen -y -f "$REMOTE_IDENTITY" > "${REMOTE_IDENTITY}.pub"
    chmod 644 "${REMOTE_IDENTITY}.pub"
  fi
  ssh-copy-id -i "${REMOTE_IDENTITY}.pub" -p "$REMOTE_PORT" "$REMOTE_HOST"
  scripts/remote/check_connection.sh
  ```

- `ssh-copy-id` 会交互式要求远端用户密码；必须由用户输入，Agent 不得索取、记录或代填密码。
- 只向远端安装 `.pub` 公钥；不得复制、输出或上传 `$REMOTE_IDENTITY` 指向的私钥。
- 公钥授权恢复后，仍须按正常流程执行远端漂移检查和工作区同步，不得绕过同步保护。

## Git

- 提交标题使用 `<类型>: <中文摘要>` 格式。
- 未经用户明确授权，不得创建 commit。
- `git push` 属于高风险操作：必须先获得准备授权；检查并报告远程仓库、源分支、目标分支和待推送 commit 后，再获得执行授权。
- 推送授权仅对当次报告的仓库、分支和 commit 有效；目标发生变化时必须重新授权。
- 强制推送以及删除远程分支或标签，必须单独说明风险并再次获得明确授权。

## 环境

- 项目使用 Python 3.11 和独立 Conda 环境；具体配置与远程运行方法以远程工作流 SOP 为准。
