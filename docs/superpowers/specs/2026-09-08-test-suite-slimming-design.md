# 测试套件瘦身设计

## 背景

当前 `tests/` 同时承载长期业务回归、阶段性 `goal-*` 验收、命令/transport/cache 等实现细节测试，文件数量已经远超维护收益。迁移阶段结束后，测试结构应从“任务编号驱动”改为“长期业务域驱动”。

仓库根目录的 `goal-1/`、`goal-2/`、`goal-3/`、`goal-4/` 属于历史规划交付物，当前长期文档已经位于 `docs/`，因此这些目录一并移除。

## 已确认目标

- 将可执行测试收敛到约 10–15 个 Python 文件，目标 13 个。
- 主动牺牲大量细粒度覆盖，只保留能阻止严重回归的核心测试。
- 核心业务边界包括：启动/命令 registry、配置、持久化、账号、玩家、图鉴、签到、公告/密函、订阅/调度、资源同步、渲染；Agent Tools 只保留轻量 smoke。
- 所有 `test_goal*` 文件退出长期测试套件；只有仍能保护长期公开行为的少量断言才迁入正式领域测试。
- 根目录所有 `goal-*` 目录删除，不归档、不保留副本。

## 目标结构

```text
tests/
├── fixtures/
├── test_entry_commands.py
├── test_config.py
├── test_persistence.py
├── test_account.py
├── test_player.py
├── test_encyclopedia.py
├── test_checkin.py
├── test_notices.py
├── test_scheduler.py
├── test_resources.py
├── test_rendering.py
├── test_agent_tools.py
└── test_integration.py
```

## 保留准入标准

测试只有在失败意味着以下至少一种情况时才应长期保留：

1. 插件无法启动、初始化或安全退出。
2. 公开命令 registry、权限或核心分发契约失效。
3. 配置、数据库事务或敏感凭据边界发生严重回归。
4. 账号、玩家、图鉴、签到、通知、订阅等核心用户流程无法工作。
5. 资源同步破坏当前可用快照，或路径安全边界失效。
6. 渲染链路无法生成 AstrBot 可消费结果。
7. Agent Tools 无法注册/调用，或允许伪造当前事件身份。

实现细节、历史迁移过程、重复的 command/transport/cache 边界、CI/branding/目录骨架、阶段评审等测试不再作为独立长期契约。

## 合并策略

- `*_commands.py`：只迁移核心 regex/权限/handler happy path 到对应领域文件。
- `*_transport.py`：只迁移关键映射与敏感信息脱敏边界，其余重试/状态码矩阵删除。
- cache/TTL/image lifecycle：只在直接影响核心用户流程时保留一个关键失效或恢复场景。
- database/persistence：统一由 `test_persistence.py` 覆盖事务、核心表和迁移 smoke。
- rendering：HTML/T2I/asset 只保留最小成功输出与安全边界。
- scheduler/subscription：合并为一个调度领域文件，覆盖 start/stop、核心推送与订阅持久化 smoke。
- resources/operations：统一到 `test_resources.py`，覆盖同步成功、失败保留旧快照、状态与路径边界。
- integration：覆盖 bootstrap → registry → service 注入 → terminate 的最小全链路，以及禁止根目录重新出现 `goal-*`。

## 明确删除范围

- 全部 `tests/test_goal*.py`。
- CI workflow、branding、entry skeleton、阶段 review/audit、旧迁移验收、重复 database/dispatch/session 等低价值独立测试。
- 被合并后的 `*_commands.py`、`*_transport.py`、独立 cache/TTL/lifecycle 文件。
- `tests/e2e/command-matrix.md` 从测试目录移除；当前命令事实源继续由 registry 与 `commands.json` 维护。
- 不再被引用的历史 fixture（例如带 `goal3` 命名的 fixture）删除。
- 根目录 `goal-1/`、`goal-2/`、`goal-3/`、`goal-4/` 全部删除。

## 验证

最终改动必须满足：

```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

并人工确认：

- `tests/test_*.py` 数量处于 10–15。
- 不存在 `tests/test_goal*.py`。
- 仓库根目录不存在 `goal-*`。
- `docs/dev/testing.md` 与新的长期测试结构一致。
