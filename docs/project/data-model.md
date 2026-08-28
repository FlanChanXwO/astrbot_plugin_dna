# 数据模型

## rewrite 当前新数据库

新入口使用 SQLAlchemy 2 async、`sqlite+aiosqlite` 和 Alembic。运行期数据库文件为
`StarTools.get_data_dir()` 下的 `dnaby.sqlite3`；它与 legacy 的 `dnaby.db` 是两个
独立路径，v0.1 不读取、不改写、也不迁移旧数据库。

`alembic/versions/0001_initial.py` 从空库创建 rewrite 的五张 normalized 表；
`0002_privacy_global_identity` 是旧 schema 的补充约束，当前 head
`0003_global_identity` 已将账号、凭据和隐私改为跨 Bot 的全局语义：

| 表 | 用途 | 关键字段 |
|---|---|---|
| `account_bindings` | 用户↔UID 全局绑定 | user_id, group_id, uid, is_active |
| `credential_records` | 私有登录凭据 | user_id, uid, app_*/web_* |
| `sign_records` | 按 UID 和日期保存签到状态 | uid, date, game_sign, bbs_sign, bbs_detail, bbs_like, bbs_share, bbs_reply |
| `privacy_settings` | 个人/群组作用域隐私 | user_id, group_id, allow_peek, uid_hidden |
| `group_privacy_settings` | 群组强制隐私 | group_id, force_allow_peek, force_uid_hidden |

`0003_global_identity` 是有意的破坏性迁移：升级时删除并重建上述四张身份/隐私
表，因此旧账号、凭据、个人隐私和群隐私行全部丢弃；`sign_records` 不删除并原样
保留。降级只恢复 `0002` 的旧空表结构，不恢复被丢弃的数据。真实部署前必须备份
`dnaby.sqlite3`；需要回退时应同时恢复旧代码和迁移前数据库备份，不能让旧代码直接
读取新 schema。

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

## 账号 use case 约束

- `account_bindings` 是按 user_id、uid 归一化的一行一 UID 记录；`group_id` 只保留
  绑定来源上下文，不参与身份键。当前 UID 用 `is_active` 表示，切换在同一个显式
  事务中先取消其他记录再激活目标。
- 登录返回的每个角色会在同一事务中写入绑定和 App/Web 凭据；达到 typed 配置中的
  `login.max_bind_count` 时整笔登录回滚，不留下半套记录。
- 角色结果带有服务端默认标记时，默认角色会成为当前 UID；没有默认标记时，只有首次
  登录才以结果中的第一个角色作为当前 UID。
- 退出登录只删除当前 active UID 的绑定和凭据，保留其他绑定；删除当前 UID 后会从
  剩余记录中确定性选择新的当前 UID。
- 凭据查询只返回 UID 与 App/Web 是否保存的状态，不提供 Cookie、token、refresh token、
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

旧 SQLModel 5 表（`dnaby/utils/database/models.py`）及其 DB 文件
`data/plugin_data/astrbot_plugin_dnaby/dnaby.db` 仅供后续行为迁移参考：

| 表 | 用途 | 关键字段 |
|---|---|---|
| `DNABind` | 用户↔UID 绑定 | user_id, bot_id, group_id, uid(多UID `_` 连接) |
| `DNAUser` | 登录凭证 | user_id, uid, bot_id, cookie, dev_code, d_num, refresh_token, web_* |
| `DNASign` | 签到记录 | uid, date, game_sign, bbs_sign, bbs_detail, bbs_like, bbs_share, bbs_reply |
| `DNAPrivacy` | 个人隐私 | user_id, bot_id, group_id, allow_peek, uid_hidden |
| `DNAGroupPrivacy` | 群隐私 | group_id, bot_id, force_allow_peek, force_uid_hidden |

订阅数据仍是 legacy 参考实现中的 JSON（`data/plugin_data/astrbot_plugin_dnaby/subscriptions.json`）；
新订阅模型不在 Task 9 范围内。
