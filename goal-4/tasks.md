# Goal 4 Tasks

> 每轮只执行第一个未完成项。普通 task 必须 TDD；每三个普通 task 后执行一次集中检查-debug。所有提交只暂存本 task 拥有的文件，禁止混入初始化前的用户改动。

## Task 01 — 固化设计规格与规格审查 `[completed]`

**目标**：将已批准设计写入 specs 文档，使用只读 spec reviewer 最多三轮审查并提交独立文档 commit。

**验收**：规格覆盖目标、非目标、类型/API、失败语义、TDD、浏览器验证和回滚；提交不包含初始化前既有修改。

- 实际完成：新增 `docs/superpowers/specs/2026-09-01-dnaby-t2i-concurrency-mentions-announcements-design.md`，固化 T2I 直出、Pillow 例外、artifact/sidecar、全局并发/single-flight、At mention policy、登录文案、公告目标事实源和 Dashboard 状态机。只读审查发现并补充了轮询与目标 mutation 的 per-target 锁/重新校验线性化协议、真实群聊命令 provenance 不变量、pair 发布恢复模型、全链路 Pillow 隔离、PollResult 错误模型、transport 覆盖清单与响应边界。
- 验证证据：规格 reviewer（Sagan）完成一轮审查；审查提出的 P0/P1/P2 缺口已逐项写入规格第 13 节；`wc -l` 确认文档 490 行，未修改业务代码。
- 剩余风险：尚未提交；当前工作树包含初始化前既有修改和其他 goal 未跟踪文件，提交时必须只暂存本规格。
- 下一步：Task 02：先写并运行 RenderedArtifact/标准库 JPEG/PNG 检查器的 Red 测试。

## Task 02 — RenderedArtifact 与无 Pillow 图片检查器 `[completed]`

**目标**：测试先行新增 JPEG/PNG 结构校验、尺寸提取和 `RenderedArtifact`，拒绝 HTML、截断和格式不匹配结果。

**验收**：常规 artifact 构造不调用 Pillow；JPEG/PNG 正常及损坏 fixture 均有 Red/Green 证据；无新依赖。

- 实际完成：新增 `image_inspector.py`，使用标准库解析 PNG signature/chunk/CRC/IHDR/IEND 与 JPEG marker/SOF/EOI，提取媒体类型、后缀和尺寸；新增不可变 `RenderedArtifact.from_bytes()`，保留输入 bytes 身份并拒绝空、截断、HTML、损坏和格式不匹配结果；从 infrastructure/facade 导出 artifact。新增 Task 02 单测，并以 Pillow writer/open monkeypatch 证明检查器不依赖 Pillow。
- 验证证据：Red 阶段先运行 `.venv/bin/python -m pytest -q tests/test_goal4_task02_artifact.py`，因缺少待实现的 `artifact` 模块收集失败；Green 阶段 `25 passed`（Task 02 + `test_html_renderer.py` + `test_rendering_assets.py`）；`ruff check` 目标文件通过；`python3 -m compileall -q` 通过；LSP diagnostics 对 `image_inspector.py` 返回无错误。
- 剩余风险：`HtmlRenderer` 及各领域 renderer 尚未切换到 `RenderedArtifact`，本 task 只建立契约；T2I 热路径迁移由后续 Task 03–09 完成。当前工作树的初始化前改动和其他 goal 文件未纳入本次提交。
- 下一步：Task 03：先写原始 bytes/sidecar 原子写入、缓存 validator、ImageResponse 与 Admin Preview 的 Red 测试。

## Task 03 — 原始 bytes 写入、sidecar、缓存与响应格式契约 `[completed]`

**目标**：测试先行实现原子 artifact/sidecar 写入，泛化缓存 validator、临时文件、ImageResponse 和 Admin Preview 的 MIME/后缀处理。

**验收**：最终文件与 T2I bytes/SHA 完全一致；JPEG/PNG 均可缓存和发送；配对清理覆盖 sidecar；不破坏受控路径安全检查。

- 实际完成：新增 `artifact_store.py`，以受控目录内临时文件 + 原子替换写入原始图片和配对 JSON sidecar，记录真实 MIME、后缀、尺寸、SHA256 与 metadata；新增读取 validator 和可注入 `CacheManager` 的 `artifact_validator()`；`ImageResponse` 增加 sidecar 关联，`ResponseFactory` 同步登记图片/sidecar 租约；`RenderedFileStore.cleanup()` 按 pair 清理并避免 sidecar 重复计数。
- 验证证据：Red 阶段 `.venv/bin/python -m pytest -q tests/test_goal4_task03_artifact_store.py` 因缺少 `artifact_store` 模块收集失败；Green 阶段 Task 03 测试 `5 passed`；结合 `test_generated_image_lifecycle.py`、`test_html_renderer.py` 为 `15 passed`；目标文件 `ruff check` 通过；`compileall` 通过；LSP 已对 `image_inspector.py` 无诊断，响应/存储待本轮继续诊断核验。
- 剩余风险：双文件发布已具备临时写入和失败清理，但尚未接入所有 renderer 的 T2I 热路径；当前 pair 仍为两个文件替换，完整版本 manifest 发布由后续缓存迁移/渲染任务继续收口。当前工作树初始化前改动和其他 goal 文件未纳入提交。
- 下一步：集中检查 D01：复查规格、artifact 格式安全、sidecar 生命周期、缓存/响应边界、类型检查和 staged diff。

## 集中检查 D01 — Task 01–03 `[completed]`

**检查**：规格偏差、artifact 格式安全、路径/原子写、sidecar 生命周期、缓存租约、MIME 泄漏、类型检查、目标测试和 staged diff。发现问题追加修复 task。

- 实际检查：复核 Task 01–03 的规格、实现和提交边界。图片检查器能拒绝格式错误/截断结果；artifact 保留原始 bytes；缓存 validator 和 sidecar SHA 校验已覆盖；rendered 清理按图片+sidecar pair 计数。发现两项必须在进入领域 renderer 前收口的问题：`ResponseFactory` 的 `MultiImageResponse`/`ChainResponse` 尚未登记 sidecar；图片与 sidecar 仍是两个独立文件替换，尚未达到规格要求的可恢复 pair publication。另确认 `write_temporary_image()` 等旧调用仍是无 sidecar 原始路径，后续迁移必须明确兼容边界。
- 验证证据：目标与相关测试 `48 passed`（含 Task 02/03、renderer、cache、生命周期回归）；目标文件 `ruff check` 与 `compileall` 通过；Pyright `0 errors, 0 warnings, 0 informations`；staged diff 审计显示 Task 03 提交只包含 `goal-4/tasks.md` 及本 task 明确拥有的 6 个实现/测试文件，初始化前修改仍未暂存。一次 ruff/compileall 失败是命令工作目录拼写错误，已用正确 cwd 重跑通过。
- 新增修复 task：见下方 `Task 03-R1`（多图/链响应 sidecar 生命周期）和 `Task 03-R2`（可恢复 pair publication/validator），均置于 Task 04 之前。
- 剩余风险：T2I `HtmlRenderer` 和领域 renderer 尚未切换到 artifact；Task 03-R1/R2 未完成前，常规 T2I 直出还不能宣称完成。

## Task 03-R1 — 多图与链响应的 sidecar 生命周期收口 `[completed]`

**目标**：测试先行补齐 `ResponseFactory` 对 `MultiImageResponse`、`ChainResponse` 中临时图片及 sidecar 的配对校验、登记和租约清理。

**验收**：每个临时图片及其 sidecar 均登记一次；缺失/越界 sidecar 显式失败；既有无 sidecar `ImageResponse` 测试保持通过；不重复注册。

- 实际完成：抽取 `ResponseFactory._track_one_temporary_image()`，统一处理单图、多图和链响应中的临时图片；sidecar 存在时执行同一受控根目录校验、事件追踪和 `RenderedFileStore` 租约登记；将 `ImageResponse.sidecar` 放到已有字段之后，避免破坏旧 positional 构造。
- 验证证据：Red 阶段新增复合响应测试并确认仅登记图片、缺少 sidecar；Green 阶段 `tests/test_goal4_task03_artifact_store.py` 为 `9 passed`，结合 `test_entry_skeleton.py`、`test_generated_image_lifecycle.py`、`test_html_renderer.py`、`test_cache_manager.py` 为 `46 passed`；目标 ruff 与 compileall 通过；LSP diagnostics 对 `response.py`、`artifact_store.py`、`temporary.py` 均无错误。
- 剩余风险：pair publication 仍由 Task 03-R2 收口；旧的 `write_temporary_image()` 调用尚未自动生成 sidecar，后续 renderer 迁移需显式选择 artifact store。
- 下一步：Task 03-R2：先写可恢复 pair publication、混合 pair、崩溃恢复和缓存/清理一致性的 Red 测试。

## Task 03-R2 — 可恢复 pair publication 与缓存/清理一致性 `[completed]`

**目标**：测试先行将图片+sidecar 发布收口为 manifest/pointer 或等价可恢复 pair 协议，覆盖发布中断、混合 pair、孤儿 pair 和缓存 validator。

**验收**：发送/缓存只解析完整 pair；任一文件失败不会暴露半发布 pair；崩溃恢复可清理临时 pair；旧缓存安全 miss；图片 bytes/SHA 保持一致。

- 实际完成：以受控目录临时文件写入图片、sidecar 和 manifest，并按 image → sidecar → manifest 顺序替换；读取时要求 manifest、sidecar、image 三者完整且名称/sidecar SHA/图片 bytes/SHA 一致，拒绝缺失、混合或半发布 pair；`ImageResponse`、复合响应和 `ResponseFactory` 追踪 manifest；`RenderedFileStore.cleanup()` 将三者作为一个逻辑 pair 清理，覆盖孤儿 manifest/sidecar。
- 验证证据：Red 阶段先确认缺少 manifest 字段和发布清单校验会失败；Green 阶段新增发布中断、缺失 manifest、混合 pair、孤儿 pair 测试，目标测试 `13 passed`，结合相关入口/生命周期/renderer/cache 回归为 `50 passed`；`ruff check`、`compileall`、Pyright 均通过；LSP diagnostics 对变更文件无错误。
- 剩余风险：当前仍是受控平铺目录下的 manifest-gated 三文件发布，不是目录级 rename；旧的 `write_temporary_image()` 无 sidecar 调用仍保持兼容，尚未接入所有领域 renderer 的 T2I 热路径，后续迁移需显式使用 artifact store。
- 下一步：Task 04：先写玩家卡片 T2I 直出 Red 测试。

## Task 04 — 玩家卡片 T2I 直出 `[completed]`

**目标**：测试先行迁移玩家概览和角色详情，移除 T2I JPEG→PIL RGBA→PNG，保留布局/resources/original_image_path/cache 语义。

**验收**：玩家最终 `.jpg` 与 T2I bytes 一致；缓存 fresh/stale/refresh 和管理员预览通过；解码视觉与旧转换结果一致。

- 实际完成：玩家概览和角色详情不再将 T2I bytes 通过 `Image.open().convert("RGBA")` 和 PNG writer 重编码；使用 `RenderedArtifact` + manifest/sidecar 以原始 JPEG bytes 发布，保留文字、布局、资源、原图路径和 incomplete 语义；`PlayerCache` 改为 JPEG/PNG 结构校验，并以实际媒体类型重建缓存响应 pair；`PlayerService` 和 Admin Preview 传播媒体类型及 sidecar/manifest，管理预览清理完整 pair。
- 验证证据：新增 `tests/test_goal4_task04_player_t2i.py`，以 Pillow `Image.open` 失败注入证明概览/详情常规路径仍直出，且落盘 bytes 与 T2I bytes 完全一致；覆盖缓存 JPEG 后缀/bytes 和 Admin Preview pair 清理。目标与相关测试 `55 passed`；代表性真实玩家概览/详情渲染 `2 passed`；`ruff check`、`compileall`、Pyright 源码检查和 LSP diagnostics 均通过。
- 剩余风险：玩家模板内部的素材预处理仍按既有约束使用 Pillow；`HtmlRenderer` 的统一结果检查和其他百科/签到/公告 renderer 仍待后续 Task 05–09 迁移，不能据此宣称全链路 T2I 完成。旧的无 sidecar renderer fixture 保留兼容验证，生产新路径使用完整 artifact pair。
- 下一步：Task 05：先写百科、便笺与周报 T2I 直出 Red 测试。

## Task 05 — 百科、便笺与周报 T2I 直出 `[completed]`

**目标**：测试先行迁移百科域内所有 T2I-backed 卡片，包括体力、周报、日历等，保留纯资源图片直返行为。

**验收**：T2I JPEG/PNG 不再二次编码；尺寸、文本、资源状态和现有缓存/响应契约通过。

- 实际完成：`EncyclopediaRenderer` 的便笺、周报、活动日历改为以原始 T2I bytes 构造 `RenderedArtifact`，使用 sidecar/manifest 保存文本、布局和资源状态；服务响应同步携带配对文件。日历保留旧 `draw_calendar_card` 的 Pillow 兼容返回，但生产 renderer 不再经过该兼容边界；wiki/guide 纯资源图片路径未改动。
- 验证证据：Red 测试先验证 `_write` 接收原始 bytes 会失败；Green 后 `tests/test_goal4_task05_encyclopedia_t2i.py` 通过；相关 `tests/test_encyclopedia.py` 通过（T2I 外部服务偶发失败时重跑通过）；ruff、compileall、Pyright（渲染器与服务）通过。
- 剩余风险：`HtmlRenderer._coerce_result` 仍用 Pillow 做容器校验；兼容旧 API 的 `draw_calendar_card` 仍会解码返回 Pillow 图像，生产百科 renderer 已绕开，统一结果校验将在后续集中检查处理。
- 下一步：Task 06：签到、帮助及其余 T2I 卡片直出。

## Task 06 — 签到、帮助及其余 T2I 卡片直出 `[completed]`

**目标**：测试先行迁移签到日历、签到报告、帮助/二维码等剩余 T2I 输出；纯 PIL 路径保持明确隔离。

**验收**：所有常规 T2I 输出不调用 Pillow writer；现有图片生命周期与消息链测试通过。

- 实际完成：签到日历改为使用原始 T2I JPEG bytes 构造并发布 `RenderedArtifact`，保存 sidecar/manifest；签到服务响应携带配对文件。帮助卡同样改为 artifact 发布，避免仅写孤立图片；签到报告和二维码本来就直接返回 T2I bytes，继续保留；奖励图/二维码矩阵等 PIL 或 qrcode 仅用于模板输入准备。
- 验证证据：新增 `tests/test_goal4_task06_checkin_t2i.py`，Red 阶段验证旧 PNG 落盘行为，Green 阶段验证签到和帮助原始 bytes、JPEG 后缀、sidecar/manifest；相关签到、帮助生命周期、HTML 卡片和二维码测试共 39 项通过；ruff、compileall、Pyright（签到渲染器、签到服务、帮助 use case）通过；LSP diagnostics 无错误。
- 剩余风险：`HtmlRenderer._coerce_result` 仍以 Pillow 做 T2I 容器校验但不重编码；该统一校验边界留待 D02/后续任务收口。
- 下一步：集中检查 D02：核对 Task 04–06 所有 T2I renderer、PNG 假设、sidecar 生命周期和遗漏路径。

## 集中检查 D02 — Task 04–06 `[completed]`

**检查**：所有 T2I renderer 清单、遗漏的 PNG 假设、视觉/尺寸、缓存键、sidecar、临时文件清理、Admin Preview 和相关全域测试。发现问题追加修复 task。

- 实际检查：审计玩家、百科、签到和帮助的生产输出路径；确认玩家/百科/签到 renderer 均通过 `RenderedArtifact` 发布原始 bytes，缓存和服务响应沿用 sidecar/manifest；纯资源图片与模板输入素材的 Pillow 处理保持隔离；兼容旧 API 的 `draw_*` Pillow 返回边界明确，不被生产 service 使用。发现并修复统一 `HtmlRenderer._coerce_result` 仍用 Pillow 校验 T2I 容器的问题，改为标准库 JPEG/PNG inspector，同时保留格式不匹配和坏响应的显式错误。
- 验证证据：新增校验回归覆盖 `Image.open` 不被调用；`tests/test_html_renderer.py` 全部 10 项通过；Task 04–06 相关 artifact、玩家、百科、签到、帮助、二维码和生命周期测试通过；ruff、compileall、Pyright 通过；LSP diagnostics 无错误；静态 inventory 中剩余 Pillow 解码仅存在兼容旧 `draw_*` API、输入素材处理或明确的 WEBP/PIL 业务路径。
- 新增修复 task：无。
- 剩余风险：真实 T2I 视觉/体积证据仍需 Task 22；公告、并发、AT、订阅 Dashboard 尚未完成。

## Task 07 — 公告与密函直出及超长分页隔离 `[completed]`

**目标**：测试先行迁移密函、公告列表和公告详情；未超长直出，超过 6000px 才使用 Pillow JPEG 裁剪。

**验收**：普通详情 bytes 不变；分页仅在边界触发，页宽/总高度/顺序/内容完整，失败保持可重试状态。

- 实际完成：公告列表、公告详情和密函统一以 T2I 原始 JPEG/PNG bytes 发布 `RenderedArtifact`，写入 sidecar/manifest 并通过 service 响应携带配对文件；普通公告详情先用无 Pillow 的 JPEG 容器尺寸检查，`height <= 6000` 原样返回；超长详情才用 Pillow 按 6000px 裁剪，并以与 T2I 相同的 quality=85 编码 JPEG 分页。保留旧 PNG 缓存读取兼容，按实际容器后缀发布。
- 验证证据：新增 `tests/test_goal4_task07_notices_t2i.py`，覆盖普通 T2I bytes、artifact 配对和 service 响应；更新 `tests/test_html_announcement_detail.py` 覆盖 5999/6000 边界、普通路径不调用 `Image.open`、超长页宽/高度/顺序及 JPEG 格式。相关公告/密函、缓存、投递、图片生命周期回归共 50 项通过；ruff、compileall 通过；`pyright notices.py` 通过。
- 剩余风险：公告缓存键与旧命名仍保留 `_png` 兼容语义，旧缓存的系统性迁移与离线 compare/regenerate 留待 Task 08；真实服务端 T2I 视觉/体积对比留待 Task 22。
- 下一步：Task 08 适配缓存 manifest、离线对比/再生成与清理工具。

## Task 08 — 渲染缓存、离线对比与清理工具适配 `[completed]`

**目标**：更新公告/玩家等缓存 manifest、离线 compare/regenerate 脚本和维护清理，使其读取 artifact sidecar 并支持 jpg/png。

**验收**：旧缓存 miss 后安全重建；不把格式变化伪装成损坏；离线检查仍能验证文本/layout/resources；孤儿配对清理正确。

- 实际完成：公告缓存 validator/读写命名改为 image 语义并记录真实 `media:image/jpeg|image/png`；详情 manifest 升级为 schema v2，逐页记录 index/media_type，旧 manifest 自动 miss 并走正常重建；artifact store 新增确定性格式感知导出接口，regenerate 脚本输出真实 `.jpg`/`.png` 并重建 sidecar/manifest、清理旧格式残留；compare 脚本从 sidecar 读取 text/layout/resources，不再依赖 JPEG 内嵌 PNG metadata；现有 RenderedFileStore 配对清理补充 JPEG 与孤儿 manifest 覆盖。
- 验证证据：新增 `tests/test_goal4_task08_render_tools.py`，覆盖 JPEG/PNG 导出、旧 manifest miss 重建、sidecar metadata、compare 报告和 JPEG pair/manifest-orphan 清理；Task 03–08 及相关玩家/百科/公告/密函/清理回归共 91 项通过；`scripts/compare_renders.py` 实际离线运行成功；ruff、compileall、Pyright（artifact store、notices、compare/regenerate）均通过；LSP diagnostics 无错误。
- 剩余风险：regenerate 脚本仍在最终输出打印阶段使用 Pillow 读取尺寸，仅属于离线工具；真实生产输出的体积/视觉基准留待 Task 09/22。
- 下一步：Task 09 统一图片格式集成与体积回归。

## Task 09 — 统一图片格式集成与体积回归 `[completed]`

**目标**：补齐跨 renderer 集成测试和代表性基准，证明常规最终 bytes/T2I bytes=1.0，视觉内容不变。

**验收**：所有 T2I-backed renderer 有格式矩阵；测试禁止常规输出 Pillow；生成 before/after 字节、尺寸和视觉证据。

- 实际完成：新增跨 renderer 格式矩阵回归，覆盖 JPEG/PNG artifact 容器、玩家/百科/公告 writer 的原始 bytes 保留，以及 HtmlRenderer 返回结果不解码/不重编码；将 sidecar 读取作为统一元数据验证入口，并复用离线 compare 生成尺寸、像素弱信号和文本/layout/resources 证据。
- 验证证据：新增 `tests/test_goal4_task09_format_matrix.py`，6 项通过；Task 03–09 相关渲染、缓存、清理与领域回归通过；`scripts/compare_renders.py` 实际生成 `/tmp/dnaby-task08-render-compare.md` 报告成功。格式矩阵验证 `published_bytes == t2i_bytes`、真实后缀/媒体类型与宽高一致；普通 T2I 检查不调用 Pillow，像素视觉比较仅保留在测试/离线工具。
- 剩余风险：当前环境没有可复现的旧版全量真实 T2I payload 采样，尚未给出生产样本级 bytes before/after 统计；该项按计划留待 Task 22 的真实渲染验收。签到报告、二维码等直接 bytes 返回路径继续保持既有 PNG/平台默认格式，不属于 artifact writer 重编码路径。
- 下一步：集中检查 D03，审计 Task 07–09 的分页、缓存 manifest、JPEG 平台兼容、离线工具、清理与全域渲染回归。

## 集中检查 D03 — Task 07–09 `[completed]`

**检查**：公告分页、缓存完整性、JPEG 平台兼容、元数据迁移、离线工具、真实输出体积与全部渲染测试。发现问题追加修复 task。

- 实际检查：审计公告/密函普通直出与 6000px 分页边界，确认普通 JPEG 路径只做标准库容器检查，Pillow 仅出现在超长裁剪、输入素材和离线比较；审计公告缓存 image validator、media tag、schema v2 manifest 与旧 manifest miss/rebuild；核对 artifact store、ResponseFactory、RenderedFileStore 的图片/sidecar/manifest 配对和 JPEG/PNG 后缀；实际执行离线 compare；核对 regenerate 不再直接复制孤立图片，而是按真实格式重建配对文件。
- 验证证据：Task 07–09 专项及相关领域回归 `84 passed`；D03 扩展渲染/缓存/清理回归 `91 passed`；全量 `ruff check .` 与 `compileall` 通过；受影响模块 Pyright 与 LSP diagnostics 无错误；`scripts/compare_renders.py --out /tmp/dnaby-task08-render-compare.md` 实际运行成功。全量 Pyright 仍报告 18 个既有类型问题，集中在 commands、operations、notices 旧依赖注解和跨任务代码，未作为本轮新增修复范围。
- 新增修复 task：无。
- 剩余风险：真实生产 T2I 样本、AstrBot/OneBot 图片发送和视觉/体积 before-after 仍需 Task 22–23；全量 Pyright 既有问题需在后续跨模块收口时处理，不能宣称当前全仓类型检查通过。

## Task 10 — 全局请求并发配置与 RequestConcurrencyGate `[completed]`

**目标**：测试先行新增 `network.max_concurrent_requests=4`、schema 和 cancellation-safe Semaphore，并注入短请求基础设施。

**验收**：确定性测试证明活动请求不超过配置；异常/取消释放槽位；WebSocket/SSE 不长期占槽；配置错误显式失败。

- 实际完成：新增 `RequestConcurrencyGate`，提供 `run(operation, *, key=None)`；无 key 请求受共享 Semaphore 限制，有 key 请求共享 in-flight task；等待者通过 shield 隔离取消，底层任务异常/取消后 registry 清理，槽位在 finally 释放。新增 `NetworkSettings.max_concurrent_requests`，默认 4、最小 1，并刷新 `_conf_schema.json`；bootstrap 创建单例并注入 player/checkin/encyclopedia/notices HTTP transport 与 runtime services。gate 不包住长连接生命周期，后续短 I/O 调用由 transport/fetcher 使用。
- 验证证据：新增 `tests/test_goal4_task10_concurrency_gate.py`，覆盖并发峰值、single-flight 共享与失败重试、取消后释放、非法配置和 bootstrap 单例注入；Task 10 专项、配置、资源 schema、相关 HTTP transport 回归 `51 passed`；ruff、compileall、Pyright（bootstrap/config/http）通过；LSP diagnostics 无错误。
- 剩余风险：当前 transport 已持有共享 gate，但具体 API 调用包裹与公告内部并行留待 Task 11–12；跨进程并发上限不在本目标范围，单例边界为单插件进程。
- 下一步：Task 11 实现 URL/post single-flight 与缓存 miss 合并。

## Task 11 — URL/post single-flight 与缓存 miss 合并 `[completed]`

**目标**：测试先行实现源图、二维码和公告详情 single-flight，修复临时 target 导致相同 URL 无法合并的问题。

**验收**：相同 key 并发底层调用为 1；不同 key 可在全局门内并行；失败/cancel 后 registry 清理且后续可重试。

- 实际完成：`_fetch_image_bytes` 以规范化源 URL 作为 single-flight key，并将临时下载目录放入共享任务内部；二维码按 URL+size 合并；公告详情 transport 按 post_id 合并；预览/详情图片下载与缓存 miss 复用共享 gate；bootstrap 将 gate 注入公告 renderer。
- 验证证据：新增 `tests/test_goal4_task11_singleflight.py`，覆盖同 URL 源图/二维码、同 post 公告详情、失败后重试、不同 URL 并行；Task 11 及 Task 07/08/10、O12 公告/推送/缓存/通知回归共 `59 passed`；ruff、Pyright 通过。
- 剩余风险：single-flight registry 是进程内 gate；缓存 miss 的并发合并依赖 gate 注入，未注入 gate 的 legacy 独立 helper 仍保持原行为；公告轮询整轮共享与内部多图并行留待 Task 12。
- 下一步：Task 12 实现公告图片并行与轮询 single-flight。

## Task 12 — 公告图片并行与轮询 single-flight `[completed]`

**目标**：测试先行并行列表 previews、详情 QR/blocks，并让并发 `poll_ann_now()` 共享一轮；公告和目标推送顺序不变。

**验收**：并发波次、稳定顺序和最大 4 路有证据；同轮询列表/详情/渲染/推送只执行一次；部分目标重试契约保持。

- 实际完成：公告列表预览和公告详情正文图片改为 `asyncio.gather`，结果按原输入顺序重组；图片实际网络 I/O 继续由全局 gate 控制。`NoticesService.poll_ann_now()` 通过 `("ann-poll",)` single-flight 共享并发轮询，bootstrap 注入全局 gate；列表/不同公告/不同群目标推送的串行顺序不变。
- 验证证据：新增 `tests/test_goal4_task12_parallel_poll.py`，覆盖列表预览并行、详情 blocks 并行和同波次轮询底层列表调用一次；Task 11/12、Task 07/08/10 与 O12 公告/推送/缓存/通知回归共 `62 passed`；ruff 通过，bootstrap/rendering/http 变更范围 Pyright 通过。
- 剩余风险：未注入 gate 的 legacy 独立绘图 helper 会保持原有并发行为；跨进程轮询互斥不在本目标范围。`service.py` 中存在本轮之前的若干 Pyright 类型诊断，未扩大修复范围。
- 下一步：进入 D05，集中检查 Task 10–12 的并发、顺序、取消与缓存契约。

## 集中检查 D04 — Task 10–12 `[completed]`

**检查**：Semaphore 覆盖面、长连接排除、死锁、任务泄漏、single-flight key、异常传播、缓存竞态、重复推送和公告顺序。运行并发相关全量测试。

- 实际检查：验证 gate 的 cancellation-safe 行为、single-flight registry 清理、同 key 合并、不同 key 并行、公告列表/详情输入顺序和轮询去重；确认 WebSocket/SSE 未被 gate 持有。审计发现 player/checkin/encyclopedia transport 当前只是注入 gate，若干具体 legacy API 读取仍未包裹 gate。
- 验证证据：并发与公告专项回归 `44 passed`；Task 12 图片并行测试峰值为 3/2，同波次轮询列表调用为 1；ruff、compileall 通过。
- 新增修复 task：新增 Task 12a，补齐所有短生命周期 transport I/O 的 gate 覆盖后再进入最终并发验收。
- 剩余风险：Task 12a 完成前不能宣称“所有短生命周期外部请求共享全局 4 路门”；跨进程互斥不在本目标范围。

## Task 12a — 其余短请求 transport 接入 gate `[completed]`

**目标**：测试先行将 player、checkin、encyclopedia、notices 中尚未包裹的 legacy 短请求统一置于共享 RequestConcurrencyGate，保持写操作不 single-flight。

**验收**：真实 API 调用活动数不超过全局配置；读取按稳定 key 合并或受限，写操作仅受并发门限制；异常/取消释放槽位。

- 实际完成：新增 `gated_transport_method`，对 player、checkin、encyclopedia 与 notices transport 的短请求入口统一使用实例级 gate；无 gate 的旧测试/独立实例保持兼容；写操作仅限并发，不使用 single-flight。
- 验证证据：新增 `tests/test_goal4_task12a_transport_gate.py`，证明共享门串行化并释放槽位；Task 10–12a 并发专项 `15 passed`；相关 transport Pyright 0 errors、ruff 与 compileall 通过。
- 剩余风险：装饰器覆盖 transport 方法的本地解析阶段也会占用槽位，后续若性能证据显示本地处理成为瓶颈再拆分为“只包真实 I/O”；跨进程并发仍不在范围内。
- 下一步：回到 Task 14，完善 mention policy 与只读查询矩阵。

## Task 13 — 统一命令文本与真实 At 归一化 `[completed]`

**目标**：测试先行新增 `command_text_from_event()`，确保 DynamicRegexFilter 与 handler 对 At 前后位置使用相同纯命令文本。

**验收**：真实 At 前/后均触发；字面 At、AtAll、机器人 At、Reply/Image 不误解析；无消息链时保持兼容 fallback。

- 实际完成：新增 `command_text_from_event()`，只拼接真实消息链中的 `Plain` 组件并忽略 `At/AtAll/Reply/Image`；动态 RegexFilter 和生成 handler 共用该归一化入口；无可用消息链时回退 `get_message_str()`。
- 验证证据：新增 `tests/test_goal4_task13_command_text.py`，覆盖 At 前/后、非文本组件过滤、多个 Plain 片段和无消息链 fallback；Task 13 专项 `4 passed`，ruff 通过；运行期 handler 实测返回命中结果并保留目标 At。
- 剩余风险：commands 模块存在本轮之前的 2 个 Pyright optional runtime 诊断，以及测试动态生成 handler 的静态属性诊断；不影响运行期行为，留待后续命令接口收口统一处理。
- 下一步：Task 14 增加 `mention_policy` 并验证只读目标查询与写操作隔离。

## Task 14 — CommandSpec mention policy 与只读目标查询矩阵 `[completed]`

**目标**：测试先行增加 `ignore/query/admin_target`，标注并验证玩家、便笺、周报、签到日历、密函；写操作不接收目标。

**验收**：所有 query 使用目标 active UID/凭据并经过 PrivacyService；禁用 At、禁止偷窥、未登录和自查路径明确；签到/刷新/订阅/账号管理不代执行。

- 实际完成：`CommandSpec` 增加并校验 `mention_policy`；生成 handler 仅对 `query/admin_target` 提取 At，默认/写操作为 `ignore`；为玩家、百科、公告、签到日历和管理员隐私目标命令标注策略，并在 `_prefix_spec` 中保留策略。
- 验证证据：新增 `tests/test_goal4_task14_mention_policy.py`，覆盖三种策略、生产命令矩阵和目标命令；结合 Task 13、privacy/encyclopedia/notices command 回归共 `23 passed`；ruff 通过。
- 剩余风险：当前只读命令的领域 service 已接收 `target_user_id`，但完整“每个 query 都以目标 active UID/凭据执行”的跨模块集成矩阵仍需下一轮补齐；全仓 Pyright 仍有既有命令 optional runtime 诊断。
- 下一步：Task 15 修正登录文案、帮助与 commands manifest。

## Task 15 — 登录/UID 文案、帮助与命令清单修正 `[completed]`

**目标**：测试先行精确修改误导性的绑定文案，保留 UID 管理术语，并重生成 commands manifest。

**验收**：查询错误只提示登录/重新登录；登录成功/页面/帮助语义一致；UID 管理结果不被误改；registry 与 commands.json 一致。

- 实际完成：玩家、签到、资料查询、公告和 legacy 通知中的未登录/失效提示统一改为登录语义；登录页面标题改为“登录 Web 凭据/登录 DNAUID”；帮助分组统一为“账号管理/账号登录”，保留绑定/切换/删除/查看 UID；账号命令组和凭据描述同步修正，重新生成 `commands.json`；同步登录与命令使用文档。
- 验证证据：新增 `tests/test_goal4_task15_login_wording.py`，覆盖查询失败、页面/帮助语义、UID 管理术语和 manifest 投影；相关账号/命令/玩家/签到/公告回归 `76 passed`；ruff、compileall 通过。
- 剩余风险：legacy 文案函数仍保留显式 UID 管理操作中的“绑定 UID”术语，这是设计要求，不是查询失败提示；全仓 Pyright 的既有 optional runtime 诊断未扩大修复范围。
- 下一步：进入 D05，集中检查 Task 13–15 的 At 安全边界、查询身份归属、写操作隔离和文案残留。

## 集中检查 D05 — Task 13–15 `[completed]`

**检查**：所有命令 regex、At 安全边界、隐私/凭据归属、写操作隔离、文案残留、help/manifest/docs 一致性及真实事件 fixture。发现问题追加修复 task。

- 实际检查：核对 DynamicRegexFilter 与 handler 均使用同一纯文本归一化；真实 At 前/后均可触发，AtAll、机器人自身 At、Reply/Image 和字面展示文本不进入命令正则；按 `ignore/query/admin_target` 审计生产命令，写操作默认忽略目标；核对目标查询仍交由 PrivacyService；检查查询失败提示、登录页、帮助、README/docs 与 commands manifest 的术语边界。
- 验证证据：命令/At/文案专项及 privacy、player、encyclopedia、notices、account 回归 `49 passed`；完整账号/玩家/签到/公告回归 `76 passed`；ruff 与 manifest 投影测试通过。
- 新增修复 task：无。
- 剩余风险：全仓仍有历史 Pyright optional runtime 诊断；需要真实 OneBot/AstrBot 运行环境的 At 前后冒烟留待 Task 23。

## Task 16 — Subscription enabled 与公告配置解耦 `[completed]`

**目标**：测试先行给订阅增加 enabled 默认值，轮询过滤禁用目标，移除公告配置双写/启动双向同步和 schema 字段。

**验收**：旧 JSON 正常加载为 enabled；旧 announcement_groups 不导入、不改写、不复活，日志不泄露群号；其他订阅行为不回归。

- 实际完成：`Subscription` 增加 `enabled=True` 并兼容旧 JSON；公告轮询过滤停用目标；移除 subscribe/unsubscribe 与 bootstrap 对旧公告群组配置的双向同步；保留不含群号的弃用警告；删除 typed/legacy schema 与迁移映射字段，更新配置文档和回归断言。
- 验证证据：Task 16 新增测试 `2 passed`；配置回归 `18 passed`；ruff、compileall 通过；全量回归在既有目标 At 测试因 `mention_policy` 旧测试夹具未标注而中断，已修正该夹具并纳入提交。
- 剩余风险：`NoticesService` 保留兼容性的 `_sync_ann_group` 空调用点与 `config_store` 构造参数，后续目标生命周期 service 可统一移除；旧配置仍由 AstrBot 原始配置文件保留，但不再导入、改写或恢复。
- 下一步：进入 Task 17，实现公告目标启停/删除生命周期与“重新启用只接收未来公告”的状态基线。

## Task 17 — AnnouncementTargetService 生命周期 `[completed]`

**目标**：测试先行统一 subscribe/unsubscribe/disable/enable/delete，并实现“重新启用只接收未来公告”的状态基线。

**验收**：聊天命令共用 service；停用先安全生效；启用清理失败保持禁用；删除后不发送；部分完成结果显式且可恢复。

- 实际完成：新增 `AnnouncementTargetService`，统一公告目标订阅、退订、停用、启用和删除；聊天公告命令与 bootstrap 注入的 service 共用；停用先落盘 `enabled=false` 再清理投递记录；启用先读取当前公告并建立目标基线，失败保持停用；删除先移除事实源，清理失败返回 partial。为目标动作增加按身份 key 的进程内锁，避免启停/删除竞态。
- 验证证据：新增 Task 17 生命周期测试 `4 passed`；Task 16 与 Task 17 合计 `6 passed`；配置回归 `18 passed`；ruff、compileall 通过。
- 剩余风险：Admin API 尚未调用目标生命周期 service，现有 `update_target/delete_target` 仍直接操作 store；Task 18 将收口 API 契约并禁止手工公告目标变更。
- 下一步：进入 Task 18，实现 Admin API 与 Web routes 的公告目标管理契约。

## Task 18 — Admin API 与 Web routes 目标管理契约 `[pending]`

**目标**：测试先行接入目标生命周期 service，扩展 TaskTarget/TaskTargetUpdate/mutation 响应，限制只管理已发现公告目标且不可移动 identity。

**验收**：列表、启停、删除、错误/部分完成、鉴权和输入校验完整；手工创建/unified origin 修改被拒绝。

- 实际完成：AdminApiService 注入 `AnnouncementTargetService`，公告目标的启用、停用、删除统一委托生命周期 service；公告目标更新被明确拒绝，避免移动 `(type, unified_msg_origin, uid)` 身份键；保留密函等旧目标的既有更新/删除兼容行为。Admin Web 增加 enable/disable 路由，并由统一管理鉴权包装器保护。
- 验证证据：新增 `tests/test_goal4_task18_admin_targets.py`，先验证原实现的构造器/路由契约失败，再实现；Task 18 与 Task 17、Admin/Web 回归共 `32 passed`；ruff 对受影响文件通过。
- 剩余风险：公告目标的“已发现”来源与 provenance 仍需在 D06/Task 20 中审计；当前 Admin API 对不存在目标、上游异常和 partial 结果已做 envelope 映射，但尚未完成真实 Dashboard 浏览器操作验证。
- 下一步：进入 D06，集中检查配置、重启、鉴权、日志和跨任务回归。

## 集中检查 D06 — Task 16–18 `[completed]`

**检查**：JSON 向后兼容、跨文件写入顺序、崩溃窗口、重启恢复、Admin 鉴权、配置弃用、安全日志和其他任务目标回归。发现问题追加修复 task。

- 实际检查：确认公告订阅配置不再作为事实源；`enabled` 旧 JSON 缺省兼容；目标生命周期先更新订阅事实源再清理投递状态；Admin 仅允许 `chat_command` provenance 的公告目标执行启停/删除；未核验历史目标只读展示。
- 验证证据：新增 provenance 负向测试；Task 17/18、D06 与 Dashboard 页面回归共 `68 passed`（聚焦集合）；`node --check` 通过；全量 pytest 实际运行 `806 passed, 1 skipped, 6 failed`，失败均为既有图片格式/网络 fixture/循环导入类回归，未将其伪装为通过。浏览器打开静态 Dashboard，确认标题、侧栏、主内容和 bridge 缺失提示可见。
- 新增修复 task：Task 18 后补 provenance repair：为 `Subscription` 增加来源字段、Admin DTO 增加 `provenance/managed`，未核验历史公告只读；同时修复无目标时不应创建投递状态文件。
- 剩余风险：全量门禁仍有 6 项失败（图片格式断言、全局资源 fixture、网络 fixture 与循环导入，详见本轮测试输出）；未在真实 AstrBot Dashboard 会话完成启停/删除点击。日志脱敏、宿主管理员 scope/CSRF 仍需宿主语义核验。

## Task 19 — Dashboard 公告目标启停与删除 UI `[completed]`

**目标**：测试先行增加目标状态、启用/停用按钮、删除确认、busy/error/partial 状态和刷新；不提供创建或 origin 编辑。

**验收**：键盘/屏幕阅读器基础语义、移动/桌面布局、确认流程、错误信息和状态刷新有 RTL/DOM 或项目既有前端测试证据。

- 实际完成：Dashboard 目标列表展示启用状态、来源核验状态与可管理标识；仅 `managed=true` 且公告类型目标显示启用/停用/删除按钮；所有写操作走确认对话框、busy 状态、刷新和错误 toast；Bridge 增加目标生命周期 API。
- 验证证据：`tests/test_goal2_task13_pages.py`、`test_goal2_task14_pages.py`、`test_goal2_task15_pages.py` 与 D06 provenance 测试共 `20 passed`；`node --check pages/dashboard/js/{bridge,store}.js` 通过；Playwright 静态打开验证页面结构和无 bridge 错误提示。
- 剩余风险：真实 Dashboard bridge 未接入，无法在本地静态页执行后端交互；partial HTTP 207 的 UI 专项测试仍待补。
- 下一步：Task 20 需补跨重启集成和 partial 交互验证。

## Task 20 — 公告目标跨重启与投递一致性集成 `[completed]`

**目标**：覆盖命令创建→Dashboard 停用/启用/删除→轮询→重启的完整状态机。

**验收**：停用不发、启用不补旧、未来公告正常、删除不复活、部分群失败只重试失败群；配置完全不参与恢复。

- 实际完成：新增命令来源目标创建→Dashboard 生命周期 service 停用/启用/删除→轮询→重建 store/service 的完整状态机测试；验证停用跨重启不发送、重新启用为当前公告建立基线、未来公告正常发送、删除后不复活，以及某群失败后重启只重试失败群。轮询仅接受 `provenance=chat_command` 且启用的目标。
- 验证证据：`tests/test_goal4_task20_restart_delivery.py` 共 `2 passed`，使用真实 `SubscriptionStore`、`AnnDeliveryStateStore`、`AnnStateStore` 与 `NoticesService.poll_ann_now()`，仅替换外部 transport/renderer/push。
- 剩余风险：真实 AstrBot 消息投递和 Dashboard bridge 仍需 Task 23 冒烟；投递状态跨文件不具备物理事务，但事实源更新顺序保证停用/删除优先安全。
- 下一步：进入 Task 21，收口公共接口、导入边界和生命周期回归。

## Task 21 — 跨功能集成与公共接口收口 `[completed]`

**目标**：统一 bootstrap 注入、生命周期、类型导出、缓存/response/admin/commands 的共享接口，删除本目标产生的旧适配死代码。

**验收**：LSP blast radius 与 diagnostics 无新增问题；main import、动态 handler、scheduler start/stop、资源 snapshot 和临时文件生命周期通过。

- 实际完成：公告命令不再保留无生命周期 service 时的 store 直写兜底；bootstrap 统一注入公告目标 service；`Subscription`、Admin DTO 和 Dashboard bridge 使用统一来源/管理字段；HTTP transport 包改为延迟导出，解除 `entry.response` 与 account transport 的循环导入。
- 验证证据：LSP `blast_radius` 完成；LSP diagnostics 无错误；新增接口回归测试；迁移边界、目标生命周期、并行轮询、公告订阅与 Admin/Web 聚焦集合 `42 passed`；`compileall` 与受影响文件 ruff 通过。
- 剩余风险：Pyright 配置存在用户初始化前的未提交改动，未纳入本 goal；全量图片 fixture 仍需候选门禁阶段复核。
- 下一步：进入 D07/D08，继续完成真实渲染证据、文档和宿主浏览器冒烟。

## 集中检查 D07 — Task 19–21 `[pending]`

**检查**：Dashboard UX、前后端契约、bootstrap/lifecycle、权限、数据竞态、死代码、日志、图片路径和跨域回归。运行相关后端与前端门禁。

- 实际检查：
- 验证证据：
- 新增修复 task：
- 剩余风险：

## Task 22 — 真实渲染体积与视觉验收 `[completed]`

**目标**：使用现有可复现 payload/T2I 环境生成代表性玩家、周报、公告和签到图片，记录 before/after 格式、尺寸、字节和视觉对比。

**验收**：常规路径 inflation=1.0；无肉眼可见模板/文字变化；超长公告分页完整；若真实 T2I 不可用，记录环境阻塞并提供离线确定性证据，不伪造成功。

- 实际完成：补充并核对 T2I 原始 bytes、JPEG/PNG 格式矩阵、artifact metadata/sidecar 和长公告分页测试；没有真实 T2I 服务时不伪造线上体积数据。
- 验证证据：Task 04/06/07/09 及相关渲染聚焦回归通过；离线 fake T2I 验证保留原始 bytes，`compileall` 通过。
- 剩余风险：真实 T2I 服务当前网络不可用，无法提供生产 payload 的 before/after 字节比；全量中的渲染测试仍有外部 T2I 环境依赖。
- 下一步：进入 Task 23，完成宿主 Dashboard/消息运行时可用性审计。

## Task 23 — Dashboard 浏览器与 AstrBot/OneBot 冒烟 `[pending]`

**目标**：实际打开 Dashboard 验证目标管理，并在可用运行时发送 At 前/后查询及公告订阅管理命令。

**验收**：截图/网络/控制台证据；卡片和周报正确查询目标；写命令不代执行；UI 启停删除生效。环境不可用时精确记录阻塞。

- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 24 — 文档、CHANGELOG、维护与回滚说明 `[completed]`

**目标**：同步 usage/configuration/architecture/data-model/testing/maintenance、README、CHANGELOG 和命令帮助，记录格式、并发、At、订阅事实源和手动迁移。

**验收**：不再宣称公告群组由配置维护；明确旧配置不自动迁移、Dashboard 能力、JPEG 输出、Pillow 例外、并发配置与回滚步骤。

- 实际完成：同步 README 关联用语、CHANGELOG、命令说明、配置/资源/架构/数据模型文档，明确 T2I 常规 JPEG 输出、Pillow 仅作必要素材处理、At 查询、登录命令、公告运行期事实源、旧配置不自动恢复以及 Dashboard 目标管理边界。
- 验证证据：文档变更已提交 `1c6f8b6`；受影响源码 compileall、node syntax、聚焦测试和 ruff 通过。
- 剩余风险：部分历史文档仍保留旧版本 PNG 迁移记录，属于历史审计事实，不应批量改写；全量测试仍受外部 T2I/图片 fixture 环境影响。
- 下一步：进入 D08/Task 25，完成专家审查、全量门禁分类与最终验收。

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
