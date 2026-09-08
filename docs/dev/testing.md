# 测试

## 命令

从插件目录运行：

```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

## 长期测试结构

测试套件按长期业务域维护，不再按迁移阶段、任务编号或实现层拆分。当前固定保留 13 个 Python 测试文件：

- `test_entry_commands.py` — 插件命令 registry、公开正则/权限、handler 生成与帮助/manifest 核心契约。
- `test_config.py` — typed 配置、schema、默认值、前缀与关键迁移边界。
- `test_persistence.py` — async SQLite、事务、核心表、凭据脱敏与 Alembic smoke。
- `test_account.py` — 登录、绑定、凭据状态和错误脱敏。
- `test_player.py` — 玩家概览/详情、目标账号、核心渲染与错误可见性。
- `test_encyclopedia.py` — 图鉴、wiki/guide/兑换码、日历/周报等核心读取与渲染。
- `test_checkin.py` — 手动签到、自动签到、签到报告和订阅关键路径。
- `test_notices.py` — 密函/公告读取、详情、渲染与错误边界。
- `test_scheduler.py` — 定时任务 start/stop、签到推送和清理任务关键路径。
- `test_resources.py` — 公共资源同步、失败可见性、single-flight 与停止行为。
- `test_rendering.py` — HTML/T2I 结果、转义、格式与错误分类。
- `test_agent_tools.py` — Agent Tools 注册、只读查询、身份覆盖拒绝和图片发送 smoke。
- `test_integration.py` — 登录/入口关键全链路恢复，以及仓库结构 hygiene。

## 保留原则

一个测试只有在失败意味着以下至少一种严重回归时才应长期保留：插件无法启动或安全退出、公开命令契约失效、配置/数据库/凭据边界破坏、核心业务流程不可用、资源同步可能破坏当前快照、渲染无法生成 AstrBot 可消费结果，或 Agent Tools 出现身份安全问题。

以下内容不再单独建立测试文件：阶段性 `test_goal*`、`*_commands.py`、`*_transport.py`、独立 cache/TTL/lifecycle 矩阵、CI/branding/目录骨架、迁移 review/audit。若其中某个行为仍然是长期关键契约，应把最小断言并入对应业务域文件，而不是重新创建阶段编号测试。

## AstrBot 集成边界

测试使用 AstrBot 本地 SDK、fake Context、事件 fixture 和原生响应构造方法；账号与持久化写入只在隔离测试目录/SQLite 中执行，不访问真实 NapCat、OneBot、手机号验证码、token 或外部登录服务。

## 仓库结构约束

根目录不再保存 `goal-*` 阶段工作区。设计、迁移和历史审计资料统一放在 `docs/`；`test_integration.py` 会阻止带内容的 `goal-*` 目录重新进入长期仓库。
