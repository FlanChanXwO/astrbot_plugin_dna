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
- `test_config.py` — `_conf_schema.json` 生成、默认值、`get_config/set_config`。
- `test_session.py` — `EventContext` 映射（mock `AstrMessageEvent`）、`Sender` 累积与结果转换。
- `test_database.py` — 5 表 CRUD + 迁移（临时 sqlite 文件）。
- `test_subscriptions.py` — 订阅增删改查 + 目标解析。
- 各功能域纯逻辑（name_convert、damage、sign 解析等）。

## 原则
- 先写失败测试（Red）→ 最小实现（Green）→ Refactor。
- 用 mock 构造 `AstrMessageEvent`，不依赖真机。

## AstrBot 集成边界

当前阶段只用 AstrBot 本地 SDK、fake Context、事件 fixture 和原生响应构造方法验证
插件加载、handler 注册和响应结果。不执行真实 NapCat、OneBot、登录、签到或写入型
账号测试；进入后续行为回归阶段时，按 `goal-1/tasks.md` 的只读/隔离边界补充证据。
