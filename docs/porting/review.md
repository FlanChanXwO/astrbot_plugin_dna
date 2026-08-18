# 迁移代码审查

> 历史存档：本文记录 `legacy-reference` 的完整移植审查，不代表当前
> `rewrite/v0.1` 的能力、测试或发布结论。当前重构阶段审查见
> [review-v0.1.md](review-v0.1.md)；最终报告将在目标全部完成后更新。

## 审查范围

审查基于当时的 legacy 工作树、`commands.json`、`_conf_schema.json`、pytest/lint/type-check 结果和本机 AstrBot 运行时重载。该结论不应覆盖当前重构区的阶段性证据。

重点覆盖入口与动态加载、权限分发、配置 schema、数据库事务、登录 Web/transport、定时任务、订阅持久化、外部请求和敏感信息日志。

## 结论

**总体：COMMENT。** 当前没有阻断运行时加载的 P0/P1 问题：入口包路径、AstrBot schema、会话标识、凭据日志、任务取消、纯文本通知和订阅实例内并发问题均已修复并通过回归；Dashboard 目标插件重载返回成功。仍有跨进程订阅写入和真实外部链路未覆盖，适合进入受控试运行，不应把本地重载等同于完整生产验收。

## Findings

### P0 — Critical

无。

### P1 — High

无未解决项。

已修复的高风险项：

- 动态加载时 `main.py` 只使用顶层 `dnaby` 导入，AstrBot 曾报 `No module named 'dnaby'`；入口现按 `__package__` 选择相对/开发态导入，并新增命名空间加载测试。
- `DNAAnnGroups` 的 object schema 缺少 `items`，AstrBot 曾报 `KeyError: 'items'`；生成器和 `_conf_schema.json` 已修复，并由 `AstrBotConfig` 实际构造测试覆盖。
- `login_helps.py` 曾以 `sha256(user_id)[:8]` 生成登录 auth；现改为进程内随机密钥的 HMAC，避免知道 user ID 即可预测会话标识。
- `utils/api/requests.py` 曾在 DEBUG 日志和异常文本中记录完整 headers、请求体和响应 data；现只记录状态摘要，避免泄漏 token/cookie。
- `terminate()` 曾只调用 `Task.cancel()` 后立即关闭 DB；现等待任务收敛后再关闭数据库。

### P2 — Medium

1. **订阅存储只覆盖实例内并发。** `dnaby/utils/subscriptions.py` 已将每个变更的读改写与落盘纳入同一 `asyncio.Lock`，当前运行时使用全局 `gs_subscribe` 单例，因此现有事件与定时任务并发路径已受保护。若未来多个进程或多个 `SubscriptionStore` 实例共享同一 JSON 文件，仍可能发生文件级最后写入覆盖；届时应引入文件级锁或单写者方案，而不是在当前单例模型中增加无据的限制。

### P3 — Low

1. 当前仍未覆盖真实手机号/验证码提交、有效 token 登录和外置 `http_poll/sse/ws` 服务；本机 NapCat
   命令矩阵与本地登录页已经完成受控 E2E，但指定隐私命令的真实 `@` 目标路径受 OneBot 群成员信息
   响应缺失阻塞。
2. AstrBot 日志仍会输出第三方 PIL 的 DEBUG 噪音；不影响功能，但会降低生产排查信噪比。

## 安全与可靠性检查

- 未发现 `gsuid_core` / `gsucore` import、SQL 字符串拼接、命令执行拼接或提交中的 Cookie/token。
- API 请求仍支持配置代理和外置登录 URL；这些是产品功能，部署时应只允许可信配置管理员修改，并避免把登录服务暴露到不受控公网。
- 登录会话只存进程内，进程重载后旧链接失效；这是有意的生命周期边界。
- 外置轮询有与服务端会话 TTL 对齐的等待窗口；网络错误与自然过期现在分开上报。

## Removal / Iteration Plan

当前没有有证据可安全删除的代码。P2 的跨进程订阅写入属于后续部署形态变化时再处理的范围；本轮已为实例内并发补充回归测试，并将 Pyright 覆盖扩展到 `dnaby` 与 `tests`。
