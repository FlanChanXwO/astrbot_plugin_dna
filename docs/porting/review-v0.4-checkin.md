# v0.4 签到阶段集中审查

> 覆盖 Task 17-19（`c25354c..b5503d8`）。复核签到状态机、调度取消、订阅边界、写入
> 隔离、并发/事务与全量门禁；本轮修复问题见「修复」小节。

## 审查范围

- 游戏/社区签到状态机（`src/modules/checkin/service.py`）：日历精简、code 711/10000、
  帖子遍历失败、已签到跳过、关闭开关与当天记录 upsert。
- 计划任务（`src/infrastructure/scheduler.py`）：`initialize()` 创建、`terminate()` 取消、
  幂等 start/stop、`scheduled_enabled`/`enable_all_users` 门控。
- 订阅边界（`src/infrastructure/subscriptions/`）：type+会话去重、原子落盘、损坏文件可见失败。
- 写入隔离（Task 19）：23 条写入命令全部离线分发，`sign` 只调用注入 transport。
- 并发/事务：`_save_snapshot` 经 `AsyncDatabase.transaction()` 写锁串行化 upsert。

## 修复（本轮集中检查发现）

1. `enable_all_users` 原是 `CheckinService` 的死参数：新 schema 没有 per-user 签到开关，
   移除该参数，并把门控语义移交 `SignScheduler`——定时自动签到任务需要
   `scheduled_enabled and enable_all_users` 才创建（承担 legacy `SigninMaster` 对全账号
   自动签到的语义）；owner 手动的 `全部签到` 不受影响。
2. 社区启用但 API 未返回启用任务时，原实现误报「帖子列表为空」；改为明确的
   `CHECKIN_TASKS_EMPTY`（社区任务列表为空），不再把「无任务」混同「无帖子」。
3. `subscribe_sign_result` 在订阅文件损坏时会让 handler 崩溃（`SubscriptionStore.load`
   显式抛错）；改为捕获并返回可见的 `SIGN_RESULT_STORE_UNAVAILABLE`，不让命令崩溃。
4. 移除 `CheckinSummary.lines` 死字段；`enable_all_users` 不再在 service 中残留。

## 复查结论

- 状态机：游戏签到在 `today_signed`/code 711 时置为已签并落盘；日历精简或索引越界返回
  失败不伪造成功；社区任务按 `community_tasks` 只执行启用项，逐任务状态可见。
- 调度取消：`SignScheduler.stop()` 取消任务并 `gather(return_exceptions=True)`；
  `CancelledError` 在 `_run_daily` 中重新抛出，不吞掉；重复 start/stop 幂等。
- 订阅边界：订阅按 type+会话去重；推送经注入闭包绑定 `Context.send_message` 公开 API，
  调度器异常由 `_run_daily` 记录，不静默。
- 写入隔离：全部写入命令只在 fake transport + 隔离 SQLite + 模拟事件下执行；真实账户
  不执行任何写入。见 [offline-write-contracts.md](offline-write-contracts.md)。
- 并发/事务：`_save_snapshot` 写锁串行化避免 (uid, date) 唯一冲突；同一 UID 并发签到
  可能在保存前重复执行写操作，记录收敛为「已签」，与 legacy 行为一致，作为接受边界
  记录在 Task 20 剩余风险。

## 门禁证据

- staging runtime 全量 pytest：`213 passed, 1 skipped, 1 warning`。
- `ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、
  `pre-commit run --all-files`、`git diff --check` 均通过。
- 参考区 `legacy-reference` 冻结在 `664b677`，`git worktree list` 只列参考区与重构区；
  未检出 `gsuid_core`/`gsucore` import。
