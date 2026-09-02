# Agent Tools

Agent Tools 是 AstrBot Agent 可调用的独立工具集合，不是聊天命令，也不进入
`commands.json`。工具通过 AstrBot 官方工具接口注册，身份和当前消息来自原始事件。

## 启用与生命周期

在 AstrBot Dashboard 的插件配置中开启 `agent_tools.enabled` 才会启用，默认值为 `false`：

- 关闭时不注册 DNABY Agent Tools。
- 开启时注册 16 个只读工具和 1 个签到工具，共 17 个。
- 工具不使用聊天命令前缀，模型按照工具名称和 schema 调用。
- 重载或停止插件时会解除已注册工具；注册或解除失败会返回明确错误。

Agent Tools 不会改变聊天命令，也不会代替管理员执行账号、凭据、隐私、订阅或资源管理操作。

## 工具清单

| 工具 | 作用 | 参数 |
| --- | --- | --- |
| `dnaby_player_overview` | 当前消息用户的角色与武器概览 | `send_image` |
| `dnaby_player_role_detail` | 指定角色的基础详情与武器信息 | `char_name`、`weapon_name_1`、`weapon_name_2`、`send_image` |
| `dnaby_stamina` | 当前消息用户的便笺和体力 | `send_image` |
| `dnaby_weekly_report_current` | 当前周资源周报 | `send_image` |
| `dnaby_weekly_report_last` | 上周资源周报 | `send_image` |
| `dnaby_calendar` | 全局活动日历 | `send_image` |
| `dnaby_wiki` | 角色、武器或魔之楔图鉴 | `name`、`send_image` |
| `dnaby_guide` | 角色攻略图片 | `char_name`、`send_image` |
| `dnaby_codes` | 当前有效兑换码 | 无 |
| `dnaby_role_directory` | 角色或武器名称目录 | `directory_type`：`characters` 或 `weapons` |
| `dnaby_mh` | 当前用户可见的当前时段密函 | `send_image` |
| `dnaby_mh_list` | 密函名称列表 | 无 |
| `dnaby_mh_subscriptions` | 当前用户在当前会话的密函订阅 | 无 |
| `dnaby_announcement_list` | 公告列表 | `send_image` |
| `dnaby_announcement_detail` | 公告详情和正文图片 | `index`：从 1 开始的整数、`send_image` |
| `dnaby_sign_calendar` | 签到日历和任务进度 | `send_image` |
| `dnaby_sign` | 执行当前用户当前激活 UID 的签到 | 无 |

除特别说明外，支持图片的工具接受可选的 `send_image` 布尔参数，默认值为 `false`。
`dnaby_sign_calendar` 只查询；`dnaby_mh_subscriptions` 只查看订阅，不创建、修改或删除订阅。

## 返回格式

工具默认返回 JSON 字符串，结构如下：

```json
{
  "ok": true,
  "kind": "stamina",
  "data": {"type": "text", "text": "..."},
  "cache": null,
  "error": null
}
```

失败时 `ok` 为 `false`，`error` 会保留明确的错误类别，不会用空数据伪装成功。图片结果只描述
发送状态，不返回本地文件路径或二进制内容。传入 `send_image=true` 后，图片会直接发送给当前消息用户，Agent 收到 `image_sent` 状态。

## 身份与签到安全

- 查询身份只从当前原始 AstrBot 事件提取，模型不能传入或覆盖目标用户、UID 或 Bot 身份。
- 工具拒绝 `user_id`、`target_user_id`、`bot_id`、`credential_user_id`、`uid` 等身份参数。
- `dnaby_sign` 不接受确认布尔值、用户、UID、目标或其它额外参数。
- 只有当前原始消息包含明确的肯定签到短语，且没有否定或疑问表达时，才允许执行签到。
- 签到固定使用当前消息用户的当前激活 UID；未绑定、凭据失效、网络失败、上游拒绝和已签到都会返回明确结果。
- 同一消息 ID 的重复调用会复用本次事件的结果，避免一次 Agent 运行中的重复签到。

配置字段见 [配置说明](configuration.md)，聊天命令见 [命令说明](commands.md)。
