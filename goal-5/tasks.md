# Goal 5 Tasks：插件资源瘦身与外置

> 每轮只执行第一个未完成项；普通代码 task 必须按 TDD Red → Green → Refactor；每三个普通 task 后执行一次集中检查-debug。每个 task 单独提交，只暂存本 task 所有文件。初始化前已有修改、其他 goal 文件和私有资源不得混入提交。

## Task 01 — 资源现状、依赖路径与真实包体积基线 `[completed]`

**目标**：建立可复核的资源清单、重复字体清单、renderer/旧 utils 路径消费者清单和真实发布包体积基线，不修改业务代码。

**范围**：`src/resources/`、`src/utils/`、`src/infrastructure/resources/`、`src/infrastructure/rendering/`、相关测试/README/打包规则；必要时使用现有打包脚本。

**验收**：记录所有大于 100 KiB 的候选文件、重复字体的哈希/路径、直接路径消费者、现有 manifest/generation/lease/listener seam；记录真实打包方式、字节数和 MiB；说明 `tests/.data`/Python/ruff 等环境阻塞。

- 实际做了什么：
  - 在隔离 worktree `codex/resource-slimming-design`、提交 `d748fe1` 的干净基线 (`HEAD=0327a0a` 后初始化提交) 上只做只读盘点，没有修改业务代码。
  - 统计 `git ls-files`：全仓 819 个 tracked files；`src/resources/` 与 `src/utils/fonts/` 共 339 个资源文件、172,537,145 bytes（164.544244 MiB）。其中 `src/resources/` 为 331 个文件、115,990,863 bytes（110.617507 MiB），`src/utils/fonts/` 为 8 个文件、56,546,282 bytes（53.926737 MiB）；纹理 273 个文件、58,801,938 bytes（56.077898 MiB），字体 8 个文件、56,546,282 bytes（53.926737 MiB），帮助素材 48 个文件、640,131 bytes（0.610476 MiB）。
  - SHA-256 盘点发现 11 个重复 digest 组、可去除的重复副本合计 56,593,269 bytes。7 组是完整字体的 `src/resources/fonts/` 与 `src/utils/fonts/` 双份：`arial-unicode-ms-bold.ttf` 17,942,992 bytes、`MiSansVF.woff2` 11,867,816 bytes、`NotoColorEmoji.ttf` 10,195,752 bytes、`arial-unicode-ms-bold-fallback.woff2` 5,774,400 bytes、`dna_fonts.ttf` 5,632,220 bytes、`dna_fonts.woff2` 2,805,896 bytes、`arial-unicode-ms-bold.woff2` 2,324,528 bytes；其余重复项为 `common/div.png` 与 `stamina/div.png`、两组帮助图标，以及两个相同的 `dna_fonts.py`。
  - 大于 100 KiB 的首批候选由字体占据前 14 个大文件：最大为双份 `arial-unicode-ms-bold.ttf`（每份 17.111771 MiB）、双份 `MiSansVF.woff2`（每份 11.318031 MiB）、双份 `NotoColorEmoji.ttf`（每份 9.723427 MiB）、双份 fallback WOFF2（每份 5.506897 MiB）、双份 `dna_fonts.ttf`（每份 5.371304 MiB）、双份 `dna_fonts.woff2`（每份 2.675911 MiB）、双份 Unicode WOFF2（每份 2.216843 MiB）；最大非字体纹理为 `src/resources/textures/stamina/bg/bg6.png`，2,463,458 bytes（2.349337 MiB），随后是角色/攻略/日历/签到背景和 frame。
  - 直接路径消费者已定位：`src/infrastructure/rendering/fonts.py:9` 的 `BUNDLED_FONT_PATH` 与 `load_runtime_font()` fallback；`player.py:62-66` 的 common/detail/role/font 常量及其多处模板 payload；`encyclopedia.py:55-61` 的 common/stamina/weekly/calendar/font 常量；`checkin.py:30-34` 的 common/sign/font 常量；`notices.py:58-63` 的 common/mh/ann/font/unicode 常量；`help.py:20` 的 `MiSansVF.woff2` 及 common/help 纹理；`payloads.py:15` 的 common 纹理；`src/utils/image.py:26,70` 的 legacy `texture2d` 路径；`src/utils/fonts/dna_fonts.py`、`src/resources/fonts/dna_fonts.py` 的三类字体路径；`src/utils/resource/RESOURCE_PATH.py` 与 `src/resources/resource/RESOURCE_PATH.py` 的运行期资源路径；`src/infrastructure/resources/encyclopedia.py:257-258` 的 snapshot 字体路径。`dnaby/` 目录在当前 worktree 不存在，不能把它当作实际消费者。
  - 现有资源 seam 已核实：`ResourceGenerationValidator` 在 `src/infrastructure/resources/generation.py:313`，`ResourceSnapshotCoordinator` 在 `generation.py:414`，listener 注册为 `subscribe()`（约 463 行），空/可选快照入口为 `optional_lease()`（约 563 行）；`ResourceManifest.validate_runtime_layout()` 在 `src/infrastructure/resources/manifest.py:131`；`EncyclopediaResourceStore`/`from_root()` 在 `src/infrastructure/resources/encyclopedia.py:110/165`；`ResourceMap`/`from_root()` 在 `src/infrastructure/rendering/player.py:548/559`。这些是后续统一解析边界应复用的既有 contract，不新建第二套下载或 snapshot 管理。
  - 没有发现仓库专用的市场打包脚本。按当前 tracked HEAD 执行 `git archive --format=zip HEAD` 得到可复现的 source-archive baseline：917 entries，压缩包 155,708,550 bytes（148.495245 MiB），ZIP 成员压缩总和 155,555,598 bytes（148.349379 MiB），未压缩总量 177,794,502 bytes（169.558050 MiB）。其中 `src/` 压缩后 154,622,977 bytes（147.459962 MiB），所以这是包含测试/文档/goal 记录的保守上界，不把它误报成市场后端的隐式排除规则；后续仍以真实提交 zip 复测。官方 AstrBot 发布文档 URL 已记录在计划来源中，确认市场以 zip 作为体积门槛。
- 验证证据：
  - 只读命令：`git ls-files` + Python SHA-256/字节统计、`git archive --format=zip HEAD` + Python `zipfile` 统计、`rg` 路径消费者检索、LSP 的符号定位/引用扫描。
  - `tests/.data` 在当前隔离 worktree 缺失；初始化基线 `python3 -m pytest` 在 `conftest.py` 收集阶段因 `tests/.data` 不存在退出码 4（`FileNotFoundError`），不是本 task 引入的回归。系统 Python 为 3.14.4，`pytest`/Pillow/SQLAlchemy/SQLModel 可导入，但 `ruff` 模块缺失；后续按仓库约定优先使用项目 `.venv` 或 runtime 根目录命令。
  - 盘点生成的完整原始报告保存在本轮临时证据 `/tmp/dnaby-goal5-task01-current/resource-inventory.txt` 与 `/tmp/dnaby-goal5-task01-current/package-baseline.txt`；它们未写入仓库，避免把构建产物或大资源加入提交。
- 剩余风险：
  - `git archive` 只是当前仓库可复现的保守 baseline，市场服务是否排除 `tests/`、`docs/` 或 goal 记录尚未由本地发布工具确认；最终必须按实际提交路径重新构建并测量。
  - 资源仓库 `dna-resource` 不在本机工作区；字体/纹理的最终归属、manifest 哈希和跨仓库可验证 generation 由 Task 02 审计，当前不能安全删除任何大文件。
  - 目前大量 renderer 仍直接拼接插件目录路径，字体 fallback 仍会把缺失资源转成 `FileNotFoundError`；这正是后续 Red/Green 任务的范围。
- 下一步建议：Task 02 审计 `dna-resource` 可访问性、manifest `file_hashes`/`resource_version` 和现有 generation validator；在没有跨仓库证据前不删除资源。

## Task 02 — `dna-resource` 仓库与 manifest 能力审计 `[pending]`

**目标**：确认完整字体/纹理应该落在哪个资源仓库、现有 manifest 结构和 validator 能力，列出必须补齐的文件与哈希；若仓库不可访问，形成明确阻塞记录。

**范围**：可访问的本地/远程 `dna-resource` 仓库、`src/infrastructure/resources/manifest.py`、generation validator、资源文档；不伪造远端变更。

**验收**：得到资源仓库路径/分支/版本、目标文件列表、`resource_version` 更新点、`file_hashes` 约束和验证命令；未授权或不可访问时只记录事实并标记阻塞，不把假设当完成。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 03 — 统一解析边界与 fallback 契约集中检查 `[pending]`

**类型**：集中检查-debug（Task 01–02 后提前检查；此处冻结设计，避免在缺少资源仓库证据时删除文件）。

**检查**：核对规格目标/非目标、当前 `ResourceSnapshotCoordinator` 的真实语义、空 snapshot 行为、renderer 消费点、资源仓库依赖和可回滚点；确定 `RuntimeAssetResolver` 是新增边界还是扩展现有 `ResourceMap`/`EncyclopediaResourceStore`，并写出逻辑 key/来源/incomplete 规则。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填（如无则写“无”）。
- 剩余风险：待填。

## Task 04 — 统一资源解析与降级路径 Red 契约 `[pending]`

**目标**：测试先行固定 verified snapshot → bootstrap allowlist → placeholder/`None` 的优先级、逻辑 key、不可读取 candidate 和缺失资源的 `incomplete` 语义。

**范围**：`tests/` 资源/generation/renderer 相关测试与最小 fake；只新增/扩展测试，不写生产实现。

**验收**：实际运行目标测试并确认因缺少/不完整解析 seam 失败；覆盖字体、纹理、角色/武器/panel 至少各一类、空 snapshot、bootstrap 命中、文件缺失、candidate 未验证、来源元数据和 `incomplete`。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 05 — 统一资源解析 Green 与现有 snapshot 接入 `[pending]`

**目标**：实现最小统一资源解析边界，接入现有 verified snapshot、bootstrap allowlist、空资源视图和 listener 刷新，不新增下载器或第二套 cache。

**范围**：`src/infrastructure/resources/`、必要的 `src/infrastructure/rendering/` seam、最小公共类型；不删除大资源。

**验收**：Task 04 Red 转 Green；renderer 不需要知道资源物理目录；只读 verified snapshot；candidate/Git cache 不可直接消费；空 snapshot 能返回明确降级状态；snapshot 发布后新的请求拿到新视图。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 06 — 解析边界集中检查 `[pending]`

**类型**：集中检查-debug（Task 04–05）。

**检查**：复查 resolver API 深度、来源优先级、路径安全、None/placeholder/incomplete 语义、快照租约和 listener 并发边界；运行资源/generation/现有 renderer 回归，发现问题就在 tasks.md 末尾追加修复 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填。
- 剩余风险：待填。

## Task 07 — Player/Encyclopedia/Checkin/Notices/Help 字体与纹理接入 Red `[pending]`

**目标**：测试先行锁定主要 renderer 使用统一 resolver、无本地完整字体时不启动失败、缺失资源能简化渲染并标记 `incomplete`。

**范围**：相关领域 renderer、`load_runtime_font()`、旧 utils 路径的测试；只新增/扩展测试。

**验收**：Red 测试实际失败；覆盖 Player、Encyclopedia、Checkin、Notices、Help 代表路径，至少覆盖启动加载、字体回退、纹理缺失、角色/武器/面板来源和 snapshot 刷新。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 08 — 主要 renderer 与 legacy 路径 Green 迁移 `[pending]`

**目标**：将主要渲染链路切到统一逻辑 key，消除插件目录硬编码资源依赖，同时保持完整 snapshot 与降级路径行为。

**范围**：`src/infrastructure/rendering/`、`src/modules/{player,encyclopedia,checkin,notices}/`、Help、必要的 `src/utils/`/`dnaby/` 适配；不删除资源文件。

**验收**：Task 07 转 Green；静态检索确认主要 renderer 不再拼接待外置资源的插件路径；不资源同步时无 `FileNotFoundError`，完整 snapshot 时能读取远端资源；listener 后无需重启刷新。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 09 — Renderer 接入与 incomplete 语义集中检查 `[pending]`

**类型**：集中检查-debug（Task 07–08）。

**检查**：逐模块审计 Player/百科/签到/公告/帮助/legacy utils 的路径和逻辑 key，验证缓存 incomplete、snapshot lease、listener、占位图/简化渲染、异常可观测性和无新增依赖；必要时追加修复 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填。
- 剩余风险：待填。

## Task 10 — `dna-resource` 补齐字体/大型纹理并更新 manifest `[pending]`

**目标**：在资源仓库中补齐完整字体变体和已确定外置纹理，写入 `file_hashes` 并更新 `resource_version`，以现有 validator 验证可发布 generation。

**范围**：独立的 `dna-resource` 工作区/分支（若可访问）；不把私有资源复制到插件仓库，不在插件仓库伪造资源文件。

**验收**：资源仓库变更可独立提交；关键字体文件头、图片可解码、SHA-256、manifest 和 generation validator 全部通过；若仓库不可访问，task 明确标记阻塞并把可继续的插件侧工作与发布风险写清楚。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 11 — 删除重复字体与已接管的大型纹理 `[pending]`

**目标**：在 resolver、renderer 和资源仓库证据齐备后，删除插件内重复/完整字体树及由 `dna-resource` 接管的大型纹理，仅保留 bootstrap allowlist。

**范围**：`src/resources/`、`src/utils/fonts/`、已确认迁移的 `textures/{calendar,common,detail,role,...}`；同步更新必要的资源清单/文档，不扩大到小图标。

**验收**：删除前静态引用审计无待删除路径消费者；目标资源在 verified snapshot 中可验证；插件导入/启动/无 snapshot 降级不抛 `FileNotFoundError`；未删除的 bootstrap 资源有清单和理由。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 12 — 资源删除与体积集中检查 `[pending]`

**类型**：集中检查-debug（Task 10–11）。

**检查**：运行全量静态路径/逻辑 key 搜索、目标测试/compile/lint/加载检查，构建真实市场发布包并记录体积；检查 `<=8 MiB`、`<=12 MiB`、`<16 MiB` 判定与最大剩余文件，发现回归或超标就追加最小修复/下一批纹理迁移 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填。
- 剩余风险：待填。

## Task 13 — README 与资源使用/维护文档同步 `[pending]`

**目标**：同步首次安装“建议执行同步资源”提示和当前资源边界、降级语义、维护/回滚说明。

**范围**：`README.md`、`docs/usage/resources.md`、必要的 `docs/dev/maintenance.md`、`docs/project/architecture.md`；不创建无关文档。

**验收**：README `> [!IMPORTANT]` 明确建议、非强制；文档描述 verified snapshot/bootstrap/placeholder/incomplete、首次同步、无重启刷新、资源仓库先行和回滚；不承诺不存在的 CI 或自动同步。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 14 — 无 snapshot / 完整 snapshot / 同步刷新运行期验证 `[pending]`

**目标**：用现有 fixture/fake 或本地可验证资源执行两种 snapshot 场景和同步后刷新冒烟，不访问真实生产账号，不提交资源内容。

**范围**：资源/generation/renderer 测试、插件加载检查、必要的最小运行脚本；不自动同步、不修改生产数据。

**验收**：无 verified snapshot 可启动、基础命令可执行、图片命令不因缺失资源崩溃并产生 `incomplete`；完整 snapshot 恢复主要渲染；发布新 generation 后无需重启使用新资源；取消/失败/非 2xx 等现有错误语义未被吞掉。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 15 — 运行期、文档、安全与回滚集中检查 `[pending]`

**类型**：集中检查-debug（Task 13–14）。

**检查**：核对规格偏差、静态引用/死代码、依赖和敏感信息、运行期数据目录、并发/缓存/manifest 一致性、README/docs、回滚路径和两个仓库交付顺序；发现问题追加修复 task。

- 实际检查：待填。
- 验证证据：待填。
- 新增修复 task：待填（如无则写“无”）。
- 剩余风险：待填。

## Task 16 — 最终发布包测量与证据收口 `[pending]`

**目标**：按真实市场提交方式生成最终插件包，记录体积、构成和阈值结论，确保没有完整大字体副本或私有文件。

**范围**：既有打包脚本/构建产物、`git ls-files`/归档内容、相关验证日志；不新增 CI。

**验收**：包可复现；字节数/MiB 明确；`<=8 MiB` 或有理由的 `<=12 MiB`，且 `<16 MiB`；最大剩余文件列出并说明保留理由；静态路径与测试证据附在 task 记录。

- 实际做了什么：待填。
- 验证证据：待填。
- 剩余风险：待填。
- 下一步建议：待填。

## Task 17 — Goal 终审与完成登记 `[pending]`

**类型**：终审。

**检查**：从 C 端体验、代码质量、资源安全、manifest/generation、缓存刷新、无/有 snapshot、错误处理、测试覆盖、构建产物、文档和回滚角度进行最大范围复查。所有已知高风险问题必须修复或明确阻塞；确认 tasks.md 所有 task 已完成/阻塞并填写证据后，登记 goal 完成。

- 实际检查：待填。
- 验证证据：待填。
- 阻塞/低风险事项：待填。
- 最终报告要点：待填。
