# 配置

插件配置入口是 AstrBot Dashboard 的插件配置页。根目录 [`_conf_schema.json`](../../_conf_schema.json)
是当前配置字段的机器可读投影；修改配置定义后，应由项目脚本重新生成，不要手工维护第二份字段清单。
修改 Dashboard 配置后请重载插件。

配置按语义分为十组：`general`、`login`、`ai`、`sign_in`、`notifications`、`client_updates`、
`display`、`network`、`resources` 和 `cache`。下面列出常用字段与默认值；完整类型、提示和可选项以
schema 为准。

## 通用 `general`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `general.command_prefixes` | `['kk']` | 命令触发前缀列表；列表中包含空字符串时允许无前缀触发。 |
| `general.allow_mention_query` | `true` | 是否允许通过 @ 查询其他用户的角色信息。 |

修改命令前缀后，发送命令时请使用新前缀；重载插件后生效。

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

## AI `ai`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `ai.agent_tools_enabled` | `false` | 是否注册二重螺旋 Agent Tools；修改后需重载插件。 |

开启后不会改变聊天命令，也不会允许工具代替管理员执行账号、隐私、订阅或资源管理操作。工具列表和安全边界见 [Agent Tools 使用说明](agent-tools.md)。

## 签到 `sign_in`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `sign_in.community_tasks` | `bbs_sign、bbs_detail、bbs_like、bbs_share、bbs_reply` | 要执行的社区任务列表。 |
| `sign_in.default_auto_sign_enabled` | `true` | 新 UID 首次绑定时的自动签到默认值。用户之后可以单独关闭或开启自己的自动签到。 |
| `sign_in.sign_time` | `00:05` | 每日自动签到时间，格式为 `HH:mm`。 |
| `sign_in.concurrency` | `1` | 自动签到并发数。 |
| `sign_in.concurrency_interval_seconds` | `[3, 5]` | 自动签到任务之间的随机间隔范围，单位为秒。 |
| `sign_in.private_report` | `false` | 是否发送私聊签到报告；本轮不改变其既有语义。 |
| `sign_in.group_report` | `false` | 群组报告总开关；开启后仍需在目标群执行 `订阅本群签到报告`。 |
| `sign_in.group_report_image` | `false` | 仅控制本群报告格式；`false` 发送文字，`true` 发送图片并保留必要明细文字。 |

自动签到的正式开关属于每个 UID 的用户状态，不再使用全局 `enable_all_users` 配置覆盖已有用户。
旧配置中的 `SignAllUser` 会迁移为 `default_auto_sign_enabled`。旧配置中的
`scheduled_enabled` 是旧版配置的兼容字段，schema 会以 invisible 字段保留它，避免 AstrBot
在插件构造前清理旧值；它不进入新的 typed model，只在首次启动时迁移为
`scheduler_state.json` 中 `dnaby_sign_daily` 的暂停状态，并写入一次性迁移标记。迁移完成后，
每日任务由 scheduler registry 的暂停/恢复状态管理，修改这个旧隐藏字段不会再次覆盖正式状态。
缺少该旧字段的新配置默认启用。该兼容迁移不改变每个 UID 的 `auto_sign_enabled`，也不影响手动“全部签到”。
`订阅签到结果` 管理所有账号、所有群的全局文字汇总，`订阅本群签到报告` 管理当前群的独立
报告，两种订阅互不覆盖。游戏签到和社区签到分别发送；私聊绑定只进入全局汇总，不会被路由到群。

## 通知 `notifications`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `notifications.announcement_enabled` | `true` | 是否启用公告推送。 |
| `notifications.announcement_check_minutes` | `10` | 公告检查间隔，单位为分钟。 |
| `notifications.secret_simple_image` | `false` | 是否使用简易密函图片。 |
| `notifications.secret_push_minute` | `0` | 每小时在该分钟推送密函，默认整点。 |
| `notifications.secret_retry_interval_seconds` | `1` | 密函数据未准备好或校验失败时的重试间隔，单位为秒。该字段保留在 schema 中但不在 Dashboard 显示。 |

公告 ID、密函订阅和客户端更新配置不属于该组。公告投递状态与密函订阅由运行期数据和聊天命令管理，客户端更新见下一节。

## 客户端更新 `client_updates`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `client_updates.enabled` | `true` | 是否启用客户端更新定时检查与推送。 |
| `client_updates.check_minutes` | `60` | 客户端更新检查间隔，单位为分钟，必须为正整数。 |
| `client_updates.channels` | `['pc_cn', 'android_astc_cn']` | 固定 channel ID 列表；只填写 registry 中的 ID，不填写 URL、branch 或 manifest key。 |
| `client_updates.merge_forward` | `true` | OneBot 平台是否将同轮多渠道更新合并为转发消息。 |

默认启用 `pc_cn` 和 `android_astc_cn` 两个 channel。每个 channel 的版本、manifest、大小、baseline
和投递事件独立管理；配置只选择 channel ID，不直接承载外部源地址。
客户端更新只读取上游版本和 manifest JSON，不下载或执行补丁。上游 PC 渠道及部分 fallback 地址仍使用
协议要求的 HTTP，存在传输内容可被篡改的风险；因此该功能只用于只读版本提示，不应被视为安全的更新来源。

## 显示 `display`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `display.guide_providers` | `['all']` | 角色攻略来源，可选 `all`、`狩月庭攻略组`、`猫冬`。 |
| `display.show_unowned_roles` | `true` | 是否在角色信息卡片中显示未拥有的角色和武器。 |

命令前缀和 AT 查询属于 `general`，不再写入 `display`。

## 网络 `network`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `network.max_concurrent_requests` | `4` | 短生命周期网络请求的最大并发数。 |
| `network.api_base_url` | 空 | 兼容 API 反代服务的 base URL；留空使用官方 API。 |
| `network.proxy_url` | 空 | App REST API 与官方业务 WebSocket 使用的代理地址；留空直连。 |
| `network.websocket_continue_seconds` | `300` | API WebSocket 保活时间，单位为秒。 |
| `network.websocket_wait_seconds` | `5` | 等待 API WebSocket 建立连接的时间，单位为秒。 |

`network.proxy_url` 只影响二重螺旋 App REST API 和官方业务 WebSocket，不影响 OneBot、外置
`dna-login`、GitHub、公共资源 CDN、AstrBot 或第三方攻略接口。WebSocket 两项也只描述 API
WebSocket，不描述 OneBot 或外置登录服务的连接。

运行期由统一 App transport 发送 REST 请求并管理官方业务 WebSocket；调用方函数名不会改变代理
范围。取消、网络断开、非 2xx、服务端响应异常和 WebSocket close/error 会分别暴露给上层处理。

旧版 `api_proxy_url`、扁平 `DNAUrlProxyUrl` 会迁移为 `network.api_base_url`。旧版局部代理只有在
`local_proxy_url` 非空、`proxy_functions` 恰为 `['all']` 且 `no_proxy_functions` 为空时，才会迁移为
`network.proxy_url`；其他组合不会扩大代理范围，会记录 warning 并要求重新配置 `network.proxy_url`。

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
| `cache.ttl_hours` | `24` | 所有 `CacheManager` 内容缓存共用的整数 TTL（小时）。`-1` 永久有效，`0` 禁用持久缓存，正整数表示缓存有效期。 |
| `cache.refresh_send_card` | `true` | 单角色主动刷新成功后是否在成功提示后发送新面板图片。`false` 仍完整刷新、渲染并更新缓存，只省略图片；批量刷新始终只返回汇总。 |

`cache.ttl_hours` 只允许 `-1`、`0` 和正整数，小于 `-1` 会在配置校验时失败：

- `-1`：内容缓存读取始终返回 `fresh`，时间维护不会删除条目；显式刷新或 `invalidate` 仍然有效。
- `0`：`get` 始终返回原因 `disabled` 的 `miss`，不读取磁盘；`put` 只校验内容并返回内存 metadata，不创建或写入持久缓存文件。维护任务仍会删除已有且无活动租约的缓存残留。
- 正整数：条目年龄小于 TTL 时返回 `fresh`；到达 TTL 后直接返回原因 `ttl_expired` 的 `miss`，不再提供旧内容回退。维护任务删除到期且无活动租约的条目。

`rendered/` 临时文件不属于内容缓存，内部固定按 24 小时清理；`resource_generations/` 等资源快照
继续由资源协调器按 generation lease 管理。旧的 `fresh_ttl_minutes`、`retention_ttl_hours`、
`announcement_ttl_hours` 会记录 warning 后丢弃，不迁移旧的自定义数值；`cache.refresh_send_card`
保留已有配置值，缺失时默认启用（`true`）。

## 数据目录与图片

插件运行期数据统一保存在 AstrBot 的插件数据目录：

```text
data/plugin_data/astrbot_plugin_dnaby/
```

目录由 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 提供，不写入插件源码目录。账号绑定、订阅、缓存、图片和公共资源都在这里管理；升级前请备份该目录，不要把其中的数据库、登录信息或订阅记录上传到公开位置。

图片卡片使用 AstrBot 4.26.0 及以上版本提供的全局 HTML/T2I 能力，不新增插件私有渲染服务配置。未启用该能力或服务返回无效图片时，需要图片的命令会返回统一失败提示，文字查询仍可继续使用。

如需查看命令前缀、登录和资源同步的实际操作，请继续阅读 [命令说明](commands.md)、[账号登录](login.md) 和 [公共资源](resources.md)。
