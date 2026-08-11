# rewrite Task 12：阶段 3 集中检查-debug

## 范围与结论

本轮复核 Task 9–11 的账号/隐私行为、AstrBot 权限入口、事务和 SQLite 一致性、凭据与
异常脱敏、测试覆盖及文档同步。参考行为来自冻结的 `legacy-reference` 源码和本地
legacy fixture；没有执行真实 NapCat、真实账号写入或外部登录请求。

结论：发现并修复 5 个代码问题（账号行为 3 个、隐私并发 1 个、transport 异常 1 个）；
新增审查测试覆盖默认角色切换、legacy 输入清理、事务回滚、并发隐私 upsert、全局隐私
数据库约束和 transport 响应结构异常。生产 schema 初始化仍是部署前置条件，见“剩余风险”。

## 审查矩阵

| 项目 | 检查结果 | 证据/处理 |
|---|---|---|
| 账号作用域 | 通过 | `EventActor` 只由 AstrBot 公开 `get_sender_id()`、`get_self_id()`、`get_group_id()` 提取；缺少作用域时显式返回错误 |
| 管理员鉴权 | 通过入口边界 | 14 条隐私命令中个人命令为 `MEMBER`，指定/全体命令为 AstrBot `PermissionType.ADMIN`；use case 不读取 legacy event 或自造权限字段 |
| 默认角色行为 | 已修复 | legacy 默认角色会切换当前 UID 且置于成功文案首位；新 `AccountService.login()` 和 `login_success()` 保持这两个语义，无默认角色时只在首次登录选择第一个角色 |
| 登录输入 | 已修复 | `_normalize_login_text()` 恢复 legacy 对空格、换行、制表符和双引号的清理；测试覆盖带内嵌空格 token |
| 缺少参数命令 | 已修复 | `绑定`、`切换`、`删除` 保留 legacy 空参数路由，由 typed service 返回格式/未绑定错误，不再静默无响应 |
| 事务原子性 | 通过 | 凭据写入抛错时，绑定和凭据均回滚；绑定数量超限在写入前返回，不留下半套登录记录 |
| 隐私并发一致性 | 已修复 | 复现时 16 个并发个人写入会产生多条全局记录；现在由 `AsyncDatabase` runtime 内写锁串行化，并在增量 Alembic `0002_privacy_global_identity` 增加 SQLite `group_id IS NULL` 部分唯一索引 |
| transport 异常 | 已修复 | legacy API 响应结构异常按 `SERVER` 归类；不捕获取消，不把异常原文或 token detail 拼入 `str/repr` |
| 凭据泄露 | 通过 | `CredentialRecord.__repr__()`/`redacted_snapshot()`、typed DTO、用户响应和 transport error 均不返回 Cookie/token/refresh token/设备码/d_num |
| UID 隐私 | 按当前边界通过 | `PrivacyService` 提供群强制优先和查询解析；角色卡片/详情等消费方尚未接入，不能宣称历史所有输出已自动遮罩 |
| 参考区隔离 | 通过 | 参考区 `legacy-reference` 只读且 clean；本轮变更仅在 `rewrite/v0.1` worktree |

## 有意保留的可见差异

- 新入口使用 normalized binding/credential 表；旧实现把多个 UID 存在一行 `_` 连接字段，
  新 schema 不迁移旧 SQLite。
- 新账号成功文案展示角色 UID 和 App/Web 凭据状态；legacy 成功文案主要展示角色名称，
  `获取ck` 原本可以导出原始凭据，新入口明确改为只展示保存状态，这是安全契约差异。
- 默认 transport 没有 page provider 时返回“服务未配置”错误；当前 rewrite 尚未注册
  legacy 本地登录 Web route，不伪造登录地址。
- 新命令 registry 仅包含当前已迁移的 23 条命令；其余 legacy 命令不注册、不展示。

## 门禁与环境

- 本轮聚焦账号/隐私/持久化测试通过；完整 staging runtime 回归、Ruff、Pyright、compileall、
  pre-commit、manifest 一致性和参考区 clean 检查在任务收尾时统一记录到 `goal-1/tasks.md`。
- 唯一已知测试 warning 为 AstrBot 依赖的 Python `audioop` 弃用提示。
- Alembic 已在 `requirements.txt` 声明，但当前本地 runtime 未安装；Alembic upgrade/downgrade
  测试按既有契约显式 skip。

## 剩余风险

- 首次部署前必须执行 `docs/usage/configuration.md` 中的 Alembic `upgrade head`；bootstrap
  当前只组装数据库和 service，不自动把测试建表逻辑带入生产。未完成该前置时，账号/隐私
  命令会收到数据库缺表异常，不能视为插件已可用。若已有新 schema 中存在重复全局隐私
  行，`0002` 会显式失败，不会自动删除或选择性覆盖数据。
- UID 隐藏策略的后续角色卡片/详情消费者、真实多平台 `@` 和 page provider 仍属后续 task；
  本轮只完成入口契约和隔离测试。
