# 皎皎角登录

账号登录 use case 以原 DNAUID 的角色绑定行为为参考（详见 `docs/legacy/` 排查档案），
新入口通过 typed transport 接收结果，不直接持有旧事件或旧数据库。

## 方式
- `登录`、`dna登录`、`DNA登录`：启动一次登录页会话并立即返回链接。
- `登录<token>`、`dna登录<token>`：token 登录。
- `登录手机号,验证码`：短信验证码命令登录（App 通道）。
- `获取ck`/`获取Token`：只返回 App 凭据保存状态，不返回 Cookie、token 或 refresh token。

## transport 边界

`AccountService` 通过 `AccountTransport` 接口接收登录页地址和认证终态。隔离测试使用
fake transport；`DnaApiAccountTransport` 只适配旧的纯 API 请求和角色响应。

登录页由 `LoginFlowCoordinator` 统一管理，支持 `local`、`http_poll`、`sse` 和 `ws`。
`local` 模式在插件 `initialize()` 中启动 `LocalLoginServer`，生成实际监听端口的链接；
插件终止时会先取消等待中的登录任务、清理会话，再释放监听端口。外置模式只使用 typed
`login.url`、`login.transport` 和 `login.shared_secret`，不会再从 legacy 全局配置读取共享密钥。

`login.url` 配置后优先作为公开地址；local 模式未配置时使用本地服务实际地址推导登录链接。
链接创建、等待回执和账号事务是分开的：聊天命令只等待链接创建，不会因等待短信或外置回执而
延迟发送链接。同一消息作用域重复发起登录会复用当前会话。

外置回执仅接受 App 凭据；成功、失败、取消、过期、空凭据和 Web 回执均转换为稳定用户文案，
并在日志中记录错误类别。不会把 auth、token、设备码、验证码、敏感 URL 或服务端正文写入日志。

实际手机号、验证码、token 和外部登录服务不在本地测试中执行；只能用隔离 SQLite、
fake transport 和事件 fixture 验证成功、取消、网络/状态码/服务端失败及脱敏。

登录 transport 的调试日志只记录受控的端点与状态；网络和非 200 失败保留稳定错误类别，
避免把上游正文带入日志或用户文案。
