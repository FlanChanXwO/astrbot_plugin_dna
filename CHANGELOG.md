# Changelog

## v0.2.0 — 管理面板与全局身份（2026-08-29）

### Added

- 新增认证的 Plugin Pages 管理面板，提供面板图、任务与推送目标、成员探测、账号与玩家预览、角色别名四个功能区。
- 新增管理员账号管理和完整卡片预览；凭据字段支持明文查看/编辑，预览固定绕过普通命令隐私设置。
- 新增统一任务状态、暂停/恢复、下一次运行时间、目标会话展示和不可恢复的 `scheduler_state.json` tombstone。
- 新增仅 `aiocqhttp`/OneBot V11 可用的成员探测与删除前复核，并将成员状态明确区分为 `present`、`absent`、`unknown`。
- 新增资源仓库之外的角色自定义别名层，支持多个自定义别名、删除和恢复默认，不修改默认资源。

### Changed

- 账号绑定、凭据记录、个人隐私和群隐私改为跨平台、跨 Bot 的全局身份语义，账号以 `(user_id, uid)` 管理。
- 管理接口统一返回 `AdminApiResponse`，凭据响应使用 `Cache-Control: no-store`；页面不使用浏览器持久化存储。
- 面板图删除仅清理已识别图片文件，保留同目录中的其他运行期文件。

### Upgrade notes

- `0003_global_identity` 会清空旧账号、凭据、个人隐私和群隐私四张表，保留签到记录；升级前必须备份 `dnaby.sqlite3`。
- 任务 tombstone、别名自定义层和面板图删除均不提供页面内恢复；回退时必须同时使用匹配的旧代码与数据库/运行期文件备份。

## goal-1 O04 — 第一阶段命令与文档收口（2026-08-28）

### Changed

- 聊天内的 `update_log`/“更新记录”命令及其渲染链已移除；更新历史统一以本文件作为长期载体。
- 当前 `commands.json` 由代码 registry 生成，共 60 条命令，仅保留 `user` 与 `admin` 权限。
- 使用文档改为说明可配置的 `display.command_prefixes`，并同步管理员权限与命令清单事实。

## 本地离线渲染对比工具（Task 30 前置）

### Added

- `scripts/compare_renders.py`：本地离线双渲染器对比（不启动 gscore）——同源密函 fixture
  喂给 legacy `draw_mh_simple` 与 rewrite `render_mh`，输出画布尺寸、rewrite 文本/布局/
  资源元数据与像素弱信号（直方图余弦距离、resize 后相同率/差异 bbox）；动态字段固定时钟
  mask；对比图入临时目录不入 Git。
- 首次对比报告 `docs/porting/render-compare-mh.md`：结构性差异（legacy 横向卡片 vs
  rewrite 纵向 1300 宽），绘制内容同源，视觉等价待人工确认。

## rewrite Task 29 — 历史 56 项能力盘点与补齐

### Added

- 盘点 legacy 56 条命令：50 条已映射到 rewrite id，`user_login/logout/get_ck` 为重命名
  （`account_*`）、`user_bind` 拆分为 5 条显式命令，均覆盖；补齐唯一缺失的别名写入能力。
- 新增 `src/modules/operations/alias_service.py`：`alias_add_delete`（添加/删除角色/武器
  别名，原子写资源根 `alias/{char,weapon}_alias.json`，去重/未找到可见）与 `alias_recover`
  （恢复内置别名并刷新 catalog）。
- 注册 `alias_add_delete`/`alias_recover` 2 条 owner 命令；`commands.json` 重新生成共 61
  条命令。
- 新增 4 条别名写入测试并纳入写入契约审计。

### Changed

- 别名写入会修改 git 管理的资源文件：下一次 `下载全部资源` 的 `pull --ff-only` 会因本地
  修改拒绝（安全边界），作为记录差异。

## rewrite Task 28 — 运维与面板阶段集中审查

### Fixed

- `PanelService._char_panel_dir` 增加路径越界守卫：解析结果必须位于运行期 `panel_custom/`
  目录内，越界拒绝写入（防御性拒绝路径逃逸）。
- 新增 `test_upload_rejects_path_escaping_char_id` 回归测试。

### Documentation

- 新增 [review-v0.6-operations.md](docs/porting/review-v0.6-operations.md)：阶段 7 集中审查的
  修复、复查结论（Git 边界/日志脱敏/配置契约/文档同步）与门禁证据。

## rewrite Task 26 — 资源更新、下载日志与更新日志展示

### Added

- 新增 `src/modules/operations/resource_service.py`：`ResourceUpdateService` 复用
  `ResourceSynchronizer`（浅克隆/`git pull --ff-only`），下载全部私有资源并校验 manifest；
  Git 缺失、认证失败、远端失败、非快进和本地修改均映射为可见错误，不自动覆盖本地修改。
- `update_log` 读取插件仓库最近提交；Git 不可用返回可见失败。
- 注册 `download_resource`（下载全部资源）与 `update_log`（更新记录/更新日志）2 条 owner
  命令；`commands.json` 重新生成共 59 条命令。

### Verification boundary

- 真实私有资源仓库未联网同步，只使用隔离 runner/fake synchronize 验证；同步器自身的
  凭据脱敏与 Git 边界已由 `test_config_resources.py` 覆盖。

## rewrite Task 25 — 面板图管理与运行期资源状态

### Added

- 新增 `src/modules/operations/`：`PanelService` 管理运行期数据目录 `panel_custom/` 的
  自定义面板图——上传（保存 WebP、按内容 sha1 去重）、列表（文本+图片链）、按 ID/全部
  删除、压缩；`原图删除` 因公开结果边界无原图引用缓存显式报告不支持。
- 新增 `resource_status` 命令展示私有资源仓库目录、manifest 格式/资源版本/必需目录与
  自定义面板数量。
- 注册 7 条 owner 命令（`upload_panel_img`/`list_panel_imgs`/`delete_panel_img_by_id`/
  `delete_all_panel_imgs`/`delete_original_panel_img`/`compress_panel_imgs`/
  `resource_status`）；`commands.json` 重新生成共 57 条命令。
- 命令层 `CommandRequest` 增加 `images` 字段，经 `images_from_event` 从 AstrBot 公开消息链
  提取图片载荷（本地路径/base64/URL）。

### Verification boundary

- 上传/删除/压缩等写操作只在隔离目录 fixture 验证，不操作真实账户或参考区；真实平台
  面板上传行为未执行，仅离线契约覆盖。

## rewrite Task 24 — 通知阶段集中审查

### Fixed

- `SubscriptionStore.add/delete/update` 改为按 `(type, origin, uid)` 精确匹配：同一会话内
  不同用户的个人密函订阅互不覆盖，删除/更新不再误伤同会话其他记录。
- 密函订阅/取消/查看按当前会话 `unified_msg_origin` 取目标：多会话用户读写各自会话的
  订阅，不串扰。
- 取消订阅后空列表直接删除订阅记录，清理死数据。
- 新增同会话多用户去重、按 uid 删除、跨会话作用域与双用户同会话 4 条回归测试。

### Documentation

- 新增 [review-v0.5-notices.md](docs/porting/review-v0.5-notices.md)：阶段 6 集中审查的
  修复、复查结论（错误分类/并发去重/生命周期/推送日志）与门禁证据。

## rewrite Task 23 — 通知脱敏、可观测错误与事件响应

### Added

- `tests/test_notices_transport.py` 新增 5 条脱敏/错误观测测试：网络失败映射 NETWORK、
  状态码错误映射 STATUS、密函/公告页面结构变化映射 SERVER 或显式抛错（不伪造空成功），
  并断言 Cookie/token 与上游 `msg` 原文不进异常 str/repr。
- 错误分类统一：用户取消（`订阅密函时间` 越界等）返回格式提示；网络/状态码/服务端/
  结构变化分别映射稳定类别，用户响应只含受控文案。

### Verification boundary

- 通知读取/订阅/推送的 Cookie/token 脱敏与错误可见性由隔离 fixture 验证；真实平台
  内容与视觉等价仍待 Task 30 只读矩阵。

## rewrite Task 22 — 通知订阅推送与取消订阅

### Added

- 扩展 `src/infrastructure/subscriptions/`：`Subscription` 增加 `uid/extra_message/
  extra_data`，store 增加作用域过滤 `get` 与 `update`。
- 注册 `mh_subscribe`/`mh_subscribe_by_name`/`mh_subscribe_cycle`/`mh_pic_subscribe`/
  `mh_text_subscribe`/`mh_test`/`ann_sub`/`ann_unsub` 8 条订阅命令；`commands.json`
  重新生成共 50 条命令。
- `NoticesService` 新增密函按名订阅/取消（去重、禁止订阅全部、推送时间窗口）、图片/文本
  会话作用域开关、owner 测试推送、公告群订阅/取消，以及计划任务 `push_mh_now`/
  `poll_ann_now`；`AnnStateStore` 记录已知公告 id，只推送新条目。
- 新增 `src/infrastructure/notices_scheduler.py`：每小时密函推送 + 周期公告轮询，
  `initialize()` 启动/`terminate()` 取消，幂等；推送闭包把文本/图片载荷映射为
  Plain/Image 组件并经 `Context.send_message` 发送。

### Changed

- 生命周期钩子扩展为 start: web → sign → notices scheduler；stop: notices → sign →
  database.dispose。
- `get_mh_any` 使用任意可用账号凭据读取密函供计划任务推送（区别于读取命令的调用者账号）。

### Verification boundary

- 订阅/推送只写入隔离 SubscriptionStore 并由注入 push fixture 验证；真实平台推送未执行，
  仅离线契约覆盖（写入型命令纳入 `test_write_contracts` 审计）。密函/公告真实内容与视觉
  等价仍待 Task 30 只读矩阵。

## rewrite Task 21 — 密函、公告与活动日历读取

### Added

- 新增 `src/modules/notices/`：typed `NoticesTransport` 契约、`NoticesService`（密函/
  密函列表/公告列表/公告详情）与 `NoticesRenderer`（1300 宽 PNG，公告图片块为 placeholder）。
- 注册 `mh`、`mh_list`、`ann` 三条读取型命令；`commands.json` 由 registry 重新生成，
  共 42 条命令。
- 新增 `DnaApiNoticesTransport`：密函复用 legacy `get_default_role_for_tool` 的
  `instanceInfo`；公告列表/详情走公共 BBS（无需凭据），HTML 清洗复用
  `dnaby/dna_ann/utils` 纯逻辑。

### Changed

- 密函改用调用者 active UID 凭据读取（区别于 legacy 随机账号 quirk，作为记录差异）；
  活动日历（`日历`）由 Task 14 资料读取提供，不重复注册。

### Verification boundary

- 密函/公告读取只在 fake transport + 隔离 SQLite + 事件 fixture 中验证；真实公告/密函
  内容与视觉等价仍待 Task 30 只读矩阵。通知订阅/推送与轮询在 Task 22 接入。

## rewrite Task 20 — 签到阶段集中审查

### Fixed

- 移除 `CheckinService.enable_all_users` 死参数；定时自动签到任务改为要求
  `scheduled_enabled and enable_all_users` 才创建（承担 legacy `SigninMaster` 对全账号
  自动签到的门控语义），owner 手动的 `全部签到` 不受影响。
- 社区启用但 API 未返回启用任务时改为明确文案 `CHECKIN_TASKS_EMPTY`，不再误报
  「帖子列表为空」。
- `subscribe_sign_result` 在订阅文件损坏时返回可见的 `SIGN_RESULT_STORE_UNAVAILABLE`，
  不让命令 handler 崩溃。
- 移除 `CheckinSummary.lines` 死字段。

### Documentation

- 新增 [review-v0.4-checkin.md](docs/porting/review-v0.4-checkin.md)：阶段 5 集中审查的
  修复、复查结论（状态机/调度取消/订阅边界/写入隔离/并发事务）与门禁证据。

## rewrite Task 19 — 写入型能力的离线契约与权限审计

### Added

- 新增 `tests/test_write_contracts.py`：集中审计 23 条写入型命令的权限边界
  （user/admin/owner）与离线契约覆盖；每条写入命令都能在 fake transport + 隔离 SQLite +
  模拟事件下通过生成后的 handler 离线分发并产出框架无关响应。
- 新增 [docs/porting/offline-write-contracts.md](docs/porting/offline-write-contracts.md)：
  明确“离线验证不等于真实行为已验证”，逐能力列出离线覆盖与未覆盖边界。

### Changed

- `sign` 离线写路径新增断言：只调用注入 transport 的 `get_sign_calendar/game_sign/
  get_task_process/bbs_sign`，不触碰真实网络边界。

### Verification boundary

- 真实账户不执行登录/签到/绑定/订阅/隐私写入；面板/资源/别名等未注册写入能力的真实平台
  验收边界由 Task 25/26/30 记录。

## rewrite Task 18 — 计划任务、结果订阅与生命周期

### Added

- 新增 `src/infrastructure/subscriptions/`：框架无关 JSON 订阅存储（type+会话去重、
  原子落盘、损坏文件可见失败），替代旧 `dnaby/utils/subscriptions.py` 与 gsucore
  `gs_subscribe` 的签到结果订阅路径。
- 注册 `sign_result_subscribe`（订阅/取消订阅签到结果，owner）；`commands.json` 由
  registry 重新生成，共 39 条命令。
- 新增 `src/infrastructure/scheduler.py` 的 `SignScheduler`：每日自动签到
  （`sign_in.sign_time`）与 2 天前记录清理，`initialize()` 创建、`terminate()` 取消，
  重复初始化幂等；`EventActor` 增加 `unified_msg_origin`（AstrBot 公开属性）。

### Changed

- `CheckinService` 新增 `subscribe_sign_result`/`auto_sign_all`/`clear_sign_records_before`；
  自动签到摘要按 legacy 语义区分游戏/社区成功数。`sign_all` 重构为共享 `_run_all_signs`。
- 生命周期钩子改为 start: web → scheduler，stop: scheduler → database.dispose；
  推送闭包绑定 `Context.send_message` 公开 API。

### Verification boundary

- 计划任务与推送只在隔离订阅存储 + fake checkin + 注入 push/now/sleep fixture 中验证；
  未执行真实 NapCat。订阅写入型能力的完整离线契约与权限测试继续由 Task 19 覆盖。

## rewrite Task 17 — 游戏/社区签到、日历与批量结果

### Added

- 新增 `src/modules/checkin/`：typed `CheckinTransport` 契约、`CheckinService`（游戏签到、
  社区任务、签到日历、owner 批量签到）和 `CheckinRenderer`（1300 宽日历 PNG）。
- 注册 `sign`（签到/社区签到/每日任务/社区任务/库街区签到/sign）、`sign_calendar`
  （签到日历/签到记录/签到历史）和 `sign_all`（全部签到，owner）；`commands.json` 由
  registry 重新生成，共 38 条命令。
- 新增 `DnaApiCheckinTransport` 复用 legacy 纯 API（sign_calendar/game_sign/bbs_sign/
  get_task_process/have_sign_in/get_post_list/get_post_detail/do_like/do_share/do_reply），
  只在 transport 边界组装 legacy `DNAUser`，不接触旧事件/数据库/消息段。
- 当天签到计数写入新 schema `sign_records` 表（新增 `SignRecordRepository.save` upsert）；
  不迁移旧数据库。

### Changed

- `AccountBindingRepository.list_all` 供 owner 批量签到读取全部绑定，不暴露凭据字段。
- 签到结果按 legacy 语义展示逐项状态（签到状态/社区任务/错误信息），失败只映射受控文案，
  不回显上游 `msg`/URL/凭据样式内容；日历/批量结果保留全部合法数据。

### Verification boundary

- 真实写操作（游戏签到、社区签到、浏览/点赞/分享/回复）只在 fake transport + 隔离
  SQLite + 事件 fixture 中验证；未执行真实 NapCat 或真实账户写入。批量签到/写入型能力
  的完整离线契约与权限测试继续由 Task 19 覆盖。

## rewrite Task 16.2 — 原图引用映射与伤害失败输出边界

### Changed

- 移除 `OriginalImageCache` 与 `PlayerService.last_original_image` 实例级共享状态：原图路径
  改为随单个 `ImageResponse.original_image_path` 传递，并发详情响应各自关联自己的原始面板。
- `原图` 命令在 AstrBot 4.27.x 公共结果边界没有已发送消息 ID 交付点（`AstrMessageEvent.send()`
  返回 `None`，`MessageEventResult` 无消息 ID 字段），因此显式更名为“角色原图（暂不支持）”，
  回复受控文案 `PLAYER_ORIGINAL_UNSUPPORTED`；不再维护永久不可命中的缓存并伪装成“未找到”。
- 伤害计算失败的用户可见内容收敛为 `PLAYER_DAMAGE_FAILED` 受控文案：transport、renderer 均
  不回显上游 `msg`、URL、Authorization/Bearer、token/cookie/dev code 等凭据样式内容。
- 移除 `display.role_original_image` 配置项；`_conf_schema.json` 与 `commands.json` 由同一
  registry/settings 定义重新生成。

### Verification boundary

- Task 16.2 只使用事件/响应 fixture：并发详情、无原图、发送失败与未支持分支均在隔离环境验证；
  未执行真实 NapCat，未使用平台私有接口。真实平台原图引用能力的验收边界仍记入 Task 30。

## rewrite Task 16.1 — 运行期资源与临时图片生命周期

### Fixed

- 资源 manifest 现要求玩家/百科实际消费的完整目录布局；同步器和 bootstrap 均拒绝已有但
  不完整的资源根。玩家与百科 renderer 从同一私有运行期根加载字体、图片、面板、wiki、攻略、
  别名、周报和日历资源，不再从插件源码读取 legacy 字体。
- 合成 `rendered/*.png` 通过 `ImageResponse.temporary` 交给 AstrBot 当前事件的临时文件
  生命周期；响应边界只登记受控渲染目录内的已生成文件，原图/wiki/攻略资源不会被删除。

### Verification boundary

- 使用隔离资源目录、Pillow、AstrBot 本地 SDK 和 event fixture 验证 manifest、bootstrap、
  provided/placeholder metadata 与事件清理；未创建/同步外部私有资源仓库，未执行真实 NapCat
  或真实账户。
- 资源接线完成不代表实际私有资源或图像视觉差异已经验收；这些结论仍留待 Task 30。

## rewrite Task 14 — 资料读取

### Added

- 增加日常便笺、本周/上周周报、日历、角色/武器/魔灵图鉴、角色攻略、兑换码和只读别名共 9 条
  显式 registry 命令；未迁移的别名写入命令不注册、不展示。
- 增加 `EncyclopediaService`、typed 资料 DTO、legacy API transport、运行期资源索引和动态 PNG
  renderer。便签、周报和日历完整遍历合法资料项，PNG 元数据仅用于离线布局/资源语义审查。
- 兑换码 provider 的每个有效码保留独立截止时间；当日期不同，响应链逐码显示对应截止时间，避免
  只展示首项造成数据丢失。

### Verification boundary

- Task 14 只使用隔离 SQLite、fake transport、临时运行期资源、Pillow 和 AstrBot 本地 SDK 验证；
  未执行真实 gscore 账户读取、真实 NapCat 或任何写入型别名操作。
- 所有资料图片写入运行期 plugin data 的 `rendered/`，资源从运行期 `resources/` 索引读取；不写入
  插件源码目录、参考区或 Git。

## rewrite Task 13 — 玩家角色查询、详情/伤害和原图

### Added

- 增加 `role_info_card`、`role_detail_card` 和 `role_original_image` 三条显式 registry
  命令；角色详情正则、可选武器参数和原图输入保持 legacy 语义。
- 增加 `PlayerService`、typed role/weapon/damage contracts、可注入 fixture transport 和
  legacy 纯 API 适配器；读取链路按隐私策略解析目标用户并从新 SQLAlchemy schema 读取
  当前 UID。
- 增加运行期 PNG renderer、完整列表遍历和动态画布；详情响应携带
  `original_image_path` 原面板引用（后续 Task 16.2 取代实例级缓存）；图片通过
  AstrBot `ImageResponse`/`image_result` 返回，PNG 元数据为离线布局与资源语义审查服务。

### Verification boundary

- Task 13 使用隔离 SQLite、fake player transport、临时图片资源和 AstrBot 本地 SDK 验证；
  未执行真实 gscore 账户读取。真实账户只读命令矩阵由 Task 15 处理。
- 生成图片写入运行期 plugin data 的 `rendered/`；未写入插件源码目录、参考区或 Git。

## rewrite Task 12 — 阶段 3 集中检查-debug

### Fixed

- 登录参数清理恢复 legacy 对空格、换行、制表符和双引号的处理；重复登录收到服务端
  默认角色时会切换到该默认 UID，并在成功文案中优先展示。
- 绑定、切换和删除命令保留 legacy 缺少参数时的 handler 路由，由业务层返回明确错误，
  不再静默无响应。
- SQLite 隐私全局设置增加部分唯一索引，并让同一 runtime 的写事务串行化，避免并发
  upsert 产生重复 `(user_id, bot_id, group_id=NULL)` 记录。
- legacy account transport 将响应结构的 `AttributeError`、`KeyError` 和 `TypeError`
  归类为服务端错误；异常字符串和 repr 仍不包含原始 detail。

### Verification boundary

- 新数据库仍须部署者通过 Alembic 初始化；本地环境未安装 Alembic，migration round-trip
  继续显式 skip，不能把测试 schema 当作生产迁移。

## rewrite Task 11 — 个人/群组隐私 use case

### Added

- 增加个人开关、群强制开关和指定目标隐私命令，共 14 条；群管理员命令由
  AstrBot `PermissionType.ADMIN` 过滤器保护。
- 增加 `PrivacyService` 的个人/群组策略查询、AT 查询解析、目标绑定校验和显式事务写入；
  群强制值按字段优先于个人设置，取消后恢复个人设置。
- 命令 handler 使用 AstrBot 公开消息链的 `At` 组件提取目标，不依赖 legacy `ctx.at`。

### Security

- 指定隐私写入要求群聊、有效 `@` 和目标已有 UID 绑定；个人写入遇到群强制设置时会拒绝且不改变个人记录。
- 隐私写入只在隔离 SQLite 测试中执行；用户可见文案集中在 privacy message 层，未把
  Cookie、token、UID 查询目标或旧消息段类型带入新入口。

## rewrite Task 10 — 账号 use case

### Added

- 增加 typed actor/login/role/credential DTO、可注入账号 transport 和显式错误类别。
- 增加登录、退出、UID 绑定/切换/删除/列表及凭据状态命令；命令清单与帮助均由同一
  registry 生成。
- 增加 normalized account repository CRUD；登录、退出、删除和凭据更新均使用显式
  SQLAlchemy async transaction。

### Security

- 用户响应、异常字符串、DTO repr 和凭据状态查询不返回 Cookie、token、refresh token、
  设备码或 d_num。
- 账号写入只在隔离 SQLite/fake transport 测试中验证；默认 runtime 未配置真实登录页
  provider 时显式报错，不发送伪造地址。

## v0.1.0 — 2026-08-11

### Changed

- 建立 `src/` 分层入口、显式 `CommandSpec` registry 和真正的异步生成器命令方法。
- 帮助命令从代码 registry 读取，只展示当前已经实现的命令。
- 配置改为按登录、网络、签到、通知和显示分组的 Pydantic typed settings，并由同一份定义生成 `_conf_schema.json`。
- 增加私有 `dnaby_resources` Git 仓库的 manifest 校验和安全同步接口：首次浅克隆，后续只允许 `git pull --ff-only`。
- 增加 SQLAlchemy 2 async + `sqlite+aiosqlite` 五表持久化骨架与 Alembic `0001_initial` revision；新数据库文件为 `dnaby.sqlite3`，凭据 ORM 表示提供脱敏边界。

### Breaking changes

- 这是重构 v0.1 的新入口，历史 55 项命令尚未注册，不会出现在帮助或 `commands.json` 中。
- 不迁移旧 DNAUID/legacy-reference SQLite 数据；新 schema 不会打开旧 `dnaby.db`，请在后续迁移阶段使用新的数据结构。
- 资源仓库需要由部署者在私有 Git 权限可用时提供；本版本不会创建、推送或公开资源仓库。
- 资源同步发现 Git、认证、远端、非快进、manifest 或本地修改错误时会直接失败，不会强制覆盖本地文件。

### Verification boundary

- 本版本仅使用 AstrBot 4.27.x 本地 SDK、fixture 和 staging runtime 验证；不执行真实 NapCat 或真实账号写入操作。
