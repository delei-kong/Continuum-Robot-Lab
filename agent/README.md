# Project Agent Assets

这里是本项目Agent工作流和Skill的权威源码，与科研代码共同进入Git版本管理。

- `workflows/`：跨角色的标准操作流程、职责边界和必要提示模板；
- `skills/`：可复用的项目级Skill。
- `settings.json`：项目级 Codex hooks 的权威配置；部署副本位于 `.codex/hooks.json`。

工具的全局安装目录和缓存只是部署副本，不能替代本目录中的版本化源码。
