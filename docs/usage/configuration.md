# 配置

插件配置在 AstrBot Dashboard 插件配置页。根目录 `_conf_schema.json` 由
`src/infrastructure/config` 中的 Pydantic 模型生成；修改配置定义后运行
`python3 scripts/generate_config_schema.py` 同步 schema，不手工维护两份字段定义。

## 分组

- `login`：登录 URL、监听地址/端口、接入方式、共享密钥、二维码/转发登录和未登录绑定数量。
  接入方式支持 `local`、`http_poll`、`sse`、`ws`；local 模式留空 URL 时使用内置服务的实际
  监听地址，配置 URL 时优先用它作为公开登录地址。
  登录展示选项由当前 rewrite 登录命令直接读取：`qr_login` 发送二维码，`tencent_docs` 将地址包装为
  腾讯文档可复制链接，`forward_login` 将登录内容包装为合并转发消息；二维码优先于腾讯文档，
  OneBot 私聊仍按平台限制发送普通消息。
- `network`：API/本地代理、需要或不需要代理的函数、WebSocket 保活和连接等待时间。
- `sign_in`：社区任务列表、定时签到时间、并发间隔和签到报告。游戏签到与社区任务固定
  启用，不提供功能开启配置；`scheduled_enabled` 仅控制每日定时任务是否运行。`sign_time`
  必须是有效的 `HH:mm` 时间；显式非法值会在配置校验/插件启动时报告错误，不会静默改用
  `00:05`。
- `notifications`：公告轮询、密函订阅与订阅级时间窗口、图片模式。密函自动推送默认在每小时
  整点，可用 `secret_push_minute` 配置分钟；当前小时缓存由服务按有效性自动管理。
- `cache`：玩家数据、玩家卡片和公告缓存的 fresh/硬保留时间，以及手动刷新后的发送策略。
- `display`：命令前缀、攻略来源、未拥有角色展示和 AT 查询开关；
  `allow_mention_query` 控制是否允许查询被 @ 的他人。命令前缀可填写字符串或字符串列表；
  显式非法结构会在配置校验时报告错误，不会静默改回 `kk`。（角色原图引用因公开结果边界
  无消息 ID 交付点暂不支持，不再提供开关。）
- `resources`：公共资源仓库的 GitHub 加速模式和自定义 HTTP(S) 加速前缀。默认
  `github_acceleration=off` 直连；`edgeone`、`hk`、`gh_proxy`、`dpik` 使用内置前缀，
  `custom` 只使用经过规范化的自定义基础 URL。镜像失败会直接报告，不会静默回退直连。
- `agent_tools`：AstrBot Agent Tools 总开关。默认关闭；工具列表、参数、返回和安全边界见
  [Agent Tools 使用说明](agent-tools.md)。

资源配置的唯一字段是：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `resources.github_acceleration` | `off` | `off/edgeone/hk/gh_proxy/dpik/custom`；只影响公共资源 Git/Raw 请求。 |
| `resources.custom_github_acceleration_url` | 空字符串 | 仅 `custom` 使用；必须是无凭据、无 query/fragment 的 HTTP(S) 基础 URL。 |

## 通知与缓存字段

公告目标由运行期 `subscriptions.json` 唯一维护；旧 `announcement_groups` 仅保留给人工参考，不再导入、同步或恢复。

`notifications` 中的公告字段用于全局开关和兼容状态；密函推送时间窗口属于每条订阅记录，
通过 `订阅密函时间17:23` 或 `订阅密函周期17:23` 设置，不是全局配置。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `notifications.announcement_enabled` | `true` | 是否启用公告推送。 |
| `notifications.announcement_ids` | `[]` | 已处理公告 ID 的兼容状态列表。 |
| `notifications.announcement_check_minutes` | `10` | 公告轮询间隔，范围 `0..60` 分钟。 |
| `notifications.secret_subscriptions` | `["group"]` | 密函订阅作用域，可选 `private`、`group`。 |
| `notifications.secret_simple_image` | `false` | 是否使用简易密函图片。 |
| `notifications.secret_push_minute` | `0` | 每小时密函推送的分钟，范围 `0..59`；默认整点。 |
| `notifications.secret_retry_interval_seconds` | `1` | 密函数据尚未准备好或校验失败时的重试间隔；取消或停止会立即结束等待。 |

密函自动推送由 scheduler 安排在每小时 `HH:<secret_push_minute>`，只按订阅记录的时间窗口筛选目标；全局
`notifications.secret_push_time` 与 `notifications.secret_cache` 已移除，旧版 `MHPushSubscribe`
和 `MHCache` 也不会进入 typed 配置或生成 schema。当前小时缓存由服务按有效性自动管理。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `cache.fresh_ttl_minutes` | `30` | 缓存保持 fresh 的时间；设为 `0` 表示立即视为 stale，设为 `-1` 表示 `CacheManager` 业务缓存永久保持 fresh 且不因时间自动清理，直到主动刷新或失效。 |
| `cache.retention_ttl_hours` | `24` | 玩家缓存的硬保留时间；超过后维护任务可清理。 |
| `cache.announcement_ttl_hours` | `24` | 公告列表、详情、manifest 和已校验源图的绝对保留时间。 |
| `cache.refresh_send_card` | `true` | 手动刷新成功后是否立即发送新的完整卡片。 |

`-1` 只对 `cache.fresh_ttl_minutes` 有特殊含义；`retention_ttl_hours` 和
`announcement_ttl_hours` 仍必须填写正数。永久模式下业务缓存不会因为时间自动失效或清理，
但 `rendered/` 临时文件仍按 `retention_ttl_hours` 回收。

## Agent Tools 配置

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `agent_tools.enabled` | `false` | 是否注册 DNABY Agent Tools；关闭时注册数量为 0，开启时注册 17 个（16 个只读查询和 1 个签到写工具）。 |

这是 Agent Tools 的唯一配置开关。它不改变聊天命令的注册，也不开放账号、凭据、隐私、订阅、
资源或管理配置写操作。修改后需重新加载插件，生命周期会在 `initialize()`/`terminate()`
中完成注册和解除注册。

fresh 过期但仍在硬保留期内时会尝试刷新；刷新失败且存在完整旧卡时会带过期提示。公告缓存的
绝对保留使用 `cache.announcement_ttl_hours`，不受已移除的全局密函缓存开关控制。

公共资源仓库、manifest、兑换码 v1、旧 GitCode `end_at` 迁移和镜像切换步骤见
[资源运维说明](resources.md)。插件没有传统 HTTP/SOCKS 代理配置；不要把
`network.local_proxy_url` 当作资源镜像配置。

新入口在 bootstrap 边界将 AstrBot 配置转换为 `DnabySettings`；use case 不直接读取
未类型化字典。legacy `dnaby/dna_config` 的 `DNAConfig.get_config("Key").data` 语义
仅为迁移参考，旧 SQLite 和旧配置不会在本阶段自动迁移；新资源下载不会回写旧配置或旧
数据库。

## 新数据库首次初始化

账号和隐私 use case 使用 `StarTools.get_data_dir("astrbot_plugin_dnaby")/dnaby.sqlite3`。
生产 runtime 不调用测试专用的 `create_schema_for_tests()`；首次启用或 schema 版本变更前，
部署者须在安装了项目依赖的环境中执行 Alembic 初始迁移，并通过环境变量提供目标 URL：

```bash
DNABY_DATABASE_URL="sqlite+aiosqlite:////绝对路径/dnaby.sqlite3" \
  alembic -c /绝对路径/astrbot_plugin_dnaby/alembic.ini upgrade head
```

迁移失败应停止部署并保留原错误；不要把旧 `dnaby.db` 改名或交给新 schema 直接打开。
当前本地验证环境未安装 Alembic，隔离 migration round-trip 按测试约定显式 skip；这不等同于
生产 schema 已完成迁移。此前 `atri` 只读核验观察到生产数据库 revision 为 `0003_global_identity`；
该观察不代表本次文档/冒烟执行了 migration，也不替代升级前备份。

`AccountService` 使用 `login.max_bind_count` 约束新增 UID；登录成功会自动建立绑定，聊天侧只保留
切换、删除和查看 UID，不提供脱离登录流程的公开绑定命令。登录页会话由 runtime 注入的
`LoginFlowCoordinator` 管理：local 服务在初始化时启动、在终止时先清理登录等待再释放端口；
外置 transport 只使用 typed `login.url`、`login.transport` 和 `login.shared_secret`。未配置
外置地址时不会伪造登录链接，而是返回稳定的登录服务失败提示。

登录凭据当前为 App-only；Web 登录页、Web token fallback 和五个 Web 凭据数据库列已移除。
执行 `alembic upgrade head` 前必须按维护文档备份并检查 `dnaby.sqlite3`；降级只创建空 Web
列，不能恢复已经删除的凭据。

`account_bindings.auto_sign_enabled` 在 `0005_auto_sign_enabled` 中新增，已有绑定默认值为
`true`。开启或关闭自动签到只修改当前用户当前 UID，切换 UID 后各绑定独立；手动“全部签到”
忽略该开关，定时任务默认尊重该开关，`sign_in.enable_all_users` 可强制全部执行。

隐私 use case 按 `display.allow_mention_query` 解析他人查询；关闭时查询目标会回到调用者，
查询自己仍然允许。个人/群强制隐私的具体命令见 [commands.md](commands.md)。

共享密钥使用 Pydantic `SecretStr`，schema 默认值保持为空；不得把实际密钥写入
Git、日志、异常或用户可见响应。

资源加速配置中的自定义 URL 只允许 HTTP(S) 基础地址，自动去除首尾空白和尾部斜杠，
拒绝控制字符、反斜杠、userinfo、query、fragment 及相对路径段；无效配置不会回显原始
输入。该配置只影响公共资源 Git/Raw 请求，不复用 `network.local_proxy_url`。

切换加速前先执行 owner 命令 `资源状态` 记录当前 manifest/resource version；修改配置后执行
`下载全部资源`，确认新 generation 的 commit 和状态，再保留配置。镜像只负责传输，插件仍
校验规范 GitHub origin、`main`、manifest 和完整资源候选；镜像不可用时会显式失败，不能把
失败当作已更新，也不会自动直连或改走 ZIP。

## HTML/T2I 图片渲染

生成型图片复用 AstrBot 4.26.0 及以上版本的全局 HTML/T2I 服务，不新增插件私有 endpoint 配置。
服务不可用或返回无效图片时，命令返回统一失败提示，详细原因仅记录到 AstrBot 日志。
