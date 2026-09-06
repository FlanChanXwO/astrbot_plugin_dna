# DNAUID（二重螺旋）

DNAUID（二重螺旋）是面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的游戏助手插件，提供账号管理、角色信息、图鉴攻略、签到、密函、公告和隐私控制等功能。插件版本与 AstrBot 兼容范围以 [`metadata.yaml`](metadata.yaml) 为准。

## 核心功能

- **账号管理**：登录、退出登录、切换 UID、查看绑定 UID，以及严格脱敏的登录状态查询。
- **角色与玩家信息**：角色总览、角色详情、面板刷新、缓存清理、日常便笺、周报和日历。
- **图鉴与攻略**：角色/武器列表、角色图鉴、别名查询、角色攻略和当前可用兑换码。
- **签到服务**：手动签到、签到日历、当前 UID 的自动签到，以及社区任务和签到报告配置。
- **密函与公告**：查看密函和公告，按会话订阅推送；管理员可以管理群聊公告订阅。
- **隐私控制**：控制他人是否可以查询自己的信息，并选择是否在卡片中显示 UID。
- **管理员工具**：批量签到、角色/武器别名维护、公共资源状态查看与资源同步。
- **可选 Agent Tools**：通过配置开关提供结构化查询工具，默认关闭，不影响聊天命令。

## 支持的 AstrBot 版本

当前插件要求 **AstrBot 4.26.0 或更高版本**。建议升级 AstrBot 后再升级插件；如果 Dashboard 报告版本不兼容，请先确认 AstrBot 版本和插件目录中的 [`metadata.yaml`](metadata.yaml)。

图片卡片使用 AstrBot 提供的全局 HTML/T2I 能力。未启用该能力时，文字查询仍可用，但需要图片渲染的命令可能无法生成卡片。

## 手动安装

1. 准备 AstrBot 4.26.0 或更高版本，并确认可以访问 AstrBot 的插件目录。
2. 在 AstrBot 根目录执行：

   ```bash
   git clone https://github.com/FlanChanXwO/astrbot_plugin_dnaby.git data/plugins/astrbot_plugin_dnaby
   python3 -m pip install -r data/plugins/astrbot_plugin_dnaby/requirements.txt
   ```

   如果 AstrBot 已自动同步插件依赖，可以跳过第二条命令。已存在插件目录时，请更新原目录，不要在插件目录下再套一层同名目录。
3. 启动或重载 AstrBot，在 Dashboard 的插件列表中确认 `astrbot_plugin_dnaby` 已启用。
4. 打开插件配置页，按需要设置登录、命令前缀和通知选项，然后发送 `kk帮助` 检查命令是否生效。

当前文档以手动安装为准；如后续提供 AstrBot Marketplace 版本，请以仓库页面和市场页面显示的实际状态为准。

## 配置

配置入口是 AstrBot Dashboard 的插件配置页。配置分为以下十组；完整字段、类型、提示和默认值见
[`_conf_schema.json`](_conf_schema.json) 与 [配置说明](docs/usage/configuration.md)。修改配置后请重载插件。

### 通用 `general`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `general.command_prefixes` | `['kk']` | 命令触发前缀列表；列表中包含空字符串时允许无前缀触发。 |
| `general.allow_mention_query` | `true` | 是否允许通过 @ 查询其他用户的角色信息。 |

### 登录 `login`

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

### AI `ai`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `ai.agent_tools_enabled` | `false` | 是否注册二重螺旋 Agent Tools；默认关闭，开启后需重载插件。 |

### 签到 `sign_in`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `sign_in.community_tasks` | `bbs_sign、bbs_detail、bbs_like、bbs_share、bbs_reply` | 要执行的社区任务列表。 |
| `sign_in.default_auto_sign_enabled` | `true` | 新 UID 首次绑定时的自动签到默认值；用户之后可以单独关闭或开启。 |
| `sign_in.sign_time` | `00:05` | 每日自动签到时间，格式为 `HH:mm`。 |
| `sign_in.concurrency` | `1` | 自动签到并发数。 |
| `sign_in.concurrency_interval_seconds` | `[3, 5]` | 自动签到任务之间的随机间隔范围，单位为秒。 |
| `sign_in.private_report` | `false` | 是否发送私聊签到报告。 |
| `sign_in.group_report` | `false` | 是否发送群聊签到报告。 |
| `sign_in.group_report_image` | `false` | 是否使用图片发送群聊签到报告。 |

自动签到的正式开关属于每个 UID 的用户状态；`sign_in.default_auto_sign_enabled` 只控制新 UID
首次绑定时的默认值。定时任务不会用全局开关覆盖用户自己的选择。

### 通知 `notifications`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `notifications.announcement_enabled` | `true` | 是否启用公告推送。 |
| `notifications.announcement_check_minutes` | `10` | 公告检查间隔，单位为分钟。 |
| `notifications.secret_simple_image` | `false` | 是否使用简易密函图片。 |
| `notifications.secret_push_minute` | `0` | 每小时在该分钟推送密函，默认整点。 |
| `notifications.secret_retry_interval_seconds` | `1` | 密函数据未准备好或校验失败时的重试间隔；该字段保留在 schema 中但不在 Dashboard 显示。 |

公告投递状态和密函订阅由运行期数据与聊天命令管理，不需要手工编辑配置文件。

### 客户端更新 `client_updates`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `client_updates.enabled` | `true` | 是否启用客户端更新定时检查与推送。 |
| `client_updates.check_minutes` | `60` | 客户端更新检查间隔，单位为分钟，必须为正整数。 |
| `client_updates.channels` | `['pc_cn', 'android_astc_cn']` | 固定 channel ID 列表；只填写受支持的 channel ID，不填写 URL 或 manifest key。 |
| `client_updates.merge_forward` | `true` | OneBot 平台是否将同轮多 channel 更新合并为转发消息；其他平台不受此开关影响。 |

每个 channel 的版本、manifest、大小、baseline 和投递事件独立管理。首次无 baseline 时只展示当前版本，
不伪造上次版本或可比较大小；手动查询不改变定时任务维护的基线。

### 显示 `display`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `display.guide_providers` | `['all']` | 角色攻略来源，可选 `all`、`狩月庭攻略组`、`猫冬`。 |
| `display.show_unowned_roles` | `true` | 是否在角色信息卡片中显示未拥有的角色和武器。 |

### 网络 `network`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `network.max_concurrent_requests` | `4` | 短生命周期网络请求的最大并发数。 |
| `network.api_base_url` | 空 | 兼容 API 反代服务的 base URL；留空使用官方 API。 |
| `network.proxy_url` | 空 | App REST API 与官方业务 WebSocket 使用的代理地址；留空直连。 |
| `network.websocket_continue_seconds` | `300` | API WebSocket 保活时间，单位为秒。 |
| `network.websocket_wait_seconds` | `5` | 等待 API WebSocket 建立连接的时间，单位为秒。 |

`network.proxy_url` 只影响二重螺旋 App REST API 和官方业务 WebSocket，不影响 OneBot、外置 `dna-login`、
GitHub、公共资源 CDN、AstrBot 或第三方攻略接口。WebSocket 两项也只描述 API WebSocket，不描述 OneBot
或外置登录服务的连接。

### 公共资源 `resources`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `resources.github_acceleration` | `off` | 公共资源同步方式，可选 `off`、`edgeone`、`hk`、`gh_proxy`、`dpik`、`custom`。 |
| `resources.custom_github_acceleration_url` | 空 | `custom` 模式使用的不含凭据、查询参数和片段的 HTTP(S) 基础地址。 |

资源不会在插件启动时自动同步。首次使用图鉴、攻略或图片卡片时，管理员可以先发送 `kk资源状态` 查看状态；
状态会显示 repository path、generation id、active pointer、resource_version 和 last sync result，且不会触发
Git、完整校验、PIL 或完整 SHA-256。再发送 `kk同步资源` 触发一次经过 manifest、摘要和图片解码校验的同步；
失败时保留原资源快照。

### 缓存 `cache`

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `cache.ttl_hours` | `24` | 所有 `CacheManager` 内容缓存共用的 TTL（小时）；`-1` 永久有效，`0` 禁用持久缓存，正整数表示有效期。 |
| `cache.refresh_send_card` | `true` | 单角色主动刷新成功后是否发送新面板图片；关闭时仍完整刷新、渲染并更新缓存。 |

## 命令

默认前缀为 `kk`。下列示例均使用默认前缀；如果修改了 `general.command_prefixes`，请把示例中的 `kk` 替换为自己的前缀。完整的 63 条命令、参数和权限见 [`commands.json`](commands.json)，命令使用说明见 [`docs/usage/commands.md`](docs/usage/commands.md)。

### 常用命令

| 场景 | 示例 | 说明 |
| --- | --- | --- |
| 帮助 | `kk帮助` | 查看当前可用命令。 |
| 登录 | `kk登录` | 发起登录流程。 |
| 账号 | `kk查看UID`、`kk切换1234567890123`、`kk删除1234567890123` | 查看、切换或删除绑定 UID。 |
| 退出 | `kk退出登录` | 退出当前登录。 |
| 信息卡片 | `kk卡片` | 查询当前 UID 的基本信息。 |
| 角色详情 | `kk菲娜面板` | 查询指定角色的基础详情。 |
| 刷新与缓存 | `kk刷新菲娜面板`、`kk清理菲娜面板缓存` | 刷新角色数据或清理指定角色缓存。 |
| 日常信息 | `kk日常`、`kk周报`、`kk上周周报`、`kk日历` | 查看便笺、周报和日历。 |
| 客户端更新 | `kk客户端更新`、`kk客户端更新 PC`、`kk客户端更新 安卓` | 查询国服客户端版本；可按 channel 筛选。 |
| 图鉴攻略 | `kk菲娜图鉴`、`kk菲娜攻略`、`kk角色列表` | 查看图鉴、攻略或角色列表。 |
| 兑换码 | `kk兑换码` | 查看当前可用的兑换码。 |
| 签到 | `kk签到`、`kk签到日历` | 手动签到或查看签到日历。 |
| 自动签到 | `kk开启自动签到`、`kk关闭自动签到` | 开关当前 UID 的自动签到。 |
| 密函 | `kk密函`、`kk密函列表`、`kk我的密函` | 查看密函、列表和当前订阅。 |
| 公告 | `kk公告`、`kk公告 1` | 查看公告列表或指定公告详情。 |
| 隐私 | `kk开偷窥`、`kk防偷窥`、`kk隐藏UID`、`kk显示UID` | 设置个人查询权限和 UID 展示方式。 |

登录参数属于敏感信息，建议在私聊中完成登录，不要直接发到公开群聊。`获取ck`、`获取Token` 等状态命令只返回脱敏状态，不会把原始登录信息作为聊天回复。

客户端更新查询是只读操作，不推进定时检查使用的 baseline。`kk订阅客户端更新` 和带平台后缀的订阅命令只允许群聊管理员执行；
`kk取消订阅客户端更新` 取消当前群的订阅。检测到多个 channel 同轮变化时，OneBot 在 `client_updates.merge_forward=true`
且能力可用时合并为一条转发消息，每个 channel 一个 Node；其他情况按普通文本逐条发送。

部分查询命令支持在消息中 @ 目标用户；是否允许查询他人由 `general.allow_mention_query` 控制。关闭后，普通查询只读取发送者自己的信息。

### 管理员命令

以下命令需要 AstrBot `ADMIN` 权限：

- `kk全部签到`：手动触发所有符合条件的账号签到。
- `kk订阅公告`、`kk取消订阅公告`：开关当前群聊的公告推送。
- `kk添加角色菲娜别名小菲`、`kk删除角色菲娜别名小菲`：维护角色别名。
- `kk添加武器武器名别名别名`、`kk删除武器武器名别名别名`：维护武器别名。
- `kk恢复别名`、`kk强制恢复别名`：重新加载默认别名，或清除自定义别名。
- `kk资源状态`、`kk同步资源`：查看或同步公共资源。

管理员隐私命令还包括 `kk指定开偷窥`、`kk指定防偷窥`、`kk全体开偷窥`、`kk全体防偷窥`、`kk指定隐藏UID` 和 `kk全体隐藏UID` 等；完整触发形式请以 [`commands.json`](commands.json) 为准。

## 数据目录与隐私

插件运行期数据统一保存在 AstrBot 的插件数据目录：

```text
data/plugin_data/astrbot_plugin_dnaby/
```

该目录由 AstrBot 的 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 提供。账号绑定、订阅、缓存、图片和公共资源等运行期文件都写入这里，不写入插件源码目录。升级或迁移前建议备份该目录；不要将其中的数据库、登录信息、订阅记录或日志上传到公开位置。

客户端更新的 baseline 与投递状态单独保存在该目录的 `client_update_state.json`，当前为 `schema_version: 3`，状态 key 使用
`region:channel_id`（例如 `cn:pc_cn`、`cn:android_astc_cn`）。旧状态读取时会在校验后原子迁移并保留 `.v2.bak`，不会补发历史更新。

隐私相关行为由以下设置和命令共同控制：

- `general.allow_mention_query` 控制是否允许通过 @ 查询他人。
- `kk开偷窥` / `kk防偷窥` 控制他人是否可以查询自己的游戏信息。
- `kk隐藏UID` / `kk显示UID` 控制生成的卡片是否显示自己的 UID。
- 反馈问题时请先移除登录信息、UID、群成员信息和其他个人数据，再提交日志或截图。

## 常见问题

### 命令没有响应怎么办？

先发送 `kk帮助`，确认插件已经启用且命令前缀仍为 `kk`。如果修改过 `general.command_prefixes`，请使用新前缀；修改配置后需要重载插件。

### 图片、图鉴或攻略显示缺失怎么办？

先让管理员发送 `kk资源状态`。如果资源目录尚未准备好，发送 `kk同步资源`；如果同步失败，检查 `resources.github_acceleration`、网络连接和 AstrBot 日志。图片卡片还需要 AstrBot 的全局 HTML/T2I 能力。

### 登录页打不开怎么办？

确认 `login.bind_host`、`login.port` 没有被其他程序占用；在其他设备访问时，监听地址和 `login.url` 必须使用调用方可访问的地址。外置接入方式还需要同时核对 `login.transport` 和共享密钥配置。

### 如何开启自动签到？

先使用 `kk开启自动签到` 为当前 UID 开启；`sign_in.default_auto_sign_enabled` 只控制新 UID 首次绑定时的默认值。定时任务按每个 UID 的开关执行，不存在全局开关覆盖所有用户的配置。手动 `kk签到`、`kk全部签到` 按命令权限和语义执行。

### 如何限制群成员查看我的信息？

发送 `kk防偷窥` 并视需要发送 `kk隐藏UID`。管理员也可以使用群聊隐私管理命令设置指定成员或全体成员的规则。

### 升级后如何确认插件版本？

检查 [`metadata.yaml`](metadata.yaml) 中的 `version`，并在 AstrBot 日志或 Dashboard 中确认插件重新加载成功。当前版本要求 AstrBot 4.26.0 或更高版本。

## 开发与本地测试

在插件目录安装依赖后，可运行以下检查：

```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

开发环境、依赖同步和测试范围见 [`docs/dev/setup.md`](docs/dev/setup.md) 与 [`docs/dev/testing.md`](docs/dev/testing.md)。命令、配置和资源的详细说明见 [`docs/README.md`](docs/README.md)。

## 问题反馈与贡献

请在 [GitHub Issues](https://github.com/FlanChanXwO/astrbot_plugin_dnaby/issues) 提交问题，在描述中尽量提供：

- AstrBot 版本、插件版本和运行平台；
- 可以复现问题的命令、配置项或最小步骤；
- 已脱敏的错误信息、日志片段或截图；
- 预期结果与实际结果。

提交前请确认没有附带登录信息、个人数据或本地路径。欢迎提交文档、测试和代码改进；涉及命令或配置变化时，请同时更新对应说明并运行本地测试。

## License

插件代码使用 [GPL-3.0](LICENSE) 许可证。
