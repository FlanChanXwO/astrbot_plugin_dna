# 架构

本页只描述当前插件的长期结构与事实源，不记录迁移阶段、临时任务或某次部署快照。判断具体行为时，以代码、生成清单和测试为准。

## 运行链路

`main.py` 是 AstrBot 的薄入口：创建 runtime，并把 `initialize()` / `terminate()` 交给 `src.bootstrap`。业务编排不应回流到入口文件。

主要分层：

- `src/entry/`：AstrBot 适配层。负责命令注册、事件解析、响应转换、生命周期、Dashboard Web 路由和 Agent Tools 注册。
- `src/modules/`：业务用例。当前覆盖账号、管理、Agent Tools、签到、客户端更新、图鉴资料、公告/密函、资源操作、玩家查询与隐私等领域。
- `src/infrastructure/`：配置、HTTP、持久化、缓存、渲染、公共资源、订阅和调度等基础设施。
- `pages/dashboard/`：由 AstrBot Dashboard 承载的插件管理页面。
- `tests/`：按长期业务域维护的 pytest 测试。

## 事实源

不要在文档中复制可直接由仓库读取的完整清单：

- 命令定义：`src/entry/commands/` 与 `src/modules/index.py`。
- 命令投影：根目录 `commands.json`，由 `scripts/generate_commands_manifest.py` 生成。
- 配置定义：`src/infrastructure/config/settings.py`。
- Dashboard 配置投影：根目录 `_conf_schema.json`，由 `scripts/generate_config_schema.py` 生成。
- 插件名称、版本与最低 AstrBot 版本：`metadata.yaml`。
- 数据库结构：`src/infrastructure/persistence/` 与 `alembic/versions/`。
- 公共资源契约：`src/infrastructure/resources/` 与 `dna-resource` 仓库的当前 manifest。

## 关键边界

- 框架交互使用 AstrBot 原生 API；业务模块不应依赖 `gsuid_core` / `gsucore`。
- 运行期数据写入 AstrBot 为插件分配的数据目录，不写回 Git 仓库中的源码目录。
- 命令 handler 负责框架输入/输出适配，领域逻辑留在 `src/modules/`，网络、存储、渲染等副作用留在 `src/infrastructure/`。
- `commands.json` 与 `_conf_schema.json` 是生成物；修改对应代码后重新生成并提交差异。
- 用户可见的当前行为写在 `docs/usage/`；开发约束和维护方式写在 `docs/dev/`；版本历史写在根目录 `CHANGELOG.md`。

## 改动入口

| 改动 | 首先查看 |
| --- | --- |
| 命令、权限、帮助 | `src/entry/commands/`、`src/modules/index.py`、`tests/test_entry_commands.py` |
| 配置 | `src/infrastructure/config/`、`_conf_schema.json`、`tests/test_config.py` |
| 登录/账号 | `src/modules/account/`、`src/infrastructure/http/`、`tests/test_account.py` |
| 玩家/图鉴 | `src/modules/player/`、`src/modules/encyclopedia/`、相关 rendering 与资源代码 |
| 数据库 | `src/infrastructure/persistence/`、`alembic/versions/`、`tests/test_persistence.py` |
| 推送/调度 | `src/infrastructure/subscriptions/`、scheduler 相关模块、对应领域测试 |
| 客户端更新 | `src/modules/client_updates/registry.py`、`src/infrastructure/http/client_updates.py`、`scripts/smoke_client_update_sources.py` |
| Dashboard | `src/entry/admin_web.py`、`src/entry/web.py`、`pages/dashboard/` |
| Agent Tools | `src/entry/agent_tools/`、`src/modules/agent_tools/`、`tests/test_agent_tools.py` |

用户使用方式见 [`../usage/`](../usage/) 下的主题文档。
