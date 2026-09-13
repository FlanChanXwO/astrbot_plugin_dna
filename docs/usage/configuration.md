# 配置

通过 AstrBot Dashboard 的插件配置页修改设置。根目录 [`_conf_schema.json`](../../_conf_schema.json) 是 Dashboard 使用的机器可读投影；真正的配置模型位于 `src/infrastructure/config/settings.py`。

修改配置后，按 AstrBot 的插件管理方式重载插件，使新的 runtime 重新读取设置。

## 配置分组

当前配置由代码生成以下分组：

- `general`：命令前缀与通用查询行为；
- `login`：内置/外置登录服务和账号绑定；
- `ai`：Agent Tools 开关；
- `sign_in`：自动签到与签到报告；
- `notifications`：密函、公告等通知；
- `client_updates`：客户端版本检查与推送；
- `display`：图鉴/攻略等显示策略；
- `network`：API、代理与网络并发；
- `resources`：公共资源同步与 GitHub 加速；
- `cache`：数据/卡片缓存策略。

字段类型、默认值、选项和 Dashboard 提示请直接查看当前 `_conf_schema.json`，避免依赖文档中的重复表格。

## 常用设置

- `general.command_prefixes`：聊天命令前缀；README 与示例默认使用 `dna`。
- `login.transport`：登录接入方式；当前支持 `local`、`http_poll`、`sse`、`ws`。其他登录字段见 [账号登录](login.md)。
- `login.dynamic_background`：控制内置 `local` 登录页的 MP4 动态背景，默认开启；关闭后使用现有静态背景。
- `ai.agent_tools_enabled`：控制是否注册 DNABY Agent Tools；修改后需要重载。见 [Agent Tools](agent-tools.md)。
- `sign_in.*`：自动签到时间、并发和报告行为。用户自己的自动签到状态仍由账号状态/命令管理。本群社区签到报告以社区签到本身为主要成功判定；浏览、点赞、分享、回复等附加任务失败仍保留为任务错误，但不会在社区签到已经完成时单独计为群报告失败并触发 `@`。
- `notifications.*`：公告和密函检查/推送行为。
- `client_updates.*`：客户端更新检查周期、Target 与消息行为。
- `resources.*`：公共资源同步传输设置。见 [公共资源](resources.md)。
- `cache.*`：玩家、公告等内容缓存和主动刷新行为。

## 客户端更新 Target

`client_updates.targets` 是客户端更新范围的唯一选择入口。一个 Target 表示
玩家实际游玩的发行渠道（区服 × 发行渠道 × 平台）；底层 Source 是观察该渠道
何时更新的技术来源，不会作为用户配置项出现。可选值由代码 registry 生成到
`_conf_schema.json`，不要手工填写 URL、branch、manifest key 或未登记的
Target ID。

当前默认只启用国服官服 PC 与 Android；已验证的国服 App Store iOS、B服
PC / Android、好游快爆 Android，以及全球服独立客户端 PC、App Store iOS 可在
Dashboard 中显式启用。例如只玩 B服，就只选择 B服 Target，官服渠道更新不会推送。
修改 Target 后需要重载插件。重载后，所有有效客户端更新订阅统一
使用当前配置；已经落盘等待投递的事件仍保留创建时的 Target 快照，不会被新配置
改写。

查询、订阅和取消订阅命令都不接受平台或 Target 参数。临时发送 `PC`、`安卓`、
`iOS` 或 Target ID 不会覆盖 Dashboard 配置。

## 客户端更新升级边界

- 旧字段 `client_updates.channels` 已删除，typed settings 会明确拒绝该配置，
  不会猜测迁移到 Target。升级前应在 Dashboard 中删除旧字段并按当前 schema
  选择 `client_updates.targets`。
- `client_update_state.json` 当前 schema 为 v4，以 Source 保存 baseline。旧
  v1/v2/v3 文件会记录 warning 后按空状态启动；旧 baseline 和旧 pending event
  不迁移，也不会由插件自动备份。首次成功轮询会建立新的 v4 baseline。
- 旧客户端更新订阅身份会保留；精确的 `{"platforms": [...]}` 元数据会在生命周期
  初始化时幂等清理为 `{}`，之后跟随当前 Target 配置。损坏或未知形状不会被静默
  改写，而是记录 warning 并跳过。
- 若需要回滚到使用旧 state 的插件版本，应先停止插件，并由部署者自行移走 v4
  state 或恢复升级前备份；不要让旧版本把 v4 文件当作可兼容数据。

## 网络与敏感配置

代理、外置登录地址和共享密钥只应通过受控的 Dashboard 配置保存。不要把 Cookie、token、共享密钥或带凭据的 URL 写进仓库、Issue、PR 或文档示例。

`network.proxy_url`、`network.api_base_url` 等字段的确切作用域以 typed settings、transport 实现和 schema 描述为准；排障时先确认当前配置，再看 AstrBot 日志中的脱敏错误。

## 对贡献者

修改配置模型后运行：

```bash
python3 scripts/generate_config_schema.py
python3 -m pytest tests/test_config.py
```

提交代码时同时提交 `_conf_schema.json` 的生成差异。不要手工维护另一份完整字段/默认值清单。
