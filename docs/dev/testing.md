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
- `test_player.py` — 角色概览/详情 fixture、动态图片尺寸、完整文本/布局/资源元数据、伤害
  结果、并发详情各自的原面板引用和伤害失败内容脱敏。
- `test_player_commands.py` — 玩家命令正则、显式 registry、AstrBot `Reply` 消息 ID提取和
  service 缺失边界。
- `test_checkin.py` — 签到成功/已签到/关闭/transport 失败/日历精简/帖子遍历/批量聚合，
  隔离 SQLite 记录落盘与 1300 宽日历 PNG。
- `test_checkin_commands.py` — 签到命令归属、正则、权限和生成 handler 的纯文本结果。
- `test_checkin_transport.py` — legacy 签到 payload 映射、code 711/10000 语义和错误脱敏。
- `test_subscription_store.py` — 订阅 JSON 持久化、type+会话去重、显式删除和损坏文件可见失败。
- `test_scheduler.py` — 计划任务幂等 start/stop、定时关闭只保留清理任务、自动签到推送订阅者和
  2 天前记录清理。
- `test_write_contracts.py` — 写入型命令权限审计、每条写入命令离线分发契约和
  “只调用注入 transport”边界（离线验证 ≠ 真实行为已验证，见
  [offline-write-contracts](../porting/offline-write-contracts.md)）。
- `test_notices.py` — 密函/公告读取 fixture、1300 宽 PNG、公告序号详情、空数据与
  transport 失败脱敏。
- `test_notices_commands.py` — 密函/公告命令归属、正则命名参数与生成 handler 边界。
- `test_notices_transport.py` — legacy 密函 `instanceInfo`、公告列表/详情映射与错误脱敏；
  覆盖网络失败/状态码错误/页面结构变化三类可观测错误，并断言 Cookie/token 原文不进异常。
- `test_notices_subscriptions.py` — 密函订阅增删/去重/推送时间、图片/文本会话开关、公告
  群订阅、计划任务文本/图片推送与公告轮询去重。
- `test_notices_scheduler.py` — 通知计划任务幂等 start/stop 与配置解析。
- `test_operations.py` — 面板图上传（WebP/sha1 去重/失败计数）、列表、删除、压缩和资源
  状态（隔离目录 fixture）。
- `test_operations_commands.py` — 面板/资源命令归属、正则、`images_from_event` 提取与生成
  handler。
- `test_player_transport.py` — legacy role API payload 到 typed overview 的映射和 transport
  错误脱敏。
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
