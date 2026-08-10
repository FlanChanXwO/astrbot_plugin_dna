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

- 状态：[ ]
- 范围：按领域建立 Pydantic settings 与 `_conf_schema.json` 生成，落地私有资源下载接口、manifest 校验、`logo.png`、`CHANGELOG.md`；明确资源 Git 同步的失败可见性和不覆盖策略。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 8：集中检查-debug（阶段 2）

- 状态：[ ]
- 范围：复核 Task 5-7 的入口契约、命令清单、配置 schema、资源边界、AstrBot 加载和完整门禁；补修复 task 并保留可回滚提交。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

## 阶段 3：`v0.2.0` 账号与隐私

### Task 9：建立 SQLAlchemy async 持久化和 Alembic 初始结构

- 状态：[ ]
- 范围：使用 `sqlite+aiosqlite`、SQLAlchemy 2 async、repository/事务边界和 Alembic 初始 revision；凭据字段私有化并确保日志/异常/DTO 脱敏；不迁移旧数据库。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 10：实现账号登录、退出、UID 绑定/切换/删除与凭据查询

- 状态：[ ]
- 范围：在隔离 transport/SQLite/事件 fixture 下迁移账号用例，使用 typed request/框架无关 DTO；覆盖成功、取消、网络/状态码/服务端错误和敏感信息脱敏。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 11：实现个人/群组隐私能力和权限边界

- 状态：[ ]
- 范围：迁移隐私查询与修改、群组/个人作用域和权限判断；写入行为只在隔离测试执行，用户可见文案统一由 notify 层提供。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 12：集中检查-debug（阶段 3）

- 状态：[ ]
- 范围：复核账号/隐私行为、鉴权、事务、凭据泄露、异常显露、测试覆盖和文档；修正已知问题并更新任务记录。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

## 阶段 4：`v0.3.0` 查询与百科

### Task 13：实现玩家角色查询、详情/伤害和原图能力

- 状态：[ ]
- 范围：迁移角色概览、详情、伤害计算、原图等读取型 use case 与渲染；保留完整合法输出，图像验证记录尺寸、消息类型、布局、文本和资源语义。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 14：实现便签、周报、日历、wiki、攻略、兑换码和别名读取

- 状态：[ ]
- 范围：迁移读取型百科/资料能力、资源语义和别名列表；建立 API fixture、素材 fixture、命令归属和响应 DTO 测试。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 15：建立 gscore 只读探测与命令行为差异矩阵

- 状态：[ ]
- 范围：通过 `ssh atri` 只读探测 gscore 入口/存储格式；在凭据不落盘的前提下选择完整账户，逐项记录 DNAUID 与迁移后读取输出及图像临时对比资料；不得执行写入型命令。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 16：集中检查-debug（阶段 4）

- 状态：[ ]
- 范围：复核查询/百科完整性、命令矩阵、动态字段 mask、图像差异结论、资源来源、网络错误和文档；未审查差异不得标为通过。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

## 阶段 5：`v0.4.0` 签到

### Task 17：实现游戏/社区签到与日历结果

- 状态：[ ]
- 范围：在 fake transport、隔离 DB 和事件 fixture 中迁移游戏/社区签到、日历、批量结果；保持错误可见，不凭空新增超时、重试或静默降级。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 18：实现计划任务、结果订阅与生命周期取消

- 状态：[ ]
- 范围：迁移签到计划、结果订阅和 `initialize()`/`terminate()` 中的 asyncio 任务启动与取消；验证资源释放、并发事务和重复初始化。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 19：补齐写入型能力的离线契约与权限测试

- 状态：[ ]
- 范围：为真实账户禁止执行的登录/签到/绑定/订阅/隐私写入等建立 fake transport、隔离 SQLite、模拟事件和旧逻辑 fixture 契约；明确“离线验证”不等于真实行为已验证。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 20：集中检查-debug（阶段 5）

- 状态：[ ]
- 范围：复核签到状态机、调度取消、订阅边界、写入隔离、并发/事务和全量门禁；发现问题追加修复 task。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

## 阶段 6：`v0.5.0` 通知

### Task 21：实现密函、公告和活动日历读取

- 状态：[ ]
- 范围：迁移通知读取用例、API fixture、文本/图片/chain 响应和命令帮助；与真实账户只读矩阵对齐。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 22：实现通知订阅推送和取消订阅

- 状态：[ ]
- 范围：使用原生订阅替代实现推送与取消，覆盖个人/群组作用域、去重、生命周期清理、权限和失败日志；写入操作仅在隔离环境执行。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 23：完善通知脱敏、可观测错误和事件响应测试

- 状态：[ ]
- 范围：验证 Cookie/token 不进入日志、异常和用户响应；区分用户取消、网络失败、状态码错误、服务端异常和页面结构变化，不伪造成功。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 24：集中检查-debug（阶段 6）

- 状态：[ ]
- 范围：复核通知读取/推送、订阅数据一致性、并发去重、敏感信息和完整门禁；将未解决问题留在清单中。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

## 阶段 7：`v0.6.0` 运维与面板

### Task 25：实现面板图管理和运行期资源状态

- 状态：[ ]
- 范围：迁移面板图查询/管理、资源状态、manifest 和本地数据目录边界；上传、删除、压缩等写操作只在隔离 fixture 验证，不操作真实账户或参考区。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

### Task 26：实现资源更新、下载日志与更新日志展示

- 状态：[ ]
- 范围：实现私有资源仓库浅克隆/`git pull --ff-only` 的检查和可见失败，更新日志读取，确认 Git 缺失、认证失败、远端失败、非快进和本地修改均不自动覆盖。
- 实际完成：
- 验证证据：
- 剩余风险/下一步：

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
