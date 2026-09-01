# DNABY T2I 直出、受控并发、At 查询与公告目标管理设计规格

> Goal 4 / Task 01；状态：已批准设计，完成审查补充后待按任务清单实施。
> 目标插件：`astrbot_plugin_dnaby`；目标运行时：AstrBot `4.27.1`；日期：2026-09-01。

## 1. 背景、目标与完成标准

当前迁移链路把 AstrBot T2I 返回的 JPEG 再交给 Pillow 解码、转换为 RGBA 并保存为 PNG，造成生成图体积较原 DNAUID 链路增长约 5–10 倍。公告渲染还存在图片依赖串行获取、重复请求和轮询重入风险；命令入口的正则匹配只依赖纯文本，真实 `At` 组件位于命令前后时无法稳定触发目标用户查询；公告订阅目标同时受配置和 `subscriptions.json` 影响，导致命令发现的群组在配置中固化、只读且可能在重启后复活。

本规格统一解决以下问题：

1. 常规 T2I 生成结果不再经过 Pillow 解码或重编码，JPEG/PNG 原始 bytes 直接校验、落盘、缓存和发送。
2. Pillow 只保留在模板输入素材处理、二维码/legacy 绘制，以及超过既有 `ANN_PAGE_LIMIT=6000` 的公告分页裁剪路径。
3. 公告卡片内部互不依赖的短请求受控并行；全插件短生命周期外部请求共享默认 4 路并发门；相同资源和公告轮询使用 single-flight。
4. 玩家卡片、角色详情、便笺、周报、签到日历和密函等只读查询支持真实 At 位于命令前或命令后；写操作不允许代被 At 用户执行。
5. 用户未完成认证时统一提示“请登录”，不再误导为“请绑定 UID”；显式 UID 管理和 UID 隐私命令仍保留原术语。
6. `subscriptions.json` 成为公告推送目标唯一事实源；旧 `notifications.announcement_groups` 只保留原值供人工参考，不再参与恢复、同步或投递。
7. Dashboard 可查看、停用、启用和删除由真实群聊命令发现的公告目标；不提供手工创建或修改会话身份；重新启用只接收未来公告。

完成必须由以下事实证明：

- 常规生成图最终文件 bytes/SHA 与 T2I 原始结果完全一致，插件引入的体积膨胀倍率为 `1.0`。
- 常规 T2I 输出路径在禁止 `PIL.Image.open/save` 后仍可完成。
- 同时进行的短生命周期外部请求不超过 `network.max_concurrent_requests`，默认值为 4。
- 相同图片 URL、二维码 URL+尺寸、公告详情 `post_id` 和公告轮询操作的并发调用只执行一次底层工作。
- 停用和删除的公告目标不再投递且重启不复活；重新启用不会补发停用期间的公告。
- T2I quality、模板、画布、文本和解码后的视觉内容不因直出而变化。

## 2. 范围与非目标

### 2.1 实施范围

- `src/infrastructure/rendering/` 的 T2I 结果契约、标准库图片检查器、artifact/sidecar 写入和临时文件生命周期。
- 玩家、百科、签到、帮助、公告、密函及其他 T2I-backed renderer 的输出适配。
- 渲染缓存、管理员预览、响应 DTO、离线渲染对比与维护清理工具的 JPEG/PNG 兼容。
- HTTP transport、图片下载器、公告轮询的共享并发门与 single-flight。
- `src/entry/` 命令文本提取、`CommandSpec` At 能力声明和目标身份传递。
- 用户可见登录提示、帮助资源和登录页面文案。
- 公告订阅存储、投递状态、聊天命令、Admin API、Web routes 与 Dashboard 状态机。
- 配置 schema、文档、回滚说明和相关测试。

### 2.2 明确不做

- 不降低现有 T2I JPEG quality（当前默认 85），不修改模板、画布、字体和业务内容。
- 不移除 Pillow 依赖；输入素材、二维码、legacy 纯 PIL 绘制和超长公告分页继续允许使用。
- 不并行公告列表分页、不同公告处理或不同群组推送，不重写公告 HTML 分页算法。
- 不新增固定超时、无依据重试上限、静默回退或请求条数上限。
- 不自动迁移旧 `announcement_groups`，不删除或改写其中的值，也不根据群号猜测 `unified_msg_origin`。
- 不在 Dashboard 手工创建公告目标，不允许修改 `type`、`unified_msg_origin`、`uid` 等目标身份。
- 不移除显式 UID 绑定、切换、删除、查看及 UID 隐私管理命令，不修改账号数据库模型。
- 不引入第三方依赖，不升级依赖或锁文件，不处理与本目标无关的既有失败或工作树改动。

## 3. 当前问题与根因

### 3.1 T2I 二次编码

`HtmlRenderer.render()` 当前返回 `bytes`，并在 `_coerce_result()` 中使用 Pillow 验证格式；各领域 renderer 又常将 JPEG bytes 交给 `Image.open(BytesIO(...)).convert("RGBA")`，最后保存为 PNG。该路径同时丢失原始媒体类型、扩大文件体积，并迫使缓存、临时文件和响应层假设 `.png`。

PNG `PngInfo` 还承载 `dnaby.text`、`dnaby.layout`、`dnaby.resources` 等测试/诊断元数据。直接 JPEG 后这些信息不能继续依赖图片内部 PNG chunk，必须迁移到结构化 artifact 和 sidecar。

### 3.2 公告串行请求与重复工作

公告预览图、二维码和正文图片互不依赖，却在同一渲染工作中串行获取；相同 URL 或公告详情的并发请求没有共享 in-flight 结果。定时循环、管理员立即轮询和其他调用者可能同时进入 `poll_ann_now()`，从而重复抓取甚至重复推送。

### 3.3 命令文本与真实 At 分离

`target_user_from_event()` 已能从 AstrBot 消息链读取最后一个有效 `At`，但动态 RegexFilter 与 handler 的命令匹配仍可能使用包含框架占位或缺少纯文本重组的输入。At 在命令前后时，过滤器与 handler 可能看到不同文本。与此同时，若统一把 At 目标传入所有 use case，会让签到、刷新、订阅和账号管理等写操作出现代执行风险。

### 3.4 公告目标双事实源

`SubscriptionStore` 已持久化 `unified_msg_origin`，但 bootstrap 仍会把 `notifications.announcement_groups` 与订阅互相同步。配置只知道群号，无法完整表达平台、Bot 和会话路由；因此自动构造 origin 既不安全，也让用户通过命令建立的目标在插件配置中固化并可能被重建。

## 4. 图片 artifact 与无 Pillow 检查

### 4.1 `RenderedArtifact`

在 `src/infrastructure/rendering/` 新增不可变值对象：

```python
@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    data: bytes
    media_type: Literal["image/jpeg", "image/png"]
    suffix: Literal[".jpg", ".png"]
    width: int
    height: int
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)
```

约束：

- `data` 必须非空并通过对应格式检查；`width`、`height` 必须来自图片结构而非调用方猜测。
- `media_type`、`suffix` 和实际 bytes 必须一致。
- `metadata` 只保存 JSON 可序列化诊断信息，不包含 Cookie、token、登录凭据或本地敏感路径。
- `HtmlRenderer.render()` 返回 `RenderedArtifact`；领域层可在不改动 bytes 的情况下追加业务 metadata。
- 纯 PIL 路径也包装为 artifact，但不改变其现有 PNG/JPEG 输出行为。

### 4.2 标准库检查器

常规 T2I 输出不得调用 Pillow。检查器只使用标准库和二进制结构：

- PNG：验证 8-byte signature；按边界遍历 chunk；要求首个有效 `IHDR` 长度为 13；读取正整数宽高；验证 chunk 长度不越界；要求完整 `IEND`；拒绝尾部截断和明显格式错配。
- JPEG：要求 SOI；遍历 marker 和 segment length；从支持的 SOF marker 提取正整数宽高；正确处理无长度 marker 和 scan data；要求 EOI；拒绝截断、非法 segment 长度、无 SOF 和格式错配。
- 在格式检查前识别空 bytes、可读 HTML/JSON 错误页等明显非图片结果，并抛 `RenderResultError`。
- 检查器不做像素解码；像素级视觉验证只在测试/验收工具中使用 Pillow，不能回流到生产热路径。

### 4.3 原始 bytes 与 sidecar

artifact 文件与相邻 sidecar 采用配对形式，例如：

```text
<stem>.jpg
<stem>.jpg.json
```

sidecar 至少包含：

```json
{
  "schema_version": 1,
  "media_type": "image/jpeg",
  "suffix": ".jpg",
  "width": 1200,
  "height": 1600,
  "sha256": "...",
  "metadata": {
    "dnaby.text": "...",
    "dnaby.layout": {},
    "dnaby.resources": {}
  }
}
```

写入规则：

1. 在目标受控目录内分别写临时文件并完成 flush/close。
2. 原子替换最终图片与 sidecar；正常成功路径的最终图片 bytes 必须与 artifact `data` 完全一致。
3. 任一步失败时清理本次部分文件并传播真实异常；不得留下“图片成功、sidecar 假成功”的返回值。
4. 响应只发送图片文件；生命周期跟踪、租约和维护清理必须把 sidecar 作为配对文件处理。
5. 缓存 validator 从真实媒体类型、后缀、结构和 sidecar 校验完整性；旧 PNG 缓存不原地改写，失配时按 cache miss 安全重建。

`ImageResponse` 可以继续以本地路径作为发送载荷，但其调用者与 Admin Preview 不再假设 `.png`；需要返回 HTTP 内容时必须根据 artifact/sidecar 使用真实 MIME。

### 4.4 公告分页例外

未超过 `ANN_PAGE_LIMIT=6000` 的公告详情直接写入并发送 T2I artifact。只有检查器得到的高度严格大于 6000 时，才允许隔离的分页函数使用 Pillow 解码和裁剪：

- 页面顺序、宽度和合计内容高度必须完整；不得因分页裁掉合法内容。
- 输出 JPEG quality 沿用触发该渲染的 `RenderSpec`，不擅自降低质量。
- 分页失败不写成功缓存，不更新已投递状态，调用方可在下一轮重试。

## 5. 请求并发与 single-flight

### 5.1 配置与实例边界

`NetworkSettings` 新增：

```python
max_concurrent_requests: int = Field(
    default=4,
    ge=1,
    description="短生命周期外部请求的全局最大并发数",
)
```

不设置无依据固定最大值。bootstrap 为插件进程创建一个 `RequestConcurrencyGate` 单例，并注入 HTTP transports、图片/二维码 fetcher 和公告服务。测试可显式注入独立 gate。

### 5.2 `RequestConcurrencyGate` 契约

建议公共接口：

```python
class RequestConcurrencyGate:
    async def run(
        self,
        operation: Callable[[], Awaitable[T]],
        *,
        key: Hashable | None = None,
    ) -> T: ...
```

语义：

- `key is None`：调用者通过共享 Semaphore 执行一次远程 I/O。
- `key is not None`：同 key 调用者等待同一个 in-flight task；底层工作只执行一次。
- Semaphore 只覆盖真实网络 await，不覆盖缓存读取、JSON store 锁、模板渲染或本地图片处理。
- 成功、异常和取消都必须释放槽位；完成的 in-flight 条目及时删除，失败不得永久缓存。
- 所有等待者获得同一真实结果或异常；某个等待者取消不得错误取消仍被其他等待者需要的共享底层工作。
- 长生命周期 WebSocket/SSE 不得在整个连接期间占用短请求槽；只在建立连接所需的短 I/O 边界使用或完全排除。

single-flight key 至少覆盖：

- 标准化源图片 URL；
- 二维码 URL + 目标尺寸；
- 公告详情 `post_id`；
- 公告轮询固定 operation key。

### 5.3 公告内部并行边界

单张公告卡片内，预览图、二维码和正文图片在依赖数据齐备后用 `asyncio.gather()` 或等价结构并行；它们仍通过全局 gate，因此不会突破上限。以下工作保持串行：

- 公告列表翻页；
- 不同公告的详情处理；
- 不同订阅目标的推送；
- 投递状态更新。

`NoticesService.poll_ann_now()` 使用 operation single-flight。两个并发调用者共享同一轮询结果，不能各自重复发送。

## 6. At 查询与命令能力模型

### 6.1 统一命令文本

在事件入口新增：

```python
def command_text_from_event(event: Any) -> str:
    """按消息链顺序拼接 Plain 文本，忽略 At/AtAll/Reply/Image 等非命令组件。"""
```

动态 RegexFilter 与实际 handler 必须调用同一函数，并在 handler 内继续执行既有 `re.match` 门禁。前置/后置 At 均不改变命令文字；字面文本 `@123` 不得被当成真实目标。

当事件 fixture 或平台只公开既有纯文本方法、没有可迭代消息链时，函数使用项目已有公开文本接口；不得通过私有字段猜测。无命令文本时返回空字符串，让正则自然不匹配。

### 6.2 `mention_policy`

`CommandSpec` 新增：

```python
MentionPolicy = Literal["ignore", "query", "admin_target"]
mention_policy: MentionPolicy = "ignore"
```

- `ignore`：不向 use case 传递 At 目标。签到执行、刷新、订阅、账号登录/绑定管理等写操作必须使用该策略。
- `query`：读取最后一个有效真实 At，过滤 AtAll、空目标和 Bot 自身；传入 `CommandRequest.target_user_id`，继续由领域 `PrivacyService` 决定是否允许查询。
- `admin_target`：仅用于既有管理员指定用户隐私管理命令，保留其权限和审计语义。

只读 `query` 命令矩阵至少包括：

- 玩家总览/基本卡片；
- 角色详情和伤害面板；
- 便笺/体力；
- 本周周报、上周周报；
- 签到日历；
- 密函查询。

全局资料类命令若业务上不依赖用户身份，保持 `ignore`。多个有效 At 延续现有“最后一个有效 At”规则。入口只提取目标，不得绕过隐私解析、凭据选择或 UID 解析。

### 6.3 文案边界

用户没有可用登录凭据、查询无法继续时，`src/modules/*/messages.py`、legacy 统一消息文件、帮助资源和登录页面中的误导文案从“请绑定 UID”改为“请登录”或语义等价文本。

以下场景继续使用 UID 术语：

- 显式绑定/切换/删除/查看 UID；
- UID 数量限制；
- UID 隐私设置；
- 已登录用户对游戏 UID 的管理说明。

handler 不硬编码文案；代码 registry 是命令事实源，修改后重新生成并校验 `commands.json`。

## 7. 公告订阅唯一事实源与 Dashboard 状态机

### 7.1 数据模型

`Subscription` 新增向后兼容字段：

```python
enabled: bool = True
```

加载旧 JSON 时缺失字段按 `True`；保存时显式写出。公告投递只读取 `type == "ann"` 且 `enabled is True` 的目标。其他订阅类型保持现有行为，除非共享 API 明确读取该字段。

目标身份由 `(type, unified_msg_origin, uid)` 决定。Dashboard 不得修改这些字段，也不得通过 `group_id`、`bot_id` 猜测或移动 origin。

### 7.2 配置弃用

`notifications.announcement_groups` 在本版本中：

- schema 中标记弃用/只供人工迁移参考；
- bootstrap 不再从它创建订阅，也不再把订阅写回配置；
- 不自动删除、清空或改写原值；
- 若检测到非空值，仅记录不包含具体群号/值的安全警告，说明配置已被忽略；
- 文档提供人工方式：在真实群聊中执行公告订阅命令，让 AstrBot 产生正确 `unified_msg_origin`。

### 7.3 `AnnouncementTargetService`

新增领域协调服务，统一供聊天命令和 Admin API 使用：

```python
class AnnouncementTargetService:
    async def subscribe(self, actor: EventActor) -> TargetMutationResult: ...
    async def unsubscribe(self, target_id: str) -> TargetMutationResult: ...
    async def disable(self, target_id: str) -> TargetMutationResult: ...
    async def enable(self, target_id: str) -> TargetMutationResult: ...
    async def delete(self, target_id: str) -> TargetMutationResult: ...
```

`TargetMutationResult` 必须区分：完全成功、未找到、校验失败、状态已应用但投递基线清理失败等部分完成结果，不得把异常伪装成无数据。

状态顺序：

- **停用**：先持久化 `enabled=False`，保证后续轮询立即不再发送；随后清理/更新相关投递状态。清理失败时目标保持禁用并返回部分完成。
- **启用**：先以当前已知公告建立“只接收未来公告”的投递基线；基线建立失败则保持禁用；成功后再写 `enabled=True`。
- **删除**：先从订阅事实源删除，使后续轮询不再发送；投递状态清理失败时保持已删除并返回部分完成。
- **聊天取消订阅**：复用同一 service，不直接操作 store，避免 Dashboard 和命令产生不同状态机。

不得在 `SubscriptionStore` 文件锁内执行网络、渲染、消息发送或投递状态清理。store 锁只保护内存列表和原子落盘。

### 7.4 Admin API 与 Dashboard

现有 `TaskTarget` / `TaskTargetUpdate` 和 Web routes 扩展为公告目标管理契约：

- 列表返回稳定 `target_id`、显示信息、`enabled`、可用操作和必要的部分状态；不返回敏感凭据。
- 更新只允许公告目标启用/停用及现有安全显示字段；拒绝 `type`、origin、uid 身份变更。
- 删除必须调用 `AnnouncementTargetService.delete()`。
- 不能通过 API 手工创建公告目标；不存在或非公告目标返回明确 `NOT_FOUND`/`VALIDATION`。
- 沿用 Dashboard 管理员鉴权、受控路径和结构化错误，不新增插件内密码。

Dashboard UI：

- 显示目标状态和来源信息；提供启用/停用按钮、删除确认、busy、error 和 partial-completion 提示。
- 操作期间禁用重复提交，完成后重新拉取权威列表。
- 不显示创建按钮，不提供 origin/type/uid 编辑控件。
- 按钮具备可访问名称、键盘操作和明确 focus 状态；桌面/移动布局均不遮挡关键操作。

## 8. 失败语义、并发安全与可观测性

- T2I 返回空 bytes、HTML/JSON 错误页、损坏图片或格式不匹配时抛 `RenderResultError`；不写缓存、不发送、不更新投递状态。
- 模板错误继续使用 `TemplateRenderError`，T2I 调用失败继续使用 `T2IRenderError`，不得 broad catch 后返回空结果。
- sidecar/图片原子写失败传播真实异常并清理本次部分文件；维护任务清理孤儿配对。
- single-flight 失败后删除 in-flight 项，后续调用可重试；取消和异常必须释放 Semaphore。
- 公告可选二维码继续遵循现有可选语义；公告正文图片失败不得静默丢失内容块；preview strict/non-strict 行为保持现状并由测试固定。
- 日志记录 operation/key 类型、耗时、bytes、媒体类型和并发状态，但不记录完整 URL 查询凭据、Cookie、token、公告群号配置值或本地敏感路径。
- 不新增无依据固定超时或重试次数；沿用真实 transport/平台已有客观限制。

## 9. TDD 与验证计划

所有实现任务遵循 Red → Green → Refactor。Red 阶段必须实际运行并证明失败由当前缺失行为导致；无法构造真实 Red 时记录阻塞，不得先实现后补测试。

### 9.1 图片契约

- JPEG/PNG 最小正常 fixture 和损坏矩阵：空、HTML、错签名、截断、非法长度、缺少尺寸、缺少结束 marker/chunk、格式与 `RenderSpec` 不一致。
- monkeypatch `PIL.Image.open/save` 为失败，证明常规 artifact 构造和落盘不调用 Pillow。
- 写入后比较最终 bytes、长度和 SHA256 与 T2I 原始结果完全一致。
- JPEG/PNG 缓存 fresh/stale/refresh、Admin Preview、ResponseFactory、临时文件和 sidecar 配对清理。
- 代表性旧 PNG 与新 JPEG 解码后的尺寸、模板文本和视觉对比；视觉工具允许使用 Pillow，但生产链路不允许。
- 超长公告在 `<=6000` 不分页，`>6000` 才分页；验证页宽、顺序、总高度和内容完整。

### 9.2 并发契约

- 使用事件/barrier 记录活动请求数，确定性证明最大值不超过配置，不用固定 sleep 作为断言。
- 同 key 多调用底层计数为 1；成功、异常、一个等待者取消、底层取消后的清理均覆盖。
- 同一卡片依赖并行，但不同公告和目标投递仍串行。
- 两个并发 `poll_ann_now()` 只抓取和推送一次，并向等待者返回一致结果/异常。

### 9.3 At、权限和文案

- 真实 AstrBot `Plain + At` / `At + Plain` 组件通过动态 filter 和 handler 双层匹配。
- 多 At、AtAll、Bot 自身、字面 `@123`、无消息链 fallback。
- 每个 `query` 命令把目标传给领域隐私解析；拒绝时保持现有隐私提示。
- 每个写命令带 At 后仍只作用于 actor 或按原规则拒绝，不能代目标签到、刷新、订阅或管理账号。
- registry、`commands.json`、帮助与用户可见消息扫描，区分应改的登录提示和应保留的 UID 管理术语。

### 9.4 公告状态机与浏览器

- 旧 JSON 缺少 `enabled` 的加载兼容；disabled/re-enabled/deleted 跨重启。
- 命令创建 → Dashboard 停用 → 轮询不发 → 启用不补旧 → 未来公告发送 → 删除不复活。
- 停用、启用基线和删除清理失败的部分完成语义；多个群仅失败群保持可重试。
- 配置非空时不会创建/写回订阅，日志不泄漏群号。
- Admin 鉴权、输入校验、禁止创建/移动身份、重复点击和陈旧状态刷新。
- 使用浏览器实际打开 Dashboard，验证桌面/移动布局、键盘语义、确认框、busy/error/partial 状态、网络响应和控制台无新增错误，并保存截图证据。
- 可用时在 AstrBot/OneBot 运行时执行前置/后置 At 查询与公告目标管理冒烟；环境不可用时精确记录阻塞，不伪造成功。

### 9.5 质量门禁

验证顺序为：最小目标测试 → 相关集成测试 → LSP/Pyright → `ruff check .` → `python3 -m compileall .` → `python3 -m pytest` → 浏览器/运行时冒烟 → staged diff 与工作树隔离审计。

## 10. 实施顺序与迁移策略

实施按 `goal-4/tasks.md` 的独立小提交推进：

1. artifact/检查器、原始写入和共享响应/缓存契约；
2. 各领域 T2I renderer 与公告分页；
3. 并发门、single-flight 和公告内部并行；
4. 命令文本、mention policy 和登录文案；
5. 公告订阅模型、领域状态机、Admin API 与 Dashboard；
6. 跨模块集成、真实渲染/浏览器证据、文档和候选发布门禁。

旧缓存不做原地批量迁移：新 validator 将不兼容项目视为 miss，按正常请求安全重建。旧 `announcement_groups` 不自动迁移；管理员需在真实目标群重新执行订阅命令，以获得正确平台/Bot origin。

## 11. 回滚方案

- **渲染**：保留 `RenderSpec` 与领域返回边界；可按 renderer 逆序回滚到旧 Pillow writer，不影响 transport 和业务数据。直出 artifact/sidecar commit 独立，便于定位回退。
- **并发**：将 `max_concurrent_requests` 设为 1 可关闭并行效果；single-flight 可独立回滚，不修改缓存数据格式。
- **订阅**：`enabled` 默认 `True` 保证新版本读旧文件。回滚到无法接受额外 JSON 字段的旧代码前，必须使用专用、可审阅迁移脚本删除 `enabled`，不得手工批量修改生产文件。
- **Dashboard**：前端回滚不会删除订阅；后端回滚前先确认旧版本对 `enabled` 的读取行为。
- **配置**：旧 `announcement_groups` 原值始终保留，可供人工参考；新版本不自动导入，因此回滚无需恢复被改写的配置。
- **Git**：每个任务只提交其拥有文件，按 task commit 逆序 revert；禁止 `reset --hard`、force push 或混入初始化前工作树改动。

## 12. 默认假设与开放验证项

- AstrBot/OneBot 可直接发送 `.jpg` 本地路径；该假设必须在响应测试和可用运行时中验证。
- 当前 T2I 对 `RenderSpec(image_format="jpeg")` 返回合法 JPEG，对 PNG 返回合法 PNG；格式错配会显式失败而不是自动转换。
- `ANN_PAGE_LIMIT=6000` 是既有兼容边界，本目标不调整数值。
- 现有 Dashboard Page、bridge 和管理员鉴权可继续承载目标管理 UI，不新增构建链。
- 真实 T2I、AstrBot 或 OneBot 环境若不可用，只能记录环境阻塞并提供离线确定性证据，不能把模拟结果表述为真实验收。

## 13. 审查补充：并发一致性、来源不变量与发布恢复

### 13.1 公告目标 mutation 与轮询的线性化协议

`poll_ann_now()` 的 operation single-flight 只负责合并同一轮轮询，不能单独解决目标状态变化与投递之间的竞态。实现必须使用每目标的进程内 mutation lock（锁键为 `(type, unified_msg_origin, uid)`），并遵循以下线性化点：

1. 轮询获取目标快照后，在每个目标实际发送前获取该目标 lock，并重新从 `SubscriptionStore` 读取目标；只有仍存在且 `enabled=True` 的目标才能发送。
2. 停用先获取同一目标 lock，再持久化 `enabled=False`；锁释放后才允许新的轮询快照继续使用该目标。已经在发送中的单次发送以获取 lock 的时刻线性化，发送完成后不再发送下一条；实现不得在停用成功后开始新的发送。
3. 删除与停用使用相同 lock；删除从事实源移除后，后续发送重新校验必然跳过。删除操作不依赖猜测 target id，且删除成功的目标不能被轮询重新写入。
4. 启用先获取 lock，在锁内以当前已知公告 ID 写入投递基线，再持久化 `enabled=True`，然后释放锁。基线建立失败时保持 `enabled=False`。轮询只能在锁释放后读取到 enabled 目标，因此不会补发基线以前的公告。
5. 投递状态 claim/update 也必须在该目标 lock 的协调范围内；不得把网络发送、渲染或 JSON store 文件锁放进同一个文件锁，但允许目标 lock 保护“重新读取—发送资格判断—投递状态 claim”的进程内临界区边界。若发送必须释放 lock，则发送前必须有不可撤销的 claim，并由状态 store 保证停用/删除后不会继续 claim；实现需通过确定性竞态测试证明。

跨进程部署不在本目标范围内；若 AstrBot 启动多个插件进程，必须在文档中记录单进程锁的边界，不得宣称跨进程 exactly-once。

### 13.2 “真实群聊命令发现”来源不变量

公告目标的唯一创建入口是带真实 `EventActor` 的群聊订阅命令。该命令必须从当前事件取得非空 `unified_msg_origin`、`group_id` 和平台/Bot 作用域，并调用 `AnnouncementTargetService.subscribe()`；Dashboard/Admin API、配置加载、普通 `SubscriptionStore.add()` 和测试 fixture 不得创建新的 `type="ann"` 目标。

为使来源可验证，`Subscription` 增加向后兼容字段：

```python
provenance: Literal["chat_command"] = "chat_command"
```

只允许 `AnnouncementTargetService.subscribe()` 构造公告订阅并写入 `provenance="chat_command"`；store 的通用 add 接口不得接受公告类型，或在公告类型输入时显式拒绝。加载缺失 provenance 的历史公告记录时不猜测其来源：Admin API/Dashboard 将其标记为 `unverified`、禁止启停和删除，并返回需要人工在真实群聊重新订阅的明确提示；轮询也不将其作为新发现目标发送。新字段的默认值只适用于非公告订阅，不得把旧公告静默升级为已验证来源。

`TaskTarget` 增加只读 `provenance`/`managed` 状态。API 测试必须证明：

- 真实群聊命令可以创建并列出 `managed=True` 目标；
- API 没有创建 endpoint；
- 伪造 target id、手工写入缺少/错误 provenance 的 JSON、配置中的群号都不能产生可管理公告目标；
- 身份字段 `(type, unified_msg_origin, uid)` 和 provenance 均不可通过更新接口修改。

### 13.3 图片与 sidecar 的配对发布及恢复

两个独立文件不能通过两次 `replace()` 获得跨文件原子性。实现采用“临时 pair 目录 + 目录 rename/版本目录”或等价的可恢复发布协议：

1. 图片临时文件与 sidecar 临时文件写入同一临时 pair 目录，完成 flush/close，并校验 sidecar 的 `sha256` 与图片 bytes 一致。
2. 将 pair 目录发布为不可复用的版本目录，当前 artifact 通过一个原子 manifest/pointer 或目录 rename 指向同一 pair；发送路径只解析已发布且完整的 pair。
3. 进程崩溃或发布中断时，启动/维护扫描删除未发布临时 pair；validator 发现图片与 sidecar 的 SHA、媒体类型、后缀或尺寸不一致时将整个 pair 视为 cache miss，隔离或删除不完整 pair 后重建，不发送旧/新混合结果。
4. 若受现有缓存目录约束必须保留平面文件，则必须使用唯一版本 stem，并以 manifest 作为唯一入口；任何没有有效 manifest 的图片/sidecar 都是孤儿，不得直接作为 fresh cache。

对应测试覆盖：图片成功/sidecar 失败、发布中断模拟、旧 pair 与新 pair 并存、validator 不匹配、孤儿配对清理，以及恢复后不会发送混合 bytes。

### 13.4 常规 T2I 全链路 Pillow 隔离证据

Task 02/03 的 artifact 单测不能替代领域链路验收。Task 04–09 必须对每个普通 T2I-backed renderer/use case（玩家、角色详情/伤害、百科/便笺/周报、签到、帮助/二维码、公告/密函）运行可完成的最小完整链路，并在测试边界 monkeypatch `PIL.Image.open` 与 `PIL.Image.save` 为失败。测试必须证明：

- 常规 T2I JPEG/PNG 路径成功且最终 bytes 不变；
- 输入素材、二维码、legacy 纯 PIL 绘制和公告 `height > 6000` 分页例外通过独立 fixture/测试标记隔离；
- 普通 use case 没有间接进入上述 Pillow 例外；
- 视觉对比测试可以使用 Pillow，但只能运行在测试/离线验收工具，不能被生产 renderer 调用。

### 13.5 轮询与 transport 的结果错误模型

公告轮询结果必须区分“成功推送 0 条”和“轮询失败”。建议返回结构化 `PollResult`：

```python
@dataclass(frozen=True, slots=True)
class PollResult:
    delivered: int
    discovered: int
    skipped: int
    failed: tuple[PollFailure, ...]
```

列表请求失败属于轮询失败并保留真实异常/失败项，不返回无上下文的 `0`；单公告详情或渲染失败只影响该公告并进入 `failed`，其他公告继续按既有串行顺序处理；单目标发送失败保留失败目标以便下一轮重试，并不得更新其成功投递状态。scheduler、立即轮询 API 和测试必须依据 `failed` 区分告警与“无新公告”。

### 13.6 全局 gate 覆盖清单

`RequestConcurrencyGate` 的单例必须覆盖所有短生命周期外部 I/O：

- 账号登录/短信/玩家、角色和百科 API；
- 签到 API、公告/密函 API；
- 头像、公告正文图片、二维码及其他素材下载；
- 成员探测和 Admin API 触发的短网络操作；
- 资源 manifest/Git 同步所需的短请求（长连接或持续流不占用槽位）。

排除项只有本规格明确的长生命周期 WebSocket/SSE 持有阶段；其建立握手若为短 I/O，按项目 transport 契约决定是否进入 gate，但不能绕过并发上限。bootstrap wiring 测试要枚举这些 transport 实例并证明都引用同一个 gate；未接入的新增 transport 必须使测试或审查失败，而不是被默认视为覆盖。

### 13.7 DTO 与 sidecar 的响应边界

`ImageResponse.image` 继续只承载可发送的本地图片路径；artifact 的 `media_type`、尺寸和 sidecar 路径由 `RenderedFileStore`/temporary lease 内部关联，不把 metadata 注入消息链。`ResponseFactory` 在注册 temporary image 时同时注册 pair；缓存图片不交给事件清理。Admin Preview 通过 artifact/sidecar resolver 读取真实 MIME、尺寸和 bytes，禁止按 `.png` 猜测；sidecar 缺失或校验失败返回结构化错误，不发送图片。
