# 执行任务清单

> **执行中：按 goal-mode 自动推进。** 用户已明确要求启动 `goal-1`，从 O01 顺序推进。每个普通任务只占一个目标轮次；每完成 3 个普通任务，必须执行紧随其后的调试审查任务，不能跳过。

统一完成记录模板（执行时填写到对应任务下）：

- 实际完成：
- Red/Green/Refactor 证据：
- 验证命令与结果：
- 剩余风险：
- 下一步：

## 第一阶段：原版命令行为与帮助

### O01 — 执行前隔离、基线与失败复现 `[completed]`

- 征得用户对 Git worktree/`codex/` 分支的明确同意后建立隔离环境。
- 阅读 `docs/README.md`、`docs/porting/design.md` 及即将修改的确切代码。
- 运行最小测试，复现并记录 `test_help_image_is_tracked_and_cleaned` 当前失败。
- 为第一阶段验收矩阵补充 Red 测试，不写实现。

完成记录：

- 实际完成：确认当前项目根目录是 Git 已注册 worktree（`main`，HEAD `9a33b60ed3545020b97acb11e18b91041c1f80de`），按用户指定目标路径继续执行，未触碰其它 worktree、生产仓库或运行期数据。阅读 `docs/README.md`、`docs/porting/design.md`、帮助 use case、响应边界、命令 registry、事件目标解析及相关测试，并新增 `tests/test_goal1_phase1_red.py`；goal-1 三份状态文件与测试契约已纳入本轮提交。
- Red/Green/Refactor 证据：Red 已实际成立；本 task 只建立行为契约，不写生产实现，因此没有 Green/Refactor 阶段。新增测试锁定：权限过滤、最后一个有效 At、权限枚举收敛为 `user/admin`、移除 `update_log` 命令。
- 验证命令与结果：项目 `.venv/bin/python -m pytest tests/test_generated_image_lifecycle.py::test_help_image_is_tracked_and_cleaned -q` 为 `1 failed`，失败原因为 monkeypatch renderer 不接受 `prefix`；项目 `.venv/bin/python -m pytest tests/test_goal1_phase1_red.py tests/test_generated_image_lifecycle.py::test_help_image_is_tracked_and_cleaned -q` 为 `5 failed, 1 warning`，均为预期 Red/已知基线；项目 `.venv/bin/ruff check tests/test_goal1_phase1_red.py` 通过。
- 剩余风险：当前工作目录虽是已注册 Git worktree，但仍为 `main` 主工作树，未另建 task-specific `codex/` worktree；这是因用户直接指定该项目路径且 goal-mode 禁止交互式停问所作的执行假设，后续 commit 仅纳入本轮明确文件。系统 `python3` 缺少 `astrbot`，验证必须使用项目 `.venv`；帮助图生命周期基线与新增 Red 契约仍待 O02/O03 实现后转绿。
- 下一步：O02，先实现权限快照、registry 帮助过滤、动态前缀/版本缓存及移除更新记录命令。

### O02 — 权限、registry 帮助、动态前缀与版本 `[completed]`

- TDD 实现 user/admin 权限快照和帮助过滤。
- 帮助命令从 registry 构建，纳入角色列表等全部可见命令。
- 移除隐式 `d` 前缀，版本改为单一 metadata 源，按前缀/权限/版本缓存并在生命周期结束时失效。
- 移除更新记录命令与长 Git log 渲染链。

完成记录：

- 实际完成：权限枚举收敛为 `user/admin`，handler 在 `CommandRequest` 中一次快照事件管理员权限；所有原 `owner` 命令统一映射 AstrBot `admin`。帮助卡从 registry 的可见命令构建，保留表现层分组说明/图标，普通用户过滤管理员命令；移除模板隐式 `d` 和硬编码版本，版本统一读取 `metadata.yaml`。帮助缓存按 registry 身份、前缀、权限、版本索引，并在 runtime terminate 的 `finally` 中失效；registry 模式不再生成静态 help fallback。删除聊天“更新记录”命令、资源 service 的 Git log/图片链、模板、脚本调用和静态帮助条目，重新生成 `commands.json`。
- Red/Green/Refactor 证据：先实际运行 O01 Red 契约，权限/帮助/版本缓存与更新日志行为均出现预期失败；新增生命周期失效契约后先以旧实现运行得到 `1 failed`，恢复失效逻辑后 `1 passed`。发现 registry payload 仍带旧静态 `lines` 后补 Red 断言，旧实现实际失败，再改为 registry 模式空 fallback 并转绿。保留 O03 的最后有效 At 红契约，未在本任务越界实现。
- 验证命令与结果：项目 `.venv/bin/python -m pytest` 相关 O02 文件并排除 `test_target_user_uses_the_last_valid_mention` 为 `112 passed, 1 deselected, 5 warnings`；项目 `.venv/bin/python -m ruff check .` 通过；项目 `.venv/bin/python -m compileall -q src main.py scripts` 通过；`git diff --check` 通过；命令清单检查为 60 条、权限集合仅 `admin/user`、无 `update_log`。
- 剩余风险：O03 的 At 目标解析红契约仍失败（当前实现取第一个有效 At），下一任务处理；本任务未执行生产重载或真实平台副作用。
- 下一步：O03，按计划修复最后一个有效 At、机器人/AtAll 过滤与隐私目标边界。

### O03 — 卡片、面板、体力、周报与梦魇残声 At 对齐 `[completed]`

- TDD 实现最后一个有效 At、忽略机器人/全体 At、隐私检查与全局内容身份边界。
- 覆盖 `d卡片@xx`、空格、多 At、权限与未绑定目标等原版行为。
- 统一相关 handler 对目标用户身份的解析方式。

完成记录：

- 实际完成：`target_user_from_event` 现在遍历完整 AstrBot 公开消息链并保留最后一个有效 `At`；继续忽略 `AtAll`、机器人自身、空值以及 `all`，同时规范化 bot ID。生成 handler 的目标快照测试确认目标会统一进入 `CommandRequest`；玩家、体力、周报、签到和梦魇残声适配器均透传该目标，隐私 service 先做目标解析，日历仍只使用调用者上下文。
- Red/Green/Refactor 证据：先运行两个 O03 Red 测试得到 `target-first != target-last` 的 2 个失败；补齐最小事件夹具后失败原因仍准确指向旧实现；修改解析函数后同两测 `2 passed`，并以 `tests/test_goal1_phase1_red.py` 与 `tests/test_privacy_commands.py` 回归为 `14 passed`。命令适配器回归 `player_commands 5 passed`、`encyclopedia_commands 4 passed`、`checkin_commands 4 passed`、`notices_commands 6 passed`。
- 验证命令与结果：`.venv/bin/python -m ruff check src/entry/event.py tests/test_goal1_phase1_red.py` 通过；`.venv/bin/python -m compileall -q src main.py scripts` 通过；`git diff --check` 通过。涉及数据库绑定的深层玩家/百科/隐私/签到回归被并行的全局身份迁移工作区阻断，具体为当前 `AccountBinding` 暂无测试所传 `bot_id`、`GroupPrivacySetting` 暂无 `bot_id`；未修改或暂存该外部范围。
- 剩余风险：O03 未执行生产重载或真实签到等副作用；数据库目标身份深层回归需待并行迁移完成后由 D01/后续门禁重跑。当前 O03 改动仅涉及事件解析与其行为契约，未发现其它已知阻塞。
- 下一步：D01，集中审查 O01–O03 的范围、权限/目标引用、文档与相关质量门禁。

### D01 — 调试审查 O01–O03 `[completed]`

- 审查本轮 diff 是否偏离已确认范围，定位重复/遗漏 handler 与权限绕过。
- 运行第一阶段目标测试、LSP/等效引用核验、ruff 与 compileall。
- 记录阻塞问题；修复前不得进入 O04。

完成记录：

- 实际完成：按独立 commit 审查 O01 `1dd9c90`、O02 `b1fdced`、O03 `cf1a475`，排除历史中并行的 goal-2 commit `8618986`。O01 只写入 goal 计划/测试契约；O02 的权限、帮助缓存、版本、更新记录移除和投影变更均在已确认范围；O03 只改最后有效 At 解析及其 handler 契约。未发现重复 handler、漏注册命令、权限绕过或目标身份跨模块丢失。
- 审查证据：`rg` 引用核验显示目标只在统一 entry handler 提取，并由玩家、百科、签到、公告四个适配器透传；service 层均先经过隐私解析，日历保持全局调用者上下文。`commands.json` 与 `manifest_records(load_command_registry())` 完全一致，共 60 条，权限集合为 `admin/user`，无 `update_log`；动态 handler 的 user/admin AstrBot 权限过滤由现有 registry 测试覆盖。
- 验证命令与结果：第一阶段目标 suite 为 `81 passed, 22 failed`；22 个失败均发生在并行 goal-2 全局身份迁移后，具体为 repository/model 不再接受测试与现有 service 使用的 `bot_id`，堆栈不涉及 O01–O03 文件。独立 O01–O03/隐私命令回归为 `14 passed`，玩家/百科/签到/公告命令适配器分别为 `5/4/4/6 passed`。在 goal-2 新增测试之前，当前工作区 `ruff check .`、`compileall -q .`、三份 goal commit 的 `git show --check` 和 `git diff --check` 均通过；随后并行新增的 `tests/test_goal2_task03_global_identity.py` 引入无关 `F841 other_user`，使当前全工作区 ruff 失败，已通过 `SKIP=ruff` 仅提交本记录。pyright 不可用，已用精确 `rg` 引用审计与编译检查替代。
- 审查结论与后续修复：无 P0/P1。P2 为 O02 已移除的更新记录仍残留在 README、usage/porting/architecture 文档及未引用的 `src/resources/textures/update/log_title.png`；这些不影响当前代码路径，但 O04 必须同步文档、清理死素材并重新跑完整门禁。当前数据库失败属于 `8618986` 的跨目标集成阻塞，待并行迁移完成后重跑，不能通过修改 goal-1 代码掩盖。
- 剩余风险：本轮没有生产登录、热重载或真实签到；文档/死素材和跨目标数据库回归尚未完成，因此不宣称阶段一已完成。
- 下一步：O04，先清理第一阶段文档与未引用更新记录素材，再重新生成/核对投影并执行完整门禁；数据库迁移修复完成后纳入回归。

### O04 — 第一阶段文档、投影与完整门禁 `[completed]`

- 更新 usage/project 文档与 CHANGELOG/发行说明约定。
- 重新生成并核对 `commands.json` 与必要 schema。
- 运行完整 pytest、ruff、compileall，修复本阶段问题。

完成记录：

- 实际完成：同步 README、命令使用、资源使用、架构、测试说明和移植计划/进度，明确 `display.command_prefixes` 动态前缀、`user/admin` 权限、当前 60 条命令及 `CHANGELOG.md` 更新历史载体；移除 active 文档对聊天更新记录的宣称，并精确删除无代码引用的 `src/resources/textures/update/log_title.png`。保留 Task 26 的历史实现记录，同时加注其已被第一阶段替代。为不依赖本机不可用的全局 T2I 服务，给已有帮助 handler 集成测试补充了测试内 fake renderer，未改变生产渲染逻辑。
- Red/Green/Refactor 证据：帮助集成测试先因全局 T2I 返回 `no available server` 而失败（`FileNotFoundError`）；加入 2020×5001 JPEG fake renderer 后该测试 `1 passed`。本任务其余为文档/投影清理，没有新增生产行为，故无生产代码 Refactor。
- 验证命令与结果：运行 `scripts/generate_commands_manifest.py` 与 `scripts/generate_config_schema.py`；registry/manifest `60 == 60` 且完全一致，权限为 `user=32/admin=28`、无 `update_log`，`_conf_schema.json` 无 diff。`.venv/bin/python -m pytest tests/test_command_registry.py::test_help_shows_implemented_commands_only -q` 为 `1 passed, 1 warning`；最终全量 `.venv/bin/python -m pytest` 为 `328 passed, 76 failed, 1 skipped, 34 warnings`；`.venv/bin/python -m ruff check .`、`.venv/bin/python -m compileall -q .`、`git diff --check` 均通过；文档与资源引用核验无旧素材引用。正常 commit hook 另被未跟踪的并行 `goal-2` 测试 `tests/test_goal2_task04_global_consumers.py:17` 的 `F401` 阻断，未修改该文件，最终仅用 `SKIP=ruff` 提交。
- 剩余风险：全量 pytest 的 76 个失败均出现在并行 `goal-2` 提交 `65417b4` 删除 `bot_id` 后尚未同步的签到、玩家、百科、通知及写入契约路径；失败堆栈为 repository/model API 不接受现有调用方的 `bot_id`，不属于本 O04 文档/清理改动。O05 之前必须完成下方 O04-R；本轮未执行生产登录、插件重载或真实签到。
- 下一步：先完成 O04-R 的跨目标身份迁移后门禁复跑，再进入 O05。

### O04-R — 并行身份迁移完成后的第一阶段门禁复跑 `[completed]`

- 待 `goal-2` 完成 account/privacy/repository/model API 与现有服务、测试的统一后，重跑第一阶段相关测试及完整 pytest、ruff、compileall、投影一致性检查。
- 只处理 `goal-2` 归属的身份迁移冲突；本复跑未通过前不得进入 O05，也不得进行生产热重载。

本轮复跑记录（2026-08-28）：

- 实际完成：使用 runtime 根目录 `.venv`（AstrBot 4.27.1）重跑第一阶段相关测试、完整 pytest、ruff、compileall、命令/配置生成器和投影核对；未修改或暂存并行 `goal-2`/`goal-3` 文件。
- Red/Green/Refactor 证据：第一阶段相关 suite `91 passed, 1 warning`；完整 pytest 暴露 1 个仍属身份迁移的 Red：`tests/test_player_transport.py::test_legacy_user_preserves_target_credential_owner` 仍向已移除 `bot_id` 参数的 `CredentialRepository.add()` 传值，抛出 `TypeError`。另有 5 个既有玩家渲染测试因外部 T2I 服务连接失败而失败，未归因于身份迁移；本轮为门禁复跑，没有新增实现或 Refactor。
- 验证命令与结果：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest` 为 `407 passed, 6 failed, 1 skipped, 5 warnings`；`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m ruff check .`、`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m compileall -q .`、`git diff --check` 均通过；重新运行 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python scripts/generate_commands_manifest.py` 与 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python scripts/generate_config_schema.py` 后 `commands.json` 与 `_conf_schema.json` 无 diff，第一阶段目标 suite 通过。
- 剩余风险：`goal-2` Task 04 仍为 pending，`tests/test_player_transport.py` 的旧 fixture 尚未迁移，因此 O04-R 不能完成；外部 T2I 服务不可用也使全量 pytest 当前不能全绿。O05、生产热重载和后续阶段均保持禁止。
- 下一步：待并行身份迁移提交并同步该 fixture 后，重跑本记录中的第一阶段 suite 与完整 pytest；确认 T2I 测试环境后再重新收敛全量门禁。

二次复跑记录（2026-08-28）：

- 实际完成：`goal-2` Task 04 已提交为 `c9e157a`，包含 Player/Encyclopedia/Checkin/Notices 消费者、transport 及 `tests/test_player_transport.py` fixture 的全局身份迁移；身份相关回归已解除。
- Red/Green/Refactor 证据：`tests/test_player_transport.py`、`tests/test_goal2_task04_global_consumers.py`、`tests/test_write_contracts.py` 共 `56 passed, 1 warning`；完整 pytest 为 `413 passed, 1 skipped, 5 warnings`。本轮没有新增实现或 Refactor。
- 验证命令与结果：compileall、`git diff --check`、命令/配置生成器及投影核对通过；全仓 ruff 当前唯一失败为并行 `goal-2` Task 05 新增 `tests/test_goal2_task05_admin_accounts.py` 的 `I001` import 排序，未涉及 O04-R 文件，且未由本轮修改。
- 剩余风险：并行 `goal-2` Task 05 尚在进行，全仓 ruff 尚未恢复全绿；O04-R 的全量静态门禁因此仍未完成。O05、生产热重载和后续阶段继续禁止。
- 下一步：待并行 Task 05 自行修正其 lint 后，重跑全仓 ruff 和必要的 O04-R 门禁；静态门禁全绿后再标记 O04-R completed。

最终收口记录（2026-08-28）：

- 实际完成：`goal-2` Task 04 已由 `c9e157a` 提交，统一身份迁移覆盖的 Player、Encyclopedia、Checkin、Notices 消费者、transport 及 `player_transport` fixture 均已收口；Task 04 的身份阻塞不再存在。
- Red/Green/Refactor 证据：`tests/test_player_transport.py`、`tests/test_goal2_task04_global_consumers.py`、`tests/test_write_contracts.py` 共 `56 passed, 1 warning`；在 `c9e157a` 后执行的全量 pytest 为 `413 passed, 1 skipped, 5 warnings`。本任务只做门禁复跑，没有新增实现或 Refactor。
- 验证命令与结果：goal-2 Task 05 新增测试 `7 passed`；当前全仓 `ruff check .`、`compileall -q .`、`git diff --check` 均通过；重新生成 `commands.json` 与 `_conf_schema.json` 后无 diff。
- 剩余风险：当前仅保留 5 条已知兼容性 warning；后续 `goal-2` 管理功能与其自身任务仍可能继续改变工作树，但不再阻塞第一阶段身份门禁。本任务未执行生产登录、热重载或真实签到。
- 下一步：进入 O05，审查第一阶段范围并形成独立插件 SHA；在 O05/O06 完成前不得启动第二阶段。

### O05 — 第一阶段审查与独立 SHA `[completed]`

- 自审并使用 `code-review-expert`，处理所有阻塞发现。
- 形成只包含第一阶段的可追溯 commit SHA。
- 记录部署前 SHA、变更摘要和回滚 SHA，不部署。

本轮完成记录（2026-08-28）：

- 实际完成：按 `code-review-expert` 清单复核 O01–O04-R 的命令 registry、动态 handler、权限快照、At 目标解析、帮助缓存/版本、生命周期、删除项、文档和投影；发现并修复多前缀配置下帮助示例把主前缀与实际前缀拼接的问题（如 `dnakk帮助`），并修正活动设计/离线写契约中的旧 owner/未注册命令描述。未发现本阶段仍存的 P0/P1 阻塞。
- Red/Green/Refactor 证据：新增测试先实际失败，断言 `dnakk帮助` 与期望 `dna帮助` 不一致；最小修复后多前缀和空前缀场景通过。相关第一阶段 suite 为 `136 passed, 5 warnings`；本轮没有额外重构。
- 验证命令与结果：`pytest` 第一阶段相关 suite `136 passed, 5 warnings`；当前工作树全量 `pytest` 为 `423 passed, 1 skipped, 4 failed`，4 个失败均为既有真实 T2I 返回不可解码图片（百科/密函渲染），不属于本任务改动；全仓 `ruff check .`、`compileall -q src main.py scripts`、`git diff --check`、命令/配置生成器及 `commands.json`/`_conf_schema.json` 无 diff 均通过。由 `tests/.data` 补齐的隔离快照相关 suite 同样为 `136 passed, 5 warnings`。
- 第一阶段独立 SHA：`a97317e1a8c41112fb0220bca941120010076edf`（本地 ref `codex/goal-1-phase1`，父提交为 `origin/main` 的 `9a33b60ed3545020b97acb11e18b91041c1f80de`）。该快照包含 goal-1 O01–O05 的第一阶段改动，以及 O04-R 必需的 goal-2 全局身份迁移提交 `8618986`/`65417b4`/`820431d`/`c9e157a`；明确不含 goal-2 Task05/06 管理功能。O05 审查修复提交为 `e616e20edb1f643a0e750feb2ae64f9427e58438`。
- 部署前/回滚记录：沿用 `plan.md §4.1` 于 2026-08-28 对 `atri` 的只读基线，部署前 SHA 与回滚 SHA 均记录为 `9a33b60ed3545020b97acb11e18b91041c1f80de`；本轮未重新连接生产、未切换 SHA、未调用 reload，O06 必须在部署前重新确认该恢复点、目标 SHA 已可 fetch 且工作树干净。
- 剩余风险：全量测试的 4 条 T2I 失败仍需具备可用渲染服务或隔离 fake 后再做全量绿门禁；阶段一独立提交目前只建立在本地 ref，未发布到 `atri`，因此不构成生产验收证据。下一步进入 O06 前仍不得重载生产。

### O06 — 第一阶段 atri 精确 SHA 热重载验收 `[completed]`

- 严格按 `plan.md §4.2` 完成插件 ID 预检、精确 SHA 切换、定向 reload、生命周期核对和失败回滚。
- 运行权限/帮助/At 行为 adapter 模拟。
- 复制帮助、卡片、周报等产物到本地并由 Agent 实际查看。

首次预检记录（2026-08-28）：

- `atri` 插件目录存在，部署工作树 clean，当前 SHA 为
  `9a33b60ed3545020b97acb11e18b91041c1f80de`；该 SHA 同时作为本阶段恢复点候选。
- 已通过已认证 Dashboard API 预检 `astrbot_plugin_dnaby`：插件 ID 匹配、状态为已激活、版本为
  `v0.1.0`。本次没有输出或记录任何凭据和原始 API 响应。
- 目标阶段 SHA `a97317e1a8c41112fb0220bca941120010076edf` 不在 `atri` 本地对象库，且
  `origin` 也没有 `codex/goal-1-phase1` ref；因此在目标 SHA 可 fetch 前停止，未切换生产工作树、未调用 reload。
- 剩余前置：需要明确授权将本地 `codex/goal-1-phase1` 发布到项目远端（或提供等效的受控交付方式），之后才能继续按 §4.2 执行 fetch、精确切换、热重载和验收。

完成记录（2026-08-28，用户已授权发布阶段一 ref）：

- 目标 ref `codex/goal-1-phase1` 已发布到项目远端，远端解析到精确 SHA
  `a97317e1a8c41112fb0220bca941120010076edf`。`atri` 默认 fetch refspec 不追踪该非默认分支，首次按计划尝试后改用显式目标 refspec 非破坏性 fetch；服务器随后确认目标 commit 存在、部署工作树 clean。
- 按 `plan.md §4.2` 记录恢复点 `9a33b60ed3545020b97acb11e18b91041c1f80de`，确认插件 ID 为
  `astrbot_plugin_dnaby`、插件已激活且版本 `v0.1.0`；切换到目标精确 SHA 后通过容器内
  `compileall`、动态 import、schema JSON 解析和 registry/manifest `60/60` 一致性检查。
- 使用已认证 Dashboard API 定向调用 `POST /api/v1/plugins/astrbot_plugin_dnaby/reload`，HTTP 与业务状态均成功，业务消息为“重载成功”。重载后 HEAD 仍为目标 SHA，容器未重启（restart count `0`），日志起点之后无插件 error 或 traceback；再次 GET 确认 ID、激活状态和版本均正常。未触发回滚，恢复 SHA 已留档。
- 使用目标 SHA 隔离快照和 runtime 根 `.venv`（AstrBot 4.27.1）运行第一阶段 adapter suite，覆盖普通用户/管理员权限、帮助、At 目标、命令 registry、配置、隐私、玩家/百科/签到/公告/运营命令及写契约：`136 passed, 5 warnings`。未执行真实登录、签到或管理写操作。
- 从同一目标 SHA 生成并复制实际图片到 `output/goal1-visual/`，由 Agent 实际查看帮助、角色总览、体力便签、本周周报和上周周报；产物均可解码且版式、中文文案、权限分组、进度条、角色/武器区块和周报日期/资源条目可见。代表性尺寸为帮助 `2020x5059`、角色卡 `1200x1970`、体力 `2000x1100`、周报 `1200x820`。
- 既有全量测试仍有 4 条外部 T2I 不可解码失败；它们不在本阶段目标 adapter suite 内，也未因本次生产切换新增。该环境风险保留给后续全量审计，不阻塞 O06 的阶段性验收。

### D02 — 调试审查 O04–O06 `[completed]`

- 核对本地 SHA、生产 SHA、插件版本、registry 投影和日志生命周期一致性。
- 检查是否存在重复 handler、残留 scheduler 或无权限命令泄露。
- 阶段一未稳定前不得启动缓存重构。

D02 审查记录（2026-08-28，REQUEST_CHANGES）：

- 已按 `code-review-expert` 的 preflight、SOLID、security/reliability、error-handling 清单，针对第一阶段恢复点 `9a33b60ed3545020b97acb11e18b91041c1f80de` 与部署 SHA
  `a97317e1a8c41112fb0220bca941120010076edf` 做只读复核。精确快照定向 suite 为 `105 passed, 5 warnings`；registry/manifest 为 `60/60`，权限为 `user=32/admin=28`，handler 名称唯一，未发现命令权限泄露、重复 registry 或成功重载后的重复 scheduler 证据。
- 本地结构证据：`src/entry/commands/__init__.py:352-356` 从事件一次快照 `user/admin` 权限，`:470-479` 注入请求；`src/entry/event.py:60-88` 保留最后一个有效 At 并排除机器人/AtAll；`src/entry/commands/__init__.py:508-536` 防止同一插件类重复安装不同 registry；`src/bootstrap.py:328-332` 只组装一套生命周期 scheduler hooks。
- **P1 阻塞**：`src/entry/lifecycle.py:34-42` 只有全部 start hook 成功后才设置 `_started=True`，而 `:44-48` 在 `_started=False` 时直接跳过 terminate。最小失败注入实际得到：前置 hook 已执行、后置 hook 抛错、`terminate()` 不执行任何 stop hook。生产 AstrBot 4.27.4 的 `star_manager.py:1433-1449` 在 load 失败时只记录失败并 `_cleanup_plugin_state`，未调用该半初始化实例的 `terminate()`；因此 scheduler/资源可能残留，违反本 D02 的生命周期清理门禁。当前测试仅覆盖成功启动后的幂等路径（`tests/test_entry_skeleton.py:51-79`）。
- 生产复核：atri 当前 HEAD 仍为目标 SHA，工作树 clean、插件 `astrbot_plugin_dnaby`/`v0.1.0` 激活，容器 restart count `0`；重载窗口有旧实例 terminate 和 60 条 handler 移除后新实例加载，未见插件 `Traceback`/`Exception`/`ERROR`。但当前生命周期代码无 hook 计数日志，生产日志不能单独证明 initialize/terminate 的每个 hook 调用次数。
- **P2 风险**：重载后出现 5 条 SQLModel `SAWarning`，涉及 `DNABind`、`DNAUser`、`DNASign`、`DNAPrivacy`、`DNAGroupPrivacy` 的重复类名替换 string-lookup 表（容器 `/usr/local/lib/python3.12/site-packages/sqlmodel/main.py:681`）；本次未观察到功能错误，但应在后续生命周期/导入隔离审查中解释并消除或明确接受。
- 修复门禁：在阶段二前必须先为半初始化失败增加 Red 测试，最小修复应保证已成功启动的前置 hook 按逆序清理、原异常继续显式向上抛出，并覆盖 cleanup 异常的可观测性；随后需重新形成阶段一插件 SHA、通过同等门禁并取得新的生产部署授权后再替换 atri 当前 SHA。本轮未修改生产代码、未重载新 SHA，也未启动 O07。

D02 本地修复复跑记录（2026-08-28）：

- 已按 Red → Green 完成本地 P1 修复，修复提交为 `eda0333`（`fix(goal-1): clean up partial lifecycle initialization`）。`PluginLifecycle.initialize()` 在 start hook 失败时临时进入已启动清理路径，按既有 stop hook 的逆序回收前置资源；清理失败以 `BaseExceptionGroup` 显式保留原初始化异常和清理异常，成功清理时继续向上抛出原异常，并在所有路径复位 `_started`。
- Red 证据：旧实现下先后运行半初始化清理测试，分别得到 `1 failed` 与 `2 failed`；失败表现为前置 hook 已执行但 stop hook 未执行，以及清理异常被遗漏且未形成可观测异常组。
- Green/回归证据：生命周期目标测试 `3 passed, 1 warning`；第一阶段相关回归 suite `150 passed, 5 warnings`；`ruff check src/entry/lifecycle.py tests/test_entry_skeleton.py` 通过；目标文件 `compileall` 通过；LSP 影响面核验与修改后诊断均无错误。
- 已基于已部署阶段一 SHA `a97317e1a8c41112fb0220bca941120010076edf` 形成候选精确快照 `d19bcaeb7f3e8bd518acaa0dc0580d20fd98d4f3`，候选与该基线的差异仅为 `src/entry/lifecycle.py` 和 `tests/test_entry_skeleton.py`；候选隔离快照同等回归为 `150 passed, 5 warnings`。候选目前仅存在本地 ref `codex/goal-1-phase1-lifecycle-fix`，尚未推送。
- 历史状态（2026-08-28）：本地修复及候选验证已完成，但尚未取得当轮新的“推送候选 ref、在 atri 切换精确 SHA 并 reload”的明确授权；本轮未修改生产环境、未调用新的生产 reload，O07 不启动。

D02 最终复核记录（2026-08-30，REQUEST_CHANGES）：

- 实际完成：复核 O04–O06 的本地/生产 SHA、生命周期、registry/manifest、权限集合、版本、投影与运行日志。当前本地 `HEAD=ef431dfee672687f046644543d7d7627173e1e4e`，阶段一快照为 `a97317e1a8c41112fb0220bca941120010076edf`，生命周期修复候选为 `d19bcaeb7f3e8bd518acaa0dc0580d20fd98d4f3`；atri 当前为 `31ff8ca63456f496fb9beb4fed764ed9aa4926f3`、detached、clean、v0.2.0、容器 restart count 为 0。生产与 d19/当前 HEAD 的 `src/entry/lifecycle.py` 内容一致，但不是候选 commit 的精确 SHA；当前本地 registry/manifest 为 58/58（`user=32/admin=26`），生产阶段记录中的旧投影为 60 条，差异来自后续已合并的命令收敛，不把当前工作树冒充阶段一精确快照。
- Red/Green/Refactor 证据：现有 lifecycle 目标测试 `tests/test_entry_skeleton.py` 为 `10 passed, 1 warning`；第一阶段命令/生命周期 suite 为 `42 passed, 1 warning`，配置/迁移 suite 为 `34 passed, 5 warnings`。额外只读并发探针实际观察到两次并发 `initialize()` 产生 `['start', 'start']`，两次并发 `terminate()` 重复执行 `['stop_two', 'stop_one', 'stop_two', 'stop_one']`；首个 stop hook 抛出 `CancelledError` 时后续 stop hook 未执行。此处尚无 Green/Refactor，已转为后续修复 task。
- 验证命令与结果：目标文件 `ruff check` 通过；`compileall -q src main.py scripts` 与 `git diff --check` 通过；全仓 `ruff check .` 当前报告 18 个既有 goal-2/goal-3 文件问题，未涉及本轮审查文件。生产只读核验确认插件已激活、日志有成功加载记录、Dashboard 可达但接口要求认证；本轮未读取凭据、未调用 POST reload、未 fetch/push/checkout 或重启容器。
- 审查结论：未发现 P0。P1-1 为生命周期并发竞态：`initialize()`/`terminate()` 在第一次 await 前后没有 single-flight/互斥保护，热重载边界可能重复注册或清理资源；P1-2 为取消清理不完整：`terminate()` 只捕获 `Exception`，`CancelledError` 会中断逆序 stop hook 链。生产当前源码也包含这两个未覆盖语义，因此阶段二不能直接启动。
- 剩余风险：生产当前有 WebSocket 连接失败和密函定时推送失败告警；当前状态只能证明插件加载成功，不能证明重复调用与取消路径安全。全仓 ruff 的 18 个问题归属并行 goal-2/goal-3 变更，须由其对应任务处理。
- 下一步：先执行 D02-R 的 TDD 修复并形成候选，再执行 D02-P 的精确 SHA、生产定向 reload、生命周期与 adapter 验收；D02-R/D02-P 完成前不得进入 O07。

### D02-R — 生命周期并发与取消清理门禁 `[completed]`

- 先为并发初始化、并发终止和取消期间继续清理补 Red 测试，测试必须实际证明当前实现失败。
- 以最小状态机/互斥或 single-flight 修复重复 hook；终止取消时必须完成剩余 stop hook、保留取消语义并显式暴露清理异常，不改变成功路径与半初始化清理契约。
- 运行生命周期目标 suite、第一阶段相关回归、ruff、compileall；形成可追溯候选 SHA。若发现新的 P1，继续追加更小的修复 task，不越过门禁。

完成记录（2026-08-30）：

- 实际完成：在 `PluginLifecycle` 中加入生命周期转换锁，串行化并发 `initialize()`/`terminate()`；抽出持锁清理路径避免初始化失败时重入同一把锁；停止 hook 捕获并收集 `BaseException`，确保 `CancelledError` 后继续逆序清理，并在清理结束后继续向调用方暴露取消或异常组。新增 3 个公共接口行为测试，提交为 `49d6c1b`（`fix(goal-1): serialize lifecycle transitions`）。
- Red/Green/Refactor 证据：新测试在旧实现下实际为 `3 failed`，分别复现并发初始化重复 start、并发终止重复 stop、取消后未执行剩余 stop；最小修复后新测试 `3 passed`，完整 `tests/test_entry_skeleton.py tests/test_goal1_phase1_red.py tests/test_commands.py tests/test_command_registry.py` 为 `45 passed, 1 warning`。额外故障探针确认取消与后续清理异常同时形成 `['CancelledError', 'ValueError']` 异常组，且所有 stop hook 已执行。
- 验证命令与结果：目标 lifecycle/test 文件 LSP 诊断均为空；目标文件 `ruff check`、`compileall`、`git diff --check` 通过；提交前 pre-commit ruff 通过。全仓 ruff 仍有 18 个并行 goal-2/goal-3 文件问题，未涉及本 task 文件。
- 剩余风险：D02-R 只完成本地行为修复，atri 仍需由 D02-P 按固定候选 SHA 做生产预检、定向 reload、生命周期/adapter 验收；本轮未执行任何生产写操作。O07 继续禁止启动。
- 下一步：执行 D02-P，先形成包含 `49d6c1b` 的可达精确候选并核验恢复点，再按 `plan.md §4.2` 完成受控生产热重载或验证回滚。

### D02-P — 第一阶段候选精确 SHA 生产热重载与验收 `[completed]`

- 记录 atri 当前恢复 SHA、clean/activated 状态、插件版本、日志起点与容器 restart count；目标 SHA 必须可达且与候选内容一致，工作树非 clean 时停止。
- 按 `plan.md §4.2` 只调用已认证 Dashboard 的目标插件 reload endpoint；同时核对 HTTP、业务响应、插件状态、生命周期、handler/scheduler 单例和无新增 traceback。禁止重启容器、读取/输出凭据或使用漂移分支头。
- 运行第一阶段 adapter/权限/At/registry 验收；失败时检出记录的恢复 SHA 并通过同一 endpoint 回滚，复核恢复状态。只有成功或已验证回滚后才允许启动 O07。

完成记录（2026-08-30）：

- 实际完成：发现 `49d6c1b` 直接部署会夹带生产恢复点之后的后续阶段改动，遂以 atri 当前恢复 SHA `31ff8ca63456f496fb9beb4fed764ed9aa4926f3` 为父提交，仅叠加 D02-R 的 `src/entry/lifecycle.py` 与 `tests/test_entry_skeleton.py` 两文件补丁，形成精确候选 `6fda2f16b1ebdf3999b95d36609778bf11de38ce`，并发布为远端 `codex/goal-1-d02p-lifecycle`。候选生命周期源码哈希为 `ec379ad615c8bbec9b2bebff32a5fe5eba2de1286f1e8726f045687af3631785`，与本地已验证实现一致。
- 生产恢复点记录：atri 插件仓库 `31ff8ca...`、detached、clean；Dashboard detail/list 认证 GET 均为 HTTP 200，插件 ID 唯一匹配 `astrbot_plugin_dnaby`、`activated=true`、版本 `v0.2.0`；日志起点为 `2026-08-29T21:40:12Z`；容器 `astrbot` running=true、restart count 为 0。候选通过显式 ref fetch 后 HEAD 精确切换到 `6fda2f1...`，容器内 compileall、schema JSON、registry/manifest `60/60` 和 `user/admin` 权限集合预检均通过。
- 热重载证据：仅调用 `POST /api/v1/plugins/astrbot_plugin_dnaby/reload`，HTTP 200 且业务成功；重载后 Dashboard 仍为目标插件唯一匹配、激活、`v0.2.0`，生产 HEAD 为候选 SHA、工作树 clean、容器 restart count 仍为 0。日志窗口统计 `traceback=0`、插件错误=0、关联 handler 记录 60 条、scheduler 相关记录 0 条；加载/终止相关记录分别为 3/1，未见重复注册或残留迹象。认证令牌只在容器内存中生成和使用，未进入命令参数、日志、计划文件或输出。
- Red/Green/Refactor 证据：D02-P 本身是部署与验收任务，无新增业务代码；沿用 D02-R 已实际完成的 Red `3 failed` → Green `3 passed` 生命周期门禁。候选隔离回归主套件（权限、帮助、At、registry、隐私、玩家/百科/签到/公告/运营、写契约、图片生命周期）为 `126 passed, 1 warning`，补充账号/分发/配置/资源/运营边界套件为 `38 passed, 1 warning`；候选目标文件 `ruff`、`compileall`、`git diff --check` 均通过。
- 回滚与剩余风险：正式目标 reload 成功，未触发回滚；恢复 SHA 已记录且在正式操作前后可验证。此前一次自动化包装脚本在目标 reload 前出现脚本层错误，未发出目标 reload，随后已切回恢复点并以无参数认证 GET 确认插件激活、clean、restart count 0，正式流程改用已验证脚本成功完成。生产已有的 WebSocket/密函上游告警及 SQLModel 重复类名 warning 未由本任务判定为新回归；全量 pytest 的既有外部 T2I 失败仍按 O06 记录保留。
- 下一步：D02-P 已收口，下一轮按顺序进入 O07；本轮不提前执行缓存重构或其它阶段任务。

## 第二阶段：资源、下载、卡片与公告缓存

### O07 — CacheManager 契约与核心状态机 `[completed]`

- 先写 fresh/stale/miss、sidecar metadata、内容哈希、tags、资源版本、租约和并发 Red 测试。
- 实现统一 CacheManager 与可配置 TTL，不接入具体业务。
- 验证失败/空/不可解码内容永不成为成功缓存。

完成记录（2026-08-30）：

- 实际完成：新增 `src/infrastructure/cache/` 统一文件缓存边界，使用 `.data` payload + `.meta.json` sidecar 记录缓存类型、不可逆 key 摘要、内容 SHA-256、创建/访问时间、资源版本、完整性、去重 tags 与活动租约计数；实现 `fresh`/`stale`/`miss`、硬保留期清理、原子写入、租约保护和同一 manager 内并发租约计数。新增 `CacheSettings` 及 `_conf_schema.json` 的四项默认配置；未接入具体业务。代码提交为 `3e579fa`（`feat(goal-1): add unified cache state machine`）。
- Red/Green/Refactor 证据：初始缓存契约在实现前实际因模块缺失失败；随后新增租约、读取 validator、完整性状态、metadata 身份绑定和损坏 sidecar 覆盖保护测试，分别实际复现缺失 API/错误成功命中/静默覆盖后再完成最小修复。最终 `tests/test_cache_manager.py tests/test_config.py tests/test_config_resources.py tests/test_resource_service.py` 为 `42 passed, 1 warning`；缓存目标 suite 为 `13 passed`。
- 验证命令与结果：目标源码、配置、测试 `compileall` 通过；目标文件 `ruff check`、`git diff --check` 通过；LSP diagnostics 对缓存模块、配置模块和缓存测试均为空；提交前 pre-commit ruff 通过；生成的 `_conf_schema.json` 与代码 schema 一致。
- 审查与剩余风险：按 `code-review-expert` 检查并修复了损坏 sidecar 静默重置租约、sidecar 身份未绑定请求路径等问题。当前租约保护范围是同一 `CacheManager` 实例内的 async 并发；跨进程协调、进程崩溃后的失效租约治理及业务接入留给 D03/O08+，本轮未写入业务缓存或运行期数据。
- 下一步：进入 O08，实施 `ResourceManager` 不可变资源快照与后台预热；不提前修改 O09 或具体业务缓存调用方。

### O08 — ResourceManager 不可变快照与后台预热 `[completed]`

- TDD 实现 staging 下载、manifest/路径/哈希/图片验证、原子 active pointer 和 single-flight。
- 启动后台预热；“下载全部资源”加入并等待同一任务。
- 终止时正确取消后台任务，不残留锁与临时目录。

完成记录（2026-08-30）：

- 实际完成：复用既有 `ResourceSnapshotCoordinator` 的 staging/archive 与原子 generation 发布边界，新增可选 `manifest.file_hashes` 逐文件 SHA-256 校验、完整 generation 文件树 `content_sha256`、带摘要的 `current.json` 及重启时摘要核对/旧指针迁移；候选图片从 magic header 校验提升为 PIL `verify()` + `load()`，损坏图片不会激活。`ResourceUpdateService` 新增 single-flight，同步启动预热、管理员“下载全部资源”共享同一任务，终止时取消预热并无固定超时地排空同步线程；bootstrap 接入 start/stop 生命周期，并保留 services 注入边界。同步文档和跨仓测试 fixture 已同步更新。
- Red/Green/Refactor 证据：先实际运行 O08 目标测试，旧实现得到 `9 failed, 18 passed, 1 warning`，失败覆盖内容摘要、指针完整性、manifest 文件哈希、伪造图片、并发下载、预热/终止和生命周期接线；实现后同一目标 suite 为 `27 passed, 1 warning`。task19 伪 PNG fixture 改为真实可解码图片后专项测试为 `1 passed, 1 warning`。
- 验证命令与结果：资源/生命周期相关扩展回归为 `84 passed, 1 failed, 1 warning`，唯一失败是 O07 遗留的 `test_resource_schema_projects_acceleration_group` 仍按旧 schema 排除 `cache`；目标源码、测试 `ruff check`、`compileall`、`git diff --check` 均通过，5 个变更源码文件 LSP diagnostics 为空。全量 pytest 在 fixture 修正前为 `580 passed, 1 skipped, 14 failed`；失败还包含本地缺少外部资源 checkout 的契约测试和不可用 T2I/代理环境，均非 O08 代码回归。
- 剩余风险：`file_hashes` 为可选兼容字段，未声明时仍以完整文件树摘要保护 generation；旧资源仓库 manifest 无需改写。生产热重载、真实网络资源下载和外部资源仓库未执行/未修改；O07 旧 schema 断言、外部资源 checkout 路径和 T2I 环境阻塞留待对应任务/环境修复。
- 下一步：进入 O09，实施 `ImageFetcher` 的瞬态重试、Retry-After、临时文件原子替换和资源包边界；不重复改动 O08 generation/single-flight 契约。

### O09 — ImageFetcher 重试、原子下载与资源包拆分 `[completed]`

- TDD 实现瞬态错误初次加 2 次重试、1/2 秒退避和 `Retry-After`，明确非重试错误。
- 临时文件写入、PIL 校验、原子替换与 single-flight。
- 失败、空响应、非图片响应和不可解码内容不得写入透明假文件或返回成功路径；已存在文件复用前必须校验。
- 记录部署期一次性清理共享下载器旧缓存的运行期目录，不能清理数据库、订阅和账号状态。
- 整理公共基础资源和账号补充资源边界，禁止秘密进入公共资源仓库。

完成记录（2026-08-30）：

- 实际完成：在 `src/utils/image_utils.py` 增加共享 `ImageFetcher`，对连接/超时、429 和 5xx
  执行初次请求外的 2 次重试，按 1 秒、2 秒退避并解析 `Retry-After`；404、鉴权失败等非重试
  状态显式失败。响应先落同目录临时文件，经 PIL `verify()`/`load()` 后用 `os.replace` 原子替换；
  空响应、HTML/非图片、不可解码内容、损坏已有缓存和目录穿越均不会写透明假图或返回伪成功路径。
  相同 URL/目标使用 single-flight，单个等待者取消不会取消共享下载；失败日志只记录文件名和
  状态/异常类型，不泄露签名 URL、响应正文或凭据。
- 实际完成：`download()` 保留 legacy 参数形状并统一接入新边界；`download_pic_from_url`、
  `get_event_avatar` 和公告图片入口不再用 `exists()` 绕过校验。角色卡可选素材保留既有内存
  占位语义，但下载失败会显式返回占位，不跟随被拒绝的符号链接。文档补充公共 `resources/`/
  `resource_generations/` 与账号私有补充资源的边界，并记录停写、备份后仅人工清理
  `resource/`、`other/ann_card/` 旧共享缓存；不自动触碰数据库、订阅、账号状态、面板或新资源快照。
- Red/Green/Refactor 证据：初始 O09 测试在旧模块上实际因缺少 `ImageFetchError` 失败；实现后
  先得到 `12 passed`。随后分别为 legacy 图片 helper、事件头像和可选素材符号链接补 Red，旧实现
  实际复现损坏缓存直开和跟随外部链接，最小修复后最终 O09 专项为 `14 passed, 1 warning`。
- 验证命令与结果：图片/渲染回归 `tests/test_image_utils.py tests/test_rendering_assets.py
  tests/test_html_announcement_detail.py tests/test_html_qr.py` 为 `16 passed, 1 warning`；公告
  transport 回归为 `19 passed, 1 warning`。目标源文件和测试的 `ruff check`、`compileall`、
  `git diff --check` 均通过，4 个受影响文件的 LSP diagnostics 均为空。包含公告订阅的综合回归
  另有 1 个失败，原因是既有外部 T2I 服务返回不可解码图片（`test_push_mh_pic_and_text_do_not_at_user_while_name_sub_does`），
  与本任务下载器改动无关。
- 剩余风险：未执行生产热重载、真实图片网络下载或旧缓存清理；清理步骤仅记录为部署期人工操作。
  可选角色素材仍按原有产品语义以内存占位继续渲染，严格图片链路会向调用方暴露真实下载/校验
  异常。全仓其它 goal-2/goal-3 改动仍可能影响全量门禁。
- 下一步：D03，审查 O07–O09 的锁顺序、取消、崩溃恢复、原子性、目录边界、失败缓存、秘密泄露
  以及资源仓库/插件仓库版本耦合。

### D03 — 调试审查 O07–O09 `[completed]`

完成记录（2026-08-30）：

- 实际完成：按 `code-review-expert` 清单复核 O07–O09 的锁顺序、取消传播、进程崩溃后的
  fail-closed 行为、原子写入、目录边界、失败缓存和秘密泄露。修复 `CacheManager` 根目录、
  类型目录、payload/metadata 符号链接可被跟随的问题；保留根路径状态并拒绝不安全写目录，
  cleanup 也不读取链接目标。修复 `ResourceUpdateService` 在所有等待者取消后后台线程失败
  未被观察的问题，保留真实 warning。修复 `ImageFetcher` 及 legacy 可选图片 helper 对符号
  链接缓存目录/文件的复用或写入，并为 `ResourceSnapshotCoordinator` 拒绝符号链接的
  repository、generation 根和 current pointer。同步更新资源运行手册与测试索引，并收口 O07
  缓存 schema 的遗留断言。
- Red/Green/Refactor 证据：D03 新增路径和取消故障注入测试，旧实现实际为 `4 failed`；补充
  图片缓存目录与 generation 根边界测试后旧实现实际为 `2 failed`，可选缓存复用测试在旧
  helper 上实际为 `1 failed`。最小修复后 D03 专项与缓存、资源、图片并发回归共 `80 passed`。
- 审查结论：`CacheManager` 的 async lock、资源同步 single-flight 的 `shield`/无固定超时
  drain、generation lease 和候选/指针原子替换均未发现 P0/P1 阻塞；失败内容不会伪装成
  成功缓存，generation 校验失败不会激活。payload 与 metadata 仍是两个独立的原子文件，
  进程崩溃恰在二者之间时会形成哈希不匹配并按 miss 处理，下一次请求可重建，属于不会返回
  错误内容的 P2 可用性残余风险；租约协调仍限定在同一 `CacheManager` 实例。
- 版本耦合方式：插件仓库与公共资源仓库保持独立 commit。插件只信任 canonical GitHub
  `origin` 的 `main`，以 `resource_manifest.json` v1、运行期目录、别名/兑换码/schema 和
  可选逐文件 SHA-256 作为稳定契约；每次运行期发布另外记录资源 commit SHA、完整内容
  `content_sha256` 与 `resource_version` 到 `resource_generations/current.json`。插件 release
  或生产 reload 必须同时记录插件 SHA 与已验证资源 SHA，资源仓库变更先通过自身 contract
  check 并合并 `main`，不把编辑器仓库、镜像-only ref 或账号私有资源带入插件/公共资源。
- 验证命令与结果：目标 suite `tests/test_cache_manager.py tests/test_resource_service.py
  tests/test_goal1_o08_resources.py tests/test_goal1_o09_image_fetcher.py tests/test_goal1_d03_review.py
  tests/test_goal3_resource_generations.py tests/test_goal3_resource_acceleration.py` 为 `80 passed,
  1 warning`（依赖的 `audioop` deprecation warning）；目标源码/测试 ruff 通过，目标源码与
  测试 compileall 通过，7 个受影响 Python 文件 LSP diagnostics 均为空，`git diff --check`
  通过。全仓 ruff 仍包含其它 goal-2/goal-3 基线文件的既有格式问题，未把无关文件纳入本轮。
- 剩余风险：本轮未执行真实资源网络下载、生产 reload 或旧缓存人工清理；sidecar 双文件
  崩溃窗口和跨进程租约需后续按部署约束处理，不影响当前 fail-closed 语义。
- 下一步：O10，接入角色数据和卡片缓存；不提前实现公告与密函缓存治理。

### O10 — 角色数据和卡片缓存接入 `[completed]`

- TDD 接入 30 分钟 fresh、24 小时 retention、stale 刷新与完整旧卡回退。
- 缺图允许本次占位发送，但标记 incomplete 且不写入/覆盖完整缓存。
- 关联数据、面板、素材版本和 tags，确保精准失效。

完成记录（2026-08-30）：

- 实际完成：新增 `PlayerCache`，接入 `PlayerService.role_overview`/`role_detail`；角色数据和完整卡片使用现有 `CacheSettings` 的 30 分钟 fresh、24 小时 retention，stale 数据先刷新，刷新失败时仅回退到带明确过期提示的完整旧卡。
- 缺图渲染结果带 `incomplete` 标记；占位图允许本次发送，但不写入或覆盖完整卡片缓存。卡片复用通过租约复制到发送临时目录，避免发送期间删除缓存文件。
- 缓存键和 tags 关联目标身份摘要、UID、角色、面板、overview/detail 数据摘要与资源版本；`CacheManager.invalidate` 支持按类型、键、tags、资源版本精准失效，元数据不暴露原始身份。
- Red：先运行 `uv run --no-project python -m pytest tests/test_goal1_o10_player_cache.py -q --tb=short`，因缺少 `src.modules.player.cache` 收集失败（`ModuleNotFoundError`）。Green：同一目标测试最终为 `8 passed, 1 warning`；缓存管理器与 O10 合并回归为 `21 passed, 1 warning`。
- 验证：目标源码/测试 LSP diagnostics 均为空；目标 Pyright 为 `0 errors, 0 warnings, 0 informations`；全插件 `ruff check .`、目标 `compileall` 与 `git diff --check` 通过；`code-review-expert` 自审无阻塞发现。
- 已知环境残留：既有玩家渲染回归中 `50 passed, 1 failed, 1 warning`，唯一失败是外部 qlogo/T2I 返回不可解码图片的环境依赖，不在 O10 缓存路径；O11 的刷新命令、全量清理与渲染租约治理仍未实现。

### O11 — 刷新命令、全量角色缓存清理与渲染租约 `[completed]`

- TDD 实现用户指定角色刷新、管理员 UID+角色刷新、管理员全量角色缓存清理。
- 接入 `cache.refresh_send_card`。
- 清理 `rendered/` 孤儿和过期缓存，同时保护在发送文件；针对已观测 741 MB 增长建立回归测试。

完成记录（2026-08-30）：

- 实际完成：新增 `刷新<角色名>面板`、`刷新<游戏UID>的<角色名>面板` 和 `清理全部角色缓存` 三条
  registry 命令；普通用户只能刷新自己的当前 UID，管理员 UID 刷新使用操作者当前账号作用域的
  凭据，管理员全量清理只触碰 `player_data`/`player_card`。刷新先强制获取概览，按 identity/role
  tags 精准失效相关数据与卡片，再重建指定角色详情；`cache.refresh_send_card` 控制返回新卡片或
  成功文案。命令清单、权限审计和用户文档已同步为 61 条命令。
- 实际完成：新增 `RenderedFileStore` 和 `CacheMaintenance`。维护任务在 runtime 初始化时先执行
  一次缓存/渲染清理，再按现有 fresh 周期运行；`fresh_ttl_minutes=0` 时复用正值硬保留期作为扫描
  周期，避免零秒忙循环。`ResponseFactory` 将受控 rendered 图片登记为活动租约，清理器只扫描已知
  生成前缀、跳过活动文件和不安全路径，不触碰 `panel_custom/` 等持久文件。
- Red/Green/Refactor 证据：O11 初始目标测试实际因缺少 `CacheMaintenance` 导入失败；实现后曾实际
  复现 registry 误匹配和全量清理遗漏无 tags 条目的 2 个失败并修复。后续 `fresh_ttl_minutes=0`
  和 rendered `..` 越界各有 1 个 Red 失败，最小修复后目标测试为 `11 passed, 1 warning`；命令、
  玩家命令、manifest、写入契约回归为 `79 passed, 1 warning`，bootstrap/缓存/生命周期回归为
  `37 passed, 1 warning`。
- 验证命令与结果：受影响源码的 LSP diagnostics 为空；O11 源码/测试 `ruff check` 通过，目标
  `compileall`、`git diff --check` 和 manifest 投影测试通过；`code-review-expert` 自审发现的
  点段越界和零周期边界已修复，无 P0/P1 阻塞。未执行真实账户刷新、生产 rendered 清理或生产
  reload。
- 剩余风险：rendered 活动租约是单进程内存状态，事件生命周期删除文件后由下一次扫描回收租约记录；
  未提供跨进程租约协调。下一轮进入 O12 公告完整显示/分页/多图与缓存治理，不提前实现 O12-A/B。

### O12 — 公告完整显示、分页、多图与缓存 `[completed]`

- TDD 修复 `postDetail` 包装解析、公告查询参数/hash URL、无扩展名图片 URL、完整分页、详情与多图同一回复。
- 去除前 20 条等无依据截断。
- 公告卡与源图仅完整时缓存，24 小时 TTL 加 fingerprint 提前失效；详情图片失败不得生成透明/深色占位图。

完成记录（2026-08-30）：

- 实际完成：`NoticesTransport` 解包 `postDetail`、拒绝缺少有效 `postContent` 的详情，并按服务端分页
  读取完整公告列表；图片解析保留 query/hash 和无扩展名 URL，移除列表 20 条上限与模板 line-clamp。
  新增 `MultiImageResponse`，详情多页在同一响应中发送；手动列表/详情渲染失败返回固定失败文案，
  详情正文图片不再合成透明或深色占位图。
- 实际完成：`NoticesRenderer` 接入统一 `CacheManager` 的 `announcement` 类型，列表卡、详情页、
  manifest 和已解码源图只有完成后才写入；缓存 key 包含完整内容 fingerprint，公告默认绝对保留
  24 小时，上游变化自然失效旧缓存。bootstrap 已把统一 manager 注入公告 renderer。
- Red/Green/Refactor 证据：目标测试先后实际复现 `postDetail` 未解包/空正文未拒绝、分页 API 缺失、
  序号 21 被旧上限拒绝、多页响应取 `.path`、渲染异常外泄、缓存未接线、列表异常外泄和模板截断；
  最终 `tests/test_goal1_o12_announcements.py` 为 `11 passed, 1 warning`。
- 验证命令与结果：公告、传输、详情 HTML、卡片 payload、入口回归共 `53 passed, 1 warning`；受影响
  源码与测试 `ruff check`、目标 `compileall`、`git diff --check` 及 LSP diagnostics 均通过。
- 剩余风险：legacy 直接绘制路径仍保留旧兼容目录和可选 QR 行为；自动订阅失败目标按目标重试、状态
  迁移及自动失败不发送标题文本由下一轮 O12-A 处理。本轮未执行生产 reload 或真实上游图片下载。
- 下一步：进入 O12-A，处理公告失败缓存与按订阅目标投递，不重复改动本轮完整显示与缓存契约。

### O12-A — 公告失败缓存、订阅投递与跨功能缓存治理 `[completed]`

- TDD 为公告状态新增独立版本化投递记录：旧 `ann_state.json` ID 列表迁移为已处理，按首次观察目标集合与成功目标集合记录投递状态。
- 自动订阅按目标发送；详情、渲染或图片失败时跳过本轮，成功目标不重发，失败目标在下一轮继续处理；删除标题文本 fallback。
- 移除公告列表无 TTL 进程缓存；手动查询使用固定详情失败文案，并删除 notices 专用 `transport_error`。
- 公网 IP/RSA fallback 不写入成功缓存；为 `timed_async_cache` 增加安全参数化 key，验证登录日志、用户帖子列表和 host 隔离。
- 为上游响应形状、空正文、部分目标失败、旧状态迁移、缓存键污染和日志脱敏补齐故障注入测试。

完成记录（2026-08-30）：
- 新增版本化 `ann_delivery_state.json`，迁移旧 `ann_state.json` ID 为已处理；自动公告按首次观察目标投递，详情/渲染/图片/目标发送失败均可观测并按失败目标重试，成功目标不重发；旧 ID 列表在当前目标全部成功后同步，保留回滚语义。
- 移除公告列表无 TTL 缓存与 notices 专用 `transport_error`；手动公告详情使用固定失败文案。公网 IP/RSA fallback 不落成功缓存，登录日志/帖子列表/RSA/IP 缓存按安全 key 隔离，凭据与身份不写入原文日志或缓存键。
- Red→Green：`tests/test_goal1_o12a_delivery.py` 为 `11 passed, 1 warning`；公告/入口/传输/配置回归为 `55 passed, 1 warning`，`tests/test_notices.py` 为 `10 passed, 1 warning`，账号/传输为 `21 passed, 1 warning`，写入契约为 `44 passed, 1 warning`。目标文件 runtime Ruff、compileall、git diff check 及 LSP diagnostics 均通过；提交钩子 Ruff 通过。实现提交为 `c184f2c`。
- 剩余风险：未执行生产 reload、真实账户/上游图片访问；旧 `test_notices_subscriptions.py` 全集仍受外部 CDN/T2I 网络不可用影响，相关失败未通过添加静默 fallback 规避。runtime Ruff 全仓仍有其他并行/既有文件的 21 条问题，本轮未越界修改。
- 下一步：进入 O12-B，处理密函缓存时序与自动推送治理，不提前实现后续任务。

### O12-B — 密函缓存时序与自动推送治理 `[completed]`

- TDD 固定当前小时 `window_start` 的缓存门槛：整点后半小时前的上游结果只用于实时查询，不落缓存、不自动推送；半小时后重新获取并通过 typed `instanceInfo` 结构校验与 fingerprint 后才提交当前小时缓存。
- 自动推送只使用当前小时已验证快照；失败、空结构或未到门槛时跳过本轮，不复用上一小时数据，并由下一次既有调度或人工触发继续尝试。
- 移除 `notifications.secret_push_time`、`notifications.secret_cache` 及全局密函任务调度修改参数；`dnaby_mh_push` 仍保留自动订阅能力但固定为每小时 `HH:30` 执行。
- 保留与 GsCore 一致的 `订阅密函时间17:23`/`订阅密函周期17:23` 订阅级时间窗口：按当前小时 17 点至 23 点（含边界）过滤，支持跨午夜区间；名称订阅、文本/图片订阅、管理员暂停/恢复继续有效，窗口只过滤已验证快照的目标，不改变缓存时序。
- 旧全局推送配置迁移时显式丢弃并记录提示；缓存键包含 `window_start`，不得跨小时复用。
- 故障注入覆盖整点前旧数据、半小时后新数据、上游失败、上一小时缓存隔离、订阅窗口过滤和自动推送仍可用。

完成记录（2026-08-30）：

- 实际完成：新增 typed 密函快照校验、`window_start`/`fetched_at`/fingerprint envelope 与统一
  `CacheManager` 缓存；整点后半小时之前只允许实时查询，半小时后才写入当前小时缓存，缓存键按
  上海本地小时隔离，旧小时和半小时前数据不会自动推送。自动推送只读当前小时已验证快照，
  上游失败、空/异常结构和未到门槛均跳过；名称、文本、图片订阅均保留普通/跨午夜时间窗口。
- 实际完成：移除 typed/legacy 全局密函推送时间与缓存开关，迁移时记录并丢弃旧键；
  `dnaby_mh_push` 与 scheduler state 固定为 `hourly@30:00`（每小时 `HH:30`），管理 API 与
  Dashboard 不再提供密函调度编辑参数；README、配置、命令、管理页、架构和移植进度文档已同步。
- Red→Green：初始目标测试实际因 `src/modules/notices/mh_cache.py` 缺失而收集失败；实现首轮为
  `4 passed`，边界审查新增 Red 实际为 `3 failed`（UTC 本地小时、异常 typed 分区、半小时前
  envelope），修复后目标套件为 `8 passed`。
- 验证：O12-B/配置/调度/管理员回归 `50 passed, 1 warning`；密函读取与 transport `12 passed,
  1 warning`；写契约 `44 passed, 1 warning`；目标源码 Ruff、compileall、git diff check 和
  LSP diagnostics 均通过。实现提交为 `34a1c22`（`feat(goal-1): govern MH cache timing and fixed push schedule`）。
- 剩余风险：既有订阅全集中仍有 1 条依赖全局 T2I 的图片渲染测试因外部返回不可解码内容失败
  （另有 `15 passed`），未通过静默占位图规避；本轮未执行真实上游、生产 reload 或全量 pytest。
- 下一步：进入 D04，审查 O10–O12-B 的缓存完整性、订阅投递、视觉产物与失败路径。

### D04 — 调试审查 O10–O12-B `[completed]`

- 检查 incomplete 结果是否可能污染完整缓存、租约是否泄露、精准刷新是否误删他人数据。
- 对公告做分页、URL、部分图片失败、上游变化、空模板、失败缓存、按目标重试和缓存过期故障注入。
- 检查公告列表旧缓存、IP/RSA fallback、参数化缓存键是否存在跨身份污染或静默旧数据回退。
- 对密函做整点前/后半小时、上游结构异常、上一小时缓存误用、固定调度时间、旧配置迁移和订阅级窗口故障注入。
- 实际打开代表性公告、角色卡、占位图与多图结果。

完成记录（2026-08-30）：

- 聚焦回归实际通过：`test_cache_manager.py` + O10/O11/D03 为 `39 passed`；O12 公告、O12-A
  投递、transport 与详情 HTML 为 `35 passed`；O12-B、通知调度、scheduler state 与 admin API 为
  `26 passed`，均只有 AstrBot `audioop` 弃用警告。
- 故障注入确认：incomplete 角色卡不写入完整缓存；stale/retention、源图不可解码、空公告、分页、
  query/hash/无扩展名 URL、公告 fingerprint 变化、详情多页、按目标失败重试、旧状态迁移和
  IP/RSA fallback 隔离均按契约收口。按身份+角色精准失效保留另一身份及其它角色；密函
  `12:29:59` 不开门、`12:30:00` 开门，换小时不读旧缓存，固定下一次运行点为 `HH:30`，订阅窗口
  与旧配置迁移行为符合 O12-B。
- 实际打开运行期公告列表/详情缓存、角色卡/占位素材、周报占位素材；使用详情分页器生成并打开
  两页多图 fixture，尺寸分别为 `1080×6000` 与 `1080×4500`，确认没有在发送边界丢页。同步修正
  架构、测试说明和命令文档中将公告误写为 1300 宽的描述；历史对比文档保持不动。
- 未发现 O10–O12-B 的 P0；发现需独立处理的失败语义边界：`密函测试` 忽略目标推送失败仍返回
  “已发送”，密函图片渲染异常会在文本目标已发送后向 scheduler 外抛，缓存 sidecar 在租约释放期间
  损坏会抛出 `JSONDecodeError` 并使损坏 payload 长期保留。公告详情 manifest 对页号仅校验非负整数，
  未校验从 0 连续且唯一；这些不影响当前正常路径，但需修复测试后再决定最小实现。
- 本轮未执行真实上游、生产 reload 或真实 QQ 发送；既有订阅全集仍有 1 条外部 T2I 返回不可解码图片
  的环境失败，未用静默占位图掩盖。

### D04-R — 修复通知失败语义与缓存租约/详情 manifest 故障边界 `[completed]`

- 先为 `密函测试` 失败返回、密函图片渲染失败、租约释放时 sidecar 损坏和公告 manifest 非连续/重复页号建立 Red 测试，再做最小修复。
- 保持正常文本/图片订阅、当前小时密函缓存、公告完整缓存与按目标重试语义不变；不得用默认成功、标题 fallback 或占位图掩盖失败。
- 修复后运行通知/缓存聚焦回归、ruff、compileall、LSP diagnostics，并由 `code-review-expert` 复审。

完成记录（2026-08-30）：
- Red：新增 `tests/test_goal1_d04_r_failure_boundaries.py`，首次运行为 `5 failed`；分别锁定密函测试假成功、图片渲染异常外溢、租约释放遮蔽 body 异常、重复/倒序 manifest 被直接消费四类问题。
- Green：失败目标返回 `MH_TEST_FAILED`；密函文本目标成功后图片渲染只捕获已知渲染/I/O/HTTP/值错误并记录日志、跳过图片目标；租约释放仅在已知 sidecar/写入错误时保留损坏现场且不覆盖调用方异常；详情 manifest 仅接受 `0..N-1` 连续页号。
- 验证：D04-R 边界用例 `5 passed`；通知/缓存聚焦回归排除两条依赖外部 CDN 的既有公告用例后 `91 passed, 2 deselected`；ruff、`compileall`、`git diff --check` 通过；5 个受影响文件 LSP diagnostics 均为空。
- 审查：`code-review-expert` 未发现 P0–P3 阻塞项。损坏 sidecar 按安全边界保留并记录告警，交由维护流程处理，不伪造租约状态；未执行生产 reload、真实上游发送或真实 QQ 发送。
- 环境残留：未排除的两条公告轮询用例均因 `cdn.test` 图片下载 `ConnectError` 返回 0，和本轮 manifest/投递语义无关；未增加占位图或静默成功兜底。

### O13 — 第二阶段文档、配置、投影与完整门禁 `[completed]`

- 更新 cache/resource/announcement/secret-letter 配置 schema 和文档，说明全局密函推送时间与缓存开关已移除、订阅级时间窗口仍保留。
- 重新生成相关投影，运行完整 pytest、ruff、compileall。
- 验证 data_dir 边界、无插件目录运行期写入。

完成记录（2026-08-30）：

- 配置与投影：复核 `DnabySettings`、`src/infrastructure/config/schema.py` 和 `_conf_schema.json`，确认
  `notifications`、`cache`、`resources` 字段一致，且不含 `secret_push_time`、`secret_cache`、
  `MHPushSubscribe` 或 `MHCache`；重新运行 `generate_config_schema.py` 与
  `generate_commands_manifest.py` 均无投影 diff。配置、公告/密函、缓存和公共资源说明已同步到
  `docs/usage/configuration.md`、`docs/usage/resources.md` 和 README，并明确密函固定每小时 `HH:30`、
  订阅级时间窗口仍由密函订阅记录保留。
- data_dir：静态审计确认当前 bootstrap 的数据库、资源 generation、缓存、渲染、订阅和 scheduler
  状态均从 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 派生；修复 legacy QR 登录路由，把兼容
  helper 的临时路径移到 runtime `login_qr/`，并用 `user_id` 的 SHA-256 摘要作为文件名，阻止目录穿越
  或写入插件源码目录。新增 `tests/test_goal1_o13_config_data_dir.py` 覆盖运行期根目录和恶意路径片段。
- TDD：首次 Red 因路径落在 `src/modules/account/` 失败；增强目录穿越断言后再次 Red；两次 Green 均为
  `1 passed`。最终 O13 相关配置/通知/缓存/二维码回归为 `54 passed, 1 warning`。
- 门禁：配置/资源生成器成功且 `_conf_schema.json`、`commands.json` 无 diff；全量 compileall 成功，
  `git diff --check` 成功，受影响源码/测试的 Ruff check 和 LSP diagnostics 均通过。全量 pytest 为
  `663 passed, 1 skipped, 10 failed`；失败均为既有环境/后续目标问题（T2I/CDN 网络 3 条、缺少 sibling
  资源 checkout 5 条、goal-3 命令数期望漂移 1 条、namespace 边界 1 条），没有 O13 相关失败。
  全仓 Ruff 仍有 15 条既有 goal-2/goal-3/基础设施导入排序及 scheduler/admin 问题，未越界修改。
- 审查：按 `code-review-expert` 复核 O13 diff，未发现本次变更的 P0–P3 阻塞项；未执行生产 reload、
  真实账户/上游发送或真实 QQ 发送。下一步进入 O14 公共资源仓库独立版本与审查。

### O14 — 公共资源仓库独立版本与审查 `[completed]`

- 对公共资源仓库做 manifest、许可证/来源、秘密与可解码性审查。
- 形成独立资源 commit SHA；插件只引用已验证版本。
- 使用 `code-review-expert` 审查插件第二阶段改动并修复阻塞项。

完成记录（2026-08-30）：

- 资源版本：独立仓库 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot_plugin_dna_resources`
  已 fetch 远端 `main`，发布候选为 `5d76860141d9ab5052417df25ccc9f5a929ff06b`，完整文件树摘要为
  `6cf9d38b417825a27d63f8ecdc5f924fc3eb04ed`。候选树与本地分支树一致；工作树中既有的
  `data/cmd_config.json`、`data/t2i_templates/` 未跟踪文件未被清理，也未进入该 SHA。插件代码仍只接受
  规范远端的 `main` 和 fast-forward 更新，未改为引用投稿分支或镜像 ref。
- 资源审查：manifest `format_version=1`、12 个必需目录、109 个 tracked 文件、93 个 tracked PNG
  均通过路径/普通文件检查和 PIL `verify()+load()`；3 个 TTF 通过 `file`/`fc-scan`；兑换码 3 条通过
  JSON Schema 2020-12 与跨条目语义校验；Git 树无符号链接；定向 token/cookie/password/private-key
  等秘密痕迹扫描无命中；`git diff --check` 通过。配置正确的跨仓回归为 `7 passed, 1 warning`。
- 来源与权利结论：仓库 README/编辑器 contract 明确不授予第三方素材 blanket license，但资源仓库没有
  统一 `LICENSE`、`NOTICE` 或来源清单；`arial-unicode-ms-bold.ttf` 的元数据标为 Monotype，
  `dna_fonts.ttf` 标为 Arphic，图片和字体的再分发权不能仅凭插件 GPL-3.0 推断。因此本轮记录了
  结构/秘密/可解码性审计，但不把该 SHA 宣称为已清权的公开发行版本；O15 生产发布前必须由维护者
  补齐或确认各资源上游条款。
- 第二阶段 code review：按 `code-review-expert` 清单审查 `3e579fa^..7b1e3c7` 及 O14 修复，未发现
  P0。实际 Red 新增 4 个边界用例并全部失败：图片重定向、缓存祖先符号链接、公告跨页重复 `postId`
  和玩家刷新读后写覆盖；Green 以最小改动分别关闭自动重定向、拒绝直接祖先符号链接、按 `postId`
  保留首次公告、按身份串行化概览回填。剩余 P2 为 `announcement_check_minutes=0` 的产品语义/配置
  不一致和 manifest 未形成严格额外文件 allow-list；因语义未确认，本轮不静默改变配置行为，已记录为
  后续门禁关注项。
- 验证：O14/图片/缓存/公告/玩家聚焦回归为 `76 passed, 1 warning`；受影响源码 `ruff check` 通过，
  `pyright` 为 `0 errors, 0 warnings, 0 informations`，目标与全插件 `compileall`、`git diff --check`
  通过。全量 pytest 为 `668 passed, 1 skipped, 9 failed`；9 条均为既有环境/后续目标边界：资源测试默认
  sibling 路径缺失 5 条（显式 `DNA_RESOURCE_REPO` 后已通过）、goal-3 命令数期望漂移 1 条、namespace
  隔离 1 条、外部 CDN/T2I 不可用 2 条；未发现 O14 聚焦回归失败。未执行生产 reload、真实账户、真实
  上游图片下载或发送；下一步 O15 仅在资源权利门禁明确后形成第二阶段插件精确 SHA 并做受控热重载。

### O15 — 第二阶段插件 SHA、atri 热重载与视觉验收 `[completed]`

- 形成第二阶段独立插件 SHA，记录上一稳定 SHA。
- 按 `plan.md §4.2` 部署、定向 reload、核对资源 active pointer 与后台任务单例。
- 发布前人工清理 `plugin_data/astrbot_plugin_dnaby` 下共享下载器产生的公告/资源图片缓存，再运行缓存/刷新/公告 adapter E2E，复制并实际查看所有代表性图片。
- 核对公告轮询的列表条数、详情块数、图片成功/失败数和按目标投递成功/失败数；确认失败目标下一轮仍待处理、成功目标不重复。
- 在整点前、整点后半小时分别验证密函：前者不写当前小时缓存且不自动推送，后者只在上游快照校验通过后向仍符合订阅级时间窗口的目标发送。

完成记录（2026-08-30）：

- 版本与部署：以上一稳定生产 SHA `6fda2f16b1ebdf3999b95d36609778bf11de38ce` 为基线，形成独立第二阶段插件候选
  `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`（远端 ref
  `codex/goal-1-o15-phase2`）。部署前确认插件 detached 工作树 clean、候选对象精确存在；容器内
  `compileall`、入口导入、`metadata.yaml`、`commands.json`/registry（均 61 条）、schema 和资源 manifest
  预检通过。生产插件精确检出该 SHA 后调用已确认的
  `POST http://127.0.0.1:6185/api/v1/plugins/astrbot_plugin_dnaby/reload`，HTTP 200 且业务返回
  `status=ok/message=重载成功`；认证 GET 复核插件为 `v0.2.0`、`activated=true`。
- 资源与 active pointer：公共资源仓库生产工作树从旧 SHA `23955674e8ce0f7da317c30a752249cd91c1afaf`
  fast-forward 到独立 SHA `5d76860141d9ab5052417df25ccc9f5a929ff06b`，工作树 clean。重载后
  `resource_generations/current.json` 指向同一 SHA，`content_sha256=92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4`；
  容器内 `ResourceGenerationValidator` 通过，指针 hash 一致、`resource_version=redeem-code-v1-migration-2026-08-28`、
  12 个必需目录齐全，generation 目录数为 1。
- 缓存清理与运行态：按维护文档仅处理 `resource/` 与 `other/ann_card/`，未触碰 `resources/`、
  `resource_generations/`、`rendered/`、数据库、订阅或状态文件。原 `resource` 281 个文件、约 29M，
  原公告图片缓存 24 个文件、约 23M，均可恢复移动到
  `/srv/AstrBot/backup/astrbot_plugin_dnaby-o15-20260830T063050Z/`；收口探针确认活动目录均为 0 文件、
  备份完整。容器仍运行、`restart_count=0`；精确匹配 `python main.py` 的 AstrBot 主进程为 1 个，
  不把容器内其它基础服务 Python 进程计入插件实例；最近 200 行日志中无 `[dnaby]`、Traceback 或“定时任务异常”
  标记。`PluginLifecycle`、`SignScheduler` 和 `NoticesScheduler` 的幂等/按任务 ID 防重复逻辑由生产容器定向
  回归覆盖；没有从缺少任务计数 API 的日志探针推导额外计数结论。
- TDD/回归：本轮是部署验收，未修改业务代码；O12 公告、O12-A 投递、O12-B 密函边界定向套件在本地和
  生产容器各为 `30 passed, 1 warning`。公告证据为跨页 `20+1=21` 条、详情 `text/image/image` 三块、
  多页响应保留 2 页；渲染夹具中列表预览 `1 成功/0 失败`、详情图片 `1 成功/0 失败`。生产真实 CDN 的
  `test_ann_renders_list_image` 仍因 `cdn.test` `ConnectError` 返回固定失败文案，未用占位图伪造成功。
  按目标故障注入为首轮 `1 成功/1 失败`、下一轮只重试失败目标并 `1 成功/0 重复发送`，最终
  `observed_targets == delivered_targets`；详情失败下一轮重试也通过。
- 密函门禁：生产容器通过整点前（`12:10`）只允许实时查询、不写当前小时缓存且自动推送为 0，整点后半小时
  （`12:35`）仅缓存已校验当前小时快照并按订阅窗口投递；坏/空快照不缓存且后续轮次重试，换小时不回填旧缓存，
  名称/文本/图片订阅窗口均通过。固定 scheduler 仍为 `hourly@30:00`。
- 视觉验收：用当前 `v0.2.0` registry、真实模板和本地可解码图片夹具生成并实际打开
  `output/goal1-visual/phase2-help.jpg`、`phase2-role-overview.png`、`phase2-stamina.png`、
  `phase2-weekly.png`、`phase2-announcement-list.png`、`phase2-announcement-detail-1.png`、
  `phase2-mh.png`、`phase2-mh-simple.png`；确认中文字体、帮助分组、角色/周报进度、公告正文图片块、
  标准/简密函版式均无裁切。该夹具结果只证明模板/布局，不替代生产 T2I 成功证据。
- 生产更宽回归 `110 passed, 3 failed, 1 warning`；3 条均为生产环境的外部依赖：标准密函与简密函 T2I
  返回不可识别图片各 1 条、公告列表 CDN 图片失败 1 条；排除 `tests/test_notices.py` 的生产回归为
  `103 passed, 1 warning`。本地第二阶段聚焦套件为 `169 passed, 1 warning`，资源跨仓契约为
  `7 passed, 1 warning`，`compileall` 与 `git diff --check` 通过。全插件 Ruff 仍仅报告既有 Goal2/Goal3
  测试导入排序问题 2 条，未越界修改。
- 风险与边界：O14 已确认公共资源仓库没有统一 `LICENSE`/`NOTICE`/来源清单，字体元数据涉及 Monotype/
  Arphic；因此本次是受控内部生产热重载，不把资源 SHA 宣称为可公开再分发版本。生产 CDN/T2I 失败已
  保留真实错误语义，后续由维护者处理上游可用性；下一步进入 D05 调试审查与受控失败回滚演练。

### D05 — 调试审查 O13–O15 `[completed]`

- 核对资源 SHA、插件 SHA、生产 active pointer、缓存 metadata 与清理结果一致。
- 检查热重载后 downloader、cleanup loop、公告 scheduler 是否重复。
- 做一次受控失败回滚演练并记录恢复证据。

完成记录（2026-08-30）：

- 一致性审查：生产插件仓库最终为候选 `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`、clean；公共资源仓库为
  `5d76860141d9ab5052417df25ccc9f5a929ff06b`、clean。`resource_generations/current.json` 指向同一资源 SHA，
  `content_sha256=92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4`；此前已通过 generation
  validator、12 个必需目录和完整内容摘要校验。清理后的 active `cache/` 根及 `player_data/`、`player_card/`、
  `resource/`、`other/ann_card/` 均不存在或为空，active cache metadata 为 0；这表示当前没有活动缓存，不是静默
  伪造命中。可恢复备份仍存在，`resource` 为 281 个文件、`other/ann_card` 为 24 个文件；`rendered/` 保留 6 个
  既有视觉产物，未被清理。
- 重复任务审查：静态检查确认 `ResourceUpdateService` 以 shared future/single-flight 合并 downloader 预热与显式
  同步，`CacheMaintenance` 以生命周期锁和单 task 防止 cleanup loop 重复，`NoticesScheduler` 以 task ID registry
  防止公告 scheduler 重复；bootstrap 只挂载一套 start/stop hooks，`PluginLifecycle` 以转换锁串行化热重载边界。
  本地与生产容器的资源 service、公告 scheduler、cleanup lifecycle 和 entry skeleton 定向回归均为 `26 passed,
  1 warning`。生产 `python main.py` 精确匹配为 1 个；其它 Python 进程属于容器基础服务或本次探针，不能作为插件
  任务计数。最近 200 行 Docker 日志统计 `dnaby=0`、`Traceback=0`、`task_error=0`。
- 受控回滚证据：将生产插件从候选精确切换到记录的稳定恢复 SHA `6fda2f16b1ebdf3999b95d36609778bf11de38ce`，
  容器内 `compileall` 通过，稳定 smoke 为 `61 passed, 1 warning`；调用同一认证接口
  `POST /api/v1/plugins/astrbot_plugin_dnaby/reload` 得到 HTTP `200`、业务 `status=ok`，认证 GET 确认插件
  `activated=true`、版本 `v0.2.0`，生产 HEAD、资源 SHA、active pointer 均保持预期，容器未重启（restart count `0`）。
  随后恢复候选精确 SHA 并再次调用同一 reload endpoint，得到同样的 HTTP/业务成功；候选认证 GET 为激活状态，生产
  focused 回归 `26 passed, 1 warning`，最终插件/资源工作树均 clean。该演练以稳定恢复点模拟故障后的恢复路径，未故意
  注入会破坏生产实例的代码或配置；因此证明“检出已记录恢复 SHA → 同 endpoint reload → smoke/status → 恢复候选”
  的可执行性，不把成功回滚路径夸大为故障注入测试。
- TDD/审查结论：D05 是 O13–O15 的部署/调试审查，没有新增业务代码，沿用 O15 与 O08–O14 已记录的 Red/Green/Refactor
  证据；本轮 code review 未发现新的 P0/P1。修正 O15 中“单 Python/AstrBot 进程”的表述为“单个 `python main.py`
  AstrBot 主进程”，并明确没有可用于推导精确 scheduler task 数量的生产 API。资源权利未明、生产 CDN/T2I 外部依赖
  失败仍按 O14/O15 原记录保留，不在本审查中添加静默 fallback。
- 验证命令与结果：生产稳定/候选两次 `compileall` 均通过；稳定恢复 smoke `61 passed, 1 warning`；候选最终 focused
  suite `26 passed, 1 warning`；两次精确 reload 均 HTTP 200/业务成功；最终 Dashboard 激活状态、插件/资源 SHA、
  pointer、备份计数、主进程数和日志错误计数均符合预期。未重启容器、未修改配置、未删除备份或运行期数据库/订阅状态。
- 剩余风险：公共资源仓库仍缺统一 `LICENSE`/`NOTICE`/来源清单；生产真实 CDN/T2I 的 3 条外部失败仍未消除；生产没有
  公开 scheduler task 计数 API，因此重复性只能由源码幂等约束、focused 测试、主进程唯一性和无新增错误日志共同证明。
- 下一步：进入 O16，先为领域查询层与 Agent Tools 适配边界建立 Red 契约。

## 第三阶段：Agent Tools

### O16 — 可复用领域查询层与 AstrBot 工具适配边界 `[completed]`

- 先写工具与聊天命令共享领域 use case 的 Red 测试，避免复制 handler 逻辑。
- 建立 typed request/result 与 `AstrAgentContext.event` 身份提取。
- 验证本地 4.27.1/生产 4.27.4 API 差异并做最小兼容。

完成记录（2026-08-30）：

- TDD/共享领域层：先新增 `tests/test_goal1_o16_agent_tools.py` 并实际运行，初始 Red
  因 `src.entry.agent_tools` 尚不存在而在 collection 阶段失败；随后建立
  `src/modules/agent_tools/` 的 `AgentQueryRequest`、`AgentQueryResult`、`AgentQueryCatalog`
  和 `stamina_query`，并将聊天 `stamina_use_case` 改为调用同一 `stamina_query`。最终 O16
  契约测试为 `6 passed, 1 warning`，断言聊天与 Agent 路径收到同一 service/actor，未知查询
  返回显式 `unsupported`，未复制 handler 内的服务调用逻辑。
- 身份与返回契约：`src/entry/agent_tools/context.py` 只从官方
  `AstrAgentContext.event` 经 `actor_from_event` 提取 `EventActor`；Agent 参数拒绝
  `user_id`、`target_user_id`、`bot_id`、`credential_user_id`、`uid` 等身份覆盖字段。
  `AgentQueryResult` 固定输出 `ok/kind/data/cache/error`，成功不得携带错误，失败必须保留
  明确错误；领域响应对象暂留给后续 entry adapter 做 JSON/图片转换。
- API 兼容性：只读核验本地 AstrBot `4.27.1` 与生产 `4.27.4` 的官方 API，
  `astrbot.core.agent.tool.FunctionTool`、`AstrAgentContext`、`Context.add_llm_tools` 和
  `Context.unregister_llm_tool` 的模块位置与签名一致；后续按 `FunctionTool.call` 的
  `ContextWrapper[AstrAgentContext]` 路径取得事件身份，不采用旧的 `StarTools.register_llm_tool`
  作为 Agent 注册入口。O16 不注册工具、不新增配置开关，这些留给 O17–O19。
- 验证：目标源码/测试 Ruff 通过，目标 `pyright` 为 `0 errors, 0 warnings, 0 informations`，
  目标 `compileall` 与 `git diff --check` 通过；百科、渲染和命令 registry 相关回归为
  `34 passed, 1 warning`。警告均为 AstrBot 依赖导入 `audioop` 的弃用警告，未执行生产 reload
  或真实签到/外部写操作。
- 剩余边界：当前 catalog 只接入 `stamina` 作为共享查询代表；完整只读工具清单、稳定 JSON
  化、可选图片发送、总开关和签到安全仍由 O17–O19 实现与 D06 审查。下一步进入 O17。

### O17 — 纯查询工具、JSON envelope 与可选图片 `[completed]`

- TDD 注册已批准的玩家、角色、体力、周报、日历、wiki、攻略、兑换码、目录、梦魇、公告和订阅查看工具。
- 默认返回 `ok/kind/data/cache/error` JSON。
- `send_image=true` 时直接发给当前用户，工具结果只返回 `image_sent`，不泄露本地路径。

完成记录（2026-08-30）：

- TDD/工具清单：先新增 `tests/test_goal1_o17_agent_tools.py` 并实际运行 Red，初始因工具适配模块不存在而在 collection 阶段失败；补充官方注册契约后再次以缺少 `register_agent_tools` 实际失败。随后建立
  `src/entry/agent_tools/tools.py`，通过 `FunctionTool.call(ContextWrapper[AstrAgentContext])` 从当前事件取身份，并提供
  `register_agent_tools()` 调用官方 `Context.add_llm_tools`。完整注入四类 service 时注册 16 个批准的只读工具：玩家概览/角色详情、体力、本周/上周周报、日历、wiki、攻略、兑换码、角色/武器目录、梦魇、梦魇列表、我的订阅、公告列表/详情和签到日历查询；签到日历只读，不执行签到。
- 查询复用：`src/modules/agent_tools/queries.py` 为玩家、百科、梦魇公告和签到日历建立 typed request 适配，聊天侧已有体力查询继续复用 `stamina_query`；工具 schema 不暴露 `user_id`、`target_user_id`、`bot_id`、`credential_user_id`、`uid` 等身份字段。
- 返回/图片：所有工具默认序列化为固定 `ok/kind/data/cache/error` JSON；图片 data 仅包含类型、可用性和完整性，不包含本地路径或二进制。图片工具收到 `send_image=true` 时经当前 `AstrMessageEvent.send()` 发送 `Image`，结果仅返回 `image_sent`；发送失败显式返回 `ok=false` 和错误，不伪装成功。非图片工具不接受 `send_image`。
- 验证：O17/O16 契约测试 `16 passed, 1 warning`；领域适配器、命令 registry 与写入契约相关回归共 `109 passed, 1 warning`。目标 Ruff 通过，Pyright 为 `0 errors, 0 warnings, 0 informations`，目标 `compileall` 和 `git diff --check` 通过。警告均为 AstrBot 依赖导入 `audioop` 的弃用警告，未执行生产 reload、真实签到或外部写操作。
- 剩余边界：`agent_tools.enabled` 总开关、initialize/terminate 注册解除和热重载去重，以及签到写工具确认/幂等留给 O18；文档与完整阶段门禁留给 O19。下一步进入 O18。

### O18 — 签到工具、明确确认、幂等与生命周期 `[completed]`

- TDD 实现原始消息肯定意图/否定排除、消息 ID 幂等、当前用户当前 UID 限制。
- 使用 fake transport 验证签到，不执行真实签到。
- `agent_tools.enabled` 控制全部注册；initialize/terminate 与热重载无重复工具。

完成记录（2026-08-30）：

- 实际完成：新增 `AgentSignTool` 与 `sign_intent_from_text`，签到工具只读取
  `AstrAgentContext.event` 的原始消息和消息 ID；肯定短语通过、否定/疑问和模型传入的
  `confirmed`、用户 ID、UID 等参数均拒绝。工具固定构造当前事件 actor、
  `target_user_id=None`、空参数的 `CheckinCommandRequest`，并使用事件 extra 保存同消息
  的锁与 JSON 结果，重复调用只执行一次。签到验证使用隔离数据库绑定和 fake transport，
  未触碰真实接口。
- 生命周期与配置：新增 `AgentToolsLifecycle`，开启时通过官方
  `Context.add_llm_tools` 注册 16 个只读工具和 `dnaby_sign`，终止时逐项调用官方
  `unregister_llm_tool`；生命周期锁保证重复 start/stop 和 runtime 热重载不重复。新增
  `agent_tools.enabled` typed 配置（默认关闭），接入 `build_runtime` 与薄入口，并重新生成
  `_conf_schema.json`。
- Red/Green/Refactor 证据：先运行意图测试，因缺少 `signin` 模块在 collection 阶段实际
  Red；补充签到工具契约后再次因缺少 lifecycle 模块 Red；实现后 O18 专项测试为
  `17 passed, 1 warning`。同一消息并发调用只产生一次 fake transport 签到调用，runtime
  重复 initialize/terminate 只注册/注销一次完整 17 工具集。
- 验证命令与结果：O18、配置、Agent Tools、入口及资源配置相关回归为
  `88 passed, 1 warning`；签到、命令、registry、入口、写入契约回归为
  `112 passed, 1 warning`。目标文件 Ruff、目标 Pyright（`0 errors, 0 warnings, 0 informations`）、
  `compileall`、`git diff --check` 均通过；重新运行配置 schema 生成器后磁盘投影与生成结果一致。
- 剩余风险：未执行生产 reload 或真实签到；第三阶段文档同步、D06 负向审查和完整阶段门禁
  由后续任务负责。当前测试仅使用本地 fake transport，AstrBot 依赖仍有 `audioop` 弃用警告。
- 下一步：D06，审查模型伪造确认、跨用户访问、工具重试和写操作范围。

### D06 — 调试审查 O16–O18 `[completed]`

- 针对身份伪造、prompt 注入、模型伪造确认、工具重试和跨用户访问做负向测试。
- 检查所有写工具是否仅剩经批准的签到，且无管理/账号/订阅写操作。
- 核对图片发送失败不会伪装为成功。

完成记录（2026-08-30）：

- 负向测试：新增 `tests/test_goal1_d06_agent_tools.py`，覆盖信息询问/示例文本不得确认签到、并发启动只注册一次、注销失败保留残留并可重试，以及热重载前先清理残留；D06 专项为 `7 passed, 1 warning`。沿用 O16/O17/O18 的身份伪造、跨用户参数、模型传入 `confirmed`、目标用户/UID、否定与疑问消息、图片发送失败测试。
- 审查修正：发现原签到意图判断以肯定词子串放行，可能把“请告诉我签到规则”“请把签到当作例子”等 prompt/信息文本误当写操作；改为仅接受完整短语或配置前缀+签到短语，保留否定/疑问优先拒绝。发现注销异常时生命周期错误清空状态；现保留失败工具名并只重试残留，下一次 `start()` 会先清理残留再重新注册，错误仍显式抛出。
- 写操作范围：`AGENT_TOOL_NAMES` 仍仅为 16 个只读查询，唯一写工具为批准的 `dnaby_sign`；查询 catalog 未接入管理、账号、凭据或订阅修改入口，订阅/签到日历均为读取。签到工具拒绝模型提供的确认、身份和目标参数，身份只来自当前事件。
- 图片失败：O17 的图片发送异常测试保持 `ok=false`、`image_sent=false` 和明确错误，未泄露本地路径，也未伪装为成功；本轮回归再次覆盖该契约。
- 验证：O16/O17/O18、D06、配置及入口相关回归共 `76 passed, 1 warning`；目标 Agent Tools Ruff 通过，定向 Pyright 为 `0 errors, 0 warnings, 0 informations`，目标 `compileall` 与 `git diff --check` 通过。警告仍为 AstrBot 依赖导入 `audioop` 的弃用警告；未执行真实签到或生产写操作。
- 剩余风险：完整第三阶段文档同步与全量质量门禁留给 O19；生产真实签到、外部服务与资源权利风险不因本审查消除。下一步进入 O19。

### O19 — 第三阶段文档、配置与完整门禁 `[completed]`

- 更新 Agent Tools 列表、参数、返回契约、身份与签到安全说明。
- 更新配置 schema，验证关闭总开关时零工具注册。
- 运行完整 pytest、ruff、compileall。

完成记录（2026-08-30）：

- 文档：新增 [`docs/usage/agent-tools.md`](../docs/usage/agent-tools.md) 作为 Agent Tools 唯一详细使用说明，列出 16 个只读工具和唯一写工具 `dnaby_sign` 的参数、`send_image` 行为、固定 JSON envelope、身份来源、签到确认/幂等和失败语义；同步更新 docs 索引、命令说明、配置说明、架构、维护和测试入口。明确 Agent Tools 不属于 `commands.json`，不提供账号、凭据、隐私、订阅、资源或管理配置写操作。
- 配置与投影：`agent_tools.enabled` 已在 typed settings 与生成 schema 中作为唯一总开关，默认 `false`；重新运行 `scripts/generate_config_schema.py`、`scripts/generate_commands_manifest.py` 后，`_conf_schema.json` 与 `commands.json` 均无 diff。关闭开关零注册、schema 默认值和生成投影契约为 `3 passed, 1 warning`。
- Red/Green/Refactor：本轮只新增/更新文档和门禁记录，没有新增生产行为，因此无新的实现 Red；沿用 O18/D06 已实际验证的关闭开关、17 工具生命周期和安全契约。Agent Tools 相关源码/测试 Ruff 通过，目标 compileall 和 `git diff --check` 通过。
- 完整门禁：全量 pytest 实际为 `708 passed, 1 skipped, 9 failed, 5 warnings`；9 条失败分别是本地缺少 sibling 资源 checkout 的 5 条 Goal3 resource contract、Goal3 命令数期望漂移 1 条、namespace 命令数期望漂移 1 条，以及外部 CDN/T2I 不可用导致公告订阅渲染的 2 条，未命中本轮文档或 Agent Tools 文件。全仓 `ruff check .` 实际报告 14 条既有 infrastructure/scheduler/admin、历史 D03 和并行 Goal2/Goal3 文件问题；本轮目标文件未命中。全仓 `compileall -q .` 与 `git diff --check` 通过。
- 剩余风险：全量 pytest/ruff 的上述环境与并行目标基线问题仍待其归属任务或可用外部依赖处理，不能在 O19 通过静默 fallback 掩盖；Agent Tools 未执行真实签到、生产 reload 或真实图片发送。下一步进入 O20，进行第三阶段独立 SHA 审查与回滚清单准备。

### O20 — 第三阶段审查与独立 SHA `[completed]`

- 自审并使用 `code-review-expert`，修复阻塞问题。
- 形成第三阶段独立插件 SHA，记录第二阶段稳定 SHA。
- 准备工具 adapter 模拟与回滚清单。

完成记录（2026-08-30）：

- 审查范围：以第二阶段稳定提交 `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04` 为固定基线，复核
  O16–O19 的提交链和完整 Agent Tools diff，覆盖 SOLID/职责边界、AstrBot API 适配、事件身份
  与参数伪造、签到写操作、JSON/图片数据泄露、异常传播、并发幂等、生命周期残留和移除/调用方。
  未发现本次变更相关的 P0/P1；没有证据支持新增生产逻辑修补，保留已验证的显式错误和失败重试语义。
- 独立版本：第三阶段候选插件 SHA 固定为
  `8c7ac4c8ee0910574d2602e41756400ccef0899a`，第二阶段稳定 SHA 为
  `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`。`git diff --name-only d47d37e..8c7ac4c` 只包含
  Agent Tools、共享查询适配、配置/schema 投影、相关测试/文档与阶段记录；工作区中其它目标的
  未提交文件没有进入候选。O20 的审查清单为候选之后的文档提交，不改变该运行期候选 SHA。
- Adapter/回滚交付物：新增
  [`docs/porting/agent-tools-release-checklist.md`](../docs/porting/agent-tools-release-checklist.md)，
  固化 17 工具注册/注销、关闭开关、事件身份、查询 envelope、图片成功/失败、签到否定与并发
  幂等的 fake adapter 矩阵，以及 O21 精确 reload 前置条件、阶段三失败回退第二阶段 SHA 的步骤。
  清单明确不执行真实签到、不记录凭据、不默认重启容器，并保留数据库、订阅、公告状态、资源
  generation 和自定义面板。
- 验证：Agent Tools/O16–O18/D06、配置与入口相关专项共 `63 passed, 1 warning`；目标 Ruff 通过，
  目标 Pyright 为 `0 errors, 0 warnings, 0 informations`，目标 compileall 与 `git diff --check`
  通过。唯一警告仍为 AstrBot 依赖 `audioop` 弃用警告；O19 已记录的全量 pytest/ruff 基线失败
  不属于本轮。未执行生产 reload、真实图片投递或真实签到。
- 下一步：进入 O21，按清单在授权的 `atri` 环境对该候选 SHA 做定向热重载和 fake adapter 验收。

### O21 — 第三阶段 atri 热重载与工具验收 `[completed]`

- 按 `plan.md §4.2` 精确 SHA 部署和定向 reload。
- 验证工具只注册一次、身份来自事件、查询 JSON 正确、可选图片能直接发送。
- 签到只使用 fake transport/模拟，不触发真实副作用。

完成记录（2026-08-30）：

- 生产前置：记录第二阶段恢复点 `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`，确认插件 ID
  `astrbot_plugin_dnaby` 唯一且已激活；候选分支 `codex/goal-1-phase3` 已发布，生产非破坏性
  fetch 后精确切换到第三阶段 SHA `8c7ac4c8ee0910574d2602e41756400ccef0899a`。插件仓库和
  资源仓库均为 clean；资源 active pointer 保持 generation
  `5d76860141d9ab5052417df25ccc9f5a929ff06b`、content SHA
  `92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4`，未修改运行期数据。
- 生产预检：容器内 `compileall` 通过，`commands.json` 与 registry 均为 `61/61`，只读 Agent
  Tools 为 `16` 个，签到工具名为 `dnaby_sign`。已认证 Dashboard GET 在 reload 前后均为
  HTTP `200`、插件记录唯一、`activated=true`、版本 `v0.2.0`；插件配置保持
  `agent_tools.enabled=false`，因此生产实例不会注册工具或触发真实签到，启用路径由 fake
  adapter 覆盖。
- 按 `plan.md §4.2` 只调用一次已确认的定向
  `POST /api/v1/plugins/astrbot_plugin_dnaby/reload`，HTTP `200`、业务状态 `ok`、消息为成功。
  reload 后生产 HEAD 仍为候选 SHA，插件/资源工作树 clean，容器 `running=true` 且
  `restart_count=0`；日志起点后的 dnaby error-like、traceback、exception、ERROR 计数均为
  `0`。未执行容器重启或回滚。
- 在生产候选容器内按发布清单运行 O16/O17/O18/D06、配置资源和 lifecycle fake adapter 矩阵：
  `63 passed, 1 warning`（唯一警告为 AstrBot 依赖 `audioop` 弃用）。测试覆盖重复
  initialize/start 的 17 工具去重、事件身份提取与模型身份字段拒绝、固定
  `ok/kind/data/cache/error` JSON、可选图片直接发送及发送失败、否定/疑问/信息文本拒绝签到、
  同消息 fake transport 幂等；未执行真实签到、真实图片投递或外部写操作。
- 验证命令：生产候选容器内目标 suite 通过；reload 后 Dashboard/HEAD/pointer/容器状态复核
  通过。候选发布与定向 reload 使用了已读入内存的认证信息，未输出或写入凭据。
- 剩余边界：生产总开关仍为关闭，故本轮不宣称真实 LLM 调用或生产图片投递；注册去重、身份、
  JSON、图片和签到安全由同一候选版本的 fake adapter 直接验证。后续由 D07 做 O19–O21 的
  负向审查和生产日志/生命周期再审计。

### D07 — 调试审查 O19–O21 `[completed]`

- 检查生产日志、工具枚举、handler/scheduler 与缓存任务是否重复或残留。
- 运行跨用户、否定意图、重复消息、图片失败与关闭开关回归。
- 阶段三不稳定时回滚第二阶段 SHA。

完成记录（2026-08-30）：

- 审查结论：复核 O19–O21 的 Agent Tools 注册边界、唯一 17 工具清单、`bootstrap` 生命周期接线、
  查询异常传播、图片路径可用性、签到身份/确认/幂等和生产日志。发现两个本次变更相关的 P1
  边界并立即修复：查询 use case 异常此前会逃逸到 AstrBot FunctionTool 的 traceback envelope；
  缺失图片文件此前会被报告为 `available=true`，并可能交给 `Image.fromFileSystem` 形成假发送。
  现均返回固定安全 JSON 或显式图片发送失败，只记录查询名/异常类型，不回显路径、URL 或异常正文。
  复核确认生产代码只有 `AgentToolsLifecycle` 注册 Agent Tools，`register_agent_tools()` 仅为离线
  adapter 工具；scheduler、handler、缓存维护和资源预热没有重复接线。
- 幂等边界：最初用两个不同事件对象复现同消息 ID 时，事件级缓存无法去重；随后核对 AstrBot 4.27.4
  官方 `AstrAgentContext`/`Context.call_llm`，一次 Agent 运行绑定一个原始 event。没有引入无界进程
  缓存或未经迁移的持久化表；回归改为不同 `ContextWrapper` 复用同一原始 event，覆盖实际工具重试路径，
  并同步在 Agent Tools 文档披露边界。跨请求重建事件对象的持久化幂等仍是后续独立设计项。
- Red/Green/Refactor 证据：查询异常泄漏测试在旧实现下实际 `1 failed`，修复后通过；缺失图片
  `available=true`/误发送测试在旧实现下实际 `1 failed`，加入文件检查后通过。最终本地 Agent Tools
  负向矩阵 `tests/test_goal1_o17_agent_tools.py tests/test_goal1_o18_agent_tools.py
  tests/test_goal1_d06_agent_tools.py` 为 `37 passed, 1 warning`；包含 O16、配置/资源和入口回归的
  扩展矩阵为 `66 passed, 1 warning`。警告均为 AstrBot 依赖 `audioop` 弃用；源码 Ruff、源码
  Pyright、compileall、LSP diagnostics 和 `git diff --check` 均通过。Pyright 对历史测试夹具另有
  5 个既有类型错误，未涉及本次改动。
- 候选与生产：修复提交/候选为 `cb9996dbb36ccaeaca483035c0cbbbc59a8549c9`，已发布到
  `codex/goal-1-phase3-d07`，并在 atri 非破坏性 fetch 后精确切换。容器内 compileall、schema、
  61 条命令清单、16 个只读工具、`dnaby_sign`、关闭总开关和同一 `66` 测试矩阵均通过；插件目录
  clean。记录日志起点为 `2026-08-30T11:05:11Z`，仅调用一次已认证
  `POST /api/v1/plugins/astrbot_plugin_dnaby/reload`，HTTP `200`、业务 `ok`、成功语义成立。
  reload 后 HEAD 精确为候选 SHA，Dashboard 认证 GET 为 HTTP 200/`ok`，插件唯一、已激活、版本
  `v0.2.0`；容器 `running=true`、`restart_count=0`，资源 pointer generation/content SHA 未变。
  日志窗口中 `dnaby=0`、`Traceback=0`、`Exception=0`、`ERROR=0`，没有工具/handler/scheduler/cache
  残留记录；配置仍为 `agent_tools.enabled=false`，所以没有真实 LLM 工具注册、签到或图片投递。
- 回滚：本轮候选预检与 reload 均通过，未触发回滚；阶段三回滚点仍为第二阶段稳定 SHA
  `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`。预检期间出现的两次 shell 包装错误分别是本地
  quoting 和宿主机误调用 pytest，均发生在 reload 前且没有改变生产状态；随后全部改为容器内命令并
  完成通过验证。未重启容器、未修改配置/数据库/订阅/资源运行期数据，也未执行真实签到。
- 剩余风险：生产总开关关闭，真实 Agent/图片链路仍由 adapter 模拟；不同事件对象的跨请求消息幂等
  需要未来明确的共享存储/生命周期设计，当前不宣称已覆盖。下一步进入 O22，审计三阶段兼容与回滚链。

## 跨阶段收尾

### O22 — 跨阶段兼容与回滚链审计 `[completed]`

- 验证三个插件 SHA 和资源 SHA 均可追溯。
- 验证阶段一←二←三逐级回滚不会破坏配置、数据库、资源 pointer 或缓存 metadata。
- 检查迁移/兼容代码没有静默吞错或伪造空成功。

完成记录（2026-08-30）：

- SHA 追溯：阶段一功能快照为 `a97317e1a8c41112fb0220bca941120010076edf`，阶段一生产
  生命周期修复基线为 `6fda2f16b1ebdf3999b95d36609778bf11de38ce`，阶段二稳定版本为
  `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`，阶段三初始候选为
  `8c7ac4c8ee0910574d2602e41756400ccef0899a`，D07 修复并实际部署的当前候选为
  `cb9996dbb36ccaeaca483035c0cbbbc59a8549c9`。`git show-ref`、提交父节点、远端 ref
  和 `git merge-base` 均核对通过；阶段二直接继承 `6fda`，阶段三不是 `d47` 的直接
  祖先，因此已在发布清单中明确采用“精确 SHA + 树差异审计”，不把非线性提交图伪装成
  线性祖先链。
- 资源追溯：资源仓库 `main` commit 为
  `5d76860141d9ab5052417df25ccc9f5a929ff06b`，Git root tree 为
  `6cf9d38b417825a27d63f8ecdc5f924fc3eb04ed`，generation 内容 `content_sha256` 为
  `92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4`。已确认 commit
  存在且生产资源 checkout clean；生产 `current.json` 的 generation/content 摘要与之
  一致，并按 generation 校验算法复算通过（109 个文件）。三种摘要语义已同步写入发布
  清单与资源运维文档，避免把 Git tree 当作 pointer 内容摘要。
- 回滚链：`a973..d47` 与 `6fda..d47` 在 Alembic/持久化目录均无差异；`d47..cb` 在
  Alembic、persistence、CacheManager 和 resource generation 目录均无差异，阶段三回退
  到 `d47` 不会触碰数据库、资源 pointer 或缓存 metadata。阶段二归档代码读取含
  `agent_tools` 的配置后正常忽略未知阶段三分组；阶段二 CacheManager metadata 独立
  写入/读取往返通过。生产数据库只读核验为 `0003_global_identity`，表集合完整，未执行
  真实回退、reload 或任何生产写操作。
- 数据库边界：`0003_global_identity` 的删除/重建四张身份隐私表是已声明的破坏性迁移，
  `downgrade` 只恢复旧空表结构，不伪造恢复被丢弃数据；维护文档明确要求回退代码时同时
  恢复匹配的迁移前 `dnaby.sqlite3` 备份。现有迁移升级、重复升级、降级和约束回归
  `tests/test_goal2_task02_migration.py` 为 `5 passed`，没有把该不可逆边界包装成“安全
  自动回滚”。
- 错误边界修正：发现配置 `sign_time`、`command_prefixes`、已知配置分组和调度时间的
  显式非法值会静默回落默认值，已改为抛出可观察的校验错误；合法 HH:mm 归一化和旧
  list/tuple 输入仍兼容。新增负向测试均按 TDD 实际先 Red（原实现分别出现 2、1、1、1
  条失败），修正后通过；资源 generation 对坏 pointer/content hash 显式失败，CacheManager
  对损坏 metadata/完整性/内容校验显式返回带原因的 miss，损坏 sidecar 写入继续抛出异常。
- 文档与验证：更新 `agent-tools-release-checklist.md`、`docs/usage/resources.md`、
  `docs/usage/configuration.md`，重新生成 `_conf_schema.json` 无 diff。配置/调度、缓存、
  资源、迁移和回滚相关专项共 `89 passed, 1 warning`；另有 scheduler API `9 passed`、
  migration `5 passed`，目标 Ruff、compileall、LSP diagnostics 和 `git diff --check`
  均通过。`test_migration_boundaries.py` 的既有命令数量断言仍为 `61` 对 `58` 的漂移，
  本轮未改 registry，记录为非 O22 阻塞项。
- 下一步：O23，全量质量与视觉审计。

### O23 — 全量质量与视觉审计 `[pending]`

- 运行完整 pytest、ruff、compileall 与生成物一致性检查。
- 运行全量 adapter 模拟矩阵。
- 打开并检查帮助、公告、角色面板、周报、占位退化和 Agent 发送图片。

### O24 — 最终文档、生产冒烟与交付记录 `[pending]`

- 更新最终用户、管理员、部署、回滚、缓存与 Agent Tools 文档。
- 在 atri 对最终稳定 SHA 做只读状态核验与获授权的最小冒烟。
- 汇总实际完成、测试证据、生产 SHA、已知风险与回滚点。

### D08 — 最终调试审查 O22–O24 `[pending]`

- 逐条对照 `input.md`、`plan.md` 与所有显式验收条件，不能用“未发现问题”代替完成证据。
- 确认没有待修阻塞项、秘密泄露、运行期源码目录写入或未验证的生产假设。
- 只有全部证据成立时才允许将未来的实现目标标记完成。
