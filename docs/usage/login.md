# 皎皎角登录

登录链路移植自原 DNAUID（详见 `docs/legacy/` 排查档案，含 2026-08-06 native 会话参数修复）。

## 方式
- `登录`、`dna登录`、`DNA登录`：内嵌 Web/App 登录页（local 模式）或外置传输（http_poll/sse/ws）。
- `登录<token>`、`dna登录<token>`：token 登录。
- `手机号,验证码`：短信验证码命令登录（App/Web 通道）。

## 本地登录服务

`DNALoginTransport=local` 时，插件会启动独立的轻量 HTTP 服务承载登录页和提交接口，
不依赖 AstrBot Dashboard 的登录 cookie。默认地址为：
`http://localhost:6189/astrbot_plugin_dnaby/dna/i/{auth}`。

- `DNALoginBindHost`：监听地址，默认 `127.0.0.1`，仅本机浏览器可访问。
- `DNALoginPort`：监听端口，默认 `6189`；端口被占用时插件会在初始化阶段显式报错。
- `DNALoginUrl`：可选的对外基地址。使用反向代理、局域网地址或公网域名时填写它，插件仍在 `DNALoginBindHost:DNALoginPort` 接收请求。

要让手机或局域网设备打开登录页，将 `DNALoginBindHost` 设为 `0.0.0.0`，并将
`DNALoginUrl` 填为实际可访问的地址，例如 `http://192.168.1.10:6189`；容器部署还需要
发布该端口。仅修改配置后需要重载插件，旧登录链接不会自动迁移。

AstrBot Dashboard 的 `register_web_api` 路由仍保留给已认证的管理端调用，但不应把
`/api/plug/...` 地址发给普通用户，因为 Dashboard 会要求额外认证。

登录链接只对应当前进程内的临时会话；AstrBot 重载或进程重启后旧链接会失效，需要重新发送 `登录`、`dna登录` 或 `DNA登录`。
旧链接现在会明确返回 HTTP 404 的无效会话页，不会伪装成可用登录表单。

机器人会先立即发送登录地址，再等待网页提交；不会等本地登录等待循环结束后才发送。
若只收到“登录超时”而没有先收到地址，应先检查插件是否已重载到包含该行为的版本。
