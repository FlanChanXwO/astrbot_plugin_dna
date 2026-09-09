# AGENTS.md

## 目标

本文件只保留 AI 在本仓库工作时需要长期加载的规则。与用户沟通默认使用简体中文；代码标识符、命令、库名和协议名保持原文。

`astrbot_plugin_dna` 是《二重螺旋》的原生 AstrBot 插件。`main.py` 保持薄入口，当前功能实现以 `src/` 为主；不要把历史迁移过程当作现行架构。

## 事实源

遇到文档与代码不一致时，按以下顺序核验并修正文档：

1. 实际代码和运行期接口；
2. 由代码生成的仓库投影；
3. 对应测试；
4. `docs/usage/` 与 `docs/dev/` 的解释性文档。

关键事实源：

- 命令：`src/entry/commands/` + `src/modules/index.py`；`commands.json` 是生成投影。
- 配置：`src/infrastructure/config/settings.py`；`_conf_schema.json` 是生成投影。
- 入口/生命周期：`main.py`、`src/bootstrap.py`、`src/entry/lifecycle.py`。
- 数据库：`src/infrastructure/persistence/`、`alembic/versions/`。
- 公共资源：`src/infrastructure/resources/` + `dna-resource` 当前 manifest。
- 插件名称、版本、最低 AstrBot 版本：`metadata.yaml`。
- 用户行为：`docs/usage/`；开发结构与维护：`docs/dev/`。

需要了解模块边界时读 `docs/dev/architecture.md`；不要预先加载所有文档。

## 按任务读取

- 改命令、正则、权限、帮助：读 `src/entry/commands/`、`src/modules/index.py`、`tests/test_entry_commands.py`；用户语义变化再读 `docs/usage/commands.md`。
- 改配置：读 `src/infrastructure/config/`、`tests/test_config.py`；用户需要知道时读 `docs/usage/configuration.md`。
- 改登录/账号：读 `src/modules/account/`、相关 HTTP transport、`tests/test_account.py`、`docs/usage/login.md`。
- 改玩家/图鉴/渲染：读对应 `src/modules/`、`src/infrastructure/rendering/` 与领域测试。
- 改持久化：读 persistence + Alembic + `tests/test_persistence.py`；先明确升级/回滚边界再动 schema。
- 改调度/订阅/推送：读对应 scheduler、subscriptions 和领域测试。
- 改 Dashboard：读 `src/entry/admin_web.py`、`src/entry/web.py`、`pages/dashboard/`、`docs/usage/admin-pages.md`。
- 改 Agent Tools：读 `src/entry/agent_tools/`、`src/modules/agent_tools/`、`tests/test_agent_tools.py`、`docs/usage/agent-tools.md`。
- 改公共资源：读 `src/infrastructure/resources/`、`tests/test_resources.py`、`docs/usage/resources.md`。

## 修改流程

1. 找到最接近行为的实现和测试，先确认当前契约。
2. 做最小、内聚的改动；入口层只做 AstrBot 适配，业务逻辑留在 `src/modules/`，副作用适配留在 `src/infrastructure/`。
3. 命令变化后运行 `python3 scripts/generate_commands_manifest.py`；配置变化后运行 `python3 scripts/generate_config_schema.py`。
4. 更新最具体的测试。修 bug 时优先加入能复现问题的回归测试。
5. 只有用户可见行为或维护方式变化时才更新文档；不要复制可由代码/JSON 直接读取的完整清单、数量或默认值表。
6. 运行受影响测试和 lint；跨模块改动再跑完整测试。

## 硬边界

- 使用 AstrBot 原生 API；新代码不依赖 `gsuid_core` / `gsucore`。
- 运行期数据库、缓存、资源快照、订阅状态和渲染产物写入 AstrBot 分配的插件数据目录，不写入源码目录。
- 不提交或输出真实 Cookie、token、验证码、Dashboard 密钥、SQLite 数据库或带凭据的 URL/日志。
- `commands.json` 与 `_conf_schema.json` 不手工维护；修改源模型后重新生成。
- `docs/` 顶层长期只保留 `dev/` 和 `usage/`。迁移计划、阶段报告、一次性 review、机器路径、生产容器名、某次 SHA/测试数量不进入长期文档；版本历史写 `CHANGELOG.md`。
- 用户可见文案当前以 `i18/zh/tip.json` 和 `src/infrastructure/i18n/` 为事实源；不要为不存在的目录维护规则。
- `CLAUDE.md` 通过 `@AGENTS.md` 复用本文件，不在两处复制同一规则。

## 验证

仓库根目录常用检查：

```bash
python3 -m pytest
ruff check .
python3 -m compileall .
```

可先跑最小相关测试文件；准备合并涉及入口、配置、持久化、生命周期、公共资源或跨领域行为的改动时，应运行完整 pytest。需要当前测试集合时使用 `python3 -m pytest --collect-only -q`，不要依赖文档中的固定数量。
