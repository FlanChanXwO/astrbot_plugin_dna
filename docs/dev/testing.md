# 测试

测试套件使用 pytest，并按长期业务域维护。不要在文档中写死“当前共有多少个测试文件/用例”；实际集合以 `tests/` 与 pytest 收集结果为准。

## 基础命令

```bash
python3 -m pytest
ruff check .
python3 -m compileall .
```

查看当前收集到的测试：

```bash
python3 -m pytest --collect-only -q
```

针对单一领域优先跑最小相关文件，例如：

```bash
python3 -m pytest tests/test_entry_commands.py
python3 -m pytest tests/test_config.py
python3 -m pytest tests/test_account.py
python3 -m pytest tests/test_resources.py
python3 -m pytest tests/test_client_updates.py tests/test_client_update_service.py tests/test_client_update_delivery.py tests/test_client_update_state.py
```

## 长期保留的测试类型

测试应保护稳定契约，而不是迁移阶段或临时任务编号。重点包括：

- 插件入口、命令 registry、正则与权限契约；
- typed 配置与 `_conf_schema.json` 投影；
- 数据库事务、迁移和凭据边界；
- 账号、玩家、图鉴、签到、公告/密函等核心业务路径；
- 调度、订阅、公共资源同步与失败回退；
- 渲染结果能够被 AstrBot 消费；
- Agent Tools 的身份、安全和副作用边界；
- 关键跨模块集成路径。

阶段性 `goal-*`、一次性审计、某个历史 PR 的验证结果不应成为长期测试结构的一部分；仍有价值的断言应并入对应业务域测试。

## 测试边界

自动测试使用 fake Context、事件 fixture、隔离数据库/临时目录和可注入 transport。测试不应依赖真实账号凭据、手机号验证码、OneBot 群成员、生产数据库或外部服务可用性。

修复 bug 时，优先补充能复现问题的最小回归测试；重构时保持行为测试先绿后改，并在完成后再次运行对应测试。

真实客户端更新 Source 不属于默认 pytest。代码与离线 fake 测试通过后，可在
隔离环境运行 `python3 scripts/smoke_client_update_sources.py`。该工具不会写 state
或订阅，也不会下载完整补丁；不要对生产数据目录运行额外的手工迁移脚本。
