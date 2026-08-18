# v0.3 查询与百科集中审查

> 审查日期：2026-08-12。范围为 Task 13--15 引入的 `cc88186..d42240f`，以及
> `tests/e2e/command-matrix.md` 的只读证据。本文不把未接入的私有资源、未取得的
> 平台发送结果或未人工接受的视觉差异写成通过。

## 审查结论

命令规格的 `id`、正则和权限与 `legacy-reference` 中本阶段 12 条查询/百科命令一致；
Task 15 的矩阵正确区分了 `结构已实测`、`差异待审查` 和 `fixture/待实测`。UID 已在
临时图片比较中明确 mask，日期、时间、动态轮换和 UUID 文件名不参与像素等价结论。

下列差异仍未接受：角色总览、便签和周报的画布/布局/placeholder；角色详情的伤害、武器
组合与引用原图链路；日历、图鉴、攻略、兑换码和别名的真实资源或时间敏感输出。它们继续
留给 Task 30，不能因 fixture 或结构计数一致而视为行为验收完成。

## Findings

### P1：`原图` 没有可达的生产缓存登记路径

`PlayerService.remember_original_image()` 只有自己的定义和测试调用；生成的命令 handler
只把 `ImageResponse` 转成 `event.image_result()` 后 `yield`，没有发送后回调。AstrBot 4.27.1
公开的 `MessageEventResult` 没有消息 ID，`AstrMessageEvent.send()` 的公开签名也返回 `None`。
因此回复详情图后，运行期从未把回复 ID 映射到原图，`原图` 命令永久走“未找到”分支。

即使后续补回调，`PlayerService.last_original_image` 也是整个 service 实例共享的可变状态；
并发详情可能把 A 的消息 ID 映射到 B 的原图。默认 bootstrap 还传入空 `ResourceMap`，所以
当前详情本身不会得到原图路径。Task 16.2 必须先确认公开 SDK 是否支持消息 ID 交付；若不能，
不能继续宣称回复取原图可用。

### P1：伤害失败消息可将未分类上游内容写入图片

`DnaApiPlayerTransport._safe_damage_message()` 只匹配少量关键词后原样返回上游 `msg`，而
`PlayerRenderer` 会将该字符串写入用户可见图片和 `dnaby.text`。例如 Authorization/Bearer、
设备编号或其他未列关键词的错误正文不会被过滤。该路径不符合凭据、异常和输出严格脱敏的
目标。Task 16.2 应使用受控失败文案，并增加覆盖多种敏感格式的回归测试。

### P1：资源文档、同步目录和生产 renderer 尚未形成闭环（已由 Task 16.1 修复）

资源文档示例只声明 `fonts/wiki/guide/panel/images`，百科索引实际还依赖
`alias/weekly_item/calendar`；成功同步示例目录后，角色/武器图鉴、攻略和别名仍不能由
`EncyclopediaResourceStore` 找到所需索引。玩家 renderer 在 bootstrap 中使用空
`ResourceMap`，两套 renderer 仍从插件源码的 legacy 字体路径读取字体。由此，Task 15
记录的 placeholder 不是可接受的视觉差异，而是当前资源接线缺失的结果。

Task 16.1 已建立该闭环：manifest 现在要求 `fonts`、`images`、`panel`、`alias`、三个 wiki
子目录、`guide`、`weekly_item` 和 `calendar`；bootstrap 会从同一运行期根装载玩家/百科资源，
两个 renderer 使用该根的字体并记录 `provided`、`placeholder` 或 `fallback`。这只证明 fixture
契约与接线，不是私有资源内容或视觉等价的接受结论。

### P2：每次图片查询都保留新的运行期 PNG（已由 Task 16.1 修复）

玩家与百科 renderer 每次以 UUID 生成 `rendered/*.png`。Task 16.1 已使服务将这类合成图标记
为临时响应，`ResponseFactory` 只在路径位于受控 `rendered/` 根时调用 AstrBot 公共事件追踪
接口；事件结束后由 SDK 清理。panel/wiki/guide 等原始资产没有临时标记，也没有固定时间或数量
删除策略。

## 网络与文档边界

- 百科 transport 将网络、状态码、服务端和结构错误转换为稳定类别，service 不回显
  `EncyclopediaTransportError.detail`；本轮未发现同类的用户可见原文泄露。
- 兑换码 provider、日历和资源均保持 `fixture/待实测` 或差异待审查状态；没有在本轮联网、
  创建资源仓库或执行真实 NapCat。
- 命令矩阵和用户文档已披露原图限制，并保留资源接线与真实资源/视觉验收的区别。Task 16.1
  完成不等于资源同步成功或图片生成成功已经通过真实行为验收。

## 后续

下一步执行 Task 16.2（原图映射和伤害输出），随后重跑完整门禁，并在 Task 30 以只读矩阵
补充人工接受结论。
