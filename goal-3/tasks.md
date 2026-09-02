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

- [ ] 状态：pending
- 目标：覆盖首次基线、版本未变化、跨多个补丁、版本回退/重复观察、状态损坏和原子写入行为。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 05：实现 `client_update_state.json` 状态边界

- [ ] 状态：pending
- 目标：在运行期数据目录中独立持久化区服/平台基线与最近变化摘要，保持并发写安全和显式损坏错误。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 06：实现版本变化检测与新增大小计算服务

- [ ] 状态：pending
- 目标：将当前快照与历史基线比较，生成旧版本、新版本和新增大小，并在成功确认后更新状态；手动查询路径保持只读。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 02：状态一致性与重复推送风险复查

- [ ] 状态：pending
- 检查：首次订阅/首次轮询、手动查询只读、版本回退、并发写、状态损坏、历史补发和事件去重语义。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 07：为 HTTP transport 编写 fake-transport/协议测试

- [ ] 状态：pending
- 目标：覆盖 PC/安卓完整路径映射、VersionList 和资源清单读取、`fileSize` 汇总、两个平台独立失败及响应结构错误；不接受未在契约中定义的直接大小字段。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 08：实现客户端更新 HTTP transport

- [ ] 状态：pending
- 目标：按更新契约实现公开 API 读取、User-Agent、响应校验和安全失败分类；复用现有 HTTP 门禁，不下载大文件。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 09：为订阅 use case 与命令 registry 编写 Red 测试

- [ ] 状态：pending
- 目标：覆盖查询参数、订阅平台筛选、群聊管理员权限、私聊/普通用户拒绝、重复订阅、取消订阅和失败时保留订阅。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 03：transport、订阅权限与命令范围复查

- [ ] 状态：pending
- 检查：API 契约覆盖、凭据/URL 泄露、命令正则与 registry 投影、权限、订阅数据格式、错误日志和文案边界。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 10：实现订阅 use case、消息文案与命令 registry

- [ ] 状态：pending
- 目标：新增 `客户端更新`、`订阅客户端更新`、取消订阅命令及 PC/安卓筛选，接入现有 command handler 与 SubscriptionStore。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 11：为定时任务与配置编写 Red 测试

- [ ] 状态：pending
- 目标：覆盖独立开关、默认约 1 小时周期、启停幂等、任务错误可观测和配置 schema 生成。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 12：实现独立 scheduler 与 bootstrap 接线

- [ ] 状态：pending
- 目标：在生命周期中组装 transport/state/service/scheduler，独立于公告启动、停止、更新周期并写入运行期状态。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## 集中检查 04：命令、配置、生命周期与数据目录复查

- [ ] 状态：pending
- 检查：命令清单一致性、配置默认值、启动/停止泄漏、运行期目录、scheduler tombstone/状态、现有公告回归。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 13：为多平台推送与 OneBot 合并转发编写 Red 测试

- [ ] 状态：pending
- 目标：覆盖每个平台独立推送、按订阅平台筛选、目标失败隔离、OneBot 开关默认开启、非 OneBot 无效果及普通消息降级。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

## Task 14：实现推送 DTO 与 OneBot 合并转发适配

- [ ] 状态：pending
- 目标：扩展推送边界，使业务层不依赖框架组件；OneBot 合并转发安全可用时使用节点，否则按平台普通消息发送并记录原因。
- 实际完成：
- 验证证据：
- 剩余风险：
- 下一步：

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
