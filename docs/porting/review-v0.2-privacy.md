# rewrite Task 11：个人/群组隐私审查

## 范围

本轮迁移 legacy `dna_privacy` 的 14 条命令、个人/群组隐私策略、AT 查询解析和目标绑定
边界。新入口不导入 legacy `Sender`、`EventContext`、`MessageSegment` 或旧数据库；真实
NapCat、真实账户和隐私写入不在本轮执行。

## 实现边界

- `src/modules/privacy/` 以 `PrivacyService` 协调个人全局设置、可选群组个人作用域、群
  强制偷窥/UID 隐藏和查询解析；群强制值按字段优先，清除后恢复个人值。
- 个人命令保存 `user_id + bot_id` 全局设置，指定命令要求群聊、有效 AstrBot `At` 目标
  和目标已有 UID 绑定；目标绑定检查只读存在性，不回显 UID。
- `src/entry/event.py` 优先使用 AstrBot 公开的 `get_messages()` 和 `At` 组件提取目标，
  同时兼容平台保留的 `<@id>`/`<@!id>` 标记和 OneBot `raw_message` At 段；目标无法解析时
  由命令入口返回明确提示，不静默回退为查询调用者。`CommandRequest.target_user_id` 将
  有效目标传给 use case。
- 文案集中于 `src/modules/privacy/messages.py`，handler 不直接拼接用户可见消息。

## 测试与门禁证据

- `tests/test_privacy.py` 覆盖默认值、个人/群强制优先级、取消恢复、跨群/Bot 隔离、指定
  目标边界和 AT 查询解析；`tests/test_privacy_commands.py` 覆盖 14 条命令、权限声明和
  AstrBot `At` 目标提取。
- 隐私写入只通过 `tmp_path` 下的 `sqlite+aiosqlite` 执行；未连接 legacy 数据库或真实
  账户。
- 聚焦测试、全量测试、Ruff、Pyright、compileall、pre-commit 和 manifest 一致性结果记录
  于 `goal-1/tasks.md` 的 Task 11 条目。

## 剩余边界

- UID 隐藏策略已经提供查询接口，但角色卡片、详情等消费方尚未在 Task 11 接入；因此本轮
  不宣称所有历史输出都已自动脱敏。
- 真实 AstrBot/OneBot 群管理员和多平台 @ 目标行为未执行；仅以本地 SDK 公开组件和事件
  fixture 验证入口契约。
