# 测试

## 命令
```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

## 测试范围（tests/）
- `test_commands.py` — `commands.json` 与分发表一致性；MASTER 正则逐条 `re.match` 命中。
- `test_config.py` — `_conf_schema.json` 生成、默认值、`get_config/set_config`。
- `test_session.py` — `EventContext` 映射（mock `AstrMessageEvent`）、`Sender` 累积与结果转换。
- `test_database.py` — 5 表 CRUD + 迁移（临时 sqlite 文件）。
- `test_subscriptions.py` — 订阅增删改查 + 目标解析。
- 各功能域纯逻辑（name_convert、damage、sign 解析等）。

## 原则
- 先写失败测试（Red）→ 最小实现（Green）→ Refactor。
- 用 mock 构造 `AstrMessageEvent`，不依赖真机。

## 受控真实 E2E

本机 AstrBot + OneBot + NapCat 的真实入站测试可向 OneBot HTTP 事件端点发送
JSON，并带上 `X-Self-ID` 头；只有 OneBot 返回 `204` 且 NapCat 日志出现实际出站
action，才算消息链路送达。命令矩阵以 `commands.json` 的 56 条记录为准，测试后要
核对数据库、订阅文件、隐私设置、别名和自定义面板图没有遗留测试状态。

登录页测试还要从出站消息中在本机变量内提取 auth，检查新链接的登录表单返回
`200`；不把 auth、Cookie、token 写入日志、报告或提交。旧 auth 是进程内临时会话，
过期时返回 `404`，必须重新发送 `dna登录`。
