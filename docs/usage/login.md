# 账号登录

账号登录 use case 以原 DNAUID 的角色关联行为为参考（详见 `docs/legacy/` 排查档案），
新入口通过 typed transport 接收结果，不直接持有旧事件或旧数据库。

## 方式
- `登录`、`dna登录`、`DNA登录`：调用注入的登录页 transport。
- `登录<token>`、`dna登录<token>`：token 登录。
- `登录手机号,验证码`：短信验证码命令登录（App 通道）。
- `获取ck`/`获取Token`：只返回凭据保存状态，不返回 Cookie、token 或 refresh token。

## transport 边界

`AccountService` 通过 `AccountTransport` 接口接收登录页地址和认证终态。隔离测试使用
fake transport；`DnaApiAccountTransport` 只适配旧的纯 API 请求和角色响应。

当前 rewrite runtime 尚未注册本地登录 Web 路由；若未注入 page provider，发送无参数
`登录` 会显式返回登录服务未配置错误。不会把配置中的 base URL 直接当成可用会话，
也不会伪造成功。

实际手机号、验证码、token 和外部登录服务不在本地测试中执行；只能用隔离 SQLite、
fake transport 和事件 fixture 验证成功、取消、网络/状态码/服务端失败及脱敏。

登录 transport 的调试日志只记录受控的端点与状态，不记录 auth、token、设备码或请求/响应正文；
网络和非 200 失败保留稳定错误类别，避免把上游正文带入日志或用户文案。
