# 配置

插件配置在 AstrBot Dashboard 插件配置页。根目录 `_conf_schema.json` 由
`src/infrastructure/config` 中的 Pydantic 模型生成；修改配置定义后运行
`python3 scripts/generate_config_schema.py` 同步 schema，不手工维护两份字段定义。

## 分组

- `login`：登录 URL、监听地址/端口、接入方式、共享密钥、二维码/转发登录和未登录绑定数量。
- `network`：API/本地代理、需要或不需要代理的函数、WebSocket 保活和连接等待时间。
- `sign_in`：游戏/社区签到、任务列表、定时签到时间、并发间隔和签到报告。
- `notifications`：公告轮询与密函订阅、缓存、推送时间和图片模式。
- `display`：攻略来源、未拥有角色展示、角色原图和 AT 查询开关；
  `allow_mention_query` 控制是否允许查询被 @ 的他人。

新入口在 bootstrap 边界将 AstrBot 配置转换为 `DnabySettings`；use case 不直接读取
未类型化字典。legacy `dnaby/dna_config` 的 `DNAConfig.get_config("Key").data` 语义
仅为迁移参考，旧 SQLite 和旧配置不会在本阶段自动迁移。

Task 10 的 `AccountService` 使用 `login.max_bind_count` 约束新增 UID；login URL、
transport、监听和二维码字段仍保留为 typed 配置，但当前 rewrite 尚未注册本地登录
Web 路由。未注入实际 page provider 时，无参数登录会显式报告服务未配置。

隐私 use case 按 `display.allow_mention_query` 解析他人查询；关闭时查询目标会回到调用者，
查询自己仍然允许。个人/群强制隐私的具体命令见 [commands.md](commands.md)。

共享密钥使用 Pydantic `SecretStr`，schema 默认值保持为空；不得把实际密钥写入
Git、日志、异常或用户可见响应。
