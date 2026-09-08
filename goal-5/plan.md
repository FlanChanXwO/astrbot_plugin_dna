# Goal 5 计划：插件资源瘦身与外置

> 状态：已初始化；后续每轮只执行 `tasks.md` 中第一个未完成 task。
> 目标来源：用户提供的资源瘦身设计规格（2026-09-08）。
> 执行分支：`codex/resource-slimming-design`。
> 隔离工作区：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_dnaby/.worktrees/resource-slimming-design`。

## 1. 权威依据与上下文

### 1.1 权威依据

- `goal-5/input.md`：用户原始请求，逐字保留。
- 用户提供的规格：
  `https://raw.githubusercontent.com/FlanChanXwO/astrbot_plugin_dna/docs/resource-slimming-design/docs/superpowers/specs/2026-09-08-resource-slimming-design.md`
- 仓库规则：`AGENTS.md`、`CLAUDE.md`（若存在）。
- 项目入口：`docs/README.md`、`docs/porting/design.md`、`docs/project/architecture.md`、`docs/usage/resources.md`。
- 运行期资源实现：`src/infrastructure/resources/`、`src/infrastructure/rendering/`、`src/resources/`、仍引用旧路径的 `src/utils/` 与 `dnaby/`。
- 现有测试：资源同步、generation/snapshot、renderer、玩家、百科、签到、公告和帮助相关测试。

### 1.2 仓库/规格对应关系假设

用户链接的规格位于 `astrbot_plugin_dna` 的 `docs/resource-slimming-design` 分支；当前工作区是其移植目标/对应实现 `astrbot_plugin_dnaby`，远程只配置了 `astrbot_plugin_dnaby`。本计划默认在当前工作区完成插件侧实现，并将规格中需要 `dna-resource` 仓库的工作作为独立前置 task：若资源仓库在本机或可访问远程中不可用，不伪造资源、哈希或“已完成”状态，而是记录真实阻塞并继续完成不依赖它的解析边界、测试、文档和静态审计。

规格要求两个仓库按顺序交付：先合并 `dna-resource`，再合并插件。当前 goal 不强行把两个仓库混成一个提交，也不把私有资源内容复制进插件仓库。

## 2. 目标

1. 最终真实市场提交包优先压到 `8 MiB` 以内；如确有必要保留 bootstrap，允许 `>8 MiB 且 <=12 MiB`，但必须明显低于 `16 MiB` 市场上限。
2. 完整字体、大型纹理、角色/武器/面板等视觉资源由已验证的 `dna-resource` snapshot 提供；插件本地只保留代码、配置、模板、i18n、logo、帮助所需小资源和极小 bootstrap fallback。
3. 统一运行期资源解析边界：verified snapshot 优先，bootstrap allowlist 次之，程序化 placeholder/简化渲染兜底；解析器不下载、不读取未验证 candidate 或 Git cache。
4. 未同步资源时插件仍能启动和执行基础/普通命令；缺失资源走 placeholder、简化渲染或既有降级路径，并正确标记 `incomplete`，不把缺失资源变成静默成功或统一拒绝。
5. 资源同步成功后继续使用现有 manifest、SHA-256、generation/snapshot 原子发布、lease 和 listener 刷新机制，不要求重启插件。
6. README 在 `> [!IMPORTANT]` 区域明确建议首次安装后执行“同步资源”，并说明未同步时图片/字体/卡片可能降级；措辞是“建议”而不是“必须”。

## 3. 非目标

- 不新增专门的包体积 CI、二进制扫描 workflow 或大规模瘦身测试套件。
- 不新增自动资源同步，不把未同步资源改成普通命令拒绝门禁。
- 不为瘦身做无关架构重构，不为了数字目标迁移大量只有几 KB/几十 KB 的小图标。
- 不引入 `gsuid_core`/`gsucore`、不新增依赖，不修改外部协议或运行期数据目录规则。
- 不提交 Cookie、token、SQLite、日志、私有资源内容或完整字体副本。
- 不删除资源前承诺已有 fallback；不 force push、不 reset、不删除历史 goal/commit。

## 4. 当前已知事实与基线风险

- `src/resources` 当前约 `111 MiB`；最大文件是多份字体：
  `arial-unicode-ms-bold.ttf`、`MiSansVF.woff2`、`NotoColorEmoji.ttf`、`arial-unicode-ms-bold-fallback.woff2`、`dna_fonts.ttf/woff2` 等。
- 同样的字体树还出现在 `src/utils/fonts/`，存在明显重复。
- 现有代码已经有 `ResourceSnapshotCoordinator`、`ResourceMap`、`EncyclopediaResourceStore`、manifest/generation validator、snapshot lease 和 listener；不能另起第二套下载/快照机制。
- `src/infrastructure/rendering/player.py`、`notices.py`、百科资源和旧 utils 中仍有插件目录硬编码路径，`load_runtime_font()` 及若干 renderer 直接依赖本地 `dna_fonts.ttf`。
- 工作区已按 `using-git-worktrees` 建立隔离 worktree；初始化时执行 `python3 -m pytest` 的基线检查在收集阶段因缺失被忽略的 `tests/.data` 失败，不能把该环境失败误报为本次实现回归。系统 Python 还未安装 `ruff`；后续应优先使用项目既有 `.venv`/runtime 检查命令，并准确记录环境缺口。

## 5. 目标设计

### 5.1 统一资源解析

实现名可为 `RuntimeAssetResolver`，或在现有 `ResourceMap` / `EncyclopediaResourceStore` 上扩展；不以名字为验收条件。边界必须能按逻辑 key 解析至少：

- `font.primary_ttf`、`font.primary_woff2`、`font.unicode_ttf`、`font.unicode_woff2`、emoji/备用字体。
- `texture.help.*`、`texture.common.*`、`texture.calendar.*`、`texture.detail.*`、`texture.role.*`、`texture.sign.*`、`texture.stamina.*`、`texture.guide.*`、`texture.wiki.*`。
- 角色头像/立绘、武器图、panel 及其 renderer 所需的公共 frame/background。

解析顺序固定为：

1. 当前已验证 snapshot；
2. 明确登记的本地 bootstrap allowlist；
3. `None`/placeholder 状态，由 renderer 生成简化结果并标记 `incomplete`。

解析器不得下载资源、不得直接读取未验证 candidate/Git cache、不得让 renderer 判断资源是在插件目录还是资源仓库。

### 5.2 渲染接入

至少审计并迁移 Player、Encyclopedia、Checkin、Notices、Help 及仍使用旧 utils 路径的 renderer。字体加载在资源删除后不能抛 `FileNotFoundError`；缺失字体/纹理应进入明确的降级结果，而不是吞异常伪造“完整”结果。snapshot lease、generation listener、incomplete 缓存与刷新语义必须保持。

### 5.3 资源仓库契约

`dna-resource` 需要补齐规格列出的字体变体和本次外置纹理，在 `resource_manifest.json` 的 `file_hashes` 中写入关键字体/纹理 SHA-256，更新 `resource_version`，并能通过现有 generation validator 的存在性、SHA、字体文件头和图片可解码性校验。插件侧只有在该仓库/manifest 可验证时才删除对应本地大资源。

### 5.4 本地资源边界与包体积

保留 `logo.png`、`src/resources/help/help.json`、帮助菜单必要小图标、程序生成优先的通用 placeholder 和必要的小型 bootstrap。删除重复/完整字体树及已经由资源仓库接管的大型纹理；如果实测仍大于 `8 MiB`，优先继续迁移 `calendar/common/detail/role` 中数百 KiB 级背景/banner/frame，而不是迁移小图标。

## 6. 实施与验证策略

- 所有代码改动遵循 TDD：先新增或扩展最小契约测试，实际确认 Red，再写最小实现转 Green，最后重构。
- 首选验证顺序：目标测试/最小复现 → 资源/generation/renderer 相关回归 → `ruff`/格式/compileall → 受影响模块构建/加载 → 无 snapshot 与完整 snapshot 两种运行期冒烟 → 真实发布包体积测量。
- 不新增专门 CI；复用现有测试和真实打包流程。包体积以实际市场提交包为准，记录构建输入、压缩方式、字节数与 MiB。
- 静态审计必须覆盖被删除字体/纹理的路径、文件名和逻辑 key；动态审计必须证明无 snapshot 启动与降级、完整 snapshot 恢复、同步后 listener 刷新且无需重启。
- 每个 task 单独提交，只暂存本 task 所有文件；不带入初始化前的修改或其他 goal 记录。

## 7. 风险、回滚与完成定义

### 7.1 主要风险

- `dna-resource` 先行约束：插件代码先切换而资源仓库尚未提供会造成发布窗口缺口。
- 旧 renderer/legacy utils 可能存在文本检索不易发现的动态路径或隐式默认字体。
- 删除大文件后某些图像链路可能仍在启动、缓存恢复或异步 listener 中访问旧路径。
- 包体积达到阈值但正常降级、帮助图标或用户可见文案被误删。
- 运行期资源状态、generation、lease 和 renderer 缓存刷新不一致。

### 7.2 回滚方案

- 每个 task 独立 commit；删除资源前保留可回滚 commit 和明确的资源清单。
- 若资源仓库验证失败，先停止删除/发布，保留本地副本，修正 manifest/资源仓库后再继续。
- 若运行回归，优先 revert 最近一个资源解析/删除 commit，恢复旧本地资源与 renderer 路径；不重写历史、不强制推送。
- snapshot 失败时继续沿用现有空 `ResourceMap`/`EncyclopediaResourceStore` 语义；不得把失败伪装成已发布完整资源。

### 7.3 完成定义

以下条件同时满足才可结束 goal：

1. 资源仓库能提供并验证完整字体及本次迁移视觉资源，或所有无法完成的跨仓库 task 已明确阻塞且由最终报告披露（不能冒充完成）。
2. 插件运行期不再依赖已删除的完整本地字体/大纹理。
3. 无 verified snapshot 时插件仍可启动并按原语义降级，图片类命令没有因缺失资源触发 `FileNotFoundError`。
4. 完整 snapshot 后主要玩家、百科、签到、公告、帮助渲染路径使用远端资源；同步后无需重启即可刷新视图。
5. README 已给出首次安装后建议执行“同步资源”的提醒。
6. 真实市场提交包优先 `<=8 MiB`；如保留有充分理由可 `<=12 MiB`，且绝对 `<16 MiB`，并记录最大剩余文件和理由。
7. 相关测试、lint、compile、加载/冒烟和静态路径审计均有实际证据，文档和回滚记录同步。
