# Goal 1 计划

## 目标与依据

本计划以 `/Users/flanchan/.codex/attachments/f3ae1b1e-3fd1-40f5-9a2f-c04df957df11/goal-objective.md` 为目标依据，目标是完成旧 DNAUID 到 AstrBot 插件的长期重构计划，并保持可回滚、可验证、私有和只读回归边界。用户原始输入保存在同目录 `input.md`，后续会话以三份 goal 文件为恢复依据。

## 当前上下文

- 参考区：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_dnaby`。
- 重构区：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_dnaby/.worktrees/rewrite-v0.1`。
- 参考区是现有移植实现的长期只读参考；业务编辑、测试、运行时验证和阶段提交均在独立 worktree 完成。
- 目标架构以 `main.py` 薄入口、`src/entry`、`src/modules`、`src/infrastructure` 和框架无关 use case/DTO 为核心。
- 不引入 `gsuid_core`/`gsucore`；AstrBot 集成只走公共原生 API，并只做插件加载、命令注册、事件 fixture 与响应结果验证。
- 资源仓库、插件仓库和测试产物保持私有；不公开、不发布 Marketplace、不创建公开 Release、不推送主插件仓库。

## 风险与控制

1. 参考区污染：开工前建立 `legacy-reference` 基线并创建 worktree；之后用 `git diff legacy-reference...rewrite/v0.1`、`git worktree list` 和状态检查确认隔离。
2. 行为漂移：以原始 gscore DNAUID 的实际输出为参考，建立命令矩阵；所有可见差异记录原因、影响和人工结论。
3. 凭据泄露：只读账户凭据仅通过 stdin/受保护进程通道注入，不落盘、不打印、不进 Git；日志、异常、响应对 Cookie/refresh token 脱敏。
4. 误执行写操作：gscore 只运行读取型命令；登录、签到、绑定、订阅、隐私修改、面板写操作等用 fake transport、隔离 SQLite 和 fixture 验证。
5. 数据不可逆：不迁移旧数据库；新增 Alembic/SQLAlchemy 结构必须有阶段提交和回滚说明，不删除用户已有参考资源。
6. 依赖/环境缺失：先记录 Python、Git、pre-commit、`pyright-langserver`、AstrBot 4.27.x、ruff 和 pytest 基线；缺失时只报告，不擅自安装。
7. 需求范围膨胀：每轮只执行 `tasks.md` 第一个未完成 task；不顺手升级依赖、重构无关代码或发布。

## 执行方案

按 `tasks.md` 顺序推进，每轮只完成一个 task，并在每三个 task 后执行一次集中检查-debug。每个实现 task 完成前必须基于 diff、诊断、测试或运行日志做自检；有代码改动时创建关联的可回滚提交，再回写 task 的实际变更、证据、剩余风险和下一步。

阶段顺序：

1. 建立参考区 Git 基线、环境/LSP 检查和重构 worktree。
2. 实现 `v0.1.0` 骨架、生命周期、帮助、资源下载、typed 配置、Alembic 初始 revision、logo 和变更记录，清理过时兼容层/移植文档。
3. 实现 `v0.2.0` 账号和隐私能力。
4. 实现 `v0.3.0` 查询与百科能力，并建立行为差异矩阵和图像比较资料。
5. 实现 `v0.4.0` 签到与计划任务/订阅结果。
6. 实现 `v0.5.0` 通知与推送。
7. 实现 `v0.6.0` 运维、面板图管理、资源状态和更新日志。
8. 补齐历史 56 项能力到 `v1.0.0`，完成全量行为差异审查、文档同步和终审。

## 验证方案

重构区每阶段至少执行并记录：

```text
ruff check .
pyright
python3 -m compileall .
python3 -m pytest
pre-commit run --all-files
```

此外按变更范围执行命令注册/权限/schema/Alembic/事务/资源 Git/API fixture/图片渲染/AstrBot 4.27.x 加载测试。需要真实 gscore 时，只读探测并选择已登录且角色数据完整的账户，真实账户只运行 objective 明确的读取型命令；写入型命令不得在真实账户上执行。AstrBot staging runtime 使用临时 runtime root 和指向重构区的 symlink，不替换参考区。

## 回滚方案

- 每个阶段以独立 Git commit 保存；问题出现时优先在重构区通过新修复提交或回到已知阶段提交定位，不对参考区做 destructive reset。
- 参考区保持 `legacy-reference` 基线和只读状态；若 worktree 失败，删除/重建 worktree 前先检查状态并保留可恢复信息，未经明确授权不删除重要数据。
- 不自动合并、推送、公开资源仓库或主插件仓库；这些是独立的用户授权步骤。
- 不迁移旧 SQLite；新 schema 通过 Alembic revision 管理，数据层变更必须能在隔离测试数据库中回滚或明确记录不可回滚边界。

## 默认假设

- 目标文件中的阶段划分、路径、版本号和安全边界均为本 goal 的约束；未在本计划中另行确认的命令、字段、目录和外部入口不擅自补全。
- 若当前仓库尚未初始化 Git，则按 objective 在参考区初始化；若已存在用户 Git 配置/改动，先保留并将基线操作收敛到明确文件范围。
- 若本机缺少 LSP、pre-commit、AstrBot SDK 或其他门禁依赖，不安装，改用现有编译器/formatter/测试做替代并记录缺口，直到用户明确授权安装。
- 资源仓库只有在用户明确允许建立/推送外部私有仓库且本机认证可用时才执行；测试期间优先使用隔离 fixture，不能把凭据写入代码或文件。
- “完成”要求所有 tasks（含集中检查和终审）完成，且无已知高风险问题；低风险剩余事项必须在最终报告中披露。
