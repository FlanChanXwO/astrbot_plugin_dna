# 写入型能力的离线契约与权限边界

> 适用范围：`rewrite/v0.1` 中全部对真实账户/平台产生写入的命令。这些能力只允许在
> **fake transport + 隔离 SQLite + 模拟事件 + 旧逻辑 fixture** 中验证；真实 NapCat 或
> 真实账户上的写入操作一律不执行。**离线验证不等于真实行为已验证。**

## 离线契约（offline ≠ real）

每条写入型命令都由一个明确的离线契约覆盖：通过生成后的 AstrBot handler 分发到真实
use case / service，service 只调用注入的 fake transport（或直接写隔离 SQLite），事件用
公开 API 的 mock fixture，最后断言产出框架无关的 `CommandResponse`。全部写入命令的权限
边界与离线契约在 `tests/test_write_contracts.py` 中集中审计：

- `WRITE_COMMANDS`：写入命令 id → 期望权限（`user`/`admin`）。
- `CONTRACT_COVERAGE`：命令 id → 覆盖它的离线契约测试文件与代表性用例。
- `test_every_write_command_dispatches_offline`：每条写入命令都能离线分发并产出结果。
- `test_sign_write_touches_only_injected_transport`：离线写路径只调用注入 transport。

## 权限边界

| 权限 | 写入命令 |
| --- | --- |
| `user` | `account_login/logout/bind/switch/delete_all/delete`、个人 `privacy` 四条、`sign`、`mh_subscribe_by_name`、`mh_subscribe_cycle` |
| `admin` | 群管理 `privacy` 十条、`sign_all`、`sign_result_subscribe`、`mh_pic_subscribe`、`mh_text_subscribe`、`mh_test`、`ann_sub`、`ann_unsub`、面板图六条、`resource_status`、`download_resource`、`alias_add_delete`、`alias_recover` |

`admin` 统一映射 AstrBot 公开的 `PermissionType.ADMIN`；插件不再保留自定义 owner
入口过滤器，也不自行读取 `admins_id`。普通群成员不能通过 AstrBot 的 admin 过滤器执行
这些命令。

## 逐能力离线覆盖

| 能力 | 契约测试文件 | 说明 |
| --- | --- | --- |
| 登录（页/ token / 验证码） | `test_account.py` | 成功持久化、取消、事务回滚、错误脱敏；凭据不入日志/响应 |
| 退出登录 | `test_account.py` | 规范化记录生命周期 |
| 绑定 / 切换 / 删除 UID | `test_account.py` | normalized 记录、事务、权限 |
| 删除全部 UID | `test_account.py` | 全部记录移除 |
| 个人隐私写入 | `test_privacy.py` | 群强制优先、拒绝时不落库、并发 upsert 唯一 |
| 群管理隐私写入 | `test_privacy_commands.py` | admin 过滤器、At 目标提取、缺失目标显式错误 |
| 游戏/社区签到 | `test_checkin.py` | 两条链路永久执行；成功落盘、已签跳过、失败可见 |
| 全部签到（批量） | `test_checkin.py` | 并发/间隔聚合 |
| 签到结果订阅 | `test_checkin.py` + `test_subscription_store.py` | 订阅/取消、去重、持久化 |

## 未覆盖/边界

- 真实平台推送、真实账户签到、真实面板上传/删除/压缩、别名修改、资源更新等写入行为
  未在真实账户上执行；面板、资源和别名命令已注册，但当前只由隔离 fixture/ fake
  transport 覆盖，不把离线结果当作真实平台验收。
- 最终真实平台写入能力验收边界由本次 goal 终审统一记录，不得以本离线契约替代。
