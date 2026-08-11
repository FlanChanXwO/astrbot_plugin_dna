# 测试

## 命令
```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

## 测试范围（tests/）
- `test_command_registry.py` — `CommandSpec` 校验、显式模块索引、重复加载、named
  parameters、动态 async-generator handler、AstrBot 公开正则/权限过滤器和帮助输出。
- `test_commands.py` — `commands.json` 与代码 registry 生成投影一致；legacy 分发器回归单独保留在
  `test_dispatch.py`，不属于 rewrite 入口。
- `test_config.py` — legacy 配置 wrapper 的兼容回归。
- `test_config_resources.py` — Pydantic 分组配置、生成 schema 的 AstrBotConfig 递归解析、
  resource manifest 路径校验、私有 Git clone/pull 失败可见性和本地修改保护。
- `test_persistence.py` — SQLAlchemy async SQLite 路径、repository 显式事务提交/回滚、五表
  metadata、凭据脱敏和 Alembic 初始 revision；Alembic 未安装时真实 upgrade/downgrade 测试会
  显式 skip，静态 revision 契约仍执行。
- `test_account.py` — typed 登录输入、fake transport、账号事务、绑定生命周期、凭据状态
  摘要和网络/状态码/服务端错误脱敏。
- `test_account_commands.py` — AstrBot 事件 fixture 到 typed actor、named/空 UID 参数和
  runtime service 注入边界。
- `test_privacy.py` — 个人/群组隐私默认值、字段优先级、取消恢复、目标绑定、AT 查询解析、
  并发 upsert 和 SQLite 全局作用域唯一性；所有隐私写入均使用隔离 SQLite。
- `test_privacy_commands.py` — 14 条隐私命令的 registry 权限、公开 `At` 目标提取和缺失目标边界。
- `test_session.py` — `EventContext` 映射（mock `AstrMessageEvent`）、`Sender` 累积与结果转换。
- `test_database.py` — 5 表 CRUD + 迁移（临时 sqlite 文件）。
- `test_subscriptions.py` — 订阅增删改查 + 目标解析。
- 各功能域纯逻辑（name_convert、damage、sign 解析等）。

## 原则
- 先写失败测试（Red）→ 最小实现（Green）→ Refactor。
- 用 mock 构造 `AstrMessageEvent`，不依赖真机。
- 生产 schema 变更走 Alembic；`create_schema_for_tests()` 只用于隔离测试，不能替代部署迁移。
- `AsyncDatabase.transaction()` 的 runtime 内写锁只用于保护 SQLite 事务一致性，没有固定
  超时、重试或静默降级；首次部署仍须先执行 Alembic `upgrade head`。

## AstrBot 集成边界

当前阶段只用 AstrBot 本地 SDK、fake Context、事件 fixture 和原生响应构造方法验证
插件加载、handler 注册和响应结果。账号与隐私写入只在隔离 SQLite 中执行；不执行真实
NapCat、OneBot、手机号验证码、token 或外部登录服务。
