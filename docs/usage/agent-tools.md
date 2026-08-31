# Agent Tools

Agent Tools 是 AstrBot Agent 可调用的独立工具集合，不是聊天命令，也不进入
`commands.json`。工具通过 AstrBot 官方 `FunctionTool`/`Context` API 注册，身份和当前
消息来自 `AstrAgentContext.event`。

## 启用与生命周期

在 AstrBot Dashboard 的插件配置中开启 `agent_tools.enabled` 才会启用。默认值为 `false`：

- 关闭时不注册任何 DNABY Agent Tool，也不创建签到写入口。
- 开启时由插件 `initialize()` 注册 16 个只读工具和 1 个签到工具，共 17 个；
  `terminate()` 逐项解除注册。
- 工具不使用聊天命令前缀，模型直接按工具名称和 schema 调用。
- 生命周期支持重复初始化/终止和热重载；注销失败会保留失败项并在下一次终止或启动时重试，
  同时向调用方暴露真实错误。

O24 对 `atri` 的只读核验确认当前 `agent_tools.enabled=false`，因此生产实例当前不注册这 17 个工具，
也不会触发真实签到；启用前仍须按发布清单完成精确 SHA 预检、认证 reload 和工具枚举复核。

## 工具清单与参数

除特别标注外，工具只允许表中参数，额外参数会返回结构化失败；所有参数名均为英文。
支持图片的工具额外提供可选 `send_image: boolean`，默认 `false`。

| 工具 | 作用 | 参数 | 类型 |
| --- | --- | --- | --- |
| `dnaby_player_overview` | 当前消息用户的角色与武器概览 | `send_image` | 只读 |
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

`dnaby_sign_calendar` 只查询，不执行签到；`dnaby_mh_subscriptions` 只查看订阅，不创建、
修改或删除订阅。Agent Tools 没有账号、凭据、隐私、资源或管理配置写操作。

## 返回契约与图片

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

失败时 `ok` 为 `false`，`error` 保留明确错误类别；不会用空数据伪装成功。图片结果只描述
类型、可用性、完整性等状态，不包含本地文件路径或二进制。

对支持图片的工具传入 `send_image=true` 后，图片会经当前原始事件直接发送给当前消息用户，
Agent 只收到 `data: {"image_sent": true}`。转换失败、发送失败或结果没有可发送图片时，
返回 `ok=false`、`image_sent=false` 和明确错误，不返回成功状态。

## 身份与签到安全

- 查询身份只从当前 `AstrAgentContext.event` 提取，不能由模型传入或覆盖。
- 工具拒绝 `user_id`、`target_user_id`、`bot_id`、`credential_user_id`、`uid` 等身份参数；
  不支持的额外参数也会失败。
- `dnaby_sign` 不接受 `confirmed`、用户/UID、目标或其它工具参数，模型不能用布尔值伪造确认。
- 只有当前原始消息包含完整、明确的肯定签到短语，且不含否定或疑问表达时，才允许执行签到；
  信息询问、示例文本和 prompt 指令不会被当成确认。
- 签到固定使用当前消息用户的当前激活 UID，真实写请求仍由注入的签到 transport 执行。
- 同一消息 ID 使用原始事件级锁和结果缓存幂等，AstrBot 同一 Agent 运行中的工具重试不会重复执行；
  不对被重新构造的不同事件对象提供跨请求持久化幂等，以免引入无界进程缓存或未经迁移的状态表。
  未绑定、凭据失效、网络失败、上游拒绝和已签到等失败会保留显式结果。

配置字段说明见[配置文档](configuration.md)，工具的生命周期维护说明见
[维护文档](../dev/maintenance.md)，离线契约测试见[测试文档](../dev/testing.md)。发布前
adapter 模拟、精确 SHA 和阶段三回滚步骤见[发布与回滚清单](../porting/agent-tools-release-checklist.md)。
