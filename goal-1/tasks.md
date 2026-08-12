# Goal 1 任务清单

状态约定：`[ ]` 未完成，`[x]` 已完成，`[B]` 阻塞。每个 task 只在本轮执行一个；完成后填写证据和剩余风险。

## 阶段 1：基线与隔离

### Task 1：检查参考区环境、规则与现状

- 状态：[x]
- 范围：读取项目规则、文档入口、目录结构和关键入口；检查 Python、Git、pre-commit、`pyright-langserver`、AstrBot 4.27.x、ruff、pytest/LSP 可用性；记录现有测试、lint、compile 基线。
- 实际完成：读取 `AGENTS.md`、`CLAUDE.md`、`docs/README.md`、`docs/porting/design.md` 以及 `docs/dev/{setup,testing,maintenance}.md`；检查 `main.py`、`commands.json`、`_conf_schema.json`、`.pre-commit-config.yaml`、`tests/` 和 `dnaby/`。当前参考区尚未初始化 Git；目录含 101 个业务 Python 文件、12 个测试 Python 文件和 18 个 `COMMANDS` 声明。`commands.json` 有 56 条记录，字段完整，`key`/`regex` 无重复，权限为 `user/admin/owner`；未检出 `gsuid_core` 或 `gsucore` 的 Python/JSON import。
- 验证证据：环境探测结果：全局 Python `3.14.4`、Git `2.50.1`、pre-commit `4.6.0`、ruff `0.15.12`、pytest `9.0.3`、Pyright/Pyright language server `1.1.411`；runtime `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv` 为 Python `3.12.13`、AstrBot `4.27.1`、ruff `0.16.1`。以 runtime venv 执行 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m compileall -q .`，退出码 0；执行 `.../.venv/bin/python -m pytest -q`，`55 passed, 1 warning`；执行 `.../.venv/bin/ruff check .`，退出码 1，报告 5 个既有测试文件的 `I001` import 排序问题。全局 `python3 -m pytest` 收集阶段有 6 个错误，分别由缺少 AstrBot 和 Python 3.14 下 `aiohttp` 导入 `cgi` 造成；全局 `ruff check .` 通过；全局 `pyright` 为 `0 errors, 0 warnings, 0 informations`。`pyright-langserver --stdio` 可执行并输出启动日志，本轮未保留服务进程。
- 剩余风险/下一步：后续命令必须显式使用 runtime venv，不能把全局 Python 3.14 的收集失败当成业务回归。Pyright venv 可执行文件不存在，后续继续使用已探测的全局 Pyright/LSP 并明确解释解释器配置；Task 2 需先初始化 Git，因此当前尚未执行 `pre-commit run --all-files`。

### Task 2：建立参考区 `legacy-reference` Git 基线

- 状态：[x]
- 范围：仅在参考区完成必要的 Git 初始化/状态确认，加入 `.worktrees/` 忽略规则，提交完整且可识别的 `legacy-reference` 基线；不覆盖用户已有改动。
- 实际完成：保留原有运行期/缓存忽略规则，补充 `.worktrees/` 和 `pyrightconfig.json.agent-lsp-backup` 忽略项；在参考区执行 `git init -b legacy-reference`，将当前源码、资源、文档、测试和 `goal-1/` 记录纳入独立本地仓库。未删除或覆盖任何已有文件；`data/`、`tests/.data/` 等运行期数据继续留在磁盘但不进入版本库。
- 验证证据：根提交 `4201be6`（`legacy-reference: capture plugin baseline`），提交统计为 485 个文件；commit hook 中的 `ruff check` 通过。提交后 `git status --short --branch` 仅显示干净的 `## legacy-reference`；`git ls-files` 未发现 `data/`、`plugin_data`、`tests/.data`、数据库/日志、Cookie/token/secret、`.DS_Store` 或 LSP backup 路径；`git worktree list` 当前仅列参考区。
- 剩余风险/下一步：参考区已冻结在 `legacy-reference`，下一轮 Task 3 从该提交创建 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_dnaby/.worktrees/rewrite-v0.1`，并验证基线与隔离状态。

### Task 3：创建 `rewrite/v0.1` 独立 worktree 并冻结参考区

- 状态：[x]
- 范围：创建指定重构 worktree，确认分支、路径、状态和基线一致；后续所有编辑/测试/runtime 命令显式以重构区为工作目录。
- 实际完成：从参考区 `legacy-reference` 创建 `.worktrees/rewrite-v0.1`，分支名为 `rewrite/v0.1`；后续代码、测试、运行时和文档编辑均以该绝对路径为工作目录，参考区只做读取、`git show`、差异和 worktree 管理。
- 验证证据：参考区与重构区均为 485 个 tracked 文件；两边 HEAD 均为 `664b6775ca7ca88f4c83876880338d57e2b986b6`；在重构区执行 `git diff --quiet legacy-reference...rewrite/v0.1` 通过；重构区 `git status --short --branch` 为干净的 `## rewrite/v0.1`；`git worktree list --porcelain` 同时列出两个指定路径；goal 三份文件在重构区存在。
- 剩余风险/下一步：重构区尚未进入业务实现；下一轮只执行 Task 4，对 Task 1-3 的隔离、门禁和未决风险做集中检查-debug。

### Task 4：集中检查-debug（阶段 1）

- 状态：[x]
- 范围：复核 Task 1-3 的需求偏离、Git 隔离、参考区污染、环境证据、回滚点和未决阻塞；发现问题则追加修复 task。
- 实际完成：复核目标范围、参考区冻结、worktree 路径/分支、忽略规则、提交回滚点和敏感数据边界；未发现业务文件越界、参考区污染、`gsuid_core`/`gsucore` import 或未授权外部发布动作。直接从嵌套 worktree 执行 pytest 时发现 2 个旧动态命名空间测试的 runtime root 层级假设；按 objective 建立临时 staging runtime root，并将 `data/plugins/astrbot_plugin_dnaby` symlink 到重构区后验证通过，因此不追加代码修复 task。
- 验证证据：参考区与重构区均 clean；`legacy-reference...rewrite/v0.1` 相对差异仅为 `goal-1/tasks.md`；两分支 tracked 路径均无 `data/`、`tests/.data`、数据库/日志、Cookie/token/secret、`.DS_Store` 或 LSP backup，且无禁用框架 import。重构区 runtime `compileall` 退出码 0；staging runtime + `PYTHONPATH` 执行 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest -q` 为 `55 passed, 1 warning`；`pyright` 为 `0 errors, 0 warnings, 0 informations`；`pre-commit run --all-files` 通过。系统 `ruff check .` 由 pre-commit 通过；runtime venv 的 ruff `0.16.1` 仍报告基线已有的 5 个 `I001`，属于工具版本差异，未改动测试格式。
- 剩余风险/下一步：后续测试命令必须以重构区为工作目录，并按 staging runtime + symlink 验证动态命名空间；继续记录系统 ruff 与 runtime venv ruff 的版本差异。阶段 1 无已知高风险问题，下一轮进入 Task 5（`v0.1.0` 骨架）。

## 阶段 2：`v0.1.0` 骨架

### Task 5：落地 `src` 分层骨架与入口生命周期

- 状态：[x]
- 范围：建立目标目录、`DnabyPlugin`、bootstrap、生命周期、web 注册边界和可测试的 AstrBot 入口；`main.py` 不承载业务编排；先覆盖加载/卸载和空能力路径。
- 实际完成：用 TDD 建立 `src/`、`src/bootstrap.py`、`src/entry/{lifecycle,web,event,response}.py`；将 `main.py` 收敛为 `DnabyPlugin(Star)`、runtime 组装和生命周期转发，移除旧的全局 regex/dispatch、DB、订阅、登录 Web server 和定时任务编排。`PluginLifecycle` 提供启动顺序、停止逆序和幂等；`WebRegistrar` 将 `WebRoute` 转换为 AstrBot `Context.register_web_api`；v0.1 显式使用空事件入口，不隐式注册旧命令。同步更新 `pyrightconfig.json`、架构文档、README 重构说明和 progress 历史状态提示；新增入口骨架契约测试，并将动态包测试改为验证空 runtime。
- 验证证据：RED 阶段旧入口初始化因依赖 `context.get_config()` 失败；GREEN 后 `tests/test_entry_skeleton.py` 的 3 条测试通过。按 Task 4 的 staging runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink 指向 worktree，`PYTHONPATH` 注入 staging root）执行 targeted 测试为 `13 passed, 1 warning`，全量为 `58 passed, 1 warning`；runtime `python3 -m compileall .` 通过；`pyright --project pyrightconfig.json` 为 `0 errors, 0 warnings, 0 informations`；系统 `ruff check .`、`pre-commit run --all-files` 和两个提交 hook 均通过。提交：`a747873 task-5: introduce thin runtime entry skeleton`、`3b37076 docs: describe rewrite v0.1 entry skeleton`。
- 剩余风险/下一步：新入口当前没有命令 registry、业务 Web 路由、配置/数据库/资源初始化，这是 v0.1 分阶段边界，分别由 Task 6–7 和后续阶段加入；runtime venv `ruff 0.16.1` 仍复现基线 5 个 `I001`，canonical system ruff/pre-commit 通过。下一轮只执行 Task 6，建立显式 `CommandSpec` registry、帮助和命令生成链路。

### Task 6：建立显式 `CommandSpec` registry、帮助和命令生成链路

- 状态：[x]
- 范围：定义命令规格与模块索引，生成真正的 async-generator 类方法并应用 AstrBot 4.27.x 公共装饰器；帮助只展示已实现命令，验证权限、重复加载、正则命名参数和无全局 dispatch/registry 修改。
- 实际完成：在 `src/entry/commands/` 建立冻结的 `CommandSpec`、typed `CommandRequest`、只读 `CommandRegistry`、重复模块/id/pattern/权限/示例校验和 manifest 投影；在 `src/modules/index.py` 建立唯一显式命令模块索引，当前只登记 `src/modules/help.py` 的 `帮助` use case。`main.py` 从 registry 为每个 spec 生成真实 async-generator `handle_<id>` class method，先设置运行时 module path，再应用 AstrBot 4.27.1 公开的 `filter.regex` 与 `filter.permission_type` decorator；handler 自己重跑 pattern、提取 named groups 并交给 `CommandRequest`，没有引入 `MASTER_PATTERN`、全局循环 dispatch、legacy `Sender/EventContext/MessageSegment` 或内部 registry API。`src/entry/response.py` 新增 text/chain/image DTO 到 AstrBot 原生结果的转换；帮助直接读取 runtime registry。新增 `scripts/generate_commands_manifest.py`，并生成新 schema 的 `commands.json`；尚未迁移的 55 条历史命令不注册、不展示。同步更新命令、架构、测试和移植设计文档；另以 runtime Ruff 机械整理 5 个既有测试 import-order 基线项。
- 验证证据：TDD targeted `tests/test_command_registry.py tests/test_commands.py tests/test_entry_skeleton.py` 为 `18 passed, 1 warning`；按目标 staging runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink 指向 worktree，`PYTHONPATH` 注入 staging root）执行全量 `.../.venv/bin/python -m pytest -q` 为 `66 passed, 1 warning`。`python3 -m compileall .` 通过；系统 Ruff 通过，runtime Ruff `0.16.1` 通过，`pyright --project pyrightconfig.json` 为 `0 errors, 0 warnings, 0 informations`，`pre-commit run --all-files` 通过。运行 manifest generator 后 `commands.json` 与 `manifest_records(COMMAND_REGISTRY)` 测试一致；包命名空间检查确认 `data.plugins.astrbot_plugin_dnaby.main.DnabyPlugin.handle_help` 是 async-generator，handler module path 正确且 filters 为 `RegexFilter` + `PermissionTypeFilter`。实现提交为 `76399db`。
- 剩余风险/下一步：当前帮助响应是纯文本 DTO，尚未复刻 legacy PIL 帮助卡片；这是 rewrite/v0.1 的明确可见差异。`owner` 当前映射到 AstrBot 公共 `ADMIN` 边界，bot-owner 细分语义待对应 use case 迁移时实现；只有 `帮助` 已实现，Task 7 进入 typed 配置、schema、私有资源入口和版本元数据。

### Task 7：实现 typed 配置、schema 生成、资源入口和版本元数据

- 状态：[x]
- 范围：按领域建立 Pydantic settings 与 `_conf_schema.json` 生成，落地私有资源下载接口、manifest 校验、`logo.png`、`CHANGELOG.md`；明确资源 Git 同步的失败可见性和不覆盖策略。
- 实际完成：在 `src/infrastructure/config/` 建立 `DnabySettings` 及 login/network/sign_in/notifications/display 五个 Pydantic 分组；`schema.py` 和 `scripts/generate_config_schema.py` 从同一份 model fields 生成 AstrBot 4.27.x 可递归解析的 `_conf_schema.json`，共享密钥使用 `SecretStr` 且 schema 默认值为空；bootstrap 在入口边界把 AstrBot 配置转换为 typed settings。`src/infrastructure/resources/` 增加 `ResourceManifest` 路径/版本校验、运行期 `StarTools.get_data_dir()` 资源路径、`ResourceSynchronizer` 和 `download_all_resources()`：首次 `git clone --depth 1`，后续只在干净 worktree 上 `git pull --ff-only`，检查 origin/worktree/manifest，Git/远端/认证/非快进/manifest/本地修改错误均显露且不强制覆盖。新增 v0.1.0 metadata、复用 `ICON.png` 生成 256x256 `logo.png`、`CHANGELOG.md`，并同步 README、AGENTS、usage/project/porting 文档。未创建或推送外部私有资源仓库。
- 验证证据：TDD 新增 `tests/test_config_resources.py`，定向 `7 passed`；临时 staging runtime（`data/plugins/astrbot_plugin_dnaby` symlink 指向 worktree）全量 `73 passed, 1 warning`，警告为 AstrBot 依赖的 `audioop` 弃用提示。系统 Ruff、runtime venv Ruff 0.16.1、Pyright（0 errors/0 warnings/0 informations）、`python3 -m compileall -q .`、`pre-commit run --all-files` 和 `git diff --check` 均通过；生成脚本后的 `_conf_schema.json` 与 `generate_astrbot_schema()` 一致；`git worktree list` 显示参考区仍为 `legacy-reference` 且未执行外部网络发布。提交：`65d23ed`。
- 剩余风险/下一步：资源仓库尚未建立，实际 clone/pull/认证只能在部署者提供私有 origin 和凭据 helper 后验证；当前只用注入式 Git fixture 验证，不泄露凭据。`download_all_resources()` 是同步基础设施接口，后续异步命令调用时需放入合适的线程/生命周期边界；旧配置与 SQLite 不自动迁移，属于 v0.1 破坏性边界。下一轮执行 Task 8 阶段 2 集中检查-debug。

### Task 8：集中检查-debug（阶段 2）

- 状态：[x]
- 范围：复核 Task 5-7 的入口契约、命令清单、配置 schema、资源边界、AstrBot 加载和完整门禁；补修复 task 并保留可回滚提交。
- 实际完成：按入口 AST、动态命名空间、公开 decorator、registry/manifest、typed settings、AstrBotConfig、metadata/logo/changelog、资源 Git 参数边界和敏感信息扫描逐项复核。确认 `main.py` 只保留 Star、bootstrap 和动态命令安装，新入口无 `gsuid_core`/`gsucore`、`MASTER_PATTERN`、legacy `Sender/EventContext/MessageSegment` 或全局 dispatch；确认未实现命令仍不注册。发现并修复 Git 错误脱敏仅覆盖 URL userinfo 的缺口，现同时覆盖常见 query token 和 Bearer 值；补充对应回归测试。发现 legacy `review.md`/`final_report.md` 会被误读为 rewrite 当前结论，增加历史存档说明并新增 `docs/porting/review-v0.1.md` 阶段审查报告。未发现需要追加 repair task 的 P0/P1 问题。
- 验证证据：staging runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink 指向 worktree）全量 `73 passed, 1 warning`；系统 Ruff、runtime Ruff 0.16.1、Pyright（0 errors/0 warnings/0 informations）、`python3 -m compileall -q .`、`pre-commit run --all-files`、`git diff --check` 均通过。动态包手工断言 `data.plugins.astrbot_plugin_dnaby.main.DnabyPlugin.handle_help` 为 async-generator，`__module__` 正确且 filters 为 `RegexFilter` + `PermissionTypeFilter`；schema/metadata/logo 一致性通过；tracked 敏感路径/凭据模式扫描 clean。参考区 `legacy-reference` 与重构区最终均 clean，未执行外部仓库创建、推送或发布。提交：`3756188`。
- 剩余风险/下一步：私有 `dnaby_resources` 尚未建立，实际认证、远端和完整资源内容仍待部署者提供私有仓库与 credential helper；当前只做注入式 Git fixture。当前仅有 `帮助`，legacy 目录仍是后续迁移参考；旧配置/SQLite 不迁移。Alembic/SQLAlchemy async 由后续 Task 9 开始，不能将本阶段审查视为数据层完成。下一轮进入 Task 9。

## 阶段 3：`v0.2.0` 账号与隐私

### Task 9：建立 SQLAlchemy async 持久化和 Alembic 初始结构

- 状态：[x]
- 范围：使用 `sqlite+aiosqlite`、SQLAlchemy 2 async、repository/事务边界和 Alembic 初始 revision；凭据字段私有化并确保日志/异常/DTO 脱敏；不迁移旧数据库。
- 实际完成：在 `src/infrastructure/persistence/` 建立 SQLAlchemy 2 `DeclarativeBase`、五张 normalized 表（`account_bindings`、`credential_records`、`sign_records`、`privacy_settings`、`group_privacy_settings`）及同名 metadata indexes。`AsyncDatabase` 使用 `sqlite+aiosqlite`、`async_sessionmaker(expire_on_commit=False)`，提供显式 `session()` 和统一提交/回滚的 `transaction()`；`from_data_dir()` 固定新文件名 `dnaby.sqlite3`，不触碰 legacy `dnaby.db`。五类 repository 均显式接收 `AsyncSession`，不创建全局 session 或隐式提交。`CredentialRecord` 将 App/Web Cookie、token、refresh token、设备标识和 d_num 保留在私有 ORM 字段中，`repr`/`redacted_snapshot()` 仅返回标识、状态和凭据存在性。新增 `alembic.ini`、async `alembic/env.py`、模板和 `0001_initial` 初始 revision，并声明 `alembic>=1.13.0`；同步更新数据模型、架构、测试说明、阶段审查和 CHANGELOG。
- 验证证据：实现提交 `1130cd0`；Task 9 定向测试 `6 passed, 1 skipped`；staging runtime 全量 pytest `79 passed, 1 skipped, 1 warning`，唯一 warning 为 AstrBot 依赖的 `audioop` 弃用提示。系统 Ruff、runtime venv Ruff `0.16.1`、Pyright（`0 errors, 0 warnings, 0 informations`）、`python3 -m compileall -q .`、`pre-commit run --all-files`、`git diff --check` 均通过；新 persistence 包 AST 检查无 `sqlmodel` import，旧 `dnaby.db` fixture 内容保持不变。
- 剩余风险/下一步：当前 runtime 与全局 Python 均未安装 Alembic，真实 `command.upgrade/downgrade` 测试按设计显式 skip；依赖已声明但未擅自安装，部署环境需安装后补跑真实 migration 往返。初始 revision 不迁移旧数据库，SQLite 中可空 `group_id` 的唯一性语义和业务 upsert/删除策略留给后续账号/隐私 use case；下一轮执行 Task 10。

### Task 10：实现账号登录、退出、UID 绑定/切换/删除与凭据查询

- 状态：[x]
- 范围：在隔离 transport/SQLite/事件 fixture 下迁移账号用例，使用 typed request/框架无关 DTO；覆盖成功、取消、网络/状态码/服务端错误和敏感信息脱敏。
- 实际完成：提交 `8e32029`。新增 `src/modules/account/` 的 typed actor、token/SMS request、
  role/credential/result contract、可注入 transport 错误分类、事务化 `AccountService` 和
  集中文案；补齐 AccountBinding/Credential repository 的 list/current/set_active/save/delete
  CRUD。bootstrap 为每个 runtime 注入独立 database/account service，handler 从 AstrBot
  公开事件方法提取 actor。新增登录页启动、token/SMS 登录、退出、绑定/切换/删除/删除全部、
  绑定列表和凭据状态命令，使用独立 regex/use case 生成 `commands.json`；新增 legacy 纯 API
  adapter，但未复用旧事件/数据库/消息段。同步 README、命令/登录/配置/数据模型/架构/测试
  文档及 `docs/porting/review-v0.2-account.md`。
- 验证证据：`tests/test_account.py` 9 条、`tests/test_account_commands.py` 4 条；账号与命令
  定向集合共 28 条通过。staging runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink
  指向 rewrite worktree）全量 pytest `92 passed, 1 skipped, 1 warning`；warning 为 AstrBot
  依赖的 `audioop` 弃用提示。system/runtime Ruff、Pyright（0 errors/0 warnings/0 informations）、
  `python3 -m compileall -q .`、`pre-commit run --all-files`、`git diff --check` 和 manifest
  生成一致性测试均通过。Alembic 仍未安装，Task 9 的真实 migration round-trip skip 保持不变。
- 剩余风险/下一步：当前 rewrite runtime 尚未注册本地登录 Web route；默认 transport 无 page
  provider 时显式返回服务未配置错误，实际 page provider/外部登录服务需后续明确接入。Task 11
  尚未实现个人/群组隐私遮罩和权限策略，因此绑定列表仅是当前离线账号行为，不代表隐私已交付。

### Task 11：实现个人/群组隐私能力和权限边界

- 状态：[x]
- 范围：迁移隐私查询与修改、群组/个人作用域和权限判断；写入行为只在隔离测试执行，用户可见文案统一由 notify 层提供。
- 实际完成：提交 `ffccb6d`。新增 `src/modules/privacy/` 的 typed `PrivacyService`、策略快照、
  查询解析和集中式用户文案；补齐个人偷窥/UID 开关、群组全体强制/取消、指定目标设置共
  14 条 `CommandSpec`，管理员命令声明为 `admin` 并映射 AstrBot `PermissionType.ADMIN`。
  指定操作要求群聊、有效公开 `At` 目标和目标已有 UID 绑定；个人操作遇到对应群强制字段
  时显式拒绝且不写入。持久化 repository 增加存在性查询、个人按作用域 upsert 和群强制字段
  清除语义；`CommandRequest` 增加可选 target user，旧 positional 字段顺序保持不变。
  同步生成 `commands.json`，更新 README、usage/project/dev 文档和
  `docs/porting/review-v0.2-privacy.md`。
- 验证证据：TDD 聚焦集合 `tests/test_privacy.py tests/test_privacy_commands.py
  tests/test_command_registry.py tests/test_commands.py tests/test_persistence.py` 为 `25 passed,
  1 warning`；账号/隐私/命令/持久化联合集合为 `43 passed, 1 skipped, 1 warning`。按目标 staging
  runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink 指向 rewrite worktree）执行全量
  `.venv/bin/python -m pytest -q` 为 `102 passed, 1 skipped, 1 warning`，唯一 warning 为
  AstrBot 依赖的 `audioop` 弃用提示。系统 Ruff、Pyright（`0 errors, 0 warnings, 0 informations`）、
  `python3 -m compileall -q .`、`pre-commit run --all-files`、`git diff --check` 和 manifest
  一致性均通过；参考区 `legacy-reference` 保持 clean。
- 剩余风险/下一步：UID 隐藏策略已提供查询接口，但角色卡片/详情等后续渲染 use case 尚未
  接入，不能据此宣称所有历史输出都已自动脱敏；真实 AstrBot/OneBot 群管理员与多平台
  `@` 行为未执行，只验证本地 SDK 和事件 fixture。下一轮只执行 Task 12，集中复核账号/隐私
  鉴权、事务、敏感信息和文档门禁；Task 9 的 Alembic 未安装 skip 仍保持原记录。

### Task 12：集中检查-debug（阶段 3）

- 状态：[x]
- 范围：复核账号/隐私行为、鉴权、事务、凭据泄露、异常显露、测试覆盖和文档；修正已知问题并更新任务记录。
- 实际完成：提交 `cc88186`。复核冻结 `legacy-reference` 的账号登录/退出/绑定/隐私行为和
  AstrBot 入口权限；按 TDD 修复 5 个问题：恢复 legacy 登录参数清理、重复登录默认角色的
  current UID 与成功文案优先级、绑定/切换/删除空参数路由、transport 响应结构异常归类，
  以及 SQLite 隐私全局 upsert 竞态。后者增加 `AsyncDatabase` runtime 内写锁、
  `privacy_settings` 的 SQLite 部分唯一索引和增量 Alembic `0002_privacy_global_identity`，
  不改写已发布的 `0001_initial`，也不自动删除历史重复数据。新增账号事务回滚、默认角色、
  空参数、transport 脱敏、并发隐私和数据库唯一性测试；同步 `commands.json`、CHANGELOG、
  数据模型/配置/测试文档和 `docs/porting/review-v0.2-debug.md`。
- 验证证据：先以失败测试复现默认角色未切换、token 内嵌空格未清理、空参数 handler 不触发、
  transport `TypeError` 原文外泄边界和 16 个并发隐私写入产生 13 条以上重复全局记录；修复后
  同组新测试通过。目标 staging runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink
  指向 rewrite worktree）全量 pytest 为 `109 passed, 1 skipped, 1 warning`；warning 仅为
  AstrBot 依赖的 `audioop` 弃用提示。`ruff check .`、`pyright --project pyrightconfig.json`
  （0/0/0）、runtime `python -m compileall -q .`、`pre-commit run --all-files`、
  `git diff --check` 和 23 条命令 manifest 一致性均通过。参考区 `legacy-reference` clean，
  worktree 列表和分支隔离保持不变。
- 剩余风险/下一步：Alembic 已在 `requirements.txt` 声明但当前本地 runtime 未安装，真实
  migration round-trip 继续按既有测试契约 skip；bootstrap 不自动执行测试建表逻辑，首次
  部署前必须按 `docs/usage/configuration.md` 执行 `alembic upgrade head`，否则账号/隐私命令
  会遇到缺表异常。若已有新 schema 中存在重复全局隐私行，`0002` 会显式失败且不自动清理。
  UID 隐藏的后续角色卡片/详情消费者、真实多平台 `@` 和 page provider 留待后续任务；下一轮
  进入 Task 13，保持参考区只读。

## 阶段 4：`v0.3.0` 查询与百科

### Task 13：实现玩家角色查询、详情/伤害和原图能力

- 状态：[x]
- 范围：迁移角色概览、详情、伤害计算、原图等读取型 use case 与渲染；保留完整合法输出，图像验证记录尺寸、消息类型、布局、文本和资源语义。
- 实际完成：提交 `6f2ad31`。新增 `src/modules/player/` typed contracts、玩家 service、3 条显式 `CommandSpec` 和集中式文案；新增 legacy API/model/伤害纯逻辑的 `DnaApiPlayerTransport`，transport 按隐私解析出的 `credential_user_id` 读取目标账号凭据，业务层不接触旧事件/数据库/消息段。新增 `PlayerRenderer`、`ResourceMap` 和 `OriginalImageCache`：概览宽度为 1200、详情宽度为 1000，动态高度遍历完整角色/武器/属性/技能/溯源/魔之楔/伤害字段；图片返回运行期 PNG 路径并写入非敏感 `dnaby.text`、`dnaby.layout`、`dnaby.resources` 元数据。原图仅接受显式登记的引用消息 ID；同律武器读取失败不再静默省略，而是返回可见服务错误。同步生成 `commands.json`，更新命令、架构、测试、进度、CHANGELOG 和 `docs/porting/review-v0.3-player.md` 行为矩阵。
- 验证证据：先以 fixture 复现 transport 缺少凭据所有者、legacy user 身份错位和同律武器错误静默降级，再修复并通过对应回归。玩家/transport 聚焦测试最终为 `10 passed, 1 warning`；含玩家命令、registry 和 transport 的聚焦集合为 `19 passed, 1 warning`。目标 staging runtime 全量 pytest 为 `123 passed, 1 skipped, 1 warning`，唯一 warning 为 AstrBot 依赖的 `audioop` 弃用提示。`ruff check .`、`pyright --project pyrightconfig.json`（0 errors/0 warnings/0 informations）、runtime `python -m compileall -q .`、`pre-commit run --all-files`、`git diff --check` 均通过；manifest 生成后 26 条命令一致，源码/测试无 `gsuid_core` 或 `gsucore` import，未跟踪文件审计未发现数据库、日志或敏感凭据。
- 剩余风险/下一步：未执行真实 gscore 只读行为矩阵，留待 Task 15；未执行真实 NapCat。默认 `ResourceMap` 只使用注入资源，缺失资源显式绘制 placeholder，私有资源 provider 留待资源阶段。平台发送详情图后仍需由发送回调调用 `PlayerService.remember_original_image(message_ids)` 才能建立原图引用缓存；未登记引用会显式提示。通用角色/武器别名读取属于 Task 14，Task 9 的 Alembic 未安装 skip 仍保持原记录；下一轮只执行 Task 14。

### Task 14：实现便签、周报、日历、wiki、攻略、兑换码和别名读取

- 状态：[x]
- 范围：迁移读取型百科/资料能力、资源语义和别名列表；建立 API fixture、素材 fixture、命令归属和响应 DTO 测试。
- 实际完成：新增 `src/modules/encyclopedia/` typed use case、9 条显式命令和集中用户文案；新增
  legacy API transport，迁移便签、周报、活动日历与兑换码读取，并将角色/武器/魔灵图鉴、攻略和只读别名
  收敛为运行期资源索引。新增动态 PNG renderer，完整遍历合法便签、周报和日历资料项；日历轮换公式在新
  transport 内以纯逻辑实现，不导入旧 renderer。攻略消息链按作者组插入一次作者文案后保留该作者全部图片。
  兑换码 DTO/响应链保留每个有效码的独立截止时间，未注册写入型别名命令。同步生成 `commands.json`，更新 README、usage、architecture、progress、CHANGELOG 和
  `docs/porting/review-v0.3-encyclopedia.md` 行为矩阵。
- 验证证据：按 TDD 先复现了“逐码截止时间丢失”和“同作者多图重复作者文案”两个失败路径，修复后新增
  对应 public response 契约，并验证日历 transport 不导入 legacy renderer。资料/命令/registry 聚焦集合在 staging runtime 为 `29 passed, 1 warning`；
  staging runtime 全量为 `137 passed, 1 skipped, 1 warning`（skip 是未安装 Alembic 的既有真实 migration
  round-trip 边界，warning 是 AstrBot 依赖 `audioop` 弃用）。`ruff check .`、runtime
  `python -m compileall -q .`、`pyright --project pyrightconfig.json`（0/0/0）、`git diff --check` 和
  `pre-commit run --all-files` 均通过；LSP 已重索引百科 service/测试，未返回诊断。
- 剩余风险/下一步：未执行真实 gscore 只读矩阵、真实私有资源仓库认证或 NapCat；图像只按尺寸、消息类型、
  完整文本、布局和资源 metadata 用 fixture 验证。下一轮只执行 Task 15，通过 `ssh atri` 做只读探测并建立
  `tests/e2e/command-matrix.md`，不得执行登录、签到、绑定、订阅或其他写入型命令。

### Task 15：建立 gscore 只读探测与命令行为差异矩阵

- 状态：[x]
- 范围：通过 `ssh atri` 只读探测 gscore 入口/存储格式；在凭据不落盘的前提下选择完整账户，逐项记录 DNAUID 与迁移后读取输出及图像临时对比资料；不得执行写入型命令。
- 实际完成：只读确认 gscore 的容器化 GsCore 入口、SQLite 数据格式和 DNAUID App 读取候选条件；以进程内 `candidate-A` 对照原插件与 rewrite 的角色概览、角色详情、便签、本周周报和上周周报。凭据只经受保护 stdin 从远端读取进程传给本地 staging 进程，未写入 worktree、临时 SQLite、日志或 Git。新增 `tests/e2e/command-matrix.md`，分别记录实测结构、临时图片资料、资源/平台未测项和未接受差异；旧 handler 的结构图禁用了下载与发送副作用，只使用真实读取 payload。
- 验证证据：原插件的角色概览、便签、两种周报和角色详情均返回 `200` 并通过 legacy Pydantic 模型；rewrite 的 `RoleOverview` / `RoleDetail` / `PlayerShortNote` / `WeeklyReport` 与同一选择条件的账号响应在已记录计数上相同。生成 worktree 外的本地 rewrite PNG 与 gscore 容器内 legacy 结构 PNG，矩阵记录了画布、布局、placeholder 和动态 UID mask。每个短进程结束前关闭 HTTP session 与签名 WebSocket；未执行真实 NapCat、登录、签到、绑定、订阅、隐私或资源写入。
- 剩余风险/下一步：图像尺寸、布局和资源 placeholder 的可见差异尚未人工接受；角色详情仍缺少真实伤害/武器/原图引用全链路，日历、图鉴、攻略、兑换码和别名仍是 fixture/资源语义证据。下一轮仅执行 Task 16，复核矩阵、动态字段 mask、资源来源、网络错误和未审查差异。

### Task 16：集中检查-debug（阶段 4）

- 状态：[x]
- 范围：复核查询/百科完整性、命令矩阵、动态字段 mask、图像差异结论、资源来源、网络错误和文档；未审查差异不得标为通过。
- 实际完成：审查 `cc88186..d42240f` 的玩家/百科实现、Task 15 的只读矩阵、运行期资源约定、AstrBot 4.27.1 公共发送边界和相关文档。查询命令的 id、正则和权限与 `legacy-reference` 对应记录一致；矩阵中结构实测、差异待审查和 fixture/待实测状态仍保持区分，未把图片尺寸/布局/placeholder、时间敏感资料或未接入私有资源标记为通过。发现原图、资源接线、伤害失败文案和生成 PNG 生命周期四项风险，已追加 Task 16.1、16.2；本轮不直接修改业务实现。
- 验证证据：Pyright LSP 对玩家 service/transport、百科 service/resources 和命令入口返回空诊断；`remember_original_image` 的语义引用只有定义与单元测试，生产 handler/response 路径没有发送后登记点。AstrBot 4.27.1 的公开 `MessageEventResult` 与 `AstrMessageEvent.send()` 均不提供已发送消息 ID，当前 `ResponseFactory` 也没有交付回调。`build_runtime()` 给 `PlayerRenderer` 使用空 `ResourceMap`，而百科索引要求 `alias/weekly_item/calendar/`，与资源文档示例目录未形成可验证的一致契约。伤害失败路径会把 `_safe_damage_message()` 返回的上游 `msg` 写进 PNG 文本，现有关键字过滤不能覆盖 Authorization/Bearer 等敏感格式。完整审查记录见 `docs/porting/review-v0.3-debug.md`。
- 剩余风险/下一步：当前 `原图` 仅有离线缓存契约，不能称为可用的平台引用功能；默认 runtime 的玩家图片和原图仍未从私有资源仓库读取；伤害失败消息存在敏感内容回显风险；每次图片查询都保留 UUID PNG，可能造成运行期数据持续增长。下一轮先执行 Task 16.1，再执行 Task 16.2；图片差异、日历/图鉴/攻略/兑换码/别名的真实资源或时间敏感验收仍留待 Task 30，未获人工接受。

### Task 16.1：修复运行期资源契约、渲染资产接线与临时图片生命周期

- 状态：[x]
- 范围：以现有私有资源同步根为唯一运行期来源，收敛 manifest、资源目录文档和 `EncyclopediaResourceStore` 的实际目录契约；为玩家/百科 renderer 注入运行期字体、面板和图片资源，移除对插件源码内旧字体/空 `ResourceMap` 的生产依赖。使用 AstrBot 4.27.x 公共临时文件生命周期接口处理已发送的合成 PNG，不对原图资产施加无依据的时间或数量限制。不得创建、推送或联网同步私有资源仓库。
- 验证要求：先以资源目录 fixture 覆盖 manifest 到 bootstrap 的完整接线，验证角色/武器/魔灵图鉴、攻略和别名能解析到已提供资源，周报/日历/角色面板在已提供时具有 `provided` 语义；覆盖缺失资源的明确失败/placeholder；验证图片响应文件在事件生命周期结束后清理而需要长期引用的原图资产不被误删；同步资源/命令/架构文档并跑全量门禁。
- 风险：资源仓库尚未获授权创建，测试只能使用隔离 fixture；不得把同步成功误写为真实私有资源或视觉等价已验收。
- 实际完成：将 `fonts`、`images`、`panel`、`alias`、`wiki/{role,weapon,spirit}`、`guide`、`weekly_item`、`calendar` 设为同步和 bootstrap 共同校验的运行期 manifest 布局；bootstrap 从唯一 `resources/` 根注入 `ResourceMap` 和 `EncyclopediaResourceStore`。玩家/百科 renderer 只读取该根的字体、图片和面板，不再读取源码 legacy 字体，并在 PNG metadata 中区分 `provided`、`placeholder` 与 `fallback`。概览、详情、便笺、周报和日历生成的 `rendered/*.png` 标记为临时响应；响应边界仅登记受控渲染根内的现存普通文件到 AstrBot 4.27.x 公开事件清理接口，原图、wiki 和攻略资源保持非临时。
- 验证证据：TDD 先确认缺少完整布局校验、bootstrap 资源注入和临时图片标记时测试失败，随后以隔离资源 fixture 覆盖 manifest/sync/bootstrap、角色/武器/魔灵图鉴、攻略、别名、周报、日历、面板和缺失 placeholder；以 `AstrMessageEvent` fixture 验证事件结束删除合成图且保留原始资源，并拒绝越界临时路径。完整 staging runtime 测试为 `144 passed, 1 skipped, 1 warning`（第三方 `audioop` 弃用警告）；`ruff check .`、`pyright --project pyrightconfig.json`（0 errors）、runtime `compileall`、`pre-commit run --all-files` 和 `git diff --check` 均通过。未创建、推送或联网同步任何资源仓库，未执行真实 NapCat 或真实账户。
- 剩余风险/下一步：fixture 接线不代表私有资源内容、同步成功或视觉等价已验收，仍由 Task 30 以只读矩阵审查；平台原图引用映射和伤害失败输出边界仍待下一轮 Task 16.2。

### Task 16.2：修复原图引用映射与详情失败输出边界

- 状态：[x]
- 范围：消除 `PlayerService.last_original_image` 的实例级共享状态，令原图路径随单个详情响应传递，避免并发详情串图。先核实 AstrBot 4.27.x 是否存在可用的公开发送结果/消息 ID 交付点；只有确实拿到平台消息 ID 后才登记缓存。若公开 API 无法支撑引用映射，必须让命令/帮助/矩阵明确显示未支持或不注册，不能把永久不可命中的缓存伪装成“未找到”。同时将伤害失败的用户可见内容收敛为受控文案，不回显上游 `msg`、URL、Authorization 或任意凭据样式。
- 验证要求：用事件/响应 fixture 覆盖两次并发详情各自对应的原图、无原图和发送失败路径；覆盖真实 handler 到公开结果边界的登记/未支持分支；以多种 token/cookie/dev code/Authorization/Bearer/URL 形式的失败 payload 断言 PNG 元数据和用户响应均不泄露；同步命令、矩阵和阶段文档并跑全量门禁。
- 风险：禁止真实 NapCat，不能用平台私有接口或真实发送副作用替代公开 SDK/fixture 证据；实现后仍须在 Task 30 记录真实平台引用能力的验收边界。
- 实际完成：提交 `6e93de8`。核实 AstrBot 4.27.1 公开边界：`AstrMessageEvent.send()` 返回 `None`、`MessageEventResult` 无消息 ID 字段、`ResponseFactory` 无交付回调——无发送后消息 ID 交付点，因此不登记任何缓存；移除 `OriginalImageCache`/`last_original_image`/`remember_original_image` 实例级共享状态与死模块 `src/infrastructure/rendering/original.py`，原图路径随单个 `ImageResponse.original_image_path` 传递，并发详情各自关联自己的原始面板。`原图` 命令更名为“角色原图（暂不支持）”，回复受控文案 `PLAYER_ORIGINAL_UNSUPPORTED`。伤害失败正文收敛为 `PLAYER_DAMAGE_FAILED` 受控文案（transport/service/renderer 三层），不再回显上游 `msg`/URL/Authorization/Bearer/token/cookie/dev code。移除 `display.role_original_image` 配置，重新生成 `commands.json` 与 `_conf_schema.json`；同步 README、usage、architecture、命令矩阵、progress、CHANGELOG，并在 `.gitignore` 忽略 `data.bak-*` 陈旧运行期残留。
- 验证证据：新增 fixture 覆盖并发详情原图各自对应（`test_concurrent_role_details_keep_their_related_original_paths`）、无原图（`original_image_path is None`）、6 种凭据样式失败 payload 不进入 PNG 文本/布局/资源元数据（`test_damage_failure_payload_never_reaches_detail_image`）和真实生成 handler 的未支持分支（`test_original_image_handler_explicitly_reports_public_boundary_unsupported`）；回归原详情/概览/同律武器失败/无绑定测试。staging runtime（临时根 symlink 指向 worktree）全量 pytest 为 `152 passed, 1 skipped, 1 warning`（skip 为既有 Alembic 未安装 round-trip，warning 为 AstrBot `audioop` 弃用）；`ruff check .`（全局 0.15.12，pre-commit 同源）、`pyright --project pyrightconfig.json`（0/0/0）、runtime `python -m compileall -q .`、`pre-commit run --all-files`、`git diff --check` 均通过。注意：全量 pytest 必须从 staging 临时根运行（`python -m pytest` 的 cwd 进入 sys.path[0]，从 worktree 内直接跑会被本地 gitignored `data/` 目录遮蔽 `data.plugins` 命名空间，造成 test_migration_boundaries 假失败）；worktree 内既有陈旧 `data/` 已改名 `data.bak-stale` 并忽略。
- 剩余风险/下一步：fixture 证据不等于真实平台原图引用能力，Task 30 需记录该验收边界；venv ruff 0.16.1 对更早 task 文件（encyclopedia/resources/privacy/账号测试）仍有 0.16 新增规则告警（I001/RUF022/UP035/DTZ007 等），与本 task 无关，门禁以 pre-commit 同源全局 ruff 为准。下一轮只执行 Task 17（v0.4.0 签到）。

## 阶段 5：`v0.4.0` 签到

### Task 17：实现游戏/社区签到与日历结果

- 状态：[x]
- 范围：在 fake transport、隔离 DB 和事件 fixture 中迁移游戏/社区签到、日历、批量结果；保持错误可见，不凭空新增超时、重试或静默降级。
- 实际完成：提交 `c25354c`。新增 `src/modules/checkin/`：typed `CheckinTransport` 契约、`CheckinService`（manual_sign/sign_calendar/sign_all）和 `CheckinRenderer`（1300 宽日历 PNG）。`sign`（签到/社区签到/每日任务/社区任务/库街区签到/sign）、`sign_calendar`（签到日历/签到记录/签到历史）和 `sign_all`（全部签到，owner）三条显式 CommandSpec，注册进 `src/modules/index.py` 并重新生成 `commands.json`（38 条）。当天签到计数经 `SignRecordRepository.save` upsert 写入新 schema `sign_records` 表；`AccountBindingRepository.list_all` 供 owner 批量读取全部绑定。`DnaApiCheckinTransport` 只在 transport 边界组装 legacy `DNAUser` 并复用纯 API（sign_calendar/game_sign/bbs_sign/get_task_process/have_sign_in/get_post_list/get_post_detail/do_like/do_share/do_reply），服务层不接触旧事件/数据库/消息段；已签到(code 711)、社区已签(code 10000)、日历精简、帖子遍历失败等均映射为稳定状态或受控文案，不回显上游 `msg`/URL/凭据样式内容。
- 验证证据：新增 `tests/test_checkin.py`（成功落盘、已签到跳过且不调用 transport、仅游戏、双关闭、transport 失败脱敏、日历精简失败、bbs_detail 帖子遍历计数、bbs_like 连续失败显式错误、日历渲染 1300 宽 PNG 布局/资源语义、批量聚合 1 成功 1 失败、无绑定、防偷窥）共 13 条；`tests/test_checkin_commands.py`（归属/正则/权限/缺 service/生成 handler）3 条；`tests/test_checkin_transport.py`（payload 映射、精简字段允许缺失、code 711/10000、错误脱敏）5 条。staging runtime 全量 pytest 为 `173 passed, 1 skipped, 1 warning`（skip 为既有 Alembic 未安装 round-trip，warning 为 AstrBot `audioop` 弃用）；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；`commands.json` 由 registry 生成且与分发表一致（test_command_registry 断言已补 sign 三条）。
- 剩余风险/下一步：真实写操作（游戏/社区签到、浏览/点赞/分享/回复）只在 fake transport + 隔离 SQLite + 事件 fixture 中验证，未执行真实 NapCat 或真实账户写入；订阅签到结果（`sign_result_subscribe`）、计划任务/自动签到（`scheduled_enabled`/`enable_all_users`）和生命周期取消仍属 Task 18，签到写入型的完整离线契约与权限测试由 Task 19 补齐。下一轮只执行 Task 18（计划任务、结果订阅与生命周期取消）。

### Task 18：实现计划任务、结果订阅与生命周期取消

- 状态：[x]
- 范围：迁移签到计划、结果订阅和 `initialize()`/`terminate()` 中的 asyncio 任务启动与取消；验证资源释放、并发事务和重复初始化。
- 实际完成：提交 `d0d764c`。新增 `src/infrastructure/subscriptions/` 框架无关 JSON 订阅存储（type+会话去重、原子落盘、损坏文件显式失败），注册 `sign_result_subscribe`（订阅/取消订阅签到结果，owner）；`commands.json` 重新生成共 39 条命令。新增 `src/infrastructure/scheduler.py` 的 `SignScheduler`：每日自动签到（`sign_in.sign_time`）与 2 天前签到记录清理两个 asyncio 任务，`initialize()` 创建、`terminate()` 取消，重复 start/stop 幂等，`scheduled_enabled` 关闭时只保留清理任务。`CheckinService` 新增 `subscribe_sign_result`/`auto_sign_all`/`clear_sign_records_before`（自动签到摘要按 legacy 语义区分游戏/社区成功数），`sign_all` 重构共享 `_run_all_signs`；`EventActor` 增加 `unified_msg_origin`（AstrBot 公开属性）用于订阅目标。生命周期钩子改为 start: web → scheduler，stop: scheduler → database.dispose；推送闭包绑定 `Context.send_message` 公开 API。
- 验证证据：新增 `tests/test_subscription_store.py`（持久化/去重/显式删除/损坏可见失败）3 条、`tests/test_scheduler.py`（幂等 start/stop、定时关闭只保留清理任务、自动签到推送订阅者、2 天前清理且不真实睡眠）5 条；`tests/test_checkin.py` 新增订阅/取消/缺 origin/auto_sign_all/清理 5 条；`tests/test_checkin_commands.py` 新增订阅命令归属与生成 handler 测试；`tests/test_command_registry.py`/`test_migration_boundaries.py` 同步 sign_result_subscribe 与生命周期 terminate 断言。staging runtime 全量 pytest 为 `184 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；未检出 `gsuid_core`/`gsucore` import（仅 docstring 提及替代关系）。
- 剩余风险/下一步：计划任务与推送只在隔离订阅存储 + fake checkin + 注入 push/now/sleep fixture 中验证，未执行真实 NapCat 或真实账户写入；订阅/登录/绑定/隐私写入的完整离线契约与权限测试由 Task 19 补齐，密函/公告轮询调度仍属 Task 22。下一轮只执行 Task 19。

### Task 19：补齐写入型能力的离线契约与权限测试

- 状态：[x]
- 范围：为真实账户禁止执行的登录/签到/绑定/订阅/隐私写入等建立 fake transport、隔离 SQLite、模拟事件和旧逻辑 fixture 契约；明确“离线验证”不等于真实行为已验证。
- 实际完成：提交 `877a13d`。新增 `tests/test_write_contracts.py`：集中审计 23 条写入型命令的权限边界（`account_*` 与个人隐私与 `sign` 为 user，群管理隐私 10 条为 admin，`sign_all`/`sign_result_subscribe` 为 owner）与离线契约覆盖（`CONTRACT_COVERAGE` 映射到 `test_account.py`/`test_privacy.py`/`test_privacy_commands.py`/`test_checkin.py` 的代表性用例并断言文件与函数存在）。每条写入命令都能通过生成后的 AstrBot handler（mock 公开事件 API）在 fake transport + 隔离 SQLite 下离线分发并产出框架无关响应；`sign` 写路径额外断言只调用注入 transport 的 `get_sign_calendar/game_sign/get_task_process/bbs_sign`，不触碰真实网络边界。新增 `docs/porting/offline-write-contracts.md` 明确“离线验证 ≠ 真实行为已验证”，逐能力列出离线覆盖、未注册写入能力（面板/别名/资源）与 Task 30 验收边界。
- 验证证据：`tests/test_write_contracts.py` 共 26 条（权限审计 1 + 契约文件审计 1 + 23 条离线分发 + sign 只调注入 transport 1）全部通过；staging runtime 全量 pytest 为 `210 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；未检出 `gsuid_core`/`gsucore` import。
- 剩余风险/下一步：离线分发契约只证明命令链路可用，不代表真实账户写入行为已验证；面板上传/删除/压缩、别名修改、资源更新等写入命令尚未注册，其实平台验收边界留待 Task 25/26 与 Task 30。下一轮执行 Task 20（阶段 5 集中检查-debug）。

### Task 20：集中检查-debug（阶段 5）

- 状态：[x]
- 范围：复核签到状态机、调度取消、订阅边界、写入隔离、并发/事务和全量门禁；发现问题追加修复 task。
- 实际完成：提交 `503deba`。复核 Task 17-19（`c25354c..b5503d8`）并修复 4 项边界问题：① 移除 `CheckinService.enable_all_users` 死参数，门控语义移交 `SignScheduler`（定时自动签到需 `scheduled_enabled and enable_all_users`，承担 legacy `SigninMaster` 对全账号自动签到的语义，owner 手动 `全部签到` 不受影响）；② 社区启用但 API 未返回启用任务时从误报「帖子列表为空」改为明确 `CHECKIN_TASKS_EMPTY`；③ `subscribe_sign_result` 在订阅文件损坏时返回可见 `SIGN_RESULT_STORE_UNAVAILABLE`，不再让 handler 崩溃；④ 移除 `CheckinSummary.lines` 死字段。完整审查记录见 `docs/porting/review-v0.4-checkin.md`。
- 验证证据：新增回归测试（无启用任务显式文案、损坏订阅文件可见错误、`enable_all_users` 门控只保留清理任务）3 条，相关聚焦集合通过；staging runtime 全量 pytest 为 `213 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；参考区 `legacy-reference` 冻结在 `664b677`，`git worktree list` 只列参考区与重构区。
- 剩余风险/下一步：同一 UID 并发签到可能在保存前重复执行写操作（`_save_snapshot` 写锁只保证 (uid, date) 唯一冲突不爆，不串行化整个读-检-签-存周期），记录收敛为「已签」，与 legacy 行为一致，作为接受边界记录在 review-v0.4-checkin.md；真实平台写入/推送行为仍未验收（Task 30）。下一轮执行 Task 21（密函、公告和活动日历读取，v0.5.0 通知）。

## 阶段 6：`v0.5.0` 通知

### Task 21：实现密函、公告和活动日历读取

- 状态：[x]
- 范围：迁移通知读取用例、API fixture、文本/图片/chain 响应和命令帮助；与真实账户只读矩阵对齐。
- 实际完成：提交 `ca78c4a`。新增 `src/modules/notices/`：typed `NoticesTransport` 契约、`NoticesService`（mh/mh_list/ann 列表与详情）和 `NoticesRenderer`（1300 宽 PNG，公告图片块标记为 placeholder 资源）。注册 `mh`（密函/委托密函/mh）、`mh_list`（密函列表）和 `ann`（公告/公告 序号，命名参数 `index`）三条读取型命令，`commands.json` 重新生成共 42 条。`DnaApiNoticesTransport` 复用 legacy `get_default_role_for_tool` 的 `instanceInfo`（密函分节）与公共 BBS 的 `get_ann_list`/`get_post_detail`（HTML 清洗/时间解析复用 `dnaby/dna_ann/utils` 纯逻辑）。活动日历（`日历`）已由 Task 14 提供，不重复注册。密函用调用者 active UID 凭据读取（区别于 legacy 随机账号 quirk，作为记录差异）；公告无需账号。
- 验证证据：新增 `tests/test_notices.py`（密函渲染 1300 宽 PNG/空数据/无绑定/transport 失败脱敏/密函列表/公告列表图/公告序号详情/序号无效/空列表）共 9 条、`tests/test_notices_commands.py`（归属/正则命名参数/缺 service/生成 handler）4 条、`tests/test_notices_transport.py`（instanceInfo 映射、公告列表/详情复用纯逻辑、错误脱敏）3 条；staging runtime 全量 pytest 为 `229 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；未检出 `gsuid_core`/`gsucore` import。
- 剩余风险/下一步：真实密函/公告内容、图片与视觉等价未验收（Task 30 只读矩阵）；通知订阅/推送与轮询属 Task 22，密函/公告订阅命令（mh_subscribe/ann_sub/ann_unsub 等）暂未注册。下一轮执行 Task 22。

### Task 22：实现通知订阅推送和取消订阅

- 状态：[x]
- 范围：使用原生订阅替代实现推送与取消，覆盖个人/群组作用域、去重、生命周期清理、权限和失败日志；写入操作仅在隔离环境执行。
- 实际完成：提交 `18a73ad`。扩展 `SubscriptionStore`（`Subscription` 增加 `uid/extra_message/extra_data`，store 增加作用域过滤 `get` 与 `update`）；注册 `mh_subscribe`/`mh_subscribe_by_name`/`mh_subscribe_cycle`/`mh_pic_subscribe`/`mh_text_subscribe`/`mh_test`/`ann_sub`/`ann_unsub` 8 条订阅命令（user/admin/owner 权限与 legacy 一致），`commands.json` 重新生成共 50 条。`NoticesService` 新增密函按名订阅/取消（按 user+会话作用域去重、禁止订阅全部、推送时间窗口 `订阅密函时间HH:HH`）、图片/文本会话作用域开关（admin）、owner 密函测试推送、公告群订阅/取消（admin，仅群聊去重），以及计划任务 `push_mh_now`（文本/图片推送）与 `poll_ann_now`（`AnnStateStore` 记录已知公告 id，只推送新条目）。新增 `src/infrastructure/notices_scheduler.py`：每小时按 `secret_push_time` 推送密函、按 `announcement_check_minutes` 轮询公告，幂等 start/stop 接入生命周期；推送闭包把 str/Path 载荷映射为 Plain/Image 组件并经 `Context.send_message` 发送。`get_mh_any` 用任意可用账号凭据读取密函供计划任务（区别于读取命令的调用者账号）。
- 验证证据：新增 `tests/test_notices_subscriptions.py`（订阅增删/去重/禁全部/时间窗口/图片文本开关/公告群订阅/计划推送/公告轮询去重/owner 测试）12 条、`tests/test_notices_scheduler.py`（幂等 start/stop、配置解析）2 条；`tests/test_write_contracts.py` 将 7 条通知订阅写入命令纳入权限与离线契约审计；`tests/test_notices_commands.py`/`test_command_registry.py` 同步断言。staging runtime 全量 pytest 为 `250 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；未检出 `gsuid_core`/`gsucore` import。
- 剩余风险/下一步：订阅/推送只写入隔离 SubscriptionStore 并由注入 push fixture 验证，真实平台推送未执行，真实密函/公告内容与视觉等价未验收（Task 30）；通知失败日志/事件响应测试与脱敏由 Task 23 完善。下一轮执行 Task 23。

### Task 23：完善通知脱敏、可观测错误和事件响应测试

- 状态：[x]
- 范围：验证 Cookie/token 不进入日志、异常和用户响应；区分用户取消、网络失败、状态码错误、服务端异常和页面结构变化，不伪造成功。
- 实际完成：提交 `5fbe57d`。强化 `tests/test_notices_transport.py`：新增 5 条测试覆盖网络失败（`aiohttp.ClientError` → NETWORK）、状态码错误（`code=403` → STATUS）、密函页面结构变化（缺 `instanceInfo` → SERVER）、公告详情结构变化（`postContent` 非列表 → 显式抛错），并断言 Cookie/token 与上游 `msg` 原文（`token=secret-*`）不进异常 str/repr；成功路径确认使用调用者/任意账号凭据。错误分类统一：用户取消（`订阅密函时间` 越界）返回格式提示，网络/状态码/服务端/结构变化分别映射稳定类别，用户响应只含受控文案，不伪造成功。
- 验证证据：`tests/test_notices_transport.py` 现 8 条全部通过；staging runtime 全量 pytest 为 `255 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过。
- 剩余风险/下一步：真实密函/公告内容、图片与视觉等价仍未验收（Task 30 只读矩阵）；事件响应由写入契约 dispatch 与生成 handler 测试覆盖。下一轮执行 Task 24（阶段 6 集中检查-debug）。

### Task 24：集中检查-debug（阶段 6）

- 状态：[x]
- 范围：复核通知读取/推送、订阅数据一致性、并发去重、敏感信息和完整门禁；将未解决问题留在清单中。
- 实际完成：提交 `81fa461`。复核 Task 21-23（`ca78c4a..0733789`）并修复 3 项订阅一致性问题：① `SubscriptionStore.add/delete/update` 改为按 `(type, origin, uid)` 精确匹配——同一会话内不同用户的个人密函订阅互不覆盖，删除/更新不再误伤同会话其他记录；② 密函订阅/取消/查看改为按当前会话 `unified_msg_origin` 取目标，多会话用户读写各自会话订阅，不串扰；③ 取消订阅后剩余列表为空时直接删除记录，清理死数据。完整审查记录见 `docs/porting/review-v0.5-notices.md`。
- 验证证据：新增 4 条回归测试（同会话多用户去重 `test_add_dedupes_by_uid_within_same_origin`、按 uid 删除 `test_delete_is_scoped_by_uid`、跨会话作用域 `test_mh_subscription_is_scoped_per_conversation`、双用户同会话 `test_mh_subscription_keeps_two_users_in_same_conversation`）全部通过；staging runtime 全量 pytest 为 `259 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过；参考区冻结在 `664b677`。
- 剩余风险/下一步：真实密函/公告内容、图片与视觉等价未验收（Task 30 只读矩阵）；真实平台推送未执行，仅注入 push fixture 覆盖契约。下一轮执行 Task 25（面板图管理和运行期资源状态，v0.6.0 运维与面板）。

## 阶段 7：`v0.6.0` 运维与面板

### Task 25：实现面板图管理和运行期资源状态

- 状态：[x]
- 范围：迁移面板图查询/管理、资源状态、manifest 和本地数据目录边界；上传、删除、压缩等写操作只在隔离 fixture 验证，不操作真实账户或参考区。
- 实际完成：提交 `f369e14`。新增 `src/modules/operations/`：`PanelService` 管理运行期数据目录 `panel_custom/` 的自定义面板图——上传（保存 WebP、按内容 sha1 去重）、列表（文本+图片链 ChainResponse）、按 ID/全部删除、压缩为 WebP（复用 legacy `compress_to_webp`）；`原图删除` 因公开结果边界无原图引用缓存显式报告暂不支持（与 Task 16.2 一致）；`resource_status` 展示私有资源仓库目录、`ResourceManifest` 格式/资源版本/必需目录存在数与本地面板数量。注册 `upload_panel_img`/`list_panel_imgs`/`delete_panel_img_by_id`/`delete_all_panel_imgs`/`delete_original_panel_img`/`compress_panel_imgs`/`resource_status` 7 条 owner 命令，`commands.json` 重新生成共 57 条。命令层 `CommandRequest` 增加 `images` 字段，经 `images_from_event` 从 AstrBot 公开消息链提取图片载荷（本地路径/base64/URL）。
- 验证证据：新增 `tests/test_operations.py`（上传 WebP/sha1 去重/无图/未知角色/坏字节失败/列表链/按 ID 删除/全部删除/压缩/资源状态 manifest）共 10 条、`tests/test_operations_commands.py`（归属 owner/正则/`images_from_event` 提取/缺 service/生成 handler）4 条；`tests/test_write_contracts.py` 将 7 条面板/资源 owner 写命令纳入权限与离线契约审计；`tests/test_command_registry.py` 同步。staging runtime 全量 pytest 为 `280 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过。
- 剩余风险/下一步：面板上传/删除/压缩只操作隔离目录 fixture，未操作真实账户或参考区；真实平台面板上传行为未执行，仅离线契约覆盖。资源更新（下载全部资源/更新日志）与 `download_resource` 命令属 Task 26。下一轮执行 Task 26。

### Task 26：实现资源更新、下载日志与更新日志展示

- 状态：[x]
- 范围：实现私有资源仓库浅克隆/`git pull --ff-only` 的检查和可见失败，更新日志读取，确认 Git 缺失、认证失败、远端失败、非快进和本地修改均不自动覆盖。
- 实际完成：提交 `f240bfb`。新增 `src/modules/operations/resource_service.py`：`ResourceUpdateService` 复用既有 `ResourceSynchronizer`（浅克隆/`git pull --ff-only` + manifest 校验），下载全部私有资源；Git 缺失（`GitUnavailableError`）、远端不匹配（`ResourceRemoteMismatchError`）、本地修改（`ResourceLocalChangesError`，不自动覆盖）、非快进/认证/远端失败（`GitCommandError`）均映射为可见错误文案；`update_log` 经 `git log` 读取插件仓库最近提交，Git 不可用/非仓库返回可见失败。注册 `download_resource`（下载全部资源）与 `update_log`（更新记录/更新日志）2 条 owner 命令，`commands.json` 重新生成共 59 条命令。
- 验证证据：新增 `tests/test_resource_service.py`（下载成功克隆/更新分支、Git 缺失/远端不匹配/本地修改/同步失败可见错误、更新日志有/无提交）共 6 条；`tests/test_write_contracts.py` 将 2 条 owner 命令纳入权限与离线契约审计；`tests/test_command_registry.py` 同步。同步器自身的凭据脱敏与 Git 边界由既有 `test_config_resources.py` 覆盖。staging runtime 全量 pytest 为 `288 passed, 1 skipped, 1 warning`；`ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、`pre-commit run --all-files`、`git diff --check` 均通过。
- 剩余风险/下一步：真实私有资源仓库未联网同步，只使用隔离 runner/fake synchronize 验证；私有资源仓库创建/推送属独立外部步骤，需用户授权。下一轮执行 Task 27（同步 v0.6 文档、配置和迁移限制）。

### Task 27：同步 v0.6 文档、配置和迁移限制

- 状态：[ ]
- 范围：更新 README、`docs/`、配置/schema、数据目录、资源依赖、未实现能力和私有发布边界；保持 `AGENTS.md` 与 `CLAUDE.md` 镜像且不超 100 行，长文拆入 docs。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 28：集中检查-debug（阶段 7）

- 状态：[ ]
- 范围：复核面板/资源更新的安全性、路径和 Git 边界、日志脱敏、配置契约、文档同步和门禁；追加必要修复 task。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

## 阶段 8：`v1.0.0` 补齐与终审

### Task 29：盘点并补齐历史 56 项能力

- 状态：[ ]
- 范围：以原命令清单、目标 registry、行为矩阵和测试为依据逐项盘点；实现缺失能力，未实现命令不注册、不展示，记录任何不可避免差异。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 30：完成全量行为差异审查与只读回归验收

- 状态：[ ]
- 范围：完成读取型 gscore 矩阵、离线写入契约、图片/文本/chain 对比、AstrBot staging 加载和全部自动化门禁；所有差异有原因、影响和人工结论。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 31：集中检查-debug（阶段 8）

- 状态：[ ]
- 范围：复核 56 项能力、权限、测试、构建、资源、数据一致性、安全、文档、可回滚提交和发布边界；问题追加修复 task，不将未审查项标为通过。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 32：终审、同步交付文档并登记完成

- 状态：[ ]
- 范围：进行最大范围终审，确认无已知高风险问题；补齐 `design.md`、`plan.md`、`review.md`、`final_report.md`、README/docs/CHANGELOG 等交付物；只在目标真正达成后标记 goal 完成。不得合并、推送或公开发布。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：
