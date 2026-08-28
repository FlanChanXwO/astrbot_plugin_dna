# Goal 2 任务清单

## 执行规则

- 每轮开始必须全量读取 `goal-2/input.md`、`goal-2/plan.md`、`goal-2/tasks.md`。
- 每轮只执行第一个未完成的普通 task 或集中检查 task，不合并、不跳序。
- 每个代码 task 必须 TDD：先运行目标测试并确认 Red，再实现 Green，最后 Refactor。
- 完成前必须基于 diff、测试、诊断、构建或浏览器证据自检；有代码改动则提交独立 commit。
- 完成后填写该 task 的“实际工作 / 验证证据 / 剩余风险 / 下一步”，再停止本轮。
- 每三个普通 task 后必须执行紧随其后的集中检查-debug 循环。

---

## Task 01 — 固化设计规格与基线

- 状态：`[x] completed`
- 目标：将已批准设计写入 `docs/superpowers/specs/2026-08-28-dnaby-pages-management-design.md`，核对当前 git 状态、测试入口、AstrBot 4.27.1 Pages 契约和参考页面许可；不修改业务行为。
- 验收：规格完整覆盖四页、全局身份、破坏性迁移、明文凭据、调度 tombstone、aiocqhttp 探测、级联删除、别名 custom 层和回滚；基线相关测试结果被记录。
- 实际工作：
- 新增 `docs/superpowers/specs/2026-08-28-dnaby-pages-management-design.md`，固化四个功能区、明确非目标、全局跨 Bot 身份、管理预览、调度器 tombstone、成员探测、级联清理、别名 custom 层、API/bridge 边界、安全和回滚设计。
- 读取 `docs/README.md`、`docs/porting/design.md`、当前架构/数据模型、`src/entry/web.py`、现有入口契约测试和 RSSHub 本地参考页面；确认参考页采用本地 PetiteVue/Chart.js，Chart.js 有 MIT 许可文件，仓库根为 AGPL。本目标只借鉴视觉，不复制业务代码，也不引入 Chart.js。
- 使用本地 `.venv` 核实 AstrBot 版本为 `4.27.1`，记录 `Context.register_web_api` 与 `astrbot.api.web` 的公共契约；同时核对官方 v4.27.1 Plugin Pages 文档和 PetiteVue 上游 MIT 许可来源。
- 验证证据：
- `.venv/bin/python -m pytest tests/test_entry_skeleton.py tests/test_migration_boundaries.py tests/test_write_contracts.py`：`61 passed, 5 warnings in 6.12s`。
- `.venv/bin/ruff check src/bootstrap.py src/entry tests/test_entry_skeleton.py tests/test_migration_boundaries.py tests/test_write_contracts.py`：`All checks passed!`。
- `.venv/bin/python -m compileall -q src main.py tests`：通过。
- 规格关键术语/约束自检全部命中；本 task 未修改业务代码。全仓 `ruff check .` 与 `git diff --check` 的既有问题、来源和范围已记录在规格基线章节，未在本轮擅自修复。
- 剩余风险：
- 工作树在本 task 开始前已有多处 Goal 1/用户修改；规格已记录 branch `main`、HEAD `1dd9c90` 和不覆盖原则。全仓 lint 与 diff-check 的既有失败仍待后续集中检查分类。
- PetiteVue 的最终 vendored 文件版本/许可副本留到 Task 13；Task 01 已锁定“固定版本 + MIT 文本 + 不使用 CDN”的要求。
- 下一步：
- Task 02：先为全局身份 schema 与破坏性迁移编写并实际运行 Red 测试，再实现 Alembic/ORM 变更。

## Task 02 — 全局身份 schema 与破坏性迁移

- 状态：`[x] completed`
- 目标：TDD 实现 Alembic revision 和 ORM 模型：账号/凭据按 `(user_id, uid)`，个人/群隐私移除 `bot_id`，每用户最多一个 active UID；明确清空四张旧表并保留 `sign_records`。
- 验收：旧 schema fixture 升级后四表为空且新约束正确；签到记录保留；迁移重复执行和 downgrade/回滚边界有明确测试或文档说明。
- 实际工作：
- 新增 `alembic/versions/0003_global_identity.py`：从旧 `0002` head 破坏性删除并重建 `account_bindings`、`credential_records`、`privacy_settings`、`group_privacy_settings`；不触碰 `sign_records`。降级只恢复 `0002` 的旧空表结构，不尝试恢复已丢弃的数据。
- 更新 `src/infrastructure/persistence/models.py`：四张身份/隐私表移除 `bot_id`；账号和凭据使用 `(user_id, uid)` 唯一键；个人隐私使用全局/群组作用域；群隐私按裸 `group_id` 唯一；账号增加每用户一个 active UID 的 SQLite 部分唯一索引；凭据脱敏表示同步移除旧 Bot 字段。
- 新增 `tests/test_goal2_task02_migration.py`，覆盖旧 schema fixture 的四表清空、签到保留、全局身份/active UID/隐私约束、重复升级无副作用和降级回滚边界。
- 同步 `docs/project/data-model.md`，明确当前 head、破坏性迁移、备份/回滚要求和 `EventActor.bot_id` 仅作运行期上下文。
- 验证证据：
- `.venv/bin/python -m pytest tests/test_goal2_task02_migration.py -q`：`5 passed`。
- `.venv/bin/ruff check src/infrastructure/persistence/models.py alembic/versions/0003_global_identity.py tests/test_goal2_task02_migration.py`：`All checks passed!`。
- `.venv/bin/python -m compileall -q src/infrastructure/persistence alembic/versions/0003_global_identity.py tests/test_goal2_task02_migration.py`：通过。
- `.venv/bin/python -m pytest tests/test_migration_boundaries.py -q`：`10 passed, 5 warnings`。
- 为执行真实 Alembic 测试，在本地 `.venv` 安装已由 `requirements.txt` 声明的 `alembic>=1.13.0`（实际 `1.19.1`）；未修改依赖清单或锁文件。
- 剩余风险：
- `repositories.py`、账号/隐私 service 和写命令仍处于旧 `bot_id` 调用契约，按 Task 03 处理；因此当前过渡状态下 `tests/test_persistence.py` 有 2 个旧 repository 用例失败，写入契约回归有 22 个旧调用失败，均已定位为下一个 task 的预期迁移面，未在本 task 越界修改。
- `0002_privacy_global_identity` 在进入 `0003` 前若遇到历史重复全局隐私行仍会显式失败；部署前需备份并审查旧 schema 脏数据。
- 下一步：
- Task 03：更新 repository、AccountService 和 PrivacyService 的全局身份签名、查询、写入与 active 切换。

## Task 03 — Repository 与全局账号/隐私服务

- 状态：`[x] completed`
- 目标：TDD 更新 repository、AccountService 和 PrivacyService 的身份签名、查询、写入、active 切换和事务约束，移除账号/隐私查询中的 `bot_id`。
- 验收：不同 Bot/平台事件对同一 `user_id` 读取同一绑定、凭据和隐私；不同用户仍隔离；身份键和 active 不变量由测试证明。
- 实际工作：
- 将账号绑定、凭据、个人隐私和群隐私 repository 全部改为全局身份签名，移除查询/写入中的 `bot_id`；更新账号登录、绑定、切换、删除、退出和状态查询 service。
- 更新 PrivacyService 的全局个人与群组策略读取、写入、回退和目标绑定检查；保留 `EventActor.bot_id` 作为事件上下文而不参与身份查询。
- `AccountBindingRepository.set_active()` 改为事务内先清零用户 active 状态再激活目标，避免 SQLite 部分唯一索引在 ORM 批量 flush 顺序下产生临时冲突。
- 新增 `tests/test_goal2_task03_global_identity.py`，覆盖跨 Bot 读取绑定/凭据/个人与群隐私、不同用户隔离和 active 切换；同步现有账号、隐私、持久化测试到新公共 API。
- 验证证据：
- 先运行新增 repository 测试确认旧实现因缺少 `bot_id` API 而失败（Red）；修正 active 切换后该垂直切片通过。
- `.venv/bin/python -m pytest tests/test_account.py tests/test_privacy.py tests/test_persistence.py tests/test_goal2_task03_global_identity.py -q`：`30 passed, 1 warning`。
- `.venv/bin/python -m pytest tests/test_write_contracts.py -q`：`40 passed, 3 failed`；剩余 3 项均为 CheckinService/签到 fixture 仍使用旧 repository `bot_id` 契约，留给 Task 04。
- `.venv/bin/ruff check src/infrastructure/persistence/repositories.py src/modules/account/service.py src/modules/privacy/service.py tests/test_goal2_task03_global_identity.py tests/test_account.py tests/test_privacy.py tests/test_persistence.py`：`All checks passed!`。
- `.venv/bin/python -m compileall -q src/infrastructure/persistence src/modules/account src/modules/privacy tests/test_goal2_task03_global_identity.py tests/test_account.py tests/test_privacy.py tests/test_persistence.py`：通过。
- Task 03 变更已提交：`65417b4 feat(goal-2): share account and privacy identities`；仅提交本 task 相关路径，未触碰其他未跟踪 goal/用户文件。
- 剩余风险：
- `Player/Encyclopedia/Checkin/Notices` 等后续消费者仍需把 repository 与 PrivacyService 调用切换为全局签名；在其完成前相关跨模块回归会失败或无法运行。
- 当前未提供 pyright 可执行文件；需在后续集中检查中使用项目可用类型检查工具或明确记录环境限制。
- 下一步：
- 集中检查 D01：复核 Task 01–03 的需求偏离、迁移丢弃范围、约束/事务、类型与回归证据，再进入 Task 04。

## 集中检查 D01 — Task 01–03

- 状态：`[x] completed`
- 检查：需求偏离、迁移数据丢弃范围、唯一约束、事务、LSP 诊断、相关 pytest、ruff、pyright、compileall、文档和回滚。
- 处理：发现问题立即修复或在末尾追加明确修复 task；不得带阻塞缺陷进入 Task 04。
- 实际工作：
- 对照 `input.md`、`plan.md`、Task 01–03 交付物和 `docs/project/data-model.md` 复核：四页管理面板、全局跨 Bot 身份、破坏性迁移、管理员凭据预览、调度 tombstone 等后续边界均未被本阶段提前实现或改变；Task 01–03 的当前范围没有发现需求偏离。
- 复核 `0003_global_identity` 的丢弃范围：仅重建 `account_bindings`、`credential_records`、`privacy_settings`、`group_privacy_settings`，保留 `sign_records`；downgrade 只恢复旧空表结构，不伪造已丢弃数据。备份要求、`0002` 历史重复隐私行的显式失败边界和 `EventActor.bot_id` 运行期语义均已写入数据模型文档。
- 复核全局约束与事务：账号/凭据 `(user_id, uid)`、隐私作用域唯一性、每用户单 active UID 均有 schema/实际数据库测试；`set_active()` 先清零再激活，避免 SQLite 部分唯一索引在同一 flush 中产生临时冲突。相关 repository、AccountService、PrivacyService 文件均无 `bot_id` 身份查询。
- 完成一个审查中发现的测试类型问题修正：Task 03 测试对未调用的 transport 使用明确的 `AccountTransport` cast；提交为 `820431d test(goal-2): satisfy account transport typing`。该修正不改变运行行为。
- 验证证据：
- `.venv/bin/python -m pytest tests/test_goal2_task02_migration.py tests/test_goal2_task03_global_identity.py tests/test_account.py tests/test_privacy.py tests/test_persistence.py tests/test_migration_boundaries.py -q`：`45 passed, 5 warnings`。
- `.venv/bin/python -m pytest tests/test_write_contracts.py -q`：`40 passed, 3 failed`；3 个失败均为计划中的 CheckinService/签到 fixture 仍传旧 `bot_id`，失败位置已确认属于 Task 04 的消费者迁移范围。
- `.venv/bin/ruff check .`、`.venv/bin/python -m compileall -q .`、`pre-commit run --all-files` 和 `/usr/bin/git diff --check` 均通过。
- `/opt/homebrew/bin/pyright --project pyrightconfig.json`：全仓仍有 `102 errors`，集中在既有 bootstrap/commands/operations、Player/Encyclopedia/Checkin/Notices 消费者及相关测试；Task 01–03 生产文件无诊断。针对 Task 01–03 文件和新增测试复跑后为 `0 errors, 0 warnings, 0 informations`。
- 当前工具集未暴露 LSP/blast-radius 能力，故以精确 `rg` 引用扫描、targeted Pyright、pytest 和编译检查替代；扫描确认 `EventActor.bot_id` 仍保留为运行期投递上下文，未进入全局身份表/服务查询。
- 剩余风险：
- 全仓 Pyright 的 102 个诊断以及写契约的 3 个 Checkin 失败尚未解决；它们不是 Task 01–03 的阻塞缺陷，Task 04 必须先完成跨模块消费者/transport 适配后再重新收敛。
- `0002_privacy_global_identity` 遇到历史重复全局隐私行时会在进入破坏性 `0003` 前显式失败；生产迁移仍必须先备份并审查旧数据，且回滚不能恢复被清空的四表内容。
- 本轮保留了工作区中已有的 README/docs、资源删除及其他 goal 未跟踪文件，未将其混入本 task 提交。
- 下一步：
- Task 04：迁移 Player、Encyclopedia、Checkin、Notices 消费者和 HTTP transport 到全局 `user_id + uid` 契约。

---

## Task 04 — 跨 Bot 消费者与 transport 适配

- 状态：`[x] completed`
- 目标：TDD 更新 Player、Encyclopedia、Checkin、Notices 凭据选择和各 HTTP transport，使其按全局 `user_id + uid` 读取，同时保留事件 `bot_id` 作为投递/legacy 上下文。
- 验收：从不同 Bot 触发玩家、百科、签到均使用同一账号；自动签到不重复处理旧 Bot 重复身份；密函任意凭据选择正常。
- 实际工作：
- 将 Player、Encyclopedia、Checkin、Notices service 的绑定与隐私读取切换为全局 `user_id + uid`；保留 Notices/Checkin 的 SubscriptionStore `bot_id` 作为投递上下文。
- 将四个 DnaApi transport 的凭据查询切换为全局键；`DNAUser.bot_id` 仍取当前事件 Bot，保证 legacy 请求上下文不丢失。`get_mh_any()` 遍历全局绑定并按凭据 fallback。
- 为无入站事件的自动签到与密函计划任务增加 `SCHEDULED_ACTOR_BOT_ID` 运行期 sentinel；它只用于 legacy actor，不写入全局身份表，并保留绑定的群上下文。
- 新增 `tests/test_goal2_task04_global_consumers.py`，覆盖不同 Bot 的玩家/百科/签到读取、全局自动签到遍历、四个 transport 的凭据与 legacy Bot 上下文、密函跨凭据 fallback；同步现有相关测试夹具到全局 repository API。
- 验证证据：
- 先运行新增跨 Bot 套件确认旧实现 Red：`9 failed, 1 warning`；实现后同一套件 `9 passed, 1 warning`。
- `tests/test_player_transport.py`、`tests/test_notices_transport.py`、`tests/test_goal2_task04_global_consumers.py`：`22 passed, 1 warning`。
- 相关 Checkin/transport/Notices subscription/write-contract 套件（排除已确认依赖外部 T2I 的通知图片用例）：`105 passed, 1 deselected, 1 warning`；`tests/test_player.py` 全文件：`15 passed, 1 warning`。
- 本轮生产代码与新增测试 targeted Pyright：`0 errors, 0 warnings, 0 informations`；变更文件 `ruff check`、文件级 `pre-commit`、`python -m compileall .` 与 `git diff --check` 均通过。
- 全仓 `ruff check .` 仍只命中既有 `.worktrees/rewrite-v0.1/tests/test_player_commands.py` 与 `dnaby/dna_sign/draw_sign.py`，未纳入本 task 修复。
- 剩余风险：
- 三个既有渲染用例在当前环境连接外部 `https://t2i.soulter.top` 被拒/超时（百科提及目标、默认密函卡片、密函推送图片），与本 task 身份查询改动无关；使用 fake renderer 的跨 Bot 套件已覆盖本 task 行为。
- legacy `DNAUser` 仍保留 `bot_id` 字段作为请求/渲染运行期上下文；全局身份表和相关 repository 不再持久化或按 Bot 查询。
- 当前工具集未提供 LSP/blast-radius 能力，本轮以精确引用扫描、targeted Pyright、pytest、ruff 和编译检查替代。
- 下一步：
- Task 05：新增 Admin 账号管理服务与完整明文凭据 DTO。

## Task 05 — Admin 账号管理服务与明文凭据 DTO

- 状态：`[x] completed`
- 目标：TDD 新增框架无关 AdminAccountService 和 DTO，支持列表、编辑来源群/active/全部 App-Web 凭据、删除单 UID/用户的预览；禁止创建账号和修改身份键。
- 验收：DTO 明文完整、普通 repr/日志仍脱敏；active 校验、重复更新、冲突和 no-store 响应契约均有测试。
- 实际工作：
- 新增 `src/modules/admin/contracts.py` 与 `src/modules/admin/service.py`，提供框架无关的 `AdminAccountService`、`AdminAccount`、`CredentialPayload`、`AdminAccountUpdate`、`DeletionPreview` 和统一 `AdminApiResponse`。
- `CredentialPayload` 覆盖全部 App/Web cookie、token、device code、d_num、refresh token 和状态字段；默认 `repr`、账号 DTO/patch 表示只显示状态与存在性，明文仅能通过显式 `to_plaintext_dict()` 导出。
- 账号列表默认只返回全局 `(user_id, uid)` 绑定及凭据状态；详情和更新返回完整明文 DTO。更新在已有绑定的同一事务内替换全部十个凭据字段，允许显式清空来源群/active，不创建账号；只读身份键回显不一致时返回 `conflict`。
- 删除 UID/用户仅生成包含受影响 UID、删除/保留资源和二次确认 payload 的 `DeletionPreview`，不执行删除。所有 admin response 固定附带 `Cache-Control: no-store`。
- 新增 `tests/test_goal2_task05_admin_accounts.py`，覆盖明文完整性与脱敏、全局列表、来源群/active/全量凭据更新、重复更新幂等、active/目标校验、身份冲突、未知账号拒绝、删除预览无副作用和 no-store。
- 验证证据：
- TDD Red：实现前运行新增测试，因 `src.modules.admin` 尚不存在而在收集阶段失败（`ModuleNotFoundError`）。
- TDD Green/回归：`.venv/bin/python -m pytest tests/test_goal2_task05_admin_accounts.py tests/test_persistence.py tests/test_account.py tests/test_goal2_task03_global_identity.py tests/test_goal2_task04_global_consumers.py -q`：`39 passed, 1 warning`。
- 按 runtime 根目录 Ruff 配置复核并修复 `tests/test_goal2_task05_admin_accounts.py` 的 `I001`：移除第三方导入与 `src` 导入之间多余的空行；定向 `.../.venv/bin/python -m ruff check data/plugins/astrbot_plugin_dnaby/tests/test_goal2_task05_admin_accounts.py --select I001` 通过。
- 插件目录全仓 `/Users/flanchan/.local/bin/ruff check .` 通过；runtime 根目录扫描整个插件仍报告 57 个既有、分布在其他文件的 `I001`/`RUF022`，本轮未扩大到 Task 05 之外。
- 2026-08-29 复核：Task 05 定向 pytest `39 passed, 1 warning`；runtime 根目录定向 `I001` 与插件目录全仓 Ruff 均通过。runtime 根目录全仓扫描仍包含其他历史文件及当前未提交 Task 12 文件的越界诊断，本轮不纳入 Task 05 修复范围。
- 定向 Pyright：`pyright --project pyrightconfig.json src/modules/admin tests/test_goal2_task05_admin_accounts.py`：`0 errors, 0 warnings, 0 informations`。
- 剩余风险：
- admin service 尚未注册 WebRoute；框架 adapter、认证上下文和实际 Dashboard 路由留给 Task 10/12，当前 service 不提供普通命令入口。
- 删除预览只描述影响范围，不执行 SQLite/JSON 级联；真实删除、membership probe 和 partial 状态留给后续 Task 07–09。
- no-store 是框架无关响应 metadata；HTTP handler 尚未接入，因此本 task 未声称已完成浏览器端缓存策略或前端 secret 生命周期。
- 下一步：
- Task 06：新增管理员完整玩家卡片预览 service，复用既有 transport/renderer 并固定绕过普通隐私链路。

## Task 06 — 管理员完整玩家卡片预览

- 状态：`[x] completed`
- 目标：TDD 新增 admin preview service，复用现有总览/详情 transport 与 renderer，固定完整 UID 显示并绕过 PrivacyService；支持选择角色和可选武器。
- 验收：基本卡和详情卡内容与命令渲染链一致；任意隐私设置下均完整渲染；上游失败分类安全；本地路径不出现在 API DTO。
- 实际工作：
- 新增框架无关的 `AdminPreviewService`、`AdminPreviewRequest` 与 `AdminPreviewImage`；以全局 `(user_id, uid)` 绑定确认目标身份，不读取或修改个人/群隐私设置。
- 总览复用 `PlayerTransport.get_overview` 与现有 renderer，详情复用角色/武器/伤害 transport 与 `render_detail`；固定传入 `uid_hidden=False`、`show_unowned=True`，支持角色别名和最多两种武器选择，并始终把目标 `user_id` 作为凭据归属传递。
- 预览结果在 service 内读取为 base64 图片 DTO，`repr`/`to_dict` 不暴露 renderer 本地路径；统一附带 `Cache-Control: no-store`，上游、渲染和空图片失败分别返回安全的 `upstream`/`internal` 错误。
- 新增 `tests/test_goal2_task06_admin_preview.py`，覆盖隐私旁路、完整 UID、跨全局身份参数、角色/武器选择、失败脱敏、未绑定身份和空图片拒绝。
- 验证证据：
- TDD Red：实现前运行 `tests/test_goal2_task06_admin_preview.py`，因尚不存在 `AdminPreviewImage` 导致收集阶段 `ImportError`；实现后定向套件 `6 passed, 1 warning`。
- `.venv/bin/python -m pytest tests/test_goal2_task06_admin_preview.py tests/test_goal2_task05_admin_accounts.py tests/test_player_transport.py -vv`：`17 passed, 1 warning`。
- `.venv/bin/python -m pytest tests/test_persistence.py tests/test_account.py tests/test_goal2_task03_global_identity.py tests/test_goal2_task04_global_consumers.py -q`：`32 passed, 1 warning`。
- `/Users/flanchan/.local/bin/ruff check .`：`All checks passed!`；`/opt/homebrew/bin/pyright --project pyrightconfig.json src/modules/admin tests/test_goal2_task06_admin_preview.py`：`0 errors, 0 warnings, 0 informations`；全仓 `python -m compileall -q .` 通过。
- `tests/test_player.py` 单文件实际为 `12 passed, 3 failed`；3 项均在既有 `PlayerRenderer` 的 T2I 返回不可解码 JPEG 链路失败，未触及本 task 文件，已保留为环境/既有回归风险。
- 剩余风险：
- Admin preview service 尚未接入 WebRoute、认证上下文和 Dashboard 页面，留给后续 Task 10/12–16；当前 service 只提供框架无关管理用例。
- 真实 `PlayerRenderer` 详情路径仍受现有 T2I 测试环境返回不可解码 JPEG 影响；不改变普通玩家命令，也不在本 task 扩大到渲染器/T2I 修复。
- 下一步：
- 集中检查 D02：复核 Task 04–06 的跨 Bot 回归、transport 契约、凭据/图片路径泄露、隐私旁路边界和真实渲染验证。

## 集中检查 D02 — Task 04–06

- 状态：`[x] completed`
- 检查：跨 Bot 回归、transport 契约、凭据泄露、隐私旁路仅限管理 API、图片生命周期、相关 pytest/ruff/pyright/compileall。
- 处理：发现问题修复或追加 task；不得以 fixture 占位冒充真实渲染契约通过。
- 实际工作：
- 对照 `goal-2` 设计、Task 04–06 交付物和调用链复核：账号/凭据 repository 查询已统一使用全局 `user_id + uid`；`EventActor.bot_id` 只保留为事件投递和 legacy `DNAUser` 上下文；Player、Encyclopedia、Checkin、Notices 的跨 Bot 消费者与 transport 没有恢复 Bot 隔离。管理预览仅从已认证请求提供的身份键读取绑定，不调用 `PrivacyService.resolve_query()`。
- 发现并修复管理预览图片生命周期缺口：`AdminPreviewService` 读取 renderer 生成的 base64 后原先未释放运行期图片。`RenderedPlayerImage` 增加显式 `temporary` 所有权标记，`PlayerRenderer` 生成结果标记为临时文件，管理预览读取后立即清理；未标记为临时的资源路径不会被服务删除，清理失败会返回 `internal` 而非伪造成功。
- 新增 `tests/test_goal2_d02_review.py`：使用真实 `HtmlRenderer`、真实 `PlayerRenderer` 和合法 JPEG T2I 替身验证总览/详情模板、完整 UID、管理隐私旁路、全局凭据身份和临时图片清理；没有用假的 renderer 结果冒充渲染链通过。同步 Task 06 的 renderer fixture 标记临时文件所有权。
- 验证证据：
- 生命周期测试先实际复现 Red：服务返回成功但 `rendered/` 仍残留生成图片；修复后 `.venv/bin/python -m pytest tests/test_player_transport.py tests/test_notices_transport.py tests/test_goal2_task04_global_consumers.py tests/test_goal2_task05_admin_accounts.py tests/test_goal2_task06_admin_preview.py tests/test_goal2_d02_review.py -q`：`36 passed, 1 warning`。
- `/Users/flanchan/.local/bin/ruff check .`：`All checks passed!`；`/opt/homebrew/bin/pyright --project pyrightconfig.json src/infrastructure/rendering/player.py src/modules/admin/preview.py tests/test_goal2_task05_admin_accounts.py tests/test_goal2_task06_admin_preview.py tests/test_goal2_d02_review.py`：`0 errors, 0 warnings, 0 informations`；`.venv/bin/python -m compileall -q .`：通过。
- 精确引用扫描确认相关 `AccountBindingRepository`、`CredentialRepository` 和 `PrivacyService` 身份查询未重新引入 `bot_id`；Task 04/05/06 的 transport、凭据脱敏、管理 no-store、隐私旁路和 DTO 路径隐藏契约均有相关测试覆盖。
- 剩余风险：
- `tests/test_player.py` 仍为 `12 passed, 3 failed`；失败都在既有真实详情渲染用例的外部 T2I 返回不可解码 JPEG 链路，未触及 Task 04–06 生产改动，后续需在合适的渲染/T2I 任务中处理或隔离环境依赖。
- Admin preview 仍是框架无关 service，WebRoute、认证上下文和 Dashboard overlay 留给 Task 10/12–16；后续 renderer 若返回合成临时文件也必须设置 `temporary=True` 才会启用 service 清理。
- 当前工具集未提供 LSP/blast-radius 能力，本轮以精确引用扫描、targeted Pyright、pytest、ruff 和 compileall 替代；未发现属于 D02 的阻塞问题。
- 下一步：
- Task 07：实现用户级联删除协调器，覆盖 SQLite/JSON 的幂等、部分失败和共享 UID 签到历史清理。

---

## Task 07 — 用户级联删除协调器

- 状态：`[x] completed`
- 目标：TDD 实现删除计划预览和幂等协调器，覆盖绑定、凭据、个人隐私、个人密函订阅及所有关联 UID 签到历史；群级订阅和群隐私不误删。
- 验收：强制签到历史删除（含共享 UID）被测试证明；SQLite/JSON 部分失败返回逐项状态，可安全重试；确认 payload 必须匹配目标 user ID。
- 实际工作：
- 新增 `AccountDeletionCoordinator` 及 `DeletionExecution`/`DeletionStepResult` 契约；复用 Task 05 的 UID/用户删除预览，并在执行前严格校验删除范围、确认 payload 与目标 `user_id`，不匹配时不产生副作用。
- SQLite 级联删除在单事务内处理账号绑定、凭据、用户级个人隐私和计划快照中的全部 UID 签到历史；单 UID 删除强制清除该 UID 的全局签到历史，即使该 UID 仍被其他用户绑定。群隐私、群订阅、群结果和通知资源明确以 `preserved` 逐项返回。
- 新增签到历史批量删除与个人隐私删除 repository；新增 `SubscriptionStore.delete_personal_subscriptions()`，只删除指定用户的个人密函记录（`type + user_id + uid` 精确匹配），JSON 写盘失败时恢复内存快照，允许同一计划安全重试。
- SQLite 提交后才执行 JSON 步骤；数据库回滚返回 `failed` 并跳过 JSON，JSON 失败返回 `partial` 和逐项状态，重复执行返回 `already_absent` 或完成状态。响应不包含异常原文或存储路径。
- 验证证据：
- TDD Red：先运行 `tests/test_goal2_task07_deletion.py`，因尚不存在 `AccountDeletionCoordinator` 在收集阶段 `ImportError`；实现后同一套件 `4 passed, 1 warning`。
- 受影响回归：`tests/test_goal2_task07_deletion.py tests/test_subscription_store.py tests/test_persistence.py tests/test_account.py tests/test_goal2_task03_global_identity.py tests/test_goal2_task04_global_consumers.py tests/test_goal2_task05_admin_accounts.py tests/test_goal2_task06_admin_preview.py`：`54 passed, 1 warning`。
- `/Users/flanchan/.local/bin/ruff check .`：`All checks passed!`；定向 Pyright（Task 07 生产文件及测试）：`0 errors, 0 warnings, 0 informations`；`.venv/bin/python -m compileall -q .` 与 `git diff --check`：通过。
- 测试覆盖确认：错误确认串无副作用；用户删除清理全部关联 UID、个人隐私和个人密函并保留群级资源；共享 UID 的签到历史强制删除；SQLite 回滚不触碰 JSON；JSON partial 可用原计划重试。
- 剩余风险：
- SQLite 与 `subscriptions.json` 仍无法共享同一物理事务；协调器仅提供串行、逐项状态、内存回滚和原计划重试语义，无法把跨存储操作提升为原子提交。
- 成员探测、删除前跨群二次复核、认证 Web adapter 和 Dashboard 路由留给 Task 09/10/12；当前协调器为框架无关 service。
- 当前工具集未提供 LSP/blast-radius 能力，本轮以精确引用扫描、定向 Pyright、pytest、ruff、compileall 和 diff 检查替代。
- 下一步：
- Task 08：建立四个内置任务 registry、可观测调度状态、暂停/恢复和不可恢复 tombstone。

## Task 08 — 调度器可观测状态、暂停与 tombstone

- 状态：`[x] completed`
- 目标：TDD 建立四个内置任务 registry、timezone-aware `next_run_at`、运行/暂停/异常状态、暂停/恢复控制和 `scheduler_state.json` 原子 tombstone。
- 验收：注入时钟下四任务时间准确；三个业务任务永久删除后重启不再创建且列表隐藏；清理任务拒绝永久删除；无恢复 API。
- 实际工作：
- 新增共享 `SchedulerRegistry`、`SchedulerTaskDefinition`、`SchedulerTaskSnapshot` 和 `SchedulerStateStore`，统一登记每日自动签到、签到记录清理、密函推送、公告轮询四个内置任务；快照提供 `id/name/state/schedule/next_run_at/targets/can_pause/can_delete`，异常状态只保留安全固定文案。
- 两个 scheduler 的 loop 均在睡眠前登记带时区的 `next_run_at`，执行异常进入 `error`、成功恢复 `running`；提供暂停/恢复/永久删除控制，并在 pause/delete 时取消对应 asyncio task，重复 start/stop 保持幂等。
- `scheduler_state.json` 只保存业务任务永久删除 tombstone，使用临时文件替换；写盘失败恢复内存状态。启动加载 tombstone 后过滤任务列表并跳过任务创建；签到记录清理标记为不可永久删除，未提供 restore API。
- bootstrap 创建运行期 data root 下的共享 registry 并注入两个 scheduler，暴露 `scheduler_registry` service；同时修正生命周期 stop hook 声明，使 `PluginLifecycle` 逆序执行时先停 scheduler、后释放数据库。
- 验证证据：
- TDD Red：先运行 `tests/test_goal2_task08_scheduler_state.py`，因尚不存在 `src.infrastructure.scheduler_state` 在收集阶段 `ModuleNotFoundError`；实现后专项套件 `6 passed, 1 warning`。
- 相关回归：`tests/test_goal2_task08_scheduler_state.py tests/test_scheduler.py tests/test_notices_scheduler.py tests/test_config.py tests/test_entry_skeleton.py tests/test_migration_boundaries.py`：`52 passed, 5 warnings`。
- `/Users/flanchan/.local/bin/ruff check .`：`All checks passed!`；本轮文件 Ruff format check 通过；定向 `/opt/homebrew/bin/pyright --project pyrightconfig.json ...`：`0 errors, 0 warnings, 0 informations`；`.venv/bin/python -m compileall -q .`、`git diff --check`：通过。
- 专项测试实际证明：四任务 registry 与重启隐藏 tombstone、cleanup 永久删除拒绝、暂停/恢复、每日下一次运行时间、异常状态脱敏、tombstone 写盘失败保留旧文件，以及 bootstrap 共享 registry wiring。
- 剩余风险：
- 实际 Dashboard `tasks/*` API、任务目标编辑与认证错误映射留给 Task 10/12；当前 `targets` 是 scheduler 级目标类别，尚未呈现可编辑的具体群聊列表。
- aiocqhttp 成员探测、跨群二次复核和删除前安全门禁留给 Task 09；本 task 只负责调度状态与 tombstone，不执行成员判断。
- 跨进程/跨存储分布式锁不在当前 scheduler 范围；状态文件写入已在进程内串行并采用临时文件原子替换。
- 下一步：
- Task 09：实现 aiocqhttp 成员探测、三态结果、跨群复核和单群清理。

## Task 09 — aiocqhttp 成员探测与跨群复核

- 状态：`[x] completed`
- 目标：TDD 实现可注入 membership probe、aiocqhttp raw client 适配、capability 判定、三态结果、关联群扫描、单群清理和全局删除前二次复核。
- 验收：present/absent/unknown、API/网络/平台失败、非 aiocqhttp 禁用、任一 unknown 阻止全局删除、群内个人订阅精确清理由 fake client 覆盖。
- 实际工作：
- 新增 `src/modules/admin/membership.py`：提供可注入 `MembershipProbe`、`MembershipCapability`、`MembershipProbeResult` 三态 DTO、跨账号绑定/个人密函订阅的关联群扫描、单群清理和全局删除前强制全量二次扫描；`unknown`、`present`、`unsupported` 均不会越过删除安全门禁。
- 新增 `AiocqhttpMembershipProbe`：仅接受 aiocqhttp/OneBot V11 raw client，调用 `get_group_member_list`，严格解析 list/响应包装；API、网络、平台及不完整响应统一返回 `unknown`，非 aiocqhttp 明确 disabled。bootstrap 暴露 `membership_probe` 与 `membership_service`，供后续 Admin API adapter 使用。
- 为 `SubscriptionStore` 增加用户 + 群 + `uid` + `user_type=group` 的个人密函精确删除方法，保留其他群、私聊、公告和其他用户记录，并沿用 JSON 原子写失败回滚语义。
- 新增 `tests/test_goal2_task09_membership.py`，覆盖 raw client 三态、失败映射、非 aiocqhttp 禁用、关联群扫描、单群精确清理、unknown/过期扫描阻止全局删除、全 absent 才委托协调器和 bootstrap wiring。
- 验证证据：
- TDD Red：初次运行 Task 09 专项测试在收集阶段因 membership 类型尚未导出而 `ImportError`；新增“无关联群仍禁用非 aiocqhttp”和“raw client 不得覆盖 discord 平台”边界测试后分别实际得到失败，再实现后转 Green。
- `.venv/bin/python -m pytest tests/test_goal2_task09_membership.py -q`：`17 passed, 1 warning`。
- 相关回归 `.venv/bin/python -m pytest tests/test_goal2_task07_deletion.py tests/test_goal2_task08_scheduler_state.py tests/test_subscription_store.py tests/test_notices_subscriptions.py tests/test_subscriptions.py tests/test_config.py -q`：`55 passed, 1 warning`。
- `/Users/flanchan/.local/bin/ruff check .`、Task 09 生产文件的 runtime-root Ruff、`/opt/homebrew/bin/pyright --project pyrightconfig.json` 定向文件检查、`.venv/bin/python -m compileall -q src main.py tests` 和改动文件 LSP diagnostics：均通过；定向 Pyright 为 `0 errors, 0 warnings, 0 informations`，改动 Python 文件 LSP 为 `0 diagnostics`。
- 剩余风险：
- 成员状态与删除协调器之间仍存在跨平台 API 的自然 TOCTOU 窗口；实现已保证删除前立即重新扫描，但无法把外部群成员状态与 SQLite/JSON 操作组成同一事务。SQLite 与 `subscriptions.json` 的跨存储部分失败仍由既有协调器以逐项状态和可重试语义处理。
- 生产成员探测当前刻意限定 aiocqhttp/OneBot V11；其他平台前后端均禁用。实际 `members/*` API、认证错误映射和 Dashboard 按钮留给 Task 10/12/14。
- 下一步：
- Task 10：实现任务、目标与成员 Admin API，并接入统一认证/错误映射。

## 集中检查 D03 — Task 07–09

- 状态：`[ ] pending`
- 检查：删除安全、跨存储一致性、永久 tombstone、下一次运行时间、探测误判、平台能力、敏感日志、相关门禁。
- 处理：重点验证失败不被伪装成 absent/success；发现问题修复或追加 task。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：

---

## Task 10 — 任务、目标与成员 Admin API

- 状态：`[x] completed`
- 目标：TDD 暴露任务快照、调度参数更新、暂停、恢复、永久删除、现有目标更新/删除、成员扫描和清理 API；不允许创建任务。
- 验收：任务 ID allowlist、typed settings 校验、不可删除维护任务、不可恢复 tombstone、partial/unsupported/upstream 错误契约均通过 API 测试。
- 实际工作：
- 新增 `src/modules/admin/api.py`，提供框架无关的 `AdminApiService`、`TaskSnapshot`、`TaskTarget` 和 `TaskTargetUpdate`；任务 API 只接受四个内置任务 ID，提供列表、严格 schedule 更新、暂停、恢复和永久删除，不提供创建/恢复入口。
- 调度 registry 增加原子定义更新；每日签到/清理、密函推送、公告轮询复用 typed settings 边界校验，成功更新后重建运行中的 loop 并清空旧 `next_run_at`，已配置的签到/通知参数同步回配置存储。
- 订阅存储增加保持 `(type, unified_msg_origin, uid)` 身份键不变的原子目标替换；Admin API 支持按任务过滤目标、更新路由元数据/附加字段和删除现有目标，写盘失败显式返回 `internal`。
- Admin API 委托 Task 09 membership service，保留 `unsupported`、`partial`、`upstream` envelope；bootstrap 暴露共享 `admin_api_service`，本 task 不注册 WebRoute，认证和 HTTP 映射留给后续 task。
- 新增 `tests/test_goal2_task10_admin_api.py`，覆盖 allowlist、typed schedule 校验、运行中重排、配置失败回滚、维护任务删除拒绝、tombstone 不可恢复、目标原子更新/删除、bootstrap wiring 和成员错误契约。
- 验证证据：
- TDD Red：首次运行 Task 10 专项测试在收集阶段因 `AdminApiService` 尚未导出而实际 `ImportError`；实现后转 Green。
- runtime `.venv/bin/python -m pytest tests/test_goal2_task10_admin_api.py -q`：`9 passed, 1 warning`。
- 相关回归（Task 03--09、账号/隐私/持久化、scheduler/notices、订阅、配置、entry、migration、write contracts）：`177 passed, 5 warnings`。
- `/Users/flanchan/.local/bin/ruff check .`、定向 `ruff format --check`、定向 `/opt/homebrew/bin/pyright --project pyrightconfig.json`、`.venv/bin/python -m compileall -q src main.py tests`、`git diff --check`、改动文件 LSP diagnostics 和显式 `pre-commit run --files ...`：均通过。
- 包含未改动 `tests/test_notices_subscriptions.py` 的更宽回归另有 `147 passed, 4 failed`；失败均发生在既有渲染/外部图片链路（T2I 返回不可解码图片或既有 payload 类型断言），Task 10 改动文件无交集，未越界修复。
- 剩余风险：
- Task 12 仍需把该框架无关 service 接入 `/astrbot_plugin_dnaby/admin/*` WebRoute，并在 handler 层接入 AstrBot Dashboard 认证、HTTP 状态和 JSON 序列化；当前 service 本身不接收 request，也不应被视为认证边界。
- `dnaby_sign_cleanup` 当前没有 typed 配置字段，API 更新可立即影响当前进程但不会跨重启持久化；后续若产品需要持久化，应先补充明确的配置字段与 schema 测试。
- 目标 ID 固定现有订阅的类型/会话/UID，更新不允许把目标移动到另一身份；跨 SQLite、JSON 和外部成员状态仍不存在单一物理事务，失败保持可重试的显式 envelope。
- 下一步：
- Task 11：实现面板图与角色别名 Admin API；完成后再进入 Task 12 Web 路由、生命周期与认证。

## Task 11 — 面板图与角色别名 Admin API

- 状态：`[x] completed`
- 目标：TDD 暴露角色面板图元数据/按需图片/上传/单删/全删/压缩；建立 `alias_custom.json` 多值追加层、冲突校验和按角色/全部恢复。
- 验收：路径逃逸继续拒绝；默认 alias 文件无 diff；默认别名不可替换；custom 原子写、重复与跨角色冲突、恢复默认均有测试。
- 实际工作：
- 新增框架无关 `AdminPanelService` 及面板图元数据/按需载荷/上传、单删、确认式全删、全量压缩 DTO；`PanelService` 增加受 `panel_custom/` 根目录约束的安全文件操作，拒绝越界目录与越界符号链接。
- 新增 `AdminAliasService`，默认 `char_alias.json` 只读，角色 custom 多值追加写入运行期 `alias_custom.json`；完成默认别名保护、重复/跨角色冲突校验、原子替换写入、按角色/全部恢复，并让既有角色别名命令复用 custom 层。
- `EncyclopediaResourceStore` 启动时合并默认与 custom 角色别名；bootstrap 暴露 `admin_panel_service` 与 `admin_alias_service`，未提前注册 Task 12 Web 路由或认证边界。
- 验证证据：
- TDD Red：专项测试初次收集实际因 Admin alias 类型未导出触发 `ImportError`；custom 路径、默认文件保护、资源重载和非布尔全删确认测试均先实际失败，再实现转 Green。
- `.venv/bin/python -m pytest tests/test_goal2_task11_admin_assets.py -q`：`11 passed, 1 warning`；相关回归（Task 10、操作、alias IO、资源配置、写入契约）：`87 passed, 1 warning`。
- `/Users/flanchan/.local/bin/ruff check .`、定向 `ruff format --check`、定向 `/opt/homebrew/bin/pyright --project pyrightconfig.json`、`.venv/bin/python -m compileall -q src main.py tests`、`git diff --check` 和改动文件 LSP diagnostics：均通过（Pyright `0 errors, 0 warnings, 0 informations`，LSP `0 diagnostics`）。
- 额外安全回归确认 `confirmed` 必须为真正的 `True`，字符串等真值不能绕过全删二次确认。
- 剩余风险：
- Task 12 仍需把这些框架无关 service 接入 `/astrbot_plugin_dnaby/admin/*` WebRoute，并完成 Dashboard 认证、HTTP 状态和 JSON 映射；当前 service 本身不是认证边界。
- 武器别名旧命令仍保持既有实现，未纳入本 task 的角色 custom 层；默认资源仓库文件不由本 task 的角色管理 API 写入。
- 下一步：
- Task 12：实现 Admin Web 路由、生命周期与安全契约。

## Task 12 — Admin Web 路由、生命周期与安全契约

- 状态：`[x] completed`
- 目标：TDD 组装 `/astrbot_plugin_dnaby/admin/*` 路由，接入 WebRegistrar/bootstrap；统一 `AdminApiResponse`、错误映射、版本读取、Dashboard 请求能力和凭据 no-store。
- 验收：所有路由只注册一次、插件初始化/终止正常、无独立未认证入口、内部异常不泄露凭据或路径、原“无业务路由”测试按新契约更新。
- 实际工作：
- 新增 `src/entry/admin_web.py`，将账号/删除预览与执行、玩家总览/详情预览、任务/目标、成员探测/清理、面板图和角色别名的 37 个管理 API 路由统一适配到 AstrBot Dashboard extension dispatcher；所有 handler 先校验 `PluginRequest.username`，只解析请求和委托框架无关 service，不直接编排数据库/文件。
- 统一 JSON envelope、HTTP 状态、固定 no-store 与安全响应头；内部异常、未知 DTO 和下游错误不向浏览器传播异常文本、路径或凭据，凭据只在显式认证账号详情/列表请求中序列化。版本每次从 `metadata.yaml` 读取，成员 capability 失败不再伪装为“不支持”。
- 在 bootstrap 注入共享 deletion coordinator、admin account/preview service 和 37 条路由；WebRegistrar 仍负责单 runtime 幂等注册，生命周期重复 initialize/terminate 不重复注册，用户删除字面路径置于 UID 通配路由之前以符合 AstrBot `<param>` matcher。
- 更新入口/迁移边界测试和架构文档，使原“无业务路由”断言改为 Dashboard 路由唯一性与生命周期契约；新增 `tests/test_goal2_task12_web.py` 覆盖认证、路由冲突、错误映射、版本、明文凭据、异常脱敏、破坏性操作确认和 runtime wiring。
- 验证证据：
- TDD Red：新增测试首次收集因 `src.entry.admin_web` 不存在而 `ModuleNotFoundError`；审查补充的用户字面路由冲突与 bootstrap failure masking 测试分别实际失败，再修复为 Green。
- Task 12 定向：`.venv/bin/python -m pytest tests/test_goal2_task12_web.py -q`：`16 passed, 1 warning`。
- Goal-2 Task 03–12、入口/迁移和配置相关回归：`122 passed, 5 warnings`；警告为 AstrBot `audioop` 弃用及动态插件命名空间既有 `__package__` 弃用提示。
- `/Users/flanchan/.local/bin/ruff check .`、Task 12 文件 `ruff format --check`、`pyright --project pyrightconfig.json` 定向检查、`python -m compileall -q src main.py tests`、`git diff --check` 和显式 `pre-commit run --files ...`：均通过；Pyright `0 errors, 0 warnings, 0 informations`，LSP 对 adapter/bootstrap/Task 12 测试为 `0 diagnostics`。
- 使用 AstrBot 4.27.1 实际 dispatcher matcher 核验 37 条 `(path, method)` 唯一，确认 `accounts/users/*`、`aliases/restore-all` 等字面路径不会被动态路由抢先匹配。
- 剩余风险：
- 真实 Dashboard 页面、浏览器交互、移动端/暗色布局和前端 bridge 尚未实现，留给 Task 13–16；当前仅完成认证 API 边界和后端 wiring。
- runtime 根目录 Ruff 配置将插件内 `src` 归类不同于插件目录配置，整仓额外扫描仍包含范围外历史/未提交 Task 12 诊断；本 task 只按插件目录项目门禁收口，不扩修其他 task。
- 下一步：
- 集中检查 D04：复核 Task 10–12 的 API、鉴权、路由冲突、错误分类、缓存头、分层、生命周期和相关后端门禁。

## 集中检查 D04 — Task 10–12

- 状态：`[x] completed`
- 检查：API 契约、Dashboard 鉴权边界、路由冲突、错误分类、缓存头、服务分层、启动/停止、全量相关后端测试和静态检查。
- 处理：确认 handler 无业务编排和 secret 日志；发现问题修复或追加 task。
- 实际工作：
- 逐项复核 Task 10–12：Admin API 仅允许四个内置任务、任务删除/调度更新遵循 typed schedule 与 tombstone 边界，目标 ID 固定现有订阅的类型/会话/UID；面板文件操作继续受 `panel_custom/` 根目录和符号链接边界保护；角色默认别名只读，自定义别名独立写入运行期 custom 层。
- 复核 Dashboard handler：所有管理路由先校验已认证 `PluginRequest.username`，仅负责请求解析、service 委托和 DTO 序列化；没有数据库/文件业务编排、`print` 或异常/secret 日志。统一响应强制 `no-store`、安全响应头和安全错误文案，内部异常、未知 DTO 和路径信息不穿透 HTTP 边界。
- 使用 AstrBot 4.27.1 实际 matcher 复核 37 条 `(path, method)` 路由唯一性及字面路径优先级；核对 bootstrap、WebRegistrar、scheduler 和数据库 stop hook 的启动/逆序停止，重复 initialize/terminate 不重复注册或遗留任务。审查中发现的用户删除动态路由抢匹配、bootstrap 掩盖 membership capability 失败和错误文案原文回退问题均已在 Task 12 修复并有回归覆盖。
- 验证证据：
- Task 10–12、Task 03–09 及入口/迁移/配置相关回归：`.venv` runtime Python 执行 `pytest`，`122 passed, 5 warnings`；警告仅为 AstrBot `audioop` 弃用和动态插件命名空间 `__package__` 弃用提示。
- `/Users/flanchan/.local/bin/ruff check .` 通过；Task 10–12 变更的 21 个 Python 文件 `ruff format --check` 通过；相关源码与测试定向 Pyright 为 `0 errors, 0 warnings, 0 informations`；`compileall`、`git diff --check` 和显式 `pre-commit run --files ...` 均通过。
- 剩余风险：
- 真实 Plugin Pages 页面、浏览器交互和前端 bridge 尚未实现，属于 Task 13–16；本审查未扩大到前端。
- runtime 根目录与插件目录采用不同 Ruff 配置，根目录整仓扫描仍会包含范围外历史诊断；插件目录项目门禁已通过。当前仅有上述 5 条环境/动态导入弃用警告，无 D04 阻塞项。
- 下一步：
- Task 13：实现 Plugin Pages 基础壳、bridge 与样式系统。

---

## Task 13 — Plugin Pages 基础壳、bridge 与样式系统

- 状态：`[x] completed`
- 目标：TDD/静态契约先行创建 `pages/dashboard/`，接入 PetiteVue、bridge API wrapper、四项导航、全局状态、toast/dialog/drawer、暗色和响应式样式；左下角显示后端版本。
- 验收：无 Node 构建链和 Chart.js；bridge 缺失显式报错；移动端导航可用；页面无帮助/首页统计；vendor 许可保留。
- 实际工作：
- 新增 `pages/dashboard/` 页面壳：四项导航（面板图、任务与探测、账号与预览、角色别名）、加载/错误/空状态、toast/dialog/drawer 和后端版本展示；Task 14/15 的业务区域保留为明确占位，不提前实现业务操作。
- 新增原生 ES module bridge/store/app：仅通过 `window.AstrBotPluginPage` 调用管理 API，bridge 缺失、方法缺失和统一错误均显式暴露；首次只读取 bootstrap，不在浏览器持久化数据或 secret。
- 复用本地参考页的 PetiteVue IIFE vendor，并随页保留 `petite-vue.LICENSE.md` MIT 许可文本；未引入 npm/build chain、CDN 或 Chart.js。
- 新增轻量自包含样式系统：浅色/系统暗色 token、白色卡片/蓝色主色、inline SVG 图标、桌面侧栏与移动端可展开的横向导航、44px 触控目标、focus-visible、loading spinner、overlay 层级和 reduced-motion 支持。
- 验证证据：
- TDD Red：`.venv/bin/python -m pytest tests/test_goal2_task13_pages.py -q` 在页面壳缺失时实际 `6 failed`；实现后同命令 `6 passed`，移动端菜单契约补强后再次 `6 passed`。
- 定向相关回归：`.venv/bin/python -m pytest tests/test_goal2_task*.py tests/test_entry_skeleton.py tests/test_migration_boundaries.py tests/test_config.py -q`：`133 passed, 5 warnings`。
- 全仓回归：`.venv/bin/python -m pytest -q`：`500 passed, 1 skipped, 5 warnings`；警告仅为 AstrBot `audioop` 弃用及动态插件命名空间 `__package__` 弃用提示。
- 依次执行 `node --check pages/dashboard/app.js`、`node --check pages/dashboard/js/bridge.js`、`node --check pages/dashboard/js/store.js`：均通过；`/Users/flanchan/.local/bin/ruff check .`、Task 13 测试 `ruff format --check`、`compileall -q src main.py tests`：均通过。
- 按 `ui-ux-pro-max` 执行设计系统与 UX 检索；已落实加载反馈、明确 overlay z-index、无装饰性无限动画、键盘焦点、移动断点与 reduced-motion。
- 剩余风险：
- 真实 AstrBot Plugin Pages 注入环境、桌面/移动/暗色视觉和跨页面实际交互仍留给 Task 16；业务页内容与读写确认流留给 Task 14/15。
- 页面依赖宿主注入 `AstrBotPluginPage`；未注入时会呈现明确错误，不提供静默网络回退。
- 下一步：
- Task 14：实现面板图、任务与离群扫描页面。

## Task 14 — 面板图、任务与离群扫描页面

- 状态：`[x] completed`
- 目标：实现角色面板图页和任务页，包括搜索、按需缩略图、上传/删除/压缩、任务状态/规则/next-run/目标、暂停/恢复/永久删除、探测与清理确认流。
- 验收：非 aiocqhttp 扫描按钮预先禁用并说明原因；不可恢复删除和全删二次确认；所有成功操作重新拉取服务端状态；移动端可操作。
- 实际工作：
- 扩展 `pages/dashboard/index.html` 的面板图区域：角色搜索/选择、元数据列表、按需读取图片、上传、单删、当前角色全删和全量压缩；不可恢复动作统一进入确认弹窗，图片引用只在读取后进入前端状态。
- 扩展任务区域：展示四个内置任务的状态、schedule、准确的 `next_run_at`、关联 targets，支持已有规则编辑、暂停/恢复和不可恢复 tombstone 删除；不提供任务创建入口。
- 集成离群用户探测：读取 capability 后仅在 `aiocqhttp`（OneBot V11）且填写 `user_id` 时启用扫描；结果保持 `present/absent/unknown` 三态，只有明确 absent 才能单群清理，只有后端允许的全 absent 结果才能进入全局删除预览和确认。
- 扩展 bridge/store API 映射及 factory 注入，覆盖 panel/task/target/membership 读写、文件上传和删除确认串；上传、删除、压缩、任务动作、群清理和用户删除成功后均重新读取服务端状态。
- 采用移动端单列/卡片布局、按需图片加载、加载/错误/空状态、44px 控件和确认成功 toast；未新增依赖、图表、分页或帮助管理。
- 验证证据：
- TDD Red：首次执行 Task 14 专项测试实际 `4 failed`（页面尚无 Task 14 契约）；实现及确认流程契约补强后 `.venv/bin/python -m pytest tests/test_goal2_task14_pages.py -q`：`5 passed`。
- 跨 Task 13/14 静态回归：`.venv/bin/python -m pytest tests/test_goal2_task13_pages.py tests/test_goal2_task14_pages.py -q`：`11 passed`。
- 相关 Goal-2/入口/迁移/配置回归：`.venv/bin/python -m pytest tests/test_goal2_task*.py tests/test_entry_skeleton.py tests/test_migration_boundaries.py tests/test_config.py -q`：`138 passed, 5 warnings`；警告仅为 AstrBot `audioop` 和动态插件命名空间 `__package__` 弃用提示。
- `node --check` 依次检查 `app.js`、`bridge.js`、`store.js` 通过；无依赖 Node harness 验证 API factory 暴露全部 Task 14 方法、动态路径编码、删除确认串，以及 panel delete/task pause/member cleanup 后的 server-state reload。
- `/Users/flanchan/.local/bin/ruff check .`、两项 Task 页面 `ruff format --check`、正确插件目录下 `compileall -q src main.py tests`、目标文件 `pre-commit run --files ...`：均通过。
- 按 `ui-ux-pro-max` 执行操作型页面 UX 检索；已落实不可恢复动作确认、可见焦点、成功反馈、加载状态、移动卡片化目标列表和图片按需加载。
- 剩余风险：
- 真实 AstrBot Plugin Pages 注入环境、桌面/移动/暗色视觉和真实交互证据留给 Task 16；本 task 未操作真实账号、订阅或生产 data root。
- 账号/完整预览/角色别名页面仍由 Task 15 实现；target 编辑/删除 API 已存在但本 task 按需求只展示任务投递目标。
- 下一步：
- Task 15：实现账号预览与角色别名页面。

## Task 15 — 账号预览与角色别名页面

- 状态：`[x] completed`
- 目标：实现全局账号折叠列表、明文凭据编辑、删 UID/用户预览、基本卡/详情卡 overlay，以及默认只读+多 custom 标签的角色别名页。
- 验收：身份键不可编辑；关闭抽屉清空 secret 与图片引用；隐私不影响预览；默认别名不能删改；恢复默认只清 custom；不出现武器别名管理。
- 实际工作：
- 新增账号与别名页面：账号按全局 `user_id` 折叠展示 UID 摘要，列表只请求 `include_credentials=false`；打开编辑抽屉后再按 `(user_id, uid)` 读取全部十项 App/Web 凭据，`user_id`/`uid` 使用只读输入，来源群和 active 状态可编辑，不提供账号创建。
- 接入 UID/用户删除预览与确认执行；删除前校验服务端返回的身份键和 `confirmation_payload`，成功后重新读取账号事实。基本信息卡和详情卡均通过认证 API 获取 base64 图片，详情支持角色名和逗号分隔的可选武器名。
- 增加 secret/图片生命周期保护：编辑器关闭会清空表单凭据、`selectedAccount` 和预览引用；详情/预览请求以 request id 忽略关闭后的迟到响应；页面和 bridge/store 不使用 `localStorage` 或 `sessionStorage`。
- 增加角色别名管理：默认别名以只读标签展示，自定义别名支持多个值追加/删除，有效集合单独展示；添加、删除、按角色恢复和全部恢复均进入确认流程，并在成功后重载服务端目录；页面没有武器别名管理入口。
- 复用统一卡片、抽屉、确认弹窗、加载/错误/空状态和移动端断点；按 `ui-ux-pro-max` UX 检索结果落实成功反馈、破坏性操作确认及窄屏无横向溢出。
- 验证证据：
- TDD Red：首次执行 `../../../.venv/bin/python -m pytest tests/test_goal2_task15_pages.py -q`，页面仍是 Task 13 占位且 bridge/store 无 Task 15 契约，实际 `6 failed`。
- Green：`../../../.venv/bin/python -m pytest tests/test_goal2_task15_pages.py -q`：`6 passed`；Task 13–15 联合：`17 passed`。
- Goal-2 相关回归：`../../../.venv/bin/python -m pytest tests/test_goal2_task*.py tests/test_entry_skeleton.py tests/test_migration_boundaries.py tests/test_config.py -q`：`144 passed, 5 warnings`；警告仅为 AstrBot `audioop` 与动态插件命名空间 `__package__` 弃用提示。
- `node --check pages/dashboard/js/bridge.js`、`node --check pages/dashboard/js/store.js`、定向 Pyright、`compileall -q src main.py tests`、`git diff --check`、Task 15 Ruff format check、全仓 `/Users/flanchan/.local/bin/ruff check .` 和变更文件 `pre-commit run --files ...`：均通过。
- 无依赖 Node harness 核验：账号列表只传 `include_credentials=false`，身份路径正确编码，详情/删除预览/预览图片 endpoint 正确；store 成功写入后重载别名/账号，关闭编辑或预览后迟到响应不会恢复 secret 或图片引用。
- 剩余风险：
- 真实 AstrBot Plugin Pages 注入环境、桌面/移动/暗色视觉与真实交互证据仍留给 Task 16；本 task 未接触真实账号、订阅或生产 data root。
- 明文凭据仍会在已认证管理请求和编辑抽屉生命周期内可见；后端 no-store、列表摘要化和关闭/竞态清理已覆盖页面边界，真实浏览器缓存与宿主 bridge 行为需 Task 16 复核。
- 预览上游与既有渲染链的真实图片可用性仍取决于隔离环境中的 transport/T2I 服务，Task 15 只负责认证 API 映射与内存图片展示。
- 下一步：
- 集中检查 D05：复核 Task 13–15 的需求偏离、UX/响应式/可访问性、secret 生命周期、bridge 错误和静态契约。

## 集中检查 D05 — Task 13–15

- 状态：`[ ] pending`
- 检查：页面需求偏离、UI/UX、暗色、响应式、键盘/焦点、loading/error/empty 状态、secret 浏览器持久化、bridge 错误、静态契约测试。
- 处理：不得添加数据 dashboard、帮助管理或无依据分页；发现问题修复或追加 task。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：

---

## Task 16 — 真实浏览器与 AstrBot Plugin Pages 验证

- 状态：`[ ] pending`
- 目标：使用浏览器类 skill 在真实 AstrBot Dashboard/隔离数据环境打开页面，验证桌面、移动端、暗色、四页导航、抽屉/弹窗、图片、能力禁用和错误状态；只修复本 goal 问题。
- 验收：保留截图或可复核日志；关键读写流程有实际交互证据；不抢占焦点、不操作真实账号/生产数据。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 17 — 文档、迁移与运维回滚说明

- 状态：`[ ] pending`
- 目标：同步 docs 索引、架构、数据模型、Pages 使用、跨 Bot/平台身份、明文凭据风险、aiocqhttp 限制、永久任务删除、破坏性迁移和回滚步骤；按仓库纪律更新相关说明。
- 验收：文档不再声称账号/隐私按 bot_id 隔离；明确备份和旧版本回退要求；不泄露真实 token、Cookie、数据库或 Dashboard 密钥。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 18 — 全量质量门禁与代码审查修复

- 状态：`[ ] pending`
- 目标：运行全量 pytest、ruff、pyright、compileall、pre-commit、diff-check；使用 `code-review-expert` 审查数据库、权限、敏感信息、并发和 UI，修复所有阻塞问题。
- 验收：全部适用门禁通过；既有无关失败被准确分类；审查无未解决阻塞项；工作树只含本 goal 预期变化。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D06 — Task 16–18

- 状态：`[ ] pending`
- 检查：C 端体验、代码质量、安全、数据一致性、权限、错误处理、测试覆盖、构建产物、文档、回滚和实际 diff；确认无调试残留或超范围改动。
- 处理：发现任何问题则在本文件末尾追加修复 task；只有全部问题关闭后才进入终审。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：

---

## Goal 终审（所有 task 完成后执行）

- 状态：`[ ] pending`
- 目标：最大范围复查目标达成、用户体验、跨平台身份、破坏性迁移、明文凭据、不可恢复任务、离群误判、级联删除、默认别名、浏览器行为、文档和回滚。
- 完成条件：没有已知高风险或阻塞问题；所有修复 task 完成；客户端 goal 标记 complete；提交最终简短证据汇报后停止自动推进。
- 实际工作：
- 验证证据：
- 剩余风险：
- 下一步：
