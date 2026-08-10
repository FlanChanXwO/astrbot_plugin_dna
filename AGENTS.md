# AGENTS.md

## 沟通语言
- 与用户沟通默认简体中文；代码标识符、命令、库名可保留英文。

## 项目形态
`astrbot_plugin_dnaby`：二重螺旋 Bot 插件，由 GsCore 插件 DNAUID 原生移植为 AstrBot 插件。命令全部为**正则触发**，命令清单集中在 `commands.json`（源自原 `help.json`）。**不引入 gsuid_core**；仅复用原纯逻辑（请求签名、伤害计算、PIL 渲染、攻略/wiki 素材、姓名别名）。

## 主要目录
- `main.py` — AstrBot 入口（Star 子类）：`@filter.regex` 主门 + 分发、`initialize()/terminate()`、Web API 注册。不写业务编排。
- `dnaby/` — 内部业务包（保留原 `dna_*` 布局）：
  - `dnaby/dna_*/__init__.py` — 每个功能域的命令处理器（`async def handle_*(sender, ctx)`）与 `COMMANDS` 声明。
  - `dnaby/dna_config/` — 配置定义（`config_default.py`/`config_sign.py`）→ 生成 `_conf_schema.json`。
  - `dnaby/utils/` — 共享：`resource.py`(数据目录)、`image.py`、`fonts.py`、`database/`(SQLModel 5 表)、`dna_api.py`、`msgs/notify.py`、`constants/`。
- `commands.json` — 命令清单（唯一事实源）：`key/group/name/desc/eg/regex/permission/handler`。
- `_conf_schema.json` — AstrBot WebUI 配置 schema（由 `dnaby/dna_config` 生成）。
- `docs/` — README 索引 + `porting/`(superpowers 交付物) + `dev/` + `usage/` + `project/` + `legacy/`(原登录排查档案)。
- `tests/` — pytest（先写测试后实现）。

## 阅读入口
- 改动前先读 `docs/README.md` 与 `docs/porting/design.md`。
- 命令/触发 → `commands.json` + `main.py`。
- 配置 → `dnaby/dna_config/` + `_conf_schema.json`。
- 数据库 → `dnaby/utils/database/`。
- 登录链路 → `dnaby/dna_user/`（`login_router.py`/`login_service.py`/`transport.py`/`templates/`）。
- 订阅/推送 → `dnaby/utils/subscriptions.py`（原生替代 gsucore `gs_subscribe`）。

## 硬约束
- **不 import gsuid_core / gsucore**。所有框架交互走 AstrBot 原生 API（`astrbot.api.*`、`StarTools`、`context`）。
- 发送回复：handler 是 async generator，`yield event.plain_result/chain_result/image_result`；`@filter.regex` 只是门，组内必须重跑 `re.match`。
- 运行期数据一律进 `StarTools.get_data_dir(self.name)`（`data/plugin_data/astrbot_plugin_dnaby/`）；禁止写 `<plugin>/data/`。
- `commands.json` 与分发表必须一致（有 pytest 断言「清单 ⊆ 分发表」）。
- 定时任务用 `asyncio` 循环，在 `initialize()` 启动、`terminate()` 取消。
- 用户可见字符串统一走 `dnaby/utils/msgs/notify.py`；不在 handler 里硬编码文案。
- 配置读法保持 `DNAConfig.get_config("Key").data` 语义（内部包装 `AstrBotConfig`）。
- 不提交 Cookie、token、SQLite 数据库、日志、Dashboard 密钥。

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
