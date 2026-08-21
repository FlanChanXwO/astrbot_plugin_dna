# 移植最终报告

> 历史存档：本文是 legacy-reference 完整移植阶段的最终报告。当前
> 当前 main 已迁移到 61 条命令；本文的 56 项能力和
> 真实 E2E 结论当作当前重构区的验收证据；目标完成前的阶段审查见
> [review-v0.1.md](review-v0.1.md)。

## 交付结论

DNAUID 已完成原生 AstrBot 插件化移植的代码交付。插件不依赖 `gsuid_core` / `gsucore`，命令、配置、数据库、订阅、推送、登录 Web 和调度均使用 AstrBot 或本地实现。当前代码可被 AstrBot 4.27.1 运行时动态加载，并已在本机 Dashboard 通过指定插件重载。

这次交付已证明“可加载、可测试、可进入受控试运行”，并完成本机真实账号数据库、AstrBot、OneBot、NapCat 和本地登录页的受控 E2E。真实短信验证码提交、有效 token 登录和外置登录服务仍不属于本轮验收范围。

## 主要产物

- `main.py`：AstrBot Star 入口；兼容 AstrBot 命名空间动态加载和插件目录本地导入。
- `dnaby/dispatch.py`、各 `dna_*` 模块：56 条正则命令、18 个功能域和权限分发。
- `dnaby/dna_config/`、`_conf_schema.json`：AstrBot Dashboard 配置 schema；object 节点符合 `items` 契约。
- `dnaby/utils/database/`：五张 SQLModel 表、私有 aiosqlite 引擎、带类型签名的 session/lock 装饰器。
- `dnaby/dna_user/`：local、http_poll、SSE、WS、token 和短信登录链路；会话 auth 为进程内 HMAC 标识。
- `dnaby/scheduler.py`、`dnaby/utils/subscriptions.py`：定时任务生命周期与原生订阅推送。
- `docs/porting/progress.md`、`review.md`：进度、审查结论和后续风险。

## 验证证据

执行环境：runtime `.venv`，Python 3.12.13，AstrBot 4.27.1 运行时可用。

| 命令/动作 | 结果 |
|---|---|
| `.venv/bin/python -m pytest -q` | `55 passed`；仅 `audioop` 弃用警告 |
| `ruff check .` | 通过 |
| `uv run --offline ruff check data/plugins/astrbot_plugin_dnaby` | 通过 |
| `pyright` | 0 errors / 0 warnings；当前配置检查 `dnaby` 与 `tests` |
| `.venv/bin/python -m compileall -q .` | 通过 |
| `.venv/bin/python -c 'import main'` | 通过 |
| runtime 根动态导入 `data.plugins.astrbot_plugin_dnaby.main` | 通过 |
| manifest/dispatch 回归 | 56/56 命令覆盖，示例 regex、权限和 handler 一致性通过 |
| `ASTRBOT_SKIP_PLUGIN_REQUIREMENTS_SYNC=1 ./scripts/astrbot/reload-plugins.sh 6196 astrbot_plugin_dnaby` | 返回 `{"status":"ok","message":"重载成功。"}` |
| 本机 OneBot/NapCat E2E | `commands.json` 56 条命令均已注入验证；登录链接立即出站并打开为 `HTTP 200` 表单，旧 auth 返回 `HTTP 404` |

重载验证显式跳过了依赖同步，因此本轮没有安装或删除项目依赖；它只请求本机 Dashboard 重载目标插件。重载成功同时覆盖入口导入、schema 解析、插件实例化和 `initialize()`。

## 修复摘要

- 入口兼容 AstrBot `data.plugins.<plugin>.main` 命名空间，修复运行时 `No module named 'dnaby'`。
- 为自由 object 配置补 `items`，修复运行时 `KeyError: 'items'`。
- 为 `with_session` / `with_lock` 使用 `ParamSpec`，修复数据库公开 API 的静态签名泄露。
- 使用 `asyncio.timeout`，统一上海时区，异步化别名文件 IO，修正懒加载 git 日志与动态密函命令顺序。
- 登录 auth 改为进程内 HMAC；API 日志移除完整凭据和响应 data；轮询网络失败保持真实错误；终止时等待后台任务取消。
- 纯文本通知统一经过 `send_dna_text()`；订阅增删改的读改写与落盘纳入同一实例锁，并补充并发回归测试。
- 登录链接改为立即通过 `Context.send_message()` 出站，再等待页面提交；本地登录服务按配置监听
  `DNALoginBindHost:DNALoginPort`，无效 auth 返回真实 `404`。
- 上传面板图适配 AstrBot `Image` 组件的本地路径转换，并通过真实 OneBot 图片段验证上传/列表/删除。
- 修复 Pillow、消息段、SQLModel 元类参数和 SQL 表达式的源码级 Pyright 诊断，将检查范围扩展到全部 `dnaby` 源码。
- 新增数据库、别名 IO、时间边界、迁移边界、命令、调度、订阅和动态加载回归测试。

## 已知限制与后续

- 尚未使用真实手机号/验证码完成登录提交、有效 token 登录或外置 dna-login 服务验收；不要把这些未覆盖项解释为第三方登录可用性证明。
- 指定隐私命令的真实 `@` 目标路径受本机 OneBot 缺失群成员信息响应阻塞；无 `@`、临时未绑定目标和其余隐私命令路径已有 E2E 证据。
- 订阅锁是 `SubscriptionStore` 实例级锁；当前运行时为全局单例。若部署形态改为多进程或多个实例共享同一 JSON 文件，需要另行设计文件级锁或单写者方案，详见 `review.md` P2。
- 工作树未纳入 Git，本次未初始化仓库、未创建提交；运行时生成的 `data/plugin_data/astrbot_plugin_dnaby/dnaby.db` 不属于交付源码。
