# rewrite Task 10：账号 use case 审查

## 范围

本轮只迁移账号登录、退出、UID 绑定/切换/删除、绑定列表和凭据状态查询。
个人/群组隐私策略留在 Task 11；真实 NapCat、手机号验证码、真实 token 和外部
登录服务不在本轮执行。

## 实现边界

- `src/modules/account/contracts.py` 定义 actor、token/SMS 输入、角色、凭据、登录
  终态和 transport 错误类别；敏感字段的 repr 只显示存在性。
- `AccountService` 通过注入的 `AccountTransport` 工作，登录角色、渠道凭据和当前绑定
  在同一个 SQLAlchemy async transaction 内写入；退出/删除会清理 normalized binding
  与 credential 记录。
- `src/entry/event.py` 只从 AstrBot 公开事件方法提取 `EventActor`；动态命令把 actor
  和 runtime service 显式放进 `CommandRequest`，业务 use case 不持有事件对象。
- `DnaApiAccountTransport` 只适配 legacy 的纯 API 请求/角色模型，不复用旧事件、旧
  数据库或消息段；没有 page provider 时，无参数登录显式返回服务端配置错误，不伪造
  登录地址。
- `获取ck`/`获取Token` 命令只返回 App/Web 凭据是否保存。Cookie、token、refresh token、
  设备码和 d_num 不进入用户响应、异常字符串、DTO repr 或凭据摘要。

## 测试与门禁证据

- `tests/test_account.py`：登录成功、取消、网络/状态码/服务端错误、事务生命周期、
  全量删除、凭据摘要和输入解析；9 条通过。
- `tests/test_account_commands.py`：事件 actor、named UID 参数、缺少 actor 的显式错误、
  无参数登录和 bootstrap service 注入；4 条通过。
- 账号/命令定向集合：26 条通过。
- staging runtime（临时 `data/plugins/astrbot_plugin_dnaby` symlink 指向 rewrite
  worktree）全量 pytest：`92 passed, 1 skipped, 1 warning`；唯一 warning 是 AstrBot
  依赖的 `audioop` 弃用提示。
- system/runtime Ruff、Pyright、compileall、pre-commit 和 `git diff --check` 均通过；
  Pyright 为 `0 errors, 0 warnings, 0 informations`。

## 剩余边界

- rewrite runtime 当前没有本地登录 Web route；实际 page provider/外部登录服务需后续
  在明确的 Web/transport task 中接入，测试已验证未配置时会显露失败。
- Task 11 尚未实现 UID 隐私遮罩、个人/群组权限和跨群查询策略，因此当前绑定列表只
  是离线账号 use case，不代表隐私能力已交付。
- Alembic 依赖仍未安装；Task 9 已记录真实 migration round-trip 的 skip，本轮未把
  `create_schema_for_tests()` 当作生产迁移替代。
