# Goal 4 Tasks

> 每轮只执行第一个未完成项。普通 task 必须 TDD；每三个普通 task 后执行一次集中检查-debug。所有提交只暂存本 task 拥有的文件，禁止混入初始化前的用户改动。

## Task 01 — 固化设计规格与规格审查 `[completed]`

**目标**：将已批准设计写入 specs 文档，使用只读 spec reviewer 最多三轮审查并提交独立文档 commit。

**验收**：规格覆盖目标、非目标、类型/API、失败语义、TDD、浏览器验证和回滚；提交不包含初始化前既有修改。

- 实际完成：新增 `docs/superpowers/specs/2026-09-01-dnaby-t2i-concurrency-mentions-announcements-design.md`，固化 T2I 直出、Pillow 例外、artifact/sidecar、全局并发/single-flight、At mention policy、登录文案、公告目标事实源和 Dashboard 状态机。只读审查发现并补充了轮询与目标 mutation 的 per-target 锁/重新校验线性化协议、真实群聊命令 provenance 不变量、pair 发布恢复模型、全链路 Pillow 隔离、PollResult 错误模型、transport 覆盖清单与响应边界。
- 验证证据：规格 reviewer（Sagan）完成一轮审查；审查提出的 P0/P1/P2 缺口已逐项写入规格第 13 节；`wc -l` 确认文档 490 行，未修改业务代码。
- 剩余风险：尚未提交；当前工作树包含初始化前既有修改和其他 goal 未跟踪文件，提交时必须只暂存本规格。
- 下一步：Task 02：先写并运行 RenderedArtifact/标准库 JPEG/PNG 检查器的 Red 测试。

## Task 02 — RenderedArtifact 与无 Pillow 图片检查器 `[pending]`

**目标**：测试先行新增 JPEG/PNG 结构校验、尺寸提取和 `RenderedArtifact`，拒绝 HTML、截断和格式不匹配结果。

**验收**：常规 artifact 构造不调用 Pillow；JPEG/PNG 正常及损坏 fixture 均有 Red/Green 证据；无新依赖。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 03 — 原始 bytes 写入、sidecar、缓存与响应格式契约 `[pending]`

**目标**：测试先行实现原子 artifact/sidecar 写入，泛化缓存 validator、临时文件、ImageResponse 和 Admin Preview 的 MIME/后缀处理。

**验收**：最终文件与 T2I bytes/SHA 完全一致；JPEG/PNG 均可缓存和发送；配对清理覆盖 sidecar；不破坏受控路径安全检查。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D01 — Task 01–03 `[pending]`

**检查**：规格偏差、artifact 格式安全、路径/原子写、sidecar 生命周期、缓存租约、MIME 泄漏、类型检查、目标测试和 staged diff。发现问题追加修复 task。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 04 — 玩家卡片 T2I 直出 `[pending]`

**目标**：测试先行迁移玩家概览和角色详情，移除 T2I JPEG→PIL RGBA→PNG，保留布局/resources/original_image_path/cache 语义。

**验收**：玩家最终 `.jpg` 与 T2I bytes 一致；缓存 fresh/stale/refresh 和管理员预览通过；解码视觉与旧转换结果一致。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 05 — 百科、便笺与周报 T2I 直出 `[pending]`

**目标**：测试先行迁移百科域内所有 T2I-backed 卡片，包括体力、周报、日历等，保留纯资源图片直返行为。

**验收**：T2I JPEG/PNG 不再二次编码；尺寸、文本、资源状态和现有缓存/响应契约通过。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 06 — 签到、帮助及其余 T2I 卡片直出 `[pending]`

**目标**：测试先行迁移签到日历、签到报告、帮助/二维码等剩余 T2I 输出；纯 PIL 路径保持明确隔离。

**验收**：所有常规 T2I 输出不调用 Pillow writer；现有图片生命周期与消息链测试通过。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D02 — Task 04–06 `[pending]`

**检查**：所有 T2I renderer 清单、遗漏的 PNG 假设、视觉/尺寸、缓存键、sidecar、临时文件清理、Admin Preview 和相关全域测试。发现问题追加修复 task。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 07 — 公告与密函直出及超长分页隔离 `[pending]`

**目标**：测试先行迁移密函、公告列表和公告详情；未超长直出，超过 6000px 才使用 Pillow JPEG 裁剪。

**验收**：普通详情 bytes 不变；分页仅在边界触发，页宽/总高度/顺序/内容完整，失败保持可重试状态。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 08 — 渲染缓存、离线对比与清理工具适配 `[pending]`

**目标**：更新公告/玩家等缓存 manifest、离线 compare/regenerate 脚本和维护清理，使其读取 artifact sidecar 并支持 jpg/png。

**验收**：旧缓存 miss 后安全重建；不把格式变化伪装成损坏；离线检查仍能验证文本/layout/resources；孤儿配对清理正确。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 09 — 统一图片格式集成与体积回归 `[pending]`

**目标**：补齐跨 renderer 集成测试和代表性基准，证明常规最终 bytes/T2I bytes=1.0，视觉内容不变。

**验收**：所有 T2I-backed renderer 有格式矩阵；测试禁止常规输出 Pillow；生成 before/after 字节、尺寸和视觉证据。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D03 — Task 07–09 `[pending]`

**检查**：公告分页、缓存完整性、JPEG 平台兼容、元数据迁移、离线工具、真实输出体积与全部渲染测试。发现问题追加修复 task。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 10 — 全局请求并发配置与 RequestConcurrencyGate `[pending]`

**目标**：测试先行新增 `network.max_concurrent_requests=4`、schema 和 cancellation-safe Semaphore，并注入短请求基础设施。

**验收**：确定性测试证明活动请求不超过配置；异常/取消释放槽位；WebSocket/SSE 不长期占槽；配置错误显式失败。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 11 — URL/post single-flight 与缓存 miss 合并 `[pending]`

**目标**：测试先行实现源图、二维码和公告详情 single-flight，修复临时 target 导致相同 URL 无法合并的问题。

**验收**：相同 key 并发底层调用为 1；不同 key 可在全局门内并行；失败/cancel 后 registry 清理且后续可重试。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 12 — 公告图片并行与轮询 single-flight `[pending]`

**目标**：测试先行并行列表 previews、详情 QR/blocks，并让并发 `poll_ann_now()` 共享一轮；公告和目标推送顺序不变。

**验收**：并发波次、稳定顺序和最大 4 路有证据；同轮询列表/详情/渲染/推送只执行一次；部分目标重试契约保持。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D04 — Task 10–12 `[pending]`

**检查**：Semaphore 覆盖面、长连接排除、死锁、任务泄漏、single-flight key、异常传播、缓存竞态、重复推送和公告顺序。运行并发相关全量测试。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 13 — 统一命令文本与真实 At 归一化 `[pending]`

**目标**：测试先行新增 `command_text_from_event()`，确保 DynamicRegexFilter 与 handler 对 At 前后位置使用相同纯命令文本。

**验收**：真实 At 前/后均触发；字面 At、AtAll、机器人 At、Reply/Image 不误解析；无消息链时保持兼容 fallback。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 14 — CommandSpec mention policy 与只读目标查询矩阵 `[pending]`

**目标**：测试先行增加 `ignore/query/admin_target`，标注并验证玩家、便笺、周报、签到日历、密函；写操作不接收目标。

**验收**：所有 query 使用目标 active UID/凭据并经过 PrivacyService；禁用 At、禁止偷窥、未登录和自查路径明确；签到/刷新/订阅/账号管理不代执行。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 15 — 登录/UID 文案、帮助与命令清单修正 `[pending]`

**目标**：测试先行精确修改误导性的绑定文案，保留 UID 管理术语，并重生成 commands manifest。

**验收**：查询错误只提示登录/重新登录；登录成功/页面/帮助语义一致；UID 管理结果不被误改；registry 与 commands.json 一致。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D05 — Task 13–15 `[pending]`

**检查**：所有命令 regex、At 安全边界、隐私/凭据归属、写操作隔离、文案残留、help/manifest/docs 一致性及真实事件 fixture。发现问题追加修复 task。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 16 — Subscription enabled 与公告配置解耦 `[pending]`

**目标**：测试先行给订阅增加 enabled 默认值，轮询过滤禁用目标，移除公告配置双写/启动双向同步和 schema 字段。

**验收**：旧 JSON 正常加载为 enabled；旧 announcement_groups 不导入、不改写、不复活，日志不泄露群号；其他订阅行为不回归。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 17 — AnnouncementTargetService 生命周期 `[pending]`

**目标**：测试先行统一 subscribe/unsubscribe/disable/enable/delete，并实现“重新启用只接收未来公告”的状态基线。

**验收**：聊天命令共用 service；停用先安全生效；启用清理失败保持禁用；删除后不发送；部分完成结果显式且可恢复。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 18 — Admin API 与 Web routes 目标管理契约 `[pending]`

**目标**：测试先行接入目标生命周期 service，扩展 TaskTarget/TaskTargetUpdate/mutation 响应，限制只管理已发现公告目标且不可移动 identity。

**验收**：列表、启停、删除、错误/部分完成、鉴权和输入校验完整；手工创建/unified origin 修改被拒绝。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D06 — Task 16–18 `[pending]`

**检查**：JSON 向后兼容、跨文件写入顺序、崩溃窗口、重启恢复、Admin 鉴权、配置弃用、安全日志和其他任务目标回归。发现问题追加修复 task。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 19 — Dashboard 公告目标启停与删除 UI `[pending]`

**目标**：测试先行增加目标状态、启用/停用按钮、删除确认、busy/error/partial 状态和刷新；不提供创建或 origin 编辑。

**验收**：键盘/屏幕阅读器基础语义、移动/桌面布局、确认流程、错误信息和状态刷新有 RTL/DOM 或项目既有前端测试证据。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 20 — 公告目标跨重启与投递一致性集成 `[pending]`

**目标**：覆盖命令创建→Dashboard 停用/启用/删除→轮询→重启的完整状态机。

**验收**：停用不发、启用不补旧、未来公告正常、删除不复活、部分群失败只重试失败群；配置完全不参与恢复。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 21 — 跨功能集成与公共接口收口 `[pending]`

**目标**：统一 bootstrap 注入、生命周期、类型导出、缓存/response/admin/commands 的共享接口，删除本目标产生的旧适配死代码。

**验收**：LSP blast radius 与 diagnostics 无新增问题；main import、动态 handler、scheduler start/stop、资源 snapshot 和临时文件生命周期通过。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D07 — Task 19–21 `[pending]`

**检查**：Dashboard UX、前后端契约、bootstrap/lifecycle、权限、数据竞态、死代码、日志、图片路径和跨域回归。运行相关后端与前端门禁。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 22 — 真实渲染体积与视觉验收 `[pending]`

**目标**：使用现有可复现 payload/T2I 环境生成代表性玩家、周报、公告和签到图片，记录 before/after 格式、尺寸、字节和视觉对比。

**验收**：常规路径 inflation=1.0；无肉眼可见模板/文字变化；超长公告分页完整；若真实 T2I 不可用，记录环境阻塞并提供离线确定性证据，不伪造成功。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 23 — Dashboard 浏览器与 AstrBot/OneBot 冒烟 `[pending]`

**目标**：实际打开 Dashboard 验证目标管理，并在可用运行时发送 At 前/后查询及公告订阅管理命令。

**验收**：截图/网络/控制台证据；卡片和周报正确查询目标；写命令不代执行；UI 启停删除生效。环境不可用时精确记录阻塞。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 24 — 文档、CHANGELOG、维护与回滚说明 `[pending]`

**目标**：同步 usage/configuration/architecture/data-model/testing/maintenance、README、CHANGELOG 和命令帮助，记录格式、并发、At、订阅事实源和手动迁移。

**验收**：不再宣称公告群组由配置维护；明确旧配置不自动迁移、Dashboard 能力、JPEG 输出、Pillow 例外、并发配置与回滚步骤。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 D08 — Task 22–24 `[pending]`

**检查**：用户体验、真实/离线证据、浏览器错误、文档事实、迁移/回滚、安全、性能指标和全部已知限制。发现问题追加修复 task。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 25 — 专家审查与候选发布全量门禁 `[pending]`

**目标**：使用 code-review-expert 自审本 goal 全部变更，修复阻塞问题，并运行最终候选的完整测试、ruff、compileall、Pyright、manifest/schema 一致性和 diff 检查。

**验收**：无已知高风险问题；失败按本次变更/既有/环境分类；提交和工作树审计不包含用户初始化前改动；形成终审所需证据。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：进入 Goal 终审轮。
