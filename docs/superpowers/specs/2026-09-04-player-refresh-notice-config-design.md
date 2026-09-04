# 玩家单角色刷新提示与发送配置设计规格

> 状态：已批准并实施；日期：2026-09-04。
> 目标插件：`astrbot_plugin_dnaby`。
> 关联范围：玩家刷新服务、缓存配置、响应 DTO、Dashboard schema 和使用说明。

## 1. 目标与边界

恢复 `cache.refresh_send_card` 配置，并让主动刷新单个角色成功时明确告诉用户
哪个正式角色面板已刷新。刷新动作本身始终执行完整的概览读取、角色详情读取、
渲染和缓存更新；配置只控制成功响应是否携带新图片。

本次不修改命令正则、`commands.json`、批量刷新语义、平台适配协议或
`display` 配置，也不新增 `display.refresh_notice`。

## 2. 已确认行为

| 场景 | 成功响应 |
| --- | --- |
| 单角色刷新，`cache.refresh_send_card=true` | 同一条消息按“文字、图片”顺序返回 `角色【正式名】面板已刷新` 和新面板图片。 |
| 单角色刷新，`cache.refresh_send_card=false` | 只返回 `角色【正式名】面板已刷新`；数据刷新、渲染和缓存更新不跳过。 |
| 批量刷新 | 保持现有成功/失败汇总，不逐张发送图片。 |
| 角色不存在、未解锁、网络/详情/渲染失败 | 只返回现有错误响应，不生成成功提示。 |

用户输入可以是别名或模糊名称。刷新概览阶段保存已解析的 `RoleItem`，成功文案
使用其 canonical name，而不是直接回显用户输入。普通用户刷新和管理员传入 UID 的
刷新都经过 `PlayerService.refresh_role()` 的同一响应逻辑。

## 3. 配置与迁移

`CacheSettings` 提供：

```python
refresh_send_card: bool = True
```

已有 `cache.refresh_send_card` 值保留并按当前值生效；缺失时默认为 `true`。
统一缓存迁移只丢弃已经移除的 TTL 字段，不再记录 warning 或删除
`refresh_send_card`。配置字段通过现有 schema 生成器投影到 `_conf_schema.json`。

## 4. 响应与生命周期

`PlayerService` 从 bootstrap 接收 `settings.cache.refresh_send_card`。刷新完成后先
完成原有 `_role_detail_from_overview()` 流程，再根据配置包装响应：

- 文本使用 `PlainTextResponse` 和动态玩家文案常量；
- 图片开启时使用现有 `ChainResponse`，组件固定为文本再图片；
- 图片仍由现有 `ImageResponse` 标记临时文件，交给 `ResponseFactory` 登记和清理。

成功文案只在详情读取和渲染流程返回图片响应后生成，因此任何已有错误响应都不会
被包装成成功链。批量刷新不调用单角色成功包装逻辑。

## 5. 验收

- 配置默认值、显式布尔值、迁移保留和 schema 字段存在性通过测试；
- bootstrap 将配置注入 `PlayerService`；
- 单角色普通/管理员刷新覆盖文字-only、文字+图片、canonical name 和失败分支；
- 批量刷新仍只返回汇总；
- `ResponseFactory` 对复合响应中的临时图片继续登记并清理；
- 目标 pytest、ruff、compileall 和 `git diff --check` 均记录实际结果，既有环境占用
  或与本改动无关的门禁失败单独说明。
