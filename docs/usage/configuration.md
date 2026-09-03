# 配置

插件配置入口是 AstrBot Dashboard 的插件配置页。根目录 [`_conf_schema.json`](../../_conf_schema.json)
是当前配置字段的机器可读投影；修改配置定义后，应由项目脚本重新生成，不要手工维护第二份字段清单。
修改 Dashboard 配置后请重载插件。

配置分为八组：`login`、`network`、`sign_in`、`notifications`、`display`、`resources`、`cache` 和
`agent_tools`。下面列出常用字段与默认值；完整类型、提示和可选项以 schema 为准。

## 登录 `login`

登录接入方式支持 `local`、`http_poll`、`sse` 和 `ws`；local 模式留空 URL 时使用内置服务的实际
监听地址，填写 `login.url` 后优先使用该公开地址。`login.qr_login` 发送二维码，
`login.tencent_docs` 将地址包装为腾讯文档可复制链接，`login.forward_login` 将登录内容包装为
合并转发消息；二维码优先于腾讯文档，OneBot 私聊仍按平台限制发送普通消息。

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `login.url` | 空 | 外置登录服务地址；留空时使用插件内置服务。 |
| `login.bind_host` | `127.0.0.1` | 内置登录服务监听地址。 |
| `login.port` | `6189` | 内置登录服务监听端口；`0` 表示由系统分配临时端口。 |
| `login.transport` | `local` | 登录接入方式，可选 `local`、`http_poll`、`sse`、`ws`。 |
| `login.shared_secret` | 空 | 外置登录接入使用的共享密钥；使用内置服务时留空。 |
| `login.tencent_docs` | `false` | 是否启用腾讯文档登录辅助。 |
| `login.qr_login` | `false` | 是否启用二维码登录。 |
| `login.forward_login` | `false` | 是否启用转发消息登录。 |
| `login.max_bind_count` | `2` | 每个用户允许绑定的最大 UID 数量。 |

`local` 模式在插件启动时使用内置登录服务；填写 `login.url` 后，登录回复优先使用该公开地址。
需要让其他设备访问时，`login.bind_host` 和 `login.url` 必须填写调用方可访问的地址。登录参数应在私聊中发送，不要发到公开群聊。

## 网络 `network`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `network.max_concurrent_requests` | `4` | 短生命周期网络请求的最大并发数。 |
| `network.api_proxy_url` | 空 | API 请求代理地址；不需要代理时留空。 |
| `network.local_proxy_url` | 空 | 本地登录或 WebSocket 请求的代理地址。 |
| `network.proxy_functions` | `[]` | 指定使用代理的功能，可选 `all`、`get_sms_code`、`login`。 |
| `network.no_proxy_functions` | `[]` | 指定强制直连的功能。 |
| `network.websocket_continue_seconds` | `300` | WebSocket 保活时间。 |
| `network.websocket_wait_seconds` | `5` | WebSocket 连接等待时间。 |

代理字段只影响对应的网络请求；公共资源的加速模式单独由 `resources` 配置。

## 签到 `sign_in`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `sign_in.community_tasks` | `bbs_sign、bbs_detail、bbs_like、bbs_share、bbs_reply` | 要执行的社区任务列表。 |
| `sign_in.enable_all_users` | `false` | 是否让定时签到覆盖所有已登录用户。 |
| `sign_in.scheduled_enabled` | `false` | 是否开启每日定时签到。 |
| `sign_in.sign_time` | `00:05` | 每日定时签到时间，格式为 `HH:mm`。 |
| `sign_in.concurrency` | `1` | 自动签到并发数。 |
| `sign_in.concurrency_interval_seconds` | `[3, 5]` | 自动签到任务之间的间隔范围，单位为秒。 |
| `sign_in.private_report` | `false` | 是否发送私聊签到报告。 |
| `sign_in.group_report` | `false` | 是否发送群聊签到报告。 |
| `sign_in.group_report_image` | `false` | 是否使用图片发送群聊签到报告。 |

`sign_in.scheduled_enabled` 默认关闭。开启后还需要设置有效的 `sign_in.sign_time`；
`sign_in.enable_all_users` 决定定时任务是否覆盖所有已登录用户，手动签到命令不受定时开关影响。

## 通知 `notifications`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `notifications.announcement_enabled` | `true` | 是否启用公告推送。 |
| `notifications.announcement_ids` | `[]` | 已处理公告 ID 列表，通常无需手动修改。 |
| `notifications.announcement_check_minutes` | `10` | 公告检查间隔，单位为分钟。 |
| `notifications.secret_subscriptions` | `['group']` | 密函订阅作用域，可选 `private`、`group`。 |
| `notifications.secret_simple_image` | `false` | 是否使用简易密函图片。 |
| `notifications.secret_push_minute` | `0` | 每小时推送密函的分钟数，`0` 表示整点。 |
| `notifications.secret_retry_interval_seconds` | `1` | 密函数据未准备好时的重试间隔，单位为秒。 |

公告与密函订阅还可以通过聊天命令管理，具体见 [命令说明](commands.md)。

## 显示 `display`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `display.command_prefixes` | `['kk']` | 命令触发前缀，可以填写字符串或字符串列表；列表中包含空字符串时允许无前缀触发。 |
| `display.guide_providers` | `['all']` | 角色攻略来源，可选 `all`、`狩月庭攻略组`、`猫冬`。 |
| `display.show_unowned_roles` | `true` | 是否在角色信息卡片中显示未拥有的角色和武器。 |
| `display.allow_mention_query` | `true` | 是否允许通过 @ 查询其他用户的角色信息。 |

如果把 `display.command_prefixes` 改成自定义前缀，发送命令时请使用新前缀；修改后重载插件即可生效。

## 公共资源 `resources`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `resources.github_acceleration` | `off` | 公共资源同步方式，可选 `off`、`edgeone`、`hk`、`gh_proxy`、`dpik`、`custom`。 |
| `resources.custom_github_acceleration_url` | 空 | `custom` 模式使用的 HTTP(S) 基础地址；其他模式无需填写。 |

默认 `resources.github_acceleration` 为 `off`。使用 `custom` 时只填写不含凭据、查询参数和片段的
HTTP(S) 基础地址；镜像请求失败会明确报告，不会把失败伪装成同步成功。资源同步和目录说明见 [公共资源](resources.md)。

## 缓存 `cache`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `cache.fresh_ttl_minutes` | `30` | 缓存保持 fresh 的时间，单位为分钟；`-1` 表示仅在主动刷新或失效时更新。 |
| `cache.retention_ttl_hours` | `24` | 缓存允许保留的时间，单位为小时。 |
| `cache.announcement_ttl_hours` | `24` | 公告和已校验资源缓存的保留时间，单位为小时。 |
| `cache.refresh_send_card` | `true` | 手动刷新成功后是否立即发送新卡片。 |

将 `cache.fresh_ttl_minutes` 设为 `0` 会让缓存立即进入待刷新状态；设为 `-1` 时业务缓存只在主动刷新或失效时更新。`cache.retention_ttl_hours` 和 `cache.announcement_ttl_hours` 仍应填写正数。

## Agent Tools `agent_tools`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `agent_tools.enabled` | `false` | 是否注册结构化查询工具；默认关闭，开启后需重载插件。 |

开启后不会改变聊天命令，也不会允许工具代替管理员执行账号、隐私、订阅或资源管理操作。工具列表和安全边界见 [Agent Tools 使用说明](agent-tools.md)。

## 数据目录与图片

插件运行期数据统一保存在 AstrBot 的插件数据目录：

```text
data/plugin_data/astrbot_plugin_dnaby/
```

目录由 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 提供，不写入插件源码目录。账号绑定、订阅、缓存、图片和公共资源都在这里管理；升级前请备份该目录，不要把其中的数据库、登录信息或订阅记录上传到公开位置。

图片卡片使用 AstrBot 4.26.0 及以上版本提供的全局 HTML/T2I 能力，不新增插件私有渲染服务配置。未启用该能力或服务返回无效图片时，需要图片的命令会返回统一失败提示，文字查询仍可继续使用。

如需查看命令前缀、登录和资源同步的实际操作，请继续阅读 [命令说明](commands.md)、[账号登录](login.md) 和 [公共资源](resources.md)。
