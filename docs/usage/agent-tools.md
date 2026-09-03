# Agent Tools

Agent Tools 是 AstrBot Agent 可调用的独立工具集合，不是聊天命令，也不进入
`commands.json`。工具通过 AstrBot 官方工具接口注册，身份和当前消息来自原始事件。

## 启用与生命周期

在 AstrBot Dashboard 的插件配置中开启 `agent_tools.enabled` 才会启用，默认值为 `false`：

- 关闭时不注册任何 DNABY Agent Tools，也不创建签到写入口。
- 开启时由插件 `initialize()` 注册 16 个只读工具和 1 个签到工具，共 17 个；
  `terminate()` 逐项解除注册。
- 修改开关后需要重新加载插件或重启 AstrBot，使 `initialize()` 重新执行；只修改 schema 不会改变
  已运行进程中的工具集合。
- 工具不使用聊天命令前缀，模型按照工具名称和 schema 调用。
- 生命周期支持重复初始化/终止和热重载；注册或注销失败会返回明确错误，注销残留会在下一次
  终止或启动时重试。

Agent Tools 不会改变聊天命令，也不会代替管理员执行账号、凭据、隐私、订阅或资源管理操作。

## 工具清单

除特别标注外，工具只允许表中参数，额外参数会返回结构化失败；所有参数名均为英文。
支持图片的工具额外提供可选 `send_image: boolean`，默认 `false`。

| 工具 | 作用 | 参数 | 类型 |
| --- | --- | --- | --- |
| `dnaby_player_overview` | 当前消息用户的角色与武器概览；返回真实拥有角色/武器的结构化清单，可选直发图片 | `send_image` | 只读 |
| `dnaby_player_role_detail` | 当前消息用户指定角色的基础详情与武器信息 | `char_name`（必填）、`weapon_name_1`、`weapon_name_2`、`send_image` | 只读 |
| `dnaby_stamina` | 当前消息用户的便笺和体力 | `send_image` | 只读 |
| `dnaby_weekly_report_current` | 当前周资源周报 | `send_image` | 只读 |
| `dnaby_weekly_report_last` | 上周资源周报 | `send_image` | 只读 |
| `dnaby_calendar` | 全局活动日历 | `send_image` | 只读 |
| `dnaby_wiki` | 角色、武器或魔之楔图鉴 | `name`（必填）、`send_image` | 只读 |
| `dnaby_guide` | 角色攻略图片 | `char_name`（必填）、`send_image` | 只读 |
| `dnaby_codes` | 当前有效兑换码 | 无 | 只读 |
| `dnaby_role_directory` | 角色或武器名称目录 | `directory_type`：`characters` 或 `weapons`，默认 `characters` | 只读 |
| `dnaby_mh` | 当前用户可见的当前时段梦魇残声/密函 | `send_image` | 只读 |
| `dnaby_mh_list` | 梦魇残声/密函名称列表 | 无 | 只读 |
| `dnaby_mh_subscriptions` | 当前消息用户在当前会话的密函订阅 | 无 | 只读 |
| `dnaby_announcement_list` | 完整官方公告列表 | `send_image` | 只读 |
| `dnaby_announcement_detail` | 公告详情和全部正文图片 | `index`（必填，1-based 整数）、`send_image` | 只读 |
| `dnaby_sign_calendar` | 当前用户的签到日历和任务进度 | `send_image` | 只读 |
| `dnaby_sign` | 执行当前用户当前激活 UID 的签到 | 无 | 唯一写工具 |

`dnaby_sign_calendar` 只查询；`dnaby_mh_subscriptions` 只查看订阅，不创建、修改或删除订阅。

`dnaby_role_directory` 返回资源仓库中的角色/武器全集，不代表当前用户拥有的内容。核验当前用户的
拥有数量和名称必须使用 `dnaby_player_overview` 的结构化 `data`。

## 返回格式

工具默认返回 JSON 字符串，字段固定为：

```json
{
  "ok": true,
  "kind": "stamina",
  "data": {"type": "text", "text": "..."},
  "cache": null,
  "error": null
}
```

失败时 `ok` 为 `false`，`error` 会保留明确的错误类别；不会用空数据伪装成功。除
`dnaby_player_overview` 外，图片结果只描述类型、可用性、完整性等状态，不返回本地文件路径或二进制。

`dnaby_player_overview` 的 `data` 来自同一次已校验的玩家概览快照，契约为：

```json
{
  "type": "player_overview",
  "role_count": 2,
  "roles": [
    {"name": "接口返回的角色甲", "level": 80},
    {"name": "接口返回的角色乙", "level": 70}
  ],
  "weapons": {
    "close": [{"name": "接口返回的近战武器", "level": 60}],
    "ranged": []
  }
}
```

`role_count` 和 `roles` 只统计玩家概览中 `unlocked=true` 的角色，并逐项保留接口返回的名称；若
接口返回 19 个已拥有角色，`role_count` 必须为 19，`roles` 必须包含这 19 个真实名称，不能由模型
根据图片或角色目录猜测。

对支持图片的工具传入 `send_image=true` 后，图片会经当前原始事件直接发送给当前消息用户。
`dnaby_player_overview` 会在上述结构化 `data` 上增加 `"image_sent": true/false`；其它图片工具
返回 `data: {"image_sent": true/false}`。转换失败、发送失败或结果没有可发送图片时，返回
`ok=false`、`image_sent=false` 和明确错误，不返回成功状态。

## 身份与签到安全

- 查询身份只从当前原始 AstrBot 事件提取，模型不能传入或覆盖目标用户、UID 或 Bot 身份。
- 工具拒绝 `user_id`、`target_user_id`、`bot_id`、`credential_user_id`、`uid` 等身份参数。
- `dnaby_sign` 不接受确认布尔值、用户、UID、目标或其它额外参数。
- 只有当前原始消息包含明确的肯定签到短语，且没有否定或疑问表达时，才允许执行签到。
- 签到固定使用当前消息用户的当前激活 UID；未绑定、凭据失效、网络失败、上游拒绝和已签到都会返回明确结果。
- 同一消息 ID 的重复调用会复用本次事件的结果，避免一次 Agent 运行中的重复签到。

配置字段见 [配置说明](configuration.md)，聊天命令见 [命令说明](commands.md)。
