# AGENTS.md

## 沟通语言
- 与用户沟通默认简体中文；代码标识符、命令、库名可保留英文。

## 项目形态
`astrbot_plugin_dnaby`：二重螺旋 Bot 插件，由 GsCore 插件 DNAUID 原生移植为 AstrBot 插件。命令全部为**正则触发**，`commands.json` 是由 `src/entry/commands` registry 生成的清单投影。**不引入 gsuid_core**；仅复用原纯逻辑（请求签名、伤害计算、PIL 渲染、攻略/wiki 素材、姓名别名）。

## 主要目录
- `main.py` — AstrBot 薄入口（Star 子类）：安装 registry handler、bootstrap、`initialize()/terminate()`。不写业务编排。
- `src/` — 迁移目标架构：`entry/`（命令/事件/响应/生命周期/web）、`modules/`（account、
  privacy、player、encyclopedia、checkin、notices、operations 各 use case 领域）、
  `infrastructure/`（config、persistence、http transports、rendering、resources、
  subscriptions、scheduler、notices_scheduler）。
- `src/infrastructure/config/` — Pydantic typed settings 与 `_conf_schema.json` 生成器。
- `src/infrastructure/resources/` — 公共 `astrbot_plugin_dna_resources` Git 仓库的路径、manifest 校验和安全同步接口。
- `dnaby/` — legacy 内部业务包（保留原 `dna_*` 布局），仅作迁移参考/复用纯逻辑（请求签名、
  伤害计算、PIL 渲染、攻略/wiki 素材、姓名别名、master char 常量、ann/mh 纯工具）。
- `commands.json` — 命令清单投影（代码 registry 是唯一事实源）。
- `_conf_schema.json` — AstrBot WebUI 配置 schema（由 `src/infrastructure/config` 生成）。
- `docs/` — README 索引 + `porting/`(superpowers 交付物) + `dev/` + `usage/` + `project/` + `legacy/`(原登录排查档案)。
- `tests/` — pytest（先写测试后实现）。

## 阅读入口
- 改动前先读 `docs/README.md` 与 `docs/porting/design.md`。
- 命令/触发 → `commands.json` + `main.py`；核心命令契约见 `tests/test_entry_commands.py`。
- 配置 → `src/infrastructure/config/` + `_conf_schema.json`；legacy 配置仅作迁移参考。
- 数据库 → `src/infrastructure/persistence/`（SQLAlchemy 2 async + Alembic；旧 `dnaby/utils/database/` 不迁移）。
- 登录链路 → `src/modules/account/` 与 `src/infrastructure/http/account.py`。
- 订阅/推送 → `src/infrastructure/subscriptions/` 与 `scheduler.py`/`notices_scheduler.py`。

## 硬约束
- **不 import gsuid_core / gsucore**。所有框架交互走 AstrBot 原生 API（`astrbot.api.*`、`StarTools`、`context`）。
- 发送回复：handler 是 async generator，`yield event.plain_result/chain_result/image_result`；`@filter.regex` 只是门，组内必须重跑 `re.match`。
- 运行期数据一律进 `StarTools.get_data_dir(self.name)`（`data/plugin_data/astrbot_plugin_dnaby/`）；禁止写 `<plugin>/data/`。
- `commands.json` 与分发表必须一致（有 pytest 断言「清单 ⊆ 分发表」）。
- 定时任务用 `asyncio` 循环，在 `initialize()` 启动、`terminate()` 取消。
- 用户可见字符串统一走 `dnaby/utils/msgs/notify.py`（legacy）或 `src/modules/*/messages.py`（rewrite）；不在 handler 里硬编码文案。
- 运行期数据目录边界：`dnaby.sqlite3`、`subscriptions.json`、`ann_state.json`、`rendered/`、`panel_custom/`、`resources/` 均位于 `StarTools.get_data_dir` 下，禁止写 `<plugin>/data/`。
- 新代码使用 `DnabySettings.from_config(...)`；legacy 代码暂保持 `DNAConfig.get_config("Key").data` 语义。
- 不提交 Cookie、token、SQLite 数据库、日志、Dashboard 密钥；资源仓库/主插件不公开、不发布。

## 文档纪律
- docs 是改动的一部分。改命令清单、配置、登录链路、数据结构时必须同步 `docs/usage|project/`。
- `AGENTS.md` + `CLAUDE.md` 互为镜像，仓库级规则变化时同改；两者各 ≤100 行，溢出进 `docs/`。

## 测试与检查命令
从插件目录运行：
```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```
从 runtime 根目录运行：
```bash
uv run ruff check data/plugins/astrbot_plugin_dnaby
```

## 更新策略
- 迁移按 superpowers 阶段推进：design.md → plan.md → TDD → subagent → review.md → final_report.md。
- 每阶段保持 pytest 绿、ruff 干净再进入下一阶段。
