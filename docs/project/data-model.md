# 数据模型

SQLModel 5 表（`dnaby/utils/database/models.py`），DB 文件：`data/plugin_data/astrbot_plugin_dnaby/dnaby.db`。

| 表 | 用途 | 关键字段 |
|---|---|---|
| `DNABind` | 用户↔UID 绑定 | user_id, bot_id, group_id, uid(多UID `_` 连接) |
| `DNAUser` | 登录凭证 | user_id, uid, bot_id, cookie, dev_code, d_num, refresh_token, web_* |
| `DNASign` | 签到记录 | uid, date, game_sign, bbs_sign, bbs_detail, bbs_like, bbs_share, bbs_reply |
| `DNAPrivacy` | 个人隐私 | user_id, bot_id, group_id, allow_peek, uid_hidden |
| `DNAGroupPrivacy` | 群隐私 | group_id, bot_id, force_allow_peek, force_uid_hidden |

订阅数据存 JSON（`data/plugin_data/astrbot_plugin_dnaby/subscriptions.json`）。
