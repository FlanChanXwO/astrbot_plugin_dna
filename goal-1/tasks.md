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

### D02 — 调试审查 O04–O06 `[pending]`

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
- D02 仍保持 `[pending]`：本地修复及候选验证已完成，但尚未取得本轮新的“推送候选 ref、在 atri 切换精确 SHA 并 reload”的明确授权；本轮未修改生产环境、未调用新的生产 reload，O07 不启动。

## 第二阶段：资源、下载、卡片与公告缓存

### O07 — CacheManager 契约与核心状态机 `[pending]`

- 先写 fresh/stale/miss、sidecar metadata、内容哈希、tags、资源版本、租约和并发 Red 测试。
- 实现统一 CacheManager 与可配置 TTL，不接入具体业务。
- 验证失败/空/不可解码内容永不成为成功缓存。

### O08 — ResourceManager 不可变快照与后台预热 `[pending]`

- TDD 实现 staging 下载、manifest/路径/哈希/图片验证、原子 active pointer 和 single-flight。
- 启动后台预热；“下载全部资源”加入并等待同一任务。
- 终止时正确取消后台任务，不残留锁与临时目录。

### O09 — ImageFetcher 重试、原子下载与资源包拆分 `[pending]`

- TDD 实现瞬态错误初次加 2 次重试、1/2 秒退避和 `Retry-After`，明确非重试错误。
- 临时文件写入、PIL 校验、原子替换与 single-flight。
- 整理公共基础资源和账号补充资源边界，禁止秘密进入公共资源仓库。

### D03 — 调试审查 O07–O09 `[pending]`

- 重点检查锁顺序、取消、进程崩溃、原子性、目录穿越、失败缓存与秘密泄露。
- 运行并发/故障注入测试及相关静态检查。
- 记录资源 repo 与插件 repo 的版本耦合方式。

### O10 — 角色数据和卡片缓存接入 `[pending]`

- TDD 接入 30 分钟 fresh、24 小时 retention、stale 刷新与完整旧卡回退。
- 缺图允许本次占位发送，但标记 incomplete 且不写入/覆盖完整缓存。
- 关联数据、面板、素材版本和 tags，确保精准失效。

### O11 — 刷新命令、全量角色缓存清理与渲染租约 `[pending]`

- TDD 实现用户指定角色刷新、管理员 UID+角色刷新、管理员全量角色缓存清理。
- 接入 `cache.refresh_send_card`。
- 清理 `rendered/` 孤儿和过期缓存，同时保护在发送文件；针对已观测 741 MB 增长建立回归测试。

### O12 — 公告完整显示、分页、多图与缓存 `[pending]`

- TDD 修复公告查询参数/hash URL、完整分页、详情与多图同一回复。
- 去除前 20 条等无依据截断。
- 公告卡与源图仅完整时缓存，24 小时 TTL 加 fingerprint 提前失效。

### D04 — 调试审查 O10–O12 `[pending]`

- 检查 incomplete 结果是否可能污染完整缓存、租约是否泄露、精准刷新是否误删他人数据。
- 对公告做分页、URL、部分图片失败、上游变化和缓存过期故障注入。
- 实际打开代表性公告、角色卡、占位图与多图结果。

### O13 — 第二阶段文档、配置、投影与完整门禁 `[pending]`

- 更新 cache/resource/announcement 配置 schema 和文档。
- 重新生成相关投影，运行完整 pytest、ruff、compileall。
- 验证 data_dir 边界、无插件目录运行期写入。

### O14 — 公共资源仓库独立版本与审查 `[pending]`

- 对公共资源仓库做 manifest、许可证/来源、秘密与可解码性审查。
- 形成独立资源 commit SHA；插件只引用已验证版本。
- 使用 `code-review-expert` 审查插件第二阶段改动并修复阻塞项。

### O15 — 第二阶段插件 SHA、atri 热重载与视觉验收 `[pending]`

- 形成第二阶段独立插件 SHA，记录上一稳定 SHA。
- 按 `plan.md §4.2` 部署、定向 reload、核对资源 active pointer 与后台任务单例。
- 运行缓存/刷新/公告 adapter E2E，复制并实际查看所有代表性图片。

### D05 — 调试审查 O13–O15 `[pending]`

- 核对资源 SHA、插件 SHA、生产 active pointer、缓存 metadata 与清理结果一致。
- 检查热重载后 downloader、cleanup loop、公告 scheduler 是否重复。
- 做一次受控失败回滚演练并记录恢复证据。

## 第三阶段：Agent Tools

### O16 — 可复用领域查询层与 AstrBot 工具适配边界 `[pending]`

- 先写工具与聊天命令共享领域 use case 的 Red 测试，避免复制 handler 逻辑。
- 建立 typed request/result 与 `AstrAgentContext.event` 身份提取。
- 验证本地 4.27.1/生产 4.27.4 API 差异并做最小兼容。

### O17 — 纯查询工具、JSON envelope 与可选图片 `[pending]`

- TDD 注册已批准的玩家、角色、体力、周报、日历、wiki、攻略、兑换码、目录、梦魇、公告和订阅查看工具。
- 默认返回 `ok/kind/data/cache/error` JSON。
- `send_image=true` 时直接发给当前用户，工具结果只返回 `image_sent`，不泄露本地路径。

### O18 — 签到工具、明确确认、幂等与生命周期 `[pending]`

- TDD 实现原始消息肯定意图/否定排除、消息 ID 幂等、当前用户当前 UID 限制。
- 使用 fake transport 验证签到，不执行真实签到。
- `agent_tools.enabled` 控制全部注册；initialize/terminate 与热重载无重复工具。

### D06 — 调试审查 O16–O18 `[pending]`

- 针对身份伪造、prompt 注入、模型伪造确认、工具重试和跨用户访问做负向测试。
- 检查所有写工具是否仅剩经批准的签到，且无管理/账号/订阅写操作。
- 核对图片发送失败不会伪装为成功。

### O19 — 第三阶段文档、配置与完整门禁 `[pending]`

- 更新 Agent Tools 列表、参数、返回契约、身份与签到安全说明。
- 更新配置 schema，验证关闭总开关时零工具注册。
- 运行完整 pytest、ruff、compileall。

### O20 — 第三阶段审查与独立 SHA `[pending]`

- 自审并使用 `code-review-expert`，修复阻塞问题。
- 形成第三阶段独立插件 SHA，记录第二阶段稳定 SHA。
- 准备工具 adapter 模拟与回滚清单。

### O21 — 第三阶段 atri 热重载与工具验收 `[pending]`

- 按 `plan.md §4.2` 精确 SHA 部署和定向 reload。
- 验证工具只注册一次、身份来自事件、查询 JSON 正确、可选图片能直接发送。
- 签到只使用 fake transport/模拟，不触发真实副作用。

### D07 — 调试审查 O19–O21 `[pending]`

- 检查生产日志、工具枚举、handler/scheduler 与缓存任务是否重复或残留。
- 运行跨用户、否定意图、重复消息、图片失败与关闭开关回归。
- 阶段三不稳定时回滚第二阶段 SHA。

## 跨阶段收尾

### O22 — 跨阶段兼容与回滚链审计 `[pending]`

- 验证三个插件 SHA 和资源 SHA 均可追溯。
- 验证阶段一←二←三逐级回滚不会破坏配置、数据库、资源 pointer 或缓存 metadata。
- 检查迁移/兼容代码没有静默吞错或伪造空成功。

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
