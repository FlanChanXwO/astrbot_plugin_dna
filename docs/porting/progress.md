# 移植进度（progress.md）

> 更新于 2026-08-30。superpowers 迁移记录；当前 rewrite 阶段审查见
> [review-v0.2-debug.md](review-v0.2-debug.md)、[review-v0.3-player.md](review-v0.3-player.md) 和
> [review-v0.3-encyclopedia.md](review-v0.3-encyclopedia.md)、[review-v0.3-debug.md](review-v0.3-debug.md)，legacy 完整审查见 [review.md](review.md)，
> legacy 交付结论见 [final_report.md](final_report.md)。

> 重构区说明：本文主体记录的是 `legacy-reference` 的历史移植状态。当前 `rewrite/v0.1`
> 已切换为 `main.py` + `src/` 薄入口，代码 registry 已包含帮助、账号、隐私、玩家查询、资料读取、签到、通知和运维共 61 条命令；
> 其余历史命令、Web 路由和业务生命周期仍按 `goal-1/tasks.md` 分阶段迁移。

### rewrite Task 13 — 玩家查询 ✅

- 已登记 `role_info_card`、`role_detail_card` 和 `role_original_image`；新增 typed
  `PlayerService`、可注入 player transport、legacy 纯 API/model/伤害适配和 Reply 消息 ID
  边界。
- 概览和详情渲染在运行期 plugin data 生成动态 PNG，完整保留合法角色、武器、技能、魔之楔、
  溯源和伤害字段；详情响应携带 per-response 的 `original_image_path` 原面板引用，不依赖
  实例级共享缓存（Task 16.2）。
- 详细行为矩阵、已知差异和图像验证格式见 [review-v0.3-player.md](review-v0.3-player.md)。

### rewrite Task 14 — 资料读取 ✅

- 已登记日常便笺、周报、日历、图鉴、攻略、兑换码和只读别名共 9 条命令；新入口只读取
  新 SQLAlchemy schema 中的当前 UID/凭据，写入型别名能力仍未注册。
- 新旧 API 的 typed transport、运行期资源索引和动态 PNG 渲染均通过隔离 fixture 验证；有效兑换码
  保留各自截止时间，图片不截断合法资料项。
- 详细行为矩阵、可见差异和资源边界见 [review-v0.3-encyclopedia.md](review-v0.3-encyclopedia.md)。

### rewrite Task 16 — 查询/百科集中审查 ⚠️

- Task 15 的结构实测、动态字段 mask 和未接受视觉差异保持明确状态；图片/资源/时间敏感
  项没有因 fixture 或 placeholder 被标为通过。
- Task 16.1 已让同步 manifest、bootstrap、玩家/百科资源索引和 renderer 使用同一私有
  运行期根，并把合成 PNG 限定为 AstrBot 事件期临时文件；真实资源内容和视觉差异仍未接受。
- Task 16.2 已移除实例级原图共享缓存（原图路径随单个详情响应传递），`原图` 命令在公开
  结果边界无消息 ID 交付点，显式报告未支持；伤害失败文案收敛为受控文本，不回显上游
  正文或凭据样式内容。真实平台原图引用能力的验收边界仍记入 Task 30。
- 完整证据和修复边界见 [review-v0.3-debug.md](review-v0.3-debug.md)。

### rewrite O10/O11 — 玩家缓存与刷新治理 ✅

- `PlayerCache` 接入玩家概览和完整角色卡片缓存；普通用户可刷新自己的指定角色，管理员可按
  游戏 UID+角色刷新，并可清理全部玩家 JSON/PNG 缓存而保留其它业务缓存。
- `cache.refresh_send_card` 控制刷新后返回新卡片或成功文案；刷新按身份和角色 tags 精准失效，
  不误删其它角色或其它缓存类型。缓存和 rendered 维护任务均纳入 runtime 生命周期。
- `RenderedFileStore` 清理已知前缀下的过期孤儿并保护活动发送租约；`ResponseFactory` 在受控
  rendered 文件交给 AstrBot 事件清理时登记租约，回归测试覆盖此前约 741 MB 无界增长问题。
- 离线证据见 `tests/test_goal1_o10_player_cache.py` 与
  `tests/test_goal1_o11_refresh_and_cleanup.py`；未执行真实账户刷新或生产文件清理。

### rewrite Task 17 — 签到 ✅（签到日历已接回 legacy 绘制核心）

- 已登记 `sign`（签到/社区签到/每日任务/社区任务/库街区签到/sign）、`sign_calendar`
  （签到日历/签到记录/签到历史）和 `sign_all`（全部签到，owner）三条命令。
- `CheckinService` 通过 `CheckinTransport` 协调游戏签到、社区任务（签到/浏览/点赞/分享/
  回复）、签到日历和批量签到；当天计数落到 `sign_records` 表，未注册订阅/计划任务
  （Task 18）。写操作只走注入 transport，默认 `DnaApiCheckinTransport` 复用 legacy 纯 API；
  服务层不接触旧事件/数据库/消息段，transport 错误只映射稳定类别。
- 成功、已签到跳过、关闭、transport 失败、日历精简、帖子遍历失败和批量聚合均由隔离
  fixture 覆盖；签到日历由 typed 快照还原 legacy 模型，复用原版 1300 宽绘制核心，
  并沿用目标用户头像与 UID 隐私状态。

### rewrite Task 18 — 计划任务、结果订阅与生命周期 ✅

- 注册 `sign_result_subscribe`（订阅/取消订阅签到结果，owner），订阅写入
  `src/infrastructure/subscriptions/` 的 JSON 存储（type+会话去重，损坏文件可见失败）。
- `SignScheduler` 在 `initialize()` 创建每日自动签到（`sign_in.sign_time`）与记录清理
  （2 天前）两个 asyncio 任务、`terminate()` 取消，重复 start/stop 幂等；`scheduled_enabled`
  关闭时只保留清理任务。自动签到摘要区分游戏/社区成功数，并经注入推送闭包发给订阅者。
- 生命周期钩子顺序为 start: web → scheduler，stop: scheduler → database.dispose；
  `EventActor` 增加 `unified_msg_origin`（AstrBot 公开属性）用于订阅目标。
- 全部行为由隔离订阅存储、fake checkin 与注入 push/now/sleep fixture 覆盖；真实推送只走
  `Context.send_message` 公开 API，未执行真实 NapCat。

### rewrite Task 19 — 写入型能力的离线契约与权限 ✅

- 新增 `tests/test_write_contracts.py`：集中审计 23 条写入型命令（登录/退出/绑定/切换/删除/
  隐私个人与群管理/签到/批量签到/订阅）的权限边界（user/admin/owner）与离线契约覆盖
  （每条命令映射到 `test_account.py`/`test_privacy*.py`/`test_checkin*.py` 的代表性用例）。
- 每条写入命令都能通过生成后的 handler 在 fake transport + 隔离 SQLite + 模拟事件下离线
  分发并产出框架无关响应；`sign` 路径额外断言只调用注入 transport，不触碰真实网络边界。
- 新增 [offline-write-contracts.md](offline-write-contracts.md)：明确“离线验证 ≠ 真实行为
  已验证”；面板等未注册写入能力及其真实平台验收边界仍由后续阶段与 Task 30 记录，别名
  写命令已移除，仅保留只读查询。

### rewrite Task 20 — 签到阶段集中审查 ✅

- 复核 Task 17-19（`c25354c..b5503d8`）：签到状态机、调度取消、订阅边界、写入隔离、
  并发/事务与全量门禁；完整结论见 [review-v0.4-checkin.md](review-v0.4-checkin.md)。
- 修复 4 项：`enable_all_users` 死参数移交 `SignScheduler` 门控（承担 legacy
  `SigninMaster` 语义）；社区无启用任务误报「帖子列表为空」改为 `CHECKIN_TASKS_EMPTY`；
  `subscribe_sign_result` 订阅文件损坏时转可见错误不崩溃；移除 `CheckinSummary.lines`
  死字段。新增对应回归测试。
- staging runtime 全量 pytest `213 passed, 1 skipped, 1 warning`；全部门禁通过；
  参考区保持冻结。

### rewrite Task 21 — 密函、公告与活动日历读取 ✅

- 注册 `mh`（密函/委托密函/mh）、`mh_list`（密函列表）和 `ann`（公告/公告 序号）三条
  读取型命令；活动日历（`日历`）已由 Task 14 的资料读取提供，不重复注册。
- `NoticesService` 通过 `NoticesTransport` 读取密函（复用 legacy
  `get_default_role_for_tool` 的 `instanceInfo` 分节）与公告列表/详情（公共 BBS，
  HTML 清洗复用 `dnaby/dna_ann/utils` 纯逻辑）；密函图片已接回 `draw_mh_simple`
  原版横向卡片，公告图片块仍保留 typed 资源状态。
- 密函需要调用者 active UID 凭据（区别于 legacy 随机账号，作为记录差异）；公告无需账号。
- 全部读取由 fake transport + 隔离 SQLite + 事件 fixture 覆盖；staging runtime 全量
  pytest `229 passed, 1 skipped, 1 warning`，全部门禁通过。

### rewrite Task 22 — 通知订阅推送与取消订阅 ✅

- 扩展 `SubscriptionStore`（`extra_message`/`extra_data`、作用域过滤、update）；注册
  `mh_subscribe`/`mh_subscribe_by_name`/`mh_subscribe_cycle`/`mh_pic_subscribe`/
  `mh_text_subscribe`/`mh_test`/`ann_sub`/`ann_unsub` 共 8 条订阅命令（50 条命令）。
- `NoticesService` 新增密函按名订阅/取消（去重、禁全部、推送时间窗口）、图片/文本会话
  开关、owner 测试推送、公告群订阅/取消与 `push_mh_now`/`poll_ann_now`（`AnnStateStore`
  记录已知公告 id，只推送新条目）。
- `NoticesScheduler` 固定每小时 `HH:30` 推送密函、按
  `announcement_check_minutes` 轮询公告，`initialize()` 启动/`terminate()` 取消，幂等；
  推送闭包把 str/Path 分别映射为 Plain/Image 组件绑定 `Context.send_message`。
- 全部订阅/推送只在隔离 SubscriptionStore + fake transport + 注入 push 下验证；
  staging runtime 全量 pytest `250 passed, 1 skipped, 1 warning`，全部门禁通过。

### rewrite Task 23 — 通知脱敏、可观测错误与事件响应 ✅

- 强化 `tests/test_notices_transport.py`：新增网络失败（NETWORK）、状态码错误（STATUS）、
  密函/公告页面结构变化（SERVER/显式抛错）三类可观测错误测试，并断言 Cookie/token 与
  上游 `msg` 原文不进异常 str/repr；成功路径确认使用任意账号凭据。
- 错误分类：用户取消（如 `订阅密函时间` 越界）返回格式提示，网络/状态码/服务端异常/
  结构变化分别映射稳定类别，不伪造成功。
- staging runtime 全量 pytest `255 passed, 1 skipped, 1 warning`；全部门禁通过。

### rewrite Task 24 — 通知阶段集中审查 ✅

- 复核 Task 21-23（`ca78c4a..0733789`）：通知读取/推送、订阅数据一致性、并发去重、
  敏感信息与全量门禁；完整结论见 [review-v0.5-notices.md](review-v0.5-notices.md)。
- 修复 3 项：`SubscriptionStore` 去重/删除/更新改为按 `(type, origin, uid)` 精确匹配
  （同一会话多用户个人订阅不再互相覆盖）；密函订阅/取消/查看按当前会话
  `unified_msg_origin` 取目标（多会话不串扰）；取消订阅后空列表直接删除记录（生命周期清理）。
- 新增 4 条回归测试（同会话多用户去重、按 uid 删除、跨会话作用域、双用户同会话）。
- staging runtime 全量 pytest `259 passed, 1 skipped, 1 warning`；全部门禁通过。

### rewrite Task 25 — 面板图管理与运行期资源状态 ✅

- 新增 `src/modules/operations/`：`PanelService` 管理运行期数据目录 `panel_custom/` 的
  自定义面板图（上传 WebP/sha1 去重、列表、按 ID/全部删除、压缩），原图删除因公开结果
  边界无引用缓存显式报告不支持；`resource_status` 展示公共资源仓库 manifest/必需目录与
  面板数量。
- 注册 `upload_panel_img`/`list_panel_imgs`/`delete_panel_img_by_id`/
  `delete_all_panel_imgs`/`delete_original_panel_img`/`compress_panel_imgs`/
  `resource_status` 7 条 owner 命令（57 条命令）；命令层经 `CommandRequest.images`
  （`images_from_event`）从公开消息链提取图片载荷。
- 写操作全部在隔离目录 fixture 验证，不操作真实账户或参考区；staging runtime 全量
  pytest `280 passed, 1 skipped, 1 warning`，全部门禁通过。

### rewrite Task 26 — 资源更新、下载日志与更新日志 ✅

- 新增 `src/modules/operations/resource_service.py`：`ResourceUpdateService` 复用
  `ResourceSynchronizer`（浅克隆/`git pull --ff-only`），把 Git 缺失/认证/远端失败/非快进/
  本地修改映射为可见错误，不自动覆盖本地修改；`update_log` 读取插件仓库最近提交。
- 注册 `download_resource`（下载全部资源）与 `update_log`（更新记录/更新日志）2 条 owner
  命令（59 条命令）。
- `帮助` 与 `update_log` 均返回图片，分别复用 legacy 帮助卡和更新日志绘制器。
- `ResourceSynchronizer`/`GitCommandError` 的凭据脱敏已由既有 `test_config_resources.py`
  覆盖；新增资源下载成功/失败分支与更新日志测试。staging runtime 全量 pytest
  `288 passed, 1 skipped, 1 warning`，全部门禁通过。

> 历史说明：本节保留 Task 26 当时的实现与验证记录；后续 `goal-1` 第一阶段已移除聊天内
> `update_log`/“更新记录”命令及其渲染链，更新历史统一由仓库根目录 `CHANGELOG.md` 承担。

## 当前状态

### 渲染等价修复（2026-08-13）

- `convert_img` 的 PIL 路径按 GsCore 语义使用 JPEG quality=85；路径和 bytes 保持原始字节。
- 便签、周报、活动日历、签到日历、密函、角色总览均通过 legacy 绘制核心；@查询会把
  resolved user 传入头像和 `EventContext`。
- 当前 worktree 全量为 `300 passed, 1 skipped`；两个 `data.plugins` 动态导入测试需从
  staging runtime 根执行，是既有嵌套 worktree 测试限制。

> 本节描述的是 `legacy-reference` 的历史移植状态；`rewrite/v0.1` 的当前状态见上方各 Task
> 记录与 `commands.json`（61 条命令）。

以下为历史移植阶段记录；当前 main 以 `commands.json` 为准，已注册 61 条命令、16 个功能组和 5 张 SQLAlchemy 表，权限仅为 `user/admin`（33/28）。历史数字与验证结果不代表当前 main 的最终状态。

硬约束已核对：源码不 import `gsuid_core` / `gsucore`；运行期数据库、订阅和资源写入 AstrBot `plugin_data` 数据目录；`commands.json` 与分发表同步；入口不承载业务编排。

## 已完成

### Phase 0 — 脚手架 ✅

- 插件骨架、`metadata.yaml`、`requirements.txt`、`README.md`、`LICENSE`、`.gitignore`、`.pre-commit-config.yaml`。
- `AGENTS.md` 与 `CLAUDE.md` 镜像规则；`docs/` 索引、设计、计划、开发、使用、架构和 legacy 档案。
- `dnaby/` 业务包、登录模板、字体与图片素材；`commands.json` 和 `_conf_schema.json`。

### Phase 1 — 原生基建 ✅

- AstrBot 事件/发送适配：`EventContext`、`Sender`、消息段和图片转换。
- 配置管理与 schema 生成；对象型配置包含 AstrBot 所需的 `items`。
- 私有 aiosqlite 数据库、`with_session` / `with_lock`、五张业务表和 CRUD。
- `StarTools` 对应的数据目录适配、JSON 订阅持久化、原生推送、API 请求签名与统一响应模型。
- 正则主门、组内重匹配、权限检查和命令分发；动态加载与开发态顶层导入均可用。
- 纯文本通知统一经过 `send_dna_text()`，保留图片、混合消息链和转发节点的原生发送路径。
- 订阅增删改的完整读改写事务统一受实例锁保护，新增并发回归测试。

### Phase 2–6 — 功能域 ✅（代码层）

- 免登录查询：角色、伤害、日历、体力、周报、公告、攻略、图鉴、兑换码。
- 账号与隐私：绑定/切换/删除 UID、App/Web/token/短信登录、退出、token 查看、隐私设置。
- 订阅与定时：签到、密函、公告推送、记录清理；`initialize()` 启动，`terminate()` 等待取消完成。
- 别名、资源下载、自定义面板图、原图和状态模块；`dna_status` 按设计作为可选能力保留统计函数，不注册 Dashboard 指标。

### 真实 E2E ✅（2026-08-09）

- 历史阶段曾通过本机 AstrBot `6196`、OneBot HTTP `6199`、NapCat 出站链路覆盖当时
  `commands.json` 的 56 条命令；该记录不替代当前 61 条命令矩阵。
- 已验证真实数据库中的登录数据仍可被查询，原绑定 UID 未变化；测试用户、订阅、别名和
  自定义面板图均在收尾检查后清理。
- `dna登录` 已验证消息命中、链接立即出站、登录页 `HTTP 200` 和表单 DOM；旧 auth 返回
  `HTTP 404` 无效会话页。无参数登录仍会在发送链接后等待网页提交，不再延迟发送链接。
- 真实 OneBot 图片段已验证上传、列表和按 ID 删除；图片转换器现使用 AstrBot 组件的
  `convert_to_file_path()`。

## 验证结果

从插件目录使用 runtime `.venv`（Python 3.12.13）：

| 检查 | 结果 |
|---|---|
| `python -m pytest -q` | `55 passed`，仅 AstrBot `audioop` 弃用警告 |
| `ruff check .` | 通过 |
| `uv run --offline ruff check data/plugins/astrbot_plugin_dnaby` | 通过 |
| `pyright` | 0 errors / 0 warnings（项目配置覆盖 `dnaby` 与 `tests`） |
| `python -m compileall -q .` | 通过 |
| `import main` | 通过 |
| `import data.plugins.astrbot_plugin_dnaby.main` | 通过 |
| 历史命令清单/分发 | 当时 56 条、18 模块；当前 main 以 61 条、16 组为准 |
| Dashboard 重载 | `ASTRBOT_SKIP_PLUGIN_REQUIREMENTS_SYNC=1 ... reload-plugins.sh 6196 astrbot_plugin_dnaby` 返回 `重载成功` |
| 历史本机真实 E2E | 当时 56 条命令有入站 `204`；当前 goal 的生产事件级 E2E 另按矩阵记录 |

## 已修复的迁移边界

- 修正公告模块失效导入、示例命令与 regex 不一致、更新日志 import 时执行 git、登录路由注册契约和入口动态包路径。
- 用 `asyncio.timeout` 替换额外的 `async-timeout`；统一上海时区并兼容 aware/naive datetime。
- 别名文件读写移入 `asyncio.to_thread`；数据库装饰器使用 `ParamSpec` 隐藏内部 session 参数，Pyright 不再泄露错误签名。
- 登录会话标识改为进程内 HMAC；API 调试日志不再记录 token/cookie/完整请求响应；外置轮询网络失败显露 `TransportError`。
- schema 对象补齐 `items`，实际 AstrBot 4.27.1 重载验证通过。
- 公告缓存按 `ClassVar` 语义写回；Pillow 路径、SQLModel 元类参数和 SQL 表达式补齐源码级类型检查。

## 尚未覆盖 / 后续

- 未执行真实手机号/短信验证码提交、有效 token 登录和外置 `http_poll/sse/ws` 服务验收；本轮
  只验证了本地登录页、无效 token 分支和已落库账号的查询链路。
- 指定隐私命令的真实 `@` 目标路径受本机 OneBot 群成员信息查询响应缺失影响；无 `@` 错误路径、
  临时未绑定 `@` 路径和其余群隐私命令均已验证，未将该环境问题伪装成插件成功。
- 订阅锁是 `SubscriptionStore` 实例级锁；当前运行时使用全局 `gs_subscribe` 单例，未来若多进程或多实例共享同一 JSON 文件，仍需引入文件级锁或单写者方案。
- 插件目录及 runtime 根目录均未发现 Git 仓库，本次未初始化 Git，也未创建提交。

## goal-1 O24 — 最终文档与生产只读审计 ✅

- O23 本地交付提交为 `b12f86e`；本轮基于该提交完成文档同步与生产只读审计，O24 文档记录随本次提交
  落盘。O23 提交未在本轮部署到生产。
- `atri` 只读状态：插件 `cb9996dbb36ccaeaca483035c0cbbbc59a8549c9`、`v0.2.0`、detached/clean，
  registry `61`；资源 generation `5d76860141d9ab5052417df25ccc9f5a929ff06b`、content SHA
  `92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4` 一致；容器 running、restart count `0`。
  `agent_tools.enabled=false`，容器内入口/registry/schema import smoke 通过，Dashboard 未认证 GET 为
  `401`，日志窗口无新增 DNABY error-like/traceback。
- 本地最终门禁：全量 pytest `721 passed, 1 skipped, 2 failed`（外部 `cdn.test` 图片连接）；全仓 Ruff
  仍有 13 条既有 admin/Goal 2/D03 基线问题；compileall、生成投影一致性和 diff check 通过。O23 的
  adapter/视觉证据仍按 `goal-1/tasks.md` 保留，真实 CDN/T2I 成功不因本只读核验被宣称。
