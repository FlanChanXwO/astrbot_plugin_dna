# 数据模型

## rewrite 当前新数据库

新入口使用 SQLAlchemy 2 async、`sqlite+aiosqlite` 和 Alembic。运行期数据库文件为
`StarTools.get_data_dir()` 下的 `dnaby.sqlite3`；它与 legacy 的 `dnaby.db` 是两个
独立路径，v0.1 不读取、不改写、也不迁移旧数据库。

`alembic/versions/0001_initial.py` 从空库创建 rewrite 的五张 normalized 表；
`0002_privacy_global_identity` 是旧 schema 的补充约束，`0003_global_identity` 已将账号、
凭据和隐私改为跨 AstrBot 平台、跨 Bot 的全局语义；当前 head 为
`0005_auto_sign_enabled`：
相同的 `user_id` 字符串在不同平台或 Bot 上视为同一身份，平台/Bot 不再是持久化身份键。

| 表 | 用途 | 关键字段 |
|---|---|---|
| `account_bindings` | 用户↔UID 全局绑定 | user_id, group_id, uid, is_active, auto_sign_enabled |
| `credential_records` | 私有 App 登录凭据 | user_id, uid, app_cookie, app_device_code, app_d_num, app_refresh_token, app_status |
| `sign_records` | 按 UID 和日期保存签到状态 | uid, date, game_sign, bbs_sign, bbs_detail, bbs_like, bbs_share, bbs_reply |
| `privacy_settings` | 个人/群组作用域隐私 | user_id, group_id, allow_peek, uid_hidden |
| `group_privacy_settings` | 群组强制隐私 | group_id, force_allow_peek, force_uid_hidden |

`0003_global_identity` 是有意的破坏性迁移：升级时删除并重建上述四张身份/隐私
表，因此旧账号、凭据、个人隐私和群隐私行全部丢弃；`sign_records` 不删除并原样
保留。降级只恢复 `0002` 的旧空表结构，不恢复被丢弃的数据。真实部署前必须备份
`dnaby.sqlite3`；需要回退时应同时恢复旧代码和迁移前数据库备份，不能让旧代码直接
读取新 schema。

`0004_app_credentials_only` 在当前 `credential_records` 表上物理删除
`web_token`、`web_device_code`、`web_d_num`、`web_refresh_token`、`web_status` 五列，
保留 App 凭据、身份绑定、签到和订阅等非凭据数据。升级前必须完成 SQLite 备份和完整性检查；
降级只会创建空的旧 Web 列，不可能恢复已经删除的值，也不能替代迁移前备份。

`0005_auto_sign_enabled` 为每条绑定增加 `auto_sign_enabled`，已有记录默认为 `true`。
该字段按 `(user_id, uid)` 绑定保存；切换 UID 不共享开关，定时签到默认尊重该字段，
`sign_in.enable_all_users` 可强制执行，手动“全部签到”忽略该字段。

`src/infrastructure/persistence/repositories.py` 的方法必须接收调用方提供的
`AsyncSession`；提交和回滚由 `AsyncDatabase.transaction()` 统一负责。生产 schema
变更走 Alembic，`create_schema_for_tests()` 仅用于隔离测试。每个 runtime 的写事务
还会串行化，以避免 SQLite 在可空 `group_id` 上发生并发 `SELECT`→`INSERT` upsert
竞态；`0003_global_identity` 通过数据库唯一约束和 SQLite 部分唯一索引约束全局
身份键、每用户一个 active UID、每用户一个全局隐私行以及裸 `group_id` 群隐私行。
旧 `0002` 在进入破坏性迁移前仍可能因历史重复全局隐私行显式失败，需部署者先备份、
审查并处理这类旧 schema 脏数据。

`credential_records` 的 Cookie、refresh token、设备标识和 d_num 只在私有 SQLite
字段中保存。`CredentialRecord.__repr__()` 与 `redacted_snapshot()` 只返回标识、状态
和是否存在凭据，不返回 secret 值；日志、异常和 DTO 仍必须沿用同一脱敏边界。

## 管理页与运行期文件边界

Dashboard 管理页的账号列表默认只返回 App 凭据状态；只有已认证管理员发起显式管理请求
（页面通常在打开账号详情时）才在管理 API 响应中携带全部 App 明文凭据。该响应使用
`Cache-Control: no-store`，
页面不写 `localStorage`/`sessionStorage`，关闭编辑器会清空前端凭据副本；这不能替代管理员对
屏幕、剪贴板、浏览器扩展、代理和截图的保护。日志、异常、普通命令响应、DTO `repr` 和备份
索引均不得出现 Cookie、token、refresh token、设备码或 d_num 原文。

管理员预览只允许从已认证的管理 API 发起，并固定绕过普通隐私显示策略；它不改变隐私表，也不
向响应暴露 renderer 的本地路径。没有可用凭据或上游/T2I 服务时，预览应返回可观察的安全错误，
不能伪造成功图片。

除 SQLite 外，以下文件/目录也位于同一 `StarTools.get_data_dir()` 运行期根目录，均不得提交：

- `scheduler_state.json` — 内置任务永久删除 tombstone；删除的业务任务没有管理 API 恢复操作。
- `alias_custom.json`、`weapon_alias_custom.json` — 角色和武器自定义别名覆盖层；默认资源别名只读且不被覆盖层改写。
- `panel_custom/` — 已移除面板管理后的历史文件；插件不再读取或删除，升级前仍可按需备份。
- `subscriptions.json`、`ann_state.json`、`ann_delivery_state.json` — 订阅、公告兼容 ID 列表与按目标
  投递状态等持久状态，不是普通缓存。
- `client_update_state.json` — 客户端更新的版本化状态文件，当前保存国服 PC/安卓各自的成功观察基线、
  最近一次变化摘要和 `pending_events`。事件以 `event_key` 去重，并保存首次匹配的 origin/uid/bot_id 目标
  及其 `pending`/`delivered` 状态；事件全部成功或目标被移除后清理，不保存凭据或原始上游响应。
- `rendered/` — 受控的运行期临时 JPEG/PNG artifact 文件，不是持久业务缓存。
- `cache/` — 玩家数据 JSON、完整 T2I 图片卡片以及公告 `announcement/` 类型缓存；玩家条目默认受
  30 分钟 fresh、24 小时硬保留和租约保护，公告条目默认 24 小时绝对保留，身份相关 key/tag
  不保存原始 user_id 或 UID。`cache.fresh_ttl_minutes=-1` 时，CacheManager 业务条目永久保持
  fresh 且不因时间自动清理，仍可由刷新、清理、资源版本变化或显式失效主动删除；`rendered/`
  临时文件不受该永久模式影响。
- `_HELP_CACHE` — 进程内帮助卡片缓存，插件终止时清空；`resource_generations/` 与
  `current.json` 由资源快照协调器按 generation lease 管理；密函缓存按当前小时保存已校验快照。

### 客户端更新状态与订阅

- `subscriptions.json` 中的客户端更新类型为 `订阅DNA客户端更新`；群聊订阅使用空 `uid`，
  `unified_msg_origin` 标识当前会话，`extra_data` 保存规范化的 `{"platforms":["pc","android"]}`
  子集。重复的 type+origin+uid 记录会更新平台筛选，停用记录不会参与投递。
- `client_update_state.json` 带 `schema_version`，当前按 `cn+pc`、`cn+android` 保存最近成功观察的
  snapshot、`observed_at` 和可选的 `last_change`，并保存待投递事件的变化快照、固定目标集合及每目标
  的 `pending`/`delivered` 状态。写入使用临时文件替换；JSON 损坏或结构非法时显式失败，不静默清空状态。
  schema v1 仅含基线时会在下一次写入升级为当前版本，已完成事件不形成无界历史。
- 客户端更新推送 DTO 只携带目标路由、平台和用户可见文本；OneBot 节点构造留在入口/bootstrap 适配边界，
  不把框架组件或真实凭据写入状态文件。

公告缓存的列表卡、详情页、详情 manifest 和源图都必须在内容完整且图片通过解码校验后写入；
公告 fingerprint 纳入 key，上游内容变化会失效旧条目。详情图片失败时不写入新的完整卡或
占位图，手动命令由服务层返回固定失败文案。旧 `ann_state.json` ID 在首次读取独立状态时迁移为
已处理，不补发历史公告；新公告只记录首次观察到的目标集合，单个目标成功后才写入 delivered
状态，失败目标留待后续轮询。

SQLite、JSON 和文件目录之间不存在同一物理事务。账号删除协调器按串行、逐项、可重试的步骤
报告 `failed`/`partial`，不能把跨存储操作表述为原子提交；运维备份与恢复步骤见
[maintenance.md](../dev/maintenance.md) 和 [admin-pages.md](../usage/admin-pages.md)。

## 账号 use case 约束

- `account_bindings` 是按 user_id、uid 归一化的一行一 UID 记录；`group_id` 只保留
  绑定来源上下文，不参与身份键。当前 UID 用 `is_active` 表示，切换在同一个显式
  事务中先取消其他记录再激活目标。
- 登录返回的每个角色会在同一事务中写入绑定和 App 凭据；达到 typed 配置中的
  `login.max_bind_count` 时整笔登录回滚，不留下半套记录。
- 角色结果带有服务端默认标记时，默认角色会成为当前 UID；没有默认标记时，只有首次
  登录才以结果中的第一个角色作为当前 UID。
- 退出登录只删除当前 active UID 的绑定和凭据，保留其他绑定；删除当前 UID 后会从
  剩余记录中确定性选择新的当前 UID。
- 凭据查询只返回 UID 与 App 是否保存的状态，不提供 Cookie、token、refresh token、
  设备码或 d_num 导出接口。`查看UID` 只展示调用者自己的绑定列表，沿用 legacy 列表
  语义；UID 隐藏策略由后续角色卡片/查询渲染 use case 调用。

## 隐私 use case 约束

- `PrivacySetting` 的个人命令沿用 legacy 行为，按 user_id 保存全局个人设置；repository
  仍支持可选 group_id 作用域，读取群组作用域时回退到全局个人值。
- `GroupPrivacySetting` 按裸 group_id 保存两个可独立清除的强制字段。查询 UID 隐藏
  和偷窥权限时，群强制字段优先；对应字段清除后恢复个人值。
- `display.allow_mention_query` 关闭时，@ 他人的查询解析回调用者；查询自己不受该开关和
  目标个人防偷窥设置影响。群强制防偷窥或目标个人 `allow_peek=False` 时同样解析回调用者。
- 指定隐私写入只检查目标是否存在任意 user UID 绑定，不向响应或异常暴露目标 UID。

`EventActor.bot_id` 仍属于运行期投递和 legacy transport 上下文，但不再参与上述四张
账号、凭据或隐私表的查询键。

## legacy-reference 迁移参考

以下表格只描述待迁移 legacy schema 的历史字段，不是当前 rewrite 的持久化契约；其中出现的
`bot_id` 不表示当前账号或隐私仍按 Bot 隔离。

旧 SQLModel 5 表（`dnaby/utils/database/models.py`）及其 DB 文件
`data/plugin_data/astrbot_plugin_dnaby/dnaby.db` 仅供后续行为迁移参考：

| 表 | 用途 | 关键字段 |
|---|---|---|
| `DNABind` | 用户↔UID 绑定 | user_id, bot_id, group_id, uid(多UID `_` 连接) |
| `DNAUser` | 登录凭证 | user_id, uid, bot_id, cookie, dev_code, d_num, refresh_token, web_* |
| `DNASign` | 签到记录 | uid, date, game_sign, bbs_sign, bbs_detail, bbs_like, bbs_share, bbs_reply |
| `DNAPrivacy` | 个人隐私 | user_id, bot_id, group_id, allow_peek, uid_hidden |
| `DNAGroupPrivacy` | 群隐私 | group_id, bot_id, force_allow_peek, force_uid_hidden |

`subscriptions.json` 是当前 rewrite 的运行期订阅存储；legacy `dnaby/utils/database` 中的旧订阅结构仅供迁移参考。
客户端更新订阅使用独立的 `订阅DNA客户端更新` 类型与 `extra_data.platforms`，不与公告/密函订阅语义混用。
