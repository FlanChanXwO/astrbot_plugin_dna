# rewrite/v0.1 阶段 2 集中审查

## 范围与结论

本审查覆盖 Task 5–7 的当前代码：薄入口与生命周期、显式命令 registry、帮助命令、
Pydantic 配置/schema、私有资源 Git 同步接口、版本元数据和 AstrBot staging 加载。
参考区为 `legacy-reference`，所有验证均在 `rewrite/v0.1` worktree 完成。

结论：在 v0.1 已声明的范围内通过，无已知 P0/P1 问题；当前只实现 `帮助`，不能把
本阶段通过解释为历史 56 项能力已经恢复。

## 证据

| 检查 | 结果 |
|---|---|
| `commands.json` 与代码 registry | `manifest_records(COMMAND_REGISTRY)` 完全一致；仅 `help` 注册，未迁移命令不展示 |
| handler 契约 | staging 动态命名空间下 `DnabyPlugin.handle_help` 为真正 async-generator，`__module__` 正确，拥有公开 `RegexFilter` 与 `PermissionTypeFilter` |
| 配置 schema | `_conf_schema.json` 与 `generate_astrbot_schema()` 一致；五个领域分组；AstrBot 4.27.1 `AstrBotConfig` 可递归构造默认值；共享密钥 schema 默认为空 |
| 资源同步 | fixture 覆盖浅克隆、后续 `pull --ff-only`、origin/worktree/manifest 检查、本地修改不 pull、Git 错误脱敏；参数列表执行，无 shell 拼接或 force 覆盖 |
| 版本元数据 | `metadata.yaml` 为 `v0.1.0`；`logo.png` 为 256x256 PNG；`CHANGELOG.md` 记录破坏性边界、私有资源和未实现能力 |
| 自动门禁 | staging pytest `73 passed, 1 warning`；系统/runtime Ruff、Pyright、compileall、pre-commit 均通过 |
| 隔离与敏感数据 | 参考区 clean；重构区 clean；无 tracked 运行期数据、数据库、日志或凭据命中；未创建/推送外部仓库 |

## Findings 与边界

- 没有发现新入口导入 `gsuid_core`/`gsucore`、legacy `Sender/EventContext/MessageSegment`、
  `MASTER_PATTERN` 或全局 dispatch；legacy `dnaby/` 仍作为后续迁移参考保留。
- 私有 `dnaby_resources` 仓库尚未由本阶段创建或推送，符合当前“外部私有仓库需单独授权”的默认假设；
  实际凭据 helper、远端认证和真实资源内容仍待部署环境提供后验证。
- `download_all_resources()` 是同步基础设施接口；后续异步命令接入时必须安排在线程/生命周期边界，
  当前未注册下载命令，也没有在导入或插件初始化时隐式同步资源。
- 新 typed 配置和旧 SQLite 不做自动迁移，已在 `CHANGELOG.md`、配置文档和任务记录中声明。
- Alembic/SQLAlchemy async 属于后续 Task 9 的持久化边界，尚未被本阶段伪装成已完成。

## 发布与回滚

Task 7 基线提交为 `65d23ed`（实现）与 `939a856`（任务记录），本轮审查修复提交为
`3756188`，分支为 `rewrite/v0.1`；参考区保持 `legacy-reference`。未合并、推送、发布
Marketplace 或创建公开 Release。出现问题时可回滚到 `fe9db5b` 之前的阶段提交，不对参考区
执行 destructive reset。
