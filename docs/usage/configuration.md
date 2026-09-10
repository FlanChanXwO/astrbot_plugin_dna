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
- `ai.agent_tools_enabled`：控制是否注册 DNABY Agent Tools；修改后需要重载。见 [Agent Tools](agent-tools.md)。
- `sign_in.*`：自动签到时间、并发和报告行为。用户自己的自动签到状态仍由账号状态/命令管理。本群社区签到报告以社区签到本身为主要成功判定；浏览、点赞、分享、回复等附加任务失败仍保留为任务错误，但不会在社区签到已经完成时单独计为群报告失败并触发 `@`。
- `notifications.*`：公告和密函检查/推送行为。
- `client_updates.*`：客户端更新检查周期、渠道与消息行为。
- `resources.*`：公共资源同步传输设置。见 [公共资源](resources.md)。
- `cache.*`：玩家、公告等内容缓存和主动刷新行为。

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
