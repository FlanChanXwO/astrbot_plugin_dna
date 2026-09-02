# Goal 3 Tasks：客户端更新查询与订阅推送

> 规则：每轮只执行第一个未完成 task；所有代码改动必须先 Red → Green → Refactor。每三个普通 task 后执行一次集中检查。每个 task 完成后填写“实际完成、验证证据、剩余风险、下一步”。

## Task 01：固化设计规格与实现边界

- [x] 状态：completed
- 目标：将已确认的客户端更新设计整理为可审查的项目规格，核对 API 契约、现有公告模式、配置与命令 registry 边界。
- 实际完成：新增 `docs/superpowers/specs/2026-09-02-client-updates-design.md`，明确了国服 PC/安卓完整 URL、安卓资源目录来源、清单大小汇总规则、独立基线与 pending 投递状态、命令 registry 登记、独立 scheduler、OneBot 合并转发和部分失败语义；同步收敛 `goal-3/plan.md` 与后续测试任务的大小口径。
- 验证证据：初次审查发现 7 项歧义；第二次审查确认仅剩 plan.md 的直接大小表述不一致；修订后第三次独立审查结论为 `APPROVED`。`git diff --check` 无输出，规格共 253 行且包含目标、边界、数据流、错误、一致性、测试和回滚章节。
- 剩余风险：实现阶段仍需用 fake API fixture 验证实际 Android `VersionList` 是否提供可确定资源目录号；参考契约未定义直接更新总大小字段，v1 按 `fileSize` 汇总。
- 下一步：Task 02，先为版本模型、版本键排序、资源清单大小汇总与结构校验编写并运行 Red 测试。

## Task 02：为版本模型与大小归一化编写 Red 测试

- [x] 状态：completed
- 目标：覆盖 PC/安卓版本解析、版本键数值排序、展示版本格式、两类资源清单的 `fileSize` 汇总、去重和结构错误；不测试未在契约中定义的直接大小字段。
- 实际完成：新增 `tests/test_goal3_task02_version_normalization.py`，以 `src.modules.client_updates.contracts` 的公共 seam 固化 `ClientPlatform`、`parse_version_list`、`sum_patch_file_sizes` 和 `ClientUpdateStructureError` 预期契约；覆盖 PC/安卓最新版本解析、整数排序、展示版本、安卓资源目录号、两类清单合并去重、空清单、大小冲突、非负整数校验及 malformed 结构。
- 验证证据：在临时补齐现有测试环境所需的 ignored `tests/.data/resource/id2name.json` 后，运行 `python3 -m pytest -q tests/test_goal3_task02_version_normalization.py`，因实现尚不存在而在收集阶段明确失败：`ModuleNotFoundError: No module named 'src.modules.client_updates'`（Red）；`ruff check tests/test_goal3_task02_version_normalization.py`、`ruff format --check tests/test_goal3_task02_version_normalization.py`、`python3 -m compileall -q tests/test_goal3_task02_version_normalization.py` 及 `git diff --check` 均通过，LSP 诊断无错误。测试用的临时 `.data` 已清理，未纳入提交。
- 剩余风险：当前仅证明测试在缺少领域实现时会失败；Task 03 需要严格按这些公共 seam 实现，并用真实 API fixture 补充 Android 资源目录字段与清单结构的 Green 回归。工作树缺少被忽略的 `tests/.data` 时，pytest 仍需由运行环境临时提供该既有 fixture。
- 下一步：Task 03，实现 typed contract、版本解析与大小归一化逻辑。

## Task 03：实现 typed contract、版本解析与大小归一化

- [x] 状态：completed
- 目标：新增客户端更新领域 contract 和纯解析逻辑；严格暴露结构错误，不依赖 AstrBot event。
- 实际完成：新增 `src/modules/client_updates/` 领域包：以 `ClientPlatform`/`ClientRegion` 和不可变 `ClientVersionSnapshot` 固化平台、区服、原始版本键、patch 版本、安卓资源目录及展示版本；`parse_version_list` 严格校验 `VersionList` 并按数值版本键选择最新记录；`sum_patch_file_sizes` 严格读取 PC/安卓目标 `pakFileInfos`，合并 `PakFilesInfo` 与 `ResDiscreteInfo`，按原始非空 `fileName` 去重并拒绝大小冲突、负数、布尔值和缺失结构。
- 验证证据：运行 `python3 -m pytest --confcutdir=tests -q tests/test_goal3_task02_version_normalization.py`，19 项全部通过；`pyright src/modules/client_updates tests/test_goal3_task02_version_normalization.py` 报告 0 errors/0 warnings/0 informations；`ruff check`、`ruff format --check`、`python3 -m compileall -q` 均通过，LSP 诊断无错误。使用 `--confcutdir=tests` 是因为当前独立工作树缺少既有 `tests/.data` 且环境未安装 `astrbot`，项目根 `conftest.py` 无法加载；该环境问题未修改产品代码。
- 剩余风险：Android 实际服务端响应若包含与数字 key 不同的显式资源目录字段，当前实现按契约允许的数字 key 原样作为目录号；后续 Task 07/08 需用 fake API fixture 验证真实响应、HTTP 错误分类及路径映射。当前模块只负责纯解析，不包含 transport、基线或调度。
- 下一步：集中检查 01，复查领域模型、版本比较、大小口径和异常边界。

## 集中检查 01：领域模型与 API 解析复查

- [x] 状态：completed
- 检查：需求偏离、类型诊断、Red/Green 证据、版本比较、大小口径、异常可见性、是否引入无依据限制。
- 实际完成：对照 `input.md`、`plan.md`、更新 API 契约和 Task 02 测试复核了当前客户端更新领域：仅支持国服 PC/安卓；版本 key 使用数值比较；展示版本由四段字段组成；安卓保留原始资源目录 key；两类清单按原始 `fileName` 去重并拒绝大小冲突；未读取未定义的直接总大小字段；模块无 AstrBot/HTTP/文件 IO 依赖，也没有凭据、URL 或大文件处理残留。
- 验证证据：目标测试 `python3 -m pytest --confcutdir=tests -q tests/test_goal3_task02_version_normalization.py` 为 19 passed；`pyright src/modules/client_updates tests/test_goal3_task02_version_normalization.py` 为 0 errors；`ruff check .`、目标范围 `ruff format --check`、`python3 -m compileall -q .` 和目标 LSP 诊断通过。全仓 `ruff format --check .` 与全仓 `pyright` 仍报告基线已有的大量格式/类型问题，未发现属于本次模块的新增问题；标准 pytest 受当前工作树缺少既有 `tests/.data` 且环境未安装 `astrbot` 阻塞，已用不加载根 conftest 的纯领域命令完成验证。Goal 基线范围 `git diff --check b49475a36f02e33752fc74aad2cf6f6bca637994..HEAD` 仅发现规格文档第 3、4 行的两处 trailing whitespace。
- 剩余风险：本轮未覆盖后续 HTTP transport、基线状态、订阅和 scheduler；Android 服务端若提供未在契约命名的显式资源目录字段，仍需后续真实/fake fixture 验证。唯一已发现的本范围可修复项是规格文档行尾空白，见下一修复 task。
- 下一步：先完成修复 Task 03.1，再进入 Task 04。

## 修复 Task 03.1：清理客户端更新规格的行尾空白

- [x] 状态：completed
- 目标：移除 `docs/superpowers/specs/2026-09-02-client-updates-design.md` 第 3、4 行的 trailing whitespace，不改变文档内容。
- 实际完成：移除规格文档日期与状态两行末尾的多余空格，未改变可见文本或其他章节。
- 验证证据：精确替换前后仅涉及第 3、4 行行尾空白；当前工作树 `git diff --check` 无输出。
- 剩余风险：无本 task 范围内的已知风险；规格文档的业务内容未变更。
- 下一步：Task 04，为观察基线与变化检测编写并运行 Red 测试。

## Task 04：为观察基线与变化检测编写 Red 测试

- [x] 状态：completed
- 目标：覆盖首次基线、版本未变化、跨多个补丁、版本回退/重复观察、状态损坏和原子写入行为。
- 实际完成：新增 `tests/test_goal3_task04_observation_state.py`，在 `ClientUpdateService.observe`、`ClientUpdateStateStore` 等预定公共 seam 上固化首次成功观察只建基线、未变化不重复产生变化、跨补丁按区间累计、回退保留旧基线、重复新版本不重复变化、typed 状态 schema、损坏状态显式失败和原子替换失败保留旧文件等 Red 契约。
- 验证证据：先运行 `python3 -m pytest --confcutdir=tests -q tests/test_goal3_task04_observation_state.py`，在实现尚不存在时于收集阶段明确失败：`ModuleNotFoundError: No module named 'src.modules.client_updates.service'`（Red）；测试文件 `python3 -m compileall -q`、`ruff check`、`ruff format --check` 和 `git diff --check` 均通过。
- 剩余风险：Task 05/06 需要按这些公共 seam 实现状态边界和观察服务后才能进入 Green；当前 Red 尚未验证实际 JSON schema 序列化、时区处理和版本回退日志接线。
- 下一步：Task 05，实现 `client_update_state.json` 的 typed 状态读写与原子更新边界。

## Task 05：实现 `client_update_state.json` 状态边界

- [x] 状态：completed
- 目标：在运行期数据目录中独立持久化区服/平台基线与最近变化摘要，保持并发写安全和显式损坏错误。
- 实际完成：新增 `src/modules/client_updates/state.py`，提供不可变 `ClientUpdateBaseline`、显式 `STATE_VERSION`、`ClientUpdateStateError` 和异步 `ClientUpdateStateStore`；状态按 `region:platform` 分槽保存快照、带时区观察时间和最近变化摘要，加载时严格校验 schema、字段类型、版本展示和身份一致性；写入在进程内锁内通过同目录临时文件替换，并在替换失败时恢复内存基线。同步补充 `ClientUpdateChange` 领域 DTO 与客户端更新包导出。
- 验证证据：状态专用选集复用 Task 04 测试并注入仅用于收集的未实现 service 测试 shim，4 passed、5 deselected；手动异步检查覆盖 PC/安卓 round-trip、变化摘要 round-trip、损坏 JSON、非法 schema、原子替换失败保留旧文件和并发写入；Task 02 回归 19 passed；`pyright src/modules/client_updates` 为 0 errors，`ruff check .`、目标格式检查、`python3 -m compileall -q .`、LSP 诊断和 `git diff --check` 均通过。
- 剩余风险：Task 04 中依赖 `ClientUpdateService` 的 5 项行为仍待 Task 06 实现后 Green；当前尚未接入 service 的版本变化计算、回退日志或 scheduler 生命周期。状态文件跨进程并发仍依赖后续部署模型，当前保证单进程 asyncio 写安全。
- 下一步：Task 06，实现版本变化检测与新增大小计算服务，并使 Task 04 的观察行为进入 Green。

## Task 06：实现版本变化检测与新增大小计算服务

- [x] 状态：completed
- 目标：将当前快照与历史基线比较，生成旧版本、新版本和新增大小，并在成功确认后更新状态；手动查询路径保持只读。
- 实际完成：新增 `src/modules/client_updates/service.py`，实现首次成功观察只建立基线、相同版本更新观察时间且不重复生成变化、版本回退显式抛错并保留旧基线，以及按 `(previous.patch_version, current.patch_version]` 汇总补丁大小；只有大小完整且变化确认成功后才写入新基线。补充缺失/非法补丁大小与回退异常类型，并从模块包导出服务 seam。
- 验证证据：Task 04 目标测试 Green，`9 passed`；Task 02 + Task 04 回归 `28 passed`；`ruff check .`、目标格式检查、`python3 -m compileall -q .`、`pyright src/modules/client_updates`（0 errors）和 service/init LSP 诊断均通过；`git diff --check` 无输出。
- 剩余风险：手动查询只读的上层 use case、HTTP transport、订阅与 scheduler 尚未接入；当前服务要求 transport 为变化区间提供完整补丁大小映射，失败分类与日志将在 transport/scheduler 任务中接线。
- 下一步：集中检查 02，复查状态一致性、手动查询只读和重复推送风险。

## 集中检查 02：状态一致性与重复推送风险复查

- [x] 状态：completed
- 检查：首次订阅/首次轮询、手动查询只读、版本回退、并发写、状态损坏、历史补发和事件去重语义。
- 实际完成：逐项复核当前阶段的状态与观察边界：`ClientUpdateService.observe` 首次成功观察只建基线、版本回退不覆盖旧基线、同一新版本重复观察不再生成变化；`ClientUpdateStateStore` 按区服/平台分槽，在单进程 asyncio 锁内原子替换并对损坏状态显式失败；`ClientUpdateChange.event_key` 为固定的区服/平台/旧补丁/新补丁键。当前尚未实现订阅、手动查询 use case、pending delivery 或 scheduler，因此没有把这些后续语义误判为已完成；当前观察服务也不会为首次观察或历史状态隐式生成可推送事件。
- 验证证据：Task 02 + Task 04 目标回归 `28 passed`；一次性异步边界检查验证 PC/安卓并发写后 schema 与两个槽位完整、变化大小累计与重复观察去重、版本回退保留基线、损坏 JSON 原文保留；`ruff check`、目标 `ruff format --check`、`python3 -m compileall -q` 和 `git diff --check` 均通过。对照规格的 pending 事件要求确认后续轮询必须先处理既有 pending、以固定事件键去重，并由后续 Task 09/10/12/13/14 补齐订阅失败保留、手动查询只读和投递状态测试。
- 剩余风险：首次订阅失败后保留订阅、下一次成功只建基线、手动查询只读、历史 pending 补发/失败重试/取消清理尚无实现或 Green 证据；当前状态锁只覆盖单进程 asyncio，不提供跨进程协调，scheduler 仍需保证单轮串行和 pending 优先处理。`last_change` 目前只是最近变化摘要，不能替代后续固定目标 pending 事件账本。
- 下一步：Task 07，为 HTTP transport 编写 fake-transport/协议 Red 测试。

## Task 07：为 HTTP transport 编写 fake-transport/协议测试

- [x] 状态：completed
- 目标：覆盖 PC/安卓完整路径映射、VersionList 和资源清单读取、`fileSize` 汇总、两个平台独立失败及响应结构错误；不接受未在契约中定义的直接大小字段。
- 实际完成：新增 `tests/test_goal3_task07_client_updates_transport.py`，固化 `ClientUpdateTransport.get_observation(platform, previous_patch_version=...)` 与 typed observation/error seam；fake session 覆盖 PC/安卓完整 VersionList/补丁清单 URL、对应 User-Agent、安卓资源目录 key、两类清单文件名去重汇总、未知直接大小字段忽略、主机一次回退、单平台网络失败隔离和 malformed VersionList/manifest 的结构错误。
- 验证证据：Red 阶段运行 `python3 -m pytest --confcutdir=tests -q tests/test_goal3_task07_client_updates_transport.py`，在 transport 模块尚不存在时明确失败：`ModuleNotFoundError: No module named 'src.infrastructure.http.client_updates'`；测试文件 `ruff format --check`、`ruff check`、`python3 -m compileall -q` 和 `git diff --check` 均通过。测试 fake 使用标准库 `OSError` 表示网络失败，避免当前 Python 3.14 环境下已安装 aiohttp 导入 `cgi` 失败掩盖预期 Red。
- 剩余风险：Task 08 尚需实现上述 transport seam、真实 HTTP 客户端与现有请求并发门；当前仅证明契约在缺少实现时会失败，尚无 Green 的主机回退、状态码分类、响应结构校验和实际服务端 fixture 证据。Python 3.14 与现有 aiohttp 安装的兼容性需在实现时通过项目既有运行时或客户端选择处理，不在本 task 静默升级依赖。
- 下一步：Task 08，实现客户端更新 HTTP transport。

## Task 08：实现客户端更新 HTTP transport

- [x] 状态：completed
- 目标：按更新契约实现公开 API 读取、User-Agent、响应校验和安全失败分类；复用现有 HTTP 门禁，不下载大文件。
- 实际完成：新增 `src/infrastructure/http/client_updates.py`，实现 PC/安卓固定主机、完整分支路径、契约 User-Agent、VersionList 与两类补丁清单 JSON 读取；按安卓资源目录 key 构造清单路径，复用 `RequestConcurrencyGate`（注入时按 URL single-flight），只汇总 `fileSize`，不请求 `.pak`/`.sig`。新增 typed observation、失败类别和安全 transport error；网络/5xx 只回退一次，4xx、JSON/清单结构错误不回退；版本清单主机切换后，补丁清单沿用成功主机并按请求回退到另一契约主机。由于当前 Python 3.14 环境的已安装 aiohttp 导入会缺少 `cgi`，保留 `aiohttp.ClientSession` fake seam，并在导入不可用时使用项目已有 `httpx` 兼容实现，未修改依赖。
- 验证证据：先新增补丁清单主机回退 Red 测试并确认失败（`ClientUpdateTransportError: network failure`），再实现回退后运行 `python3 -m pytest --confcutdir=tests -q tests/test_goal3_task07_client_updates_transport.py`，7 项通过；Task02/04/07 相关回归共 35 项通过。`ruff check .`、目标文件 `ruff format --check`、`python3 -m compileall -q .`、`pyright src/modules/client_updates src/infrastructure/http/client_updates.py`（0 errors）和 `git diff --check` 均通过；3 个受影响 Python 文件 LSP 诊断无错误。
- 剩余风险：尚未连接真实上游执行在线冒烟；实际服务端的 HTTP 响应兼容性仍由后续集成/部署验证。客户端更新 service、订阅、scheduler 和 bootstrap 尚未实现。
- 下一步：Task 09，为订阅 use case 与命令 registry 编写 Red 测试。

## Task 09：为订阅 use case 与命令 registry 编写 Red 测试

- [x] 状态：completed
- 目标：覆盖查询参数、订阅平台筛选、群聊管理员权限、私聊/普通用户拒绝、重复订阅、取消订阅和失败时保留订阅。
- 实际完成：新增 `tests/test_goal3_task09_client_update_subscriptions.py`，以未来 `src.modules.client_updates.commands.COMMAND_SPECS`、命令 use case 和 `ClientUpdateService(..., transport=..., subscriptions=...)` 为公共 Red seam；覆盖查询默认/平台参数、查询与订阅权限、私聊/普通群成员拒绝、PC/安卓/全部筛选、同群目标幂等、取消订阅、首次 transport 失败保留订阅且不建立基线。
- 验证证据：使用项目 `.venv` 的 Python 运行 `pytest --confcutdir=tests -q tests/test_goal3_task09_client_update_subscriptions.py`，在 `commands.py` 尚不存在时于收集阶段明确失败：`ImportError: cannot import name 'commands' from src.modules.client_updates`（Red）。`ruff format --check`、`ruff check`、`compileall`、LSP 诊断和 `git diff --check` 通过。
- 剩余风险：实现尚未写入，当前 Red 只证明命令模块缺失；AstrBot test runtime requires project `.venv`，系统 Python 缺少 AstrBot；Task10 必须实现上述 seam 后再运行 Green。完整根级 conftest 未使用，因为该 worktree 缺少被忽略的 `tests/.data`。
- 下一步：集中检查 03，随后 Task10 实现订阅 use case、消息文案与命令 registry。

## 集中检查 03：transport、订阅权限与命令范围复查

- [x] 状态：completed
- 检查：API 契约覆盖、凭据/URL 泄露、命令正则与 registry 投影、权限、订阅数据格式、错误日志和文案边界。
- 实际完成：复查 `src/infrastructure/http/client_updates.py` 与更新 API 契约：固定国服 PC/安卓主机、分支和 User-Agent，仅读取 JSON，不请求 `.pak`/`.sig`，网络/5xx 只回退一次，4xx/结构错误不回退；确认错误字符串与 repr 不带原始响应、URL 或凭据。复查 `SubscriptionStore` 的 `type + unified_msg_origin + uid` 去重和原子 JSON 写入，以及 `CommandRegistry` 的显式模块索引、权限过滤和 manifest 生成边界。确认客户端更新命令、模块索引和 `commands.json` 投影目前尚未实现，符合 Task10 的后续边界，而现有 manifest 没有漂移。
- 验证证据：使用项目 `.venv` 运行 transport、版本/状态、订阅存储和命令 registry 回归，共 `62 passed`；相关 transport、contract、订阅存储、命令 registry 和模块索引文件的 LSP 诊断均无错误；静态检索确认客户端更新实现只含契约声明的公开 URL、无 token/cookie/authorization，Task09 Red 测试仍明确锁定缺失的 `src.modules.client_updates.commands`。
- 剩余风险：Task10 必须实现命令与文案、加入 `src/modules/index.py` 并重新生成 `commands.json`；use case 不能只依赖 `admin` 权限过滤，还必须拒绝私聊并校验群聊 actor，且要验证 `extra_data` 为固定顺序的 `{"platforms": ["pc", "android"]}` 子集。Task10/12/15 还需保证 transport 错误日志只记录 `kind/resource` 等安全摘要、不输出 `detail`，并处理领域 `ClientUpdateTransport` protocol 与基础设施同名实现的导入边界。当前无本轮阻塞问题。
- 下一步：Task10，实现订阅 use case、消息文案与命令 registry。

## Task 10：实现订阅 use case、消息文案与命令 registry

- [x] 状态：completed
- 目标：新增 `客户端更新`、`订阅客户端更新`、取消订阅命令及 PC/安卓筛选，接入现有 command handler 与 SubscriptionStore。
- 实际完成：新增 `ClientUpdateRequest` 与平台归一化 contract、客户端更新查询/订阅/取消订阅 service、用户可见文案和命令 use case；命令显式加入 `src/modules/index.py`，订阅以固定顺序的 `extra_data` 写入 `SubscriptionStore`，群管理员/群聊边界与失败后保留订阅均已落实；同步生成 `commands.json` 与 registry 期望清单。
- 验证证据：Task09 Red 先因缺失 `src.modules.client_updates.commands` 收集失败；实现后目标及相关回归测试 `68 passed`；`python3 -m compileall -q .`、目标文件 `ruff check`、`git diff --check` 通过；受影响文件 LSP diagnostics 无错误。
- 剩余风险：定时轮询、bootstrap 组装、待投递事件与配置/使用文档仍按后续 Task11–15 处理；项目级 `ruff check .` 仍有本任务范围外的既有问题，未扩大范围修复。
- 下一步：Task 11，为定时任务与配置编写 Red 测试。

## Task 11：为定时任务与配置编写 Red 测试

- [x] 状态：completed
- 目标：覆盖独立开关、默认约 1 小时周期、启停幂等、任务错误可观测和配置 schema 生成。
- 实际完成：新增 `tests/test_goal3_task11_client_updates_scheduler.py`，为 `NotificationSettings` 的客户端更新三项配置、正周期校验、typed schema 默认值，以及独立 `ClientUpdatesScheduler` 的任务 ID/targets/`interval@60m`、关闭开关、启停幂等和 registry error 可观测性建立 Red 契约；测试使用可注入 sleep 与事件，不依赖真实时钟。
- 验证证据：Red 阶段运行目标测试得到 `6 failed`：配置字段/schema 当前缺失，scheduler 模块当前尚未实现；随后该测试文件通过 `ruff check`、`compileall`、`git diff --check`，新文件 LSP diagnostics 为空。
- 剩余风险：本轮只登记契约，尚未实现 `ClientUpdatesScheduler`、scheduler registry 新任务 ID 或三项配置；这些留给 Task12/后续配置同步任务。
- 下一步：Task 12，实现独立 scheduler 与 bootstrap 接线。

## Task 12：实现独立 scheduler 与 bootstrap 接线

- [x] 状态：completed
- 目标：在生命周期中组装 transport/state/service/scheduler，独立于公告启动、停止、更新周期并写入运行期状态。
- 实际完成：在 `NotificationSettings` 增加客户端更新独立开关、正整数检查周期和 OneBot 合并转发配置，并生成 `_conf_schema.json`；扩展 scheduler registry 的内置任务与 schedule 解析；新增独立 `ClientUpdatesScheduler`，复用共享 `SchedulerRegistry`，实现 `interval@Nm`、启停幂等、暂停/恢复/删除、运行期重排和安全错误状态；为 `ClientUpdateService` 增加按固定 PC/安卓顺序轮询并保存成功基线的 `poll_now()`；在 `bootstrap.py` 组装 transport/state/service/scheduler，使用运行期目录下的 `client_update_state.json`，接入 Admin API 与生命周期 hook，保持公告 scheduler 独立。
- 验证证据：Task 12 新增 Red 测试先因 `poll_now()` 和 bootstrap 注入参数缺失得到 `3 failed`；Green 阶段目标与相关回归共 `102 passed`（含 Task 11、Task 12、版本/状态/transport/订阅/registry、scheduler、配置、Admin API）；`python3 -m compileall -q .`、本轮变更文件 `ruff check`、`git diff --check` 均通过；变更 Python 文件 LSP diagnostics 均为空。全仓 `ruff check .` 仍报告 25 项既有、非本轮改动问题，未扩大范围修复。
- 剩余风险：本轮 `poll_now()` 只负责 PC/安卓成功观察和基线维护；pending 事件投递、目标失败重试与 OneBot 合并转发仍按计划留给 Task 13/14。运行期状态文件会在首次成功轮询时创建，损坏时按现有 state store 显式失败。
- 下一步：集中检查 04，复查命令/配置/生命周期、运行期目录、scheduler tombstone 与公告回归。

## 集中检查 04：命令、配置、生命周期与数据目录复查

- [x] 状态：completed
- 检查：命令清单一致性、配置默认值、启动/停止泄漏、运行期目录、scheduler tombstone/状态、现有公告回归。
- 实际完成：复查命令 registry 与 `commands.json` 投影、typed 配置与 `_conf_schema.json` 投影；确认 bootstrap 的数据库、订阅、公告、客户端更新、资源缓存和渲染产物均从 AstrBot 运行期数据目录派生；复查生命周期逆序停止与客户端 scheduler 启停幂等；新增客户端更新任务 tombstone 重启回归测试。发现并修复 `build_runtime` 把可注入客户端 transport 错标为具体 HTTP class 的类型边界，改为领域 protocol 注解并给默认实现使用明确别名。
- 验证证据：命令与配置投影脚本分别报告 `commands.json exact projection: True`（63 条）和 `_conf_schema.json exact projection: True`（8 组），客户端命令与三项配置默认值均存在；命令/registry 回归 `22 passed`，配置/资源回归 `26 passed`，scheduler、tombstone 与 bootstrap 回归 `16 passed`，公告 scheduler/服务/订阅回归 `35 passed`；客户端更新相关模块、测试及调度状态测试 `pyright` 报告 `0 errors`；`python3 -m compileall -q .`、`ruff check .`、目标文件 `ruff format --check`、`git diff --check` 均通过，相关文件 LSP diagnostics 为空。
- 剩余风险：全仓 `ruff format --check .` 仍会报告既有 151 个文件待格式化，本轮未进行范围外格式化扫荡；使用说明、配置说明和数据模型文档的最终同步留给 Task 15。当前未执行真实上游网络轮询，客户端 transport 的端到端推送链路仍按后续 Task 13/14 验证。
- 下一步：Task 13，先为多平台推送与 OneBot 合并转发编写并运行 Red 测试。

## Task 13：为多平台推送与 OneBot 合并转发编写 Red 测试

- [x] 状态：completed
- 目标：覆盖每个平台独立推送、按订阅平台筛选、目标失败隔离、OneBot 开关默认开启、非 OneBot 无效果及普通消息降级。
- 实际完成：新增 `tests/test_goal3_task13_client_update_delivery.py`，以 `src.modules.client_updates.delivery` 的框架无关 seam 固化 `ClientUpdatePushTarget`、`ClientUpdatePushMessage`、`ClientUpdatePush`、`ClientUpdateDeliveryService` 与 `ClientUpdatePushAdapter` 预期契约；覆盖 PC/安卓按订阅筛选、每个目标独立尝试、单目标失败隔离、OneBot 默认合并转发、非 OneBot 忽略开关、OneBot 关闭开关时分别发送普通消息，以及合并转发失败时普通消息降级。
- 验证证据：运行 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest --confcutdir=tests -q tests/test_goal3_task13_client_update_delivery.py`，在实现不存在时于收集阶段明确 Red：`ModuleNotFoundError: No module named 'src.modules.client_updates.delivery'`；新测试文件 `ruff check`、`ruff format --check`、`python3 -m compileall -q` 与 `git diff --check` 通过。
- 剩余风险：当前仅固化推送 seam，尚未实现 DTO、订阅投递编排、AstrBot/OneBot 节点构造、日志和 bootstrap 接线；目标推送状态/pending 重试的持久化由后续 Task 14/16 验证。
- 下一步：Task 14，实现推送 DTO 与 OneBot 合并转发适配。

## Task 14：实现推送 DTO 与 OneBot 合并转发适配

- [x] 状态：completed
- 目标：扩展推送边界，使业务层不依赖框架组件；OneBot 合并转发安全可用时使用节点，否则按平台普通消息发送并记录原因。
- 实际完成：新增 `src/modules/client_updates/delivery.py`，提供框架无关的 `ClientUpdatePushTarget`、`ClientUpdatePushMessage`、`ClientUpdatePush` DTO 与 `ClientUpdatePushPort`；`ClientUpdateDeliveryService` 按订阅 JSON 平台筛选、固定 PC/安卓顺序构造消息并隔离目标失败；`ClientUpdatePushAdapter` 仅在 OneBot 且开关开启且存在转发端口时请求合并转发，端口缺失、抛错或返回失败均记录错误类型/原因并降级为逐平台普通消息，普通消息失败继续尝试同目标的其他平台消息。模块不导入 AstrBot 组件，节点构造由注入的 forward port 负责。
- 验证证据：Task 13 Red 测试在实现后 Green，目标客户端更新回归共 `56 passed`；新增日志断言确认合并失败会记录 OneBot 原因但不泄露异常原文；`pyright` 报告 `0 errors`，目标文件 `ruff check`、`ruff format --check`、`python3 -m compileall -q` 与 `git diff --check` 均通过。
- 剩余风险：当前提交固化并实现框架无关推送边界，具体 AstrBot `MessageChain`/OneBot `Node` 构造、bootstrap 注入和 pending 事件持久化仍需后续集成任务覆盖；本轮未执行真实平台发送。
- 下一步：Task 15，同步命令、配置与数据模型文档。

## Task 15：同步命令、配置与数据模型文档

- [ ] 状态：pending
- 目标：更新 `commands.json`、`_conf_schema.json`、使用说明、配置说明、数据模型和必要的 CHANGELOG；不泄露真实运行期状态或链接凭据。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 05：推送体验、安全与文档复查

- [ ] 状态：pending
- 检查：消息字段、单位格式、OneBot 适配器兼容性、失败可见性、URL/日志安全、文档和命令投影一致性。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 16：补充端到端 fake API 与持久化回归测试

- [ ] 状态：pending
- 目标：模拟首次订阅、多个轮次版本变化、PC/安卓分别失败、多个群订阅、取消后重新订阅和状态重载。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 17：执行最小相关验证与修复本范围失败

- [ ] 状态：pending
- 目标：运行目标测试、类型/编译检查和 ruff；只修复本次客户端更新变更引入或归属的失败。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 18：集中检查 06：候选版本全链路复查

- [ ] 状态：pending
- 检查：从命令入口、transport、状态、订阅、scheduler、推送、配置、文档、数据一致性和回滚路径检查全链路。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 19：执行最终测试、构建和代码审查

- [ ] 状态：pending
- 目标：运行项目要求的 compileall、pytest、ruff，并完成 code-review-expert 级别自审；确认没有高风险已知问题。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 20：终审、回滚核对与 goal 完成

- [ ] 状态：pending
- 目标：复核 input/plan/tasks 与实际实现一致，确认文档、配置、测试、回滚说明完整；通过后再登记 goal 完成。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：
