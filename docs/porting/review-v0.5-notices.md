# v0.5 通知阶段集中审查

> 覆盖 Task 21-23（`ca78c4a..0733789`）。复核通知读取/推送、订阅数据一致性、并发去重、
> 敏感信息与全量门禁；本轮修复问题见「修复」小节，未解决问题留待后续阶段。

## 审查范围

- 通知读取：密函/公告列表与详情（`src/modules/notices/`），错误分类与脱敏。
- 订阅一致性：`src/infrastructure/subscriptions/` 的 type+origin 去重、作用域与生命周期。
- 并发去重：`SubscriptionStore` 写操作在进程内锁内原子落盘。
- 敏感信息：Cookie/token 不进日志、异常、用户响应。

## 修复（本轮集中检查发现）

1. **订阅去重丢失同会话多用户记录**：`SubscriptionStore.add` 原按 `(type, origin)` 去重，
   同一会话内第二个用户的个人密函订阅会覆盖第一个用户的记录。改为按
   `(type, origin, uid)` 去重；`delete`/`update` 同步按 `(type, origin, uid)` 精确匹配。
2. **密函订阅跨会话串扰**：`subscribe_mh`/`unsubscribe_mh`/`mh_subscriptions` 原按
   user+bot 取「第一条」记录，多会话用户会读写错误的会话订阅。改为按当前会话
   `unified_msg_origin` 精确取目标，取消时清空列表即删除整条记录（生命周期清理）。
3. 移除取消订阅后残留的空 `extra_message` 死记录：剩余列表为空时直接删除订阅。

## 复查结论

- 通知读取错误分类：用户取消（`订阅密函时间` 越界）返回格式提示；网络/状态码/服务端/
  页面结构变化分别映射 NETWORK/STATUS/SERVER/显式抛错，不伪造成功；Token/Cookie 与上游
  `msg` 原文不进异常 str/repr（Task 23 测试覆盖）。
- 并发去重：`SubscriptionStore` 与 `AnnStateStore` 写操作均在 `asyncio.Lock` 内原子落盘，
  同一 (type, origin, uid) 不重复。
- 生命周期：`initialize()` 启动 sign/notices 调度任务、`terminate()` 逆序取消；重复
  start/stop 幂等。
- 计划任务推送失败由 `_run_hourly`/`_run_periodic` 记录日志，异常分类可见不静默。

## 未解决问题（留待后续）

- 真实密函/公告内容、图片与视觉等价未验收（Task 30 只读矩阵）。
- 真实平台推送行为（`Context.send_message`）未执行，仅注入 push fixture 覆盖契约。

## 门禁证据

- staging runtime 全量 pytest：`259 passed, 1 skipped, 1 warning`。
- `ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、
  `pre-commit run --all-files`、`git diff --check` 均通过。
- 参考区 `legacy-reference` 冻结在 `664b677`；未检出 `gsuid_core`/`gsucore` import。
