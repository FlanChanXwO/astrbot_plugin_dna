# 客户端更新 Target / Source 实施计划

> 对应设计：`docs/dev/client-updates-targets-design.md`
>
> 对应 PR：#41 `fix: redesign client update targets and recovery`
>
> 基线：`main@6afab31`（v0.3.2）

## 目标与约束

在一个 PR 中完成客户端更新子系统的 Target / Source 重构，并修复生产已复现的 VersionList 历史断档故障。管理员以“区服 × 账号生态 × 平台”的完整 Target 配置检测范围；用户通过严格无参数命令查询或订阅当前配置范围；底层以可复用 Source 获取真实版本并维护 baseline。

- `Target` 是用户侧唯一身份；`Source` 是技术更新源身份。
- 下载商店若最终进入相同账号生态与相同服务器，不拆 Target。
- 只有经过验证的合法 Target / Source 才能进入 registry；禁止猜 URL、branch、manifest 或客户端存在性。
- 多个 Target 可共享 Source；同一个 Source 每轮最多请求一次。
- 采用一次性垂直重构，不保留 channel/Target 双模型或临时兼容业务路径。
- 默认配置保持现有行为，只启用 CN 官服 PC / Android。
- 旧 `channels` 配置不迁移并由 typed settings 明确拒绝；state v1/v2/v3 warning 后按空状态启动且不备份；旧 `platforms` 订阅元数据幂等清理为 `{}`。
- history gap 是成功观察的降级状态，不是 contract error；不得伪造更新大小。
- `commands.json` 和 `_conf_schema.json` 继续由脚本生成，不手工维护。
- 保持精简测试布局：新增最多一个客户端更新专用测试文件，其余断言并入现有配置/命令测试。

## 1. 建立真实 Target / Source 清单

先确认事实，再写 registry。

1. 对当前已知客户端更新端点做只读探测，确认 CN 官服 PC / Android 现有 Source 契约仍有效。
2. 核实 CN bilibili 各平台当前是否存在独立客户端，以及其版本源是否与官服共用。
3. 核实全球 America / Europe / Asia / SEA / HMT 是否共享客户端包；分别确认 PC / Android / iOS 的真实版本来源。
4. 核实 iOS 使用的 App Store 条目，并确认哪些 Target 共用同一条目。
5. 整理最终 registry 数据：`target_id / display_name / region_id / ecosystem_id / platform / source_id`。
6. 对无法验证的组合不注册，并在 PR 描述中列出“候选但未登记”的原因。

建议新增长期只读检查脚本 `scripts/check_client_update_sources.py`。脚本只读取 registry 并检查当前版本，不修改 baseline、订阅或生产数据，也不下载完整补丁正文。

**验收**：每个最终 Source 至少能返回当前版本；每个 Target 都有现实发行依据并引用存在的平台一致 Source。

## 2. 引入 Target / Source typed registry

主要文件：

- 新增 `src/modules/client_updates/registry.py`
- 修改 `src/modules/client_updates/contracts.py`
- 修改 `src/modules/client_updates/__init__.py`
- 逐步淘汰 `src/modules/client_updates/channels.py` 的现行职责

工作：

1. 定义 `ClientUpdateTarget`：`target_id / region_id / ecosystem_id / platform / source_id / display_name`。
2. 定义 `ClientUpdateSource`：`source_id / platform / provider_kind / provider_config`。
3. 建立 `CLIENT_UPDATE_TARGETS` 和 `CLIENT_UPDATE_SOURCES`。
4. 校验 ID 唯一、`(region, ecosystem, platform)` 唯一、Target 引用 Source 存在且平台一致、display name 非空。
5. 提供 `resolve_client_update_target()`、`resolve_client_update_source()`、`normalize_client_update_target_ids()`、按 platform 过滤和按 source 分组能力。
6. 删除业务代码对 `_DEFAULT_CHANNEL_BY_PLATFORM` 的依赖。
7. 删除新业务代码对 `channels.py` 的依赖；不为旧 state/config 保留迁移映射，避免继续传播“channel”歧义。

测试放在新增的 `tests/test_client_updates.py`。

**提交检查点**：`refactor: add client update target and source registry`

## 3. 把版本观察改成 Source-neutral contract

主要文件：

- `src/modules/client_updates/contracts.py`
- `src/infrastructure/http/client_updates.py`
- 必要时新增 `src/infrastructure/http/client_update_app_store.py`

工作：

1. 将现有携带 `region/channel_id` 的版本快照改成 Source-neutral 观察对象。
2. 版本对象至少承载 `source_id`、用户可见 `version_text`、稳定 `revision_id`、可选 `order_key`，以及 typed provider metadata。
3. 不把所有 provider 强制塞进整数 `patchVersion`。
4. manifest provider 继续解析 VersionList / PakFilesInfo / ResDiscreteInfo。
5. 只有真实 iOS Target 核验成功时才实现 app-store provider；其只承诺当前版本可比较，无法可靠获取差分大小时保持 size unknown。
6. Transport 公开入口改为 `get_observation(source_id, baseline=...)`。

**提交检查点**：`refactor: make client update observations source-oriented`

## 4. 修复 VersionList 跳号与 history gap

主要文件：

- `src/infrastructure/http/client_updates.py`
- `src/modules/client_updates/contracts.py`
- `src/modules/client_updates/service.py`
- `tests/test_client_updates.py`

先写回归测试，再改实现。必须先出现以下红测：

1. `baseline=100, VersionList=[100,102,103]`：现实现错误要求 101。
2. `baseline=100, VersionList=[102,103]`：现实现返回 contract failure。
3. 生产形态的大跨度编号跳跃。

修复规则：

1. Transport 只遍历 VersionList 中实际存在、且位于 baseline 之后的条目。
2. baseline 仍在窗口时，`history_complete=True`，只计算实际后续条目的 manifest size。
3. baseline 已离开窗口时，当前版本仍成功返回，`history_complete=False`，`added_size_bytes=None`。
4. Service 层 `_sum_new_patch_sizes()` 同样移除 `range()` 连续整数假设，只汇总 observation 实际返回的版本/size。
5. 真正的 manifest 缺失或结构损坏仍为 contract failure；current < baseline 仍按 rollback 处理。

**提交检查点**：`fix: recover client updates from sparse version history`

## 5. State v4：baseline 改为 Source 身份

主要文件：

- `src/modules/client_updates/state.py`
- `src/modules/client_updates/contracts.py`
- `tests/test_client_updates.py`

工作：

1. schema version 固定为 4，baseline key 改为 `source_id`。
2. event key 使用 `source_id + previous.revision_id + current.revision_id`。
3. change 与 pending delivery 保存事件创建时的 `target_ids` 快照。
4. v1/v2/v3 load 时 warning 后返回空 state，不迁移、不备份旧 baseline 或 pending event。
5. 首次成功 poll 建立 baseline；query 仍保持只读。
6. baseline + pending event 保持原子落盘；写失败恢复旧文件。

**提交检查点**：`refactor: reset legacy client update state to source baselines`

## 6. Service 按 Source 去重、按 Target 展开

主要文件：

- `src/modules/client_updates/service.py`
- `src/modules/client_updates/delivery.py`
- `src/modules/client_updates/routing.py`
- `tests/test_client_updates.py`

工作：

1. Service 构造时接收 enabled `target_ids`，不再接收 channels。
2. 每轮按 `source_id` 分组，确保一个 Source 只请求一次。
3. query 每 Source 请求一次、不修改 baseline，再展开为请求覆盖的 Target。
4. poll 正常更新或 history-gap 后原子推进 source baseline，并映射到事件发生时启用的 Target 集合。
5. pending delivery 固定创建时 Target 集合，避免之后配置变化改变已生成事件语义。
6. 一个 Source 失败继续处理其它 Source；只有全部失败才整体 unavailable。

必须覆盖“全球 5 个区服 Target 共用 1 个 PC Source 时只请求一次”和“history-gap 只通知一次”的测试。

**提交检查点**：`refactor: route client update observations through targets`

## 7. 配置改为 `client_updates.targets`

主要文件：

- `src/infrastructure/config/settings.py`
- `src/infrastructure/config/schema.py`
- `tests/test_config.py`
- `_conf_schema.json`（生成）

工作：

1. `ClientUpdatesSettings.channels` 改成 `targets: list[str]`。
2. options 从 `CLIENT_UPDATE_TARGETS` 生成。
3. 默认仅 `cn-official-pc`、`cn-official-android`。
4. 旧 `channels` 不迁移，typed settings 以未知字段明确拒绝。
5. schema 不继续暴露旧 `channels`。
6. 保持 `enabled/check_minutes/merge_forward` 不变。
7. 非法 Target ID 明确 ValidationError。
8. 运行 `python3 scripts/generate_config_schema.py`。

**提交检查点**：`feat: expose client update targets in config`

## 8. 无参数命令与配置驱动订阅

主要文件：

- `src/modules/client_updates/commands.py`
- `src/modules/client_updates/contracts.py`
- `src/modules/client_updates/service.py`
- `src/modules/client_updates/routing.py`
- `src/modules/client_updates/messages.py`
- `tests/test_entry_commands.py`
- `tests/test_client_updates.py`

目标命令：

```text
客户端更新
订阅客户端更新
取消订阅客户端更新
```

工作：

1. 三个命令改为严格无参数；平台名、Target ID 和其它尾随参数均不匹配。
2. query 始终读取当前配置启用的全部 `target_ids`，且不修改 baseline。
3. 新订阅 `extra_data` 保存 `{}`，只表达订阅 identity。
4. 生命周期初始化时将旧 `{"platforms":[...]}` 幂等清理为 `{}`；损坏元数据 warning 后跳过。
5. 所有有效订阅在 AstrBot 标准插件重载后统一使用当前配置 Target；不增加运行中热配置监听器。
6. pending event 固定创建时的 Target 集合，配置重载不改变既有事件语义。
7. 消息显示完整 Target 名称；同 Source 多 Target 可合并，但必须列出实际覆盖 Target。
8. 运行 `python3 scripts/generate_commands_manifest.py`。

**提交检查点**：`feat: make client update subscriptions config-driven`

## 9. 帮助、文档与维护入口

主要文件：

- `src/resources/help/help.json`
- `docs/usage/commands.md`
- `docs/usage/configuration.md`
- `docs/dev/maintenance.md`（若保留 Source 检查脚本）
- `tests/test_help_subscriptions.py`

解释 Target = 区服 × 账号生态 × 平台、配置是唯一 Target 选择入口、三个命令均无参数，并明确下载入口不等于账号生态。文档不复制完整 Target 表，完整 options 仍以生成 schema 为事实源。

**提交检查点**：`docs: document client update targets and recovery`

## 测试布局

当前仓库已有 15 个顶层测试文件。此次只新增：

- `tests/test_client_updates.py`

集中覆盖 registry、transport/provider、service、state v4 reset、subscription metadata cleanup、history-gap。

现有文件继续负责：

- `tests/test_config.py`：配置模型和 schema 投影
- `tests/test_entry_commands.py`：严格无参数命令匹配
- `tests/test_help_subscriptions.py`：帮助中的订阅/取消订阅可发现性

不重新引入 `test_goal*_client_updates_*` 系列。

## 验证顺序

每个检查点先跑最小相关测试，最终 PR head 跑：

```bash
python3 scripts/generate_config_schema.py
python3 scripts/generate_commands_manifest.py

python3 -m pytest tests/test_client_updates.py tests/test_config.py tests/test_entry_commands.py tests/test_help_subscriptions.py -q
ruff check src/modules/client_updates src/infrastructure/http/client_updates.py src/infrastructure/config tests/test_client_updates.py tests/test_config.py tests/test_entry_commands.py
python3 -m compileall src main.py

python3 -m pytest
ruff check .
python3 -m compileall .
```

随后 GitHub Actions 的 plugin load 与 plugin lifecycle 必须通过。

## 真实环境验收

代码和 CI 全绿后，在服务器隔离目录执行，不直接热改生产：

1. 用只读 smoke script 检查全部登记 Source。
2. 构造当前生产相同的旧 v3 baseline：PC `1410192`、Android `1010184`。
3. 验证旧 state 被 warning 后忽略，首次成功 poll 建立 v4 baseline。
4. query 必须返回当前版本；history gap 只能表现为大小未知，不能再返回“客户端更新暂时无法获取”。
5. poll 第一次可产生 history-gap resync 并推进 baseline；第二次相同版本不得重复通知。
6. 验证同 Source 多 Target 每轮只产生一次实际 HTTP observation。
7. 全程不触碰生产订阅、生产 baseline 和正在运行的插件实例。

## PR 提交结构与合并门槛

整个实现继续使用 PR #41，不拆新 PR。设计提交已存在；后续建议按以下原子检查点追加：

1. `docs: add client update implementation plan`
2. `refactor: add client update target and source registry`
3. `refactor: make client update observations source-oriented`
4. `fix: recover client updates from sparse version history`
5. `refactor: reset legacy client update state to source baselines`
6. `refactor: route client update observations through targets`
7. `feat: expose client update targets in config`
8. `feat: make client update subscriptions config-driven`
9. `docs: document client update targets and recovery`

PR #41 只有同时满足以下条件才转 Ready：

- Target registry 包含全部当前可验证合法组合，非法组合未登记。
- 配置 options 与 Target registry 一致。
- CN 官服/B服、全球各独立服务器能够按真实账号生态和平台表达。
- 同 Source Target 不重复轮询。
- 查询与订阅命令严格无参数并跟随配置 Target；pending delivery 固定事件创建时的 Target。
- VersionList 跳号不再失败。
- baseline 掉出历史窗口时 query 可用、poll 可一次性 resync，且不伪造大小。
- 旧 `channels` 配置被拒绝；旧 state 被忽略并重建 v4 baseline；旧 `platforms` 元数据清理为 `{}`。
- 生成投影无漂移。
- 相关测试、完整 pytest、ruff、compileall、plugin load、plugin lifecycle 全绿。
- 隔离环境真实上游和生产旧状态复现验证通过。
