# 客户端更新 Target / Source 重构设计

## 背景

当前客户端更新子系统虽然已经引入 `channel_id`，但用户侧仍主要按
`platform`（PC / Android）工作：

- `ClientRegion` 只有 `CN`；
- `CLIENT_UPDATE_CHANNELS` 只有 `pc_cn` 与 `android_astc_cn`；
- 配置 `client_updates.channels` 只能选择这两个值；
- 查询、订阅和投递仍以 `platforms` 作为筛选语义；
- 订阅 `extra_data` 只保存 `{"platforms": [...]}`；
- 用户消息只显示“国服 PC / 安卓”，不能表达账号生态和真实服务器。

这无法正确表达真实用户身份：全球服 America / Europe / Asia / SEA / HMT
之间角色数据不互通；国服官方账号与 bilibili 账号属于不同账号生态；而
Steam、Epic、TapTap、WeGame 等下载入口只要最终进入同一账号生态和服务器，
就不应该被误建成独立“渠道”。

同时，生产环境已复现一个版本检测故障：transport 把 `patchVersion` 当作
连续整数，通过 `range(previous + 1, latest + 1)` 推断中间版本。当版本号发生
合法跳跃，或旧 baseline 已离开上游有限的 `VersionList` 历史窗口时，查询和
定时轮询都会永久落入 `patch version entry is missing`。

本设计要求在一个 PR 中同时完成身份模型重构和 history-gap 修复。

## 目标与非目标

目标：

1. 用户配置的最小单位改为 **Target**：`区服 × 账号生态 × 平台` 的合法组合。
2. 所有当前已验证存在的 Target 都出现在 `client_updates.targets` 配置 options；
   非法组合不能被构造。
3. 技术更新端点独立建模为 **Source**；多个 Target 可共享一个 Source。
4. 配置和展示使用 Target；查询、订阅命令不接受筛选参数，版本观察、补丁大小和 baseline 使用 Source。
5. 支持所有已验证平台；iOS 仅在核验到真实 Target 与 App Store 条目后登记，并允许不同平台使用不同 provider。
6. 修复合法版本号跳跃和 baseline 脱离历史窗口造成的永久失败。
7. 明确拒绝旧 `channels` 配置；旧 v1/v2/v3 state 不迁移；旧 `platforms` 订阅元数据一次性清理为 `{}`。
8. 采用一次性垂直重构，不保留 channel/Target 双模型或临时兼容业务路径。

非目标：

- 不把 Steam、Epic、TapTap、WeGame、好游快爆、联想 PC 商店等单纯下载入口
  建成独立 Target。
- 不猜测未验证的 B 服、全球服或 iOS 更新 URL、branch 或 manifest。
- 不修改账号、签到、资源同步、玩家查询等其它业务模块。
- 首版不把 Target/Source registry 远程下发到 `dna-resource`。

## 核心模型

### Target：用户可见身份

```text
ClientUpdateTarget
  target_id: str
  region_id: str
  ecosystem_id: str
  platform: ClientPlatform
  source_id: str
  display_name: str
```

- `region_id`：真正隔离玩家数据的服务器；
- `ecosystem_id`：账号/发行生态，例如 `official`、`bilibili`；
- `platform`：`pc`、`android`、`ios`；
- `source_id`：该 Target 实际使用的更新检测 Source；
- `display_name`：稳定的用户可见名称。

Target 是配置和展示的唯一用户侧主键；命令不提供临时 Target 选择能力。

### Source：技术更新源

```text
ClientUpdateSource
  source_id: str
  platform: ClientPlatform
  provider_kind: str
  provider_config: typed provider config
```

首版必须支持 `manifest_cdn`（现有 PC / Android 的 `VersionList + manifest` 协议）。只有核验到合法 iOS Target 与真实 App Store 条目时才实现并登记 `app_store` provider；不得为了预留能力创建猜测实现。

Source 只负责版本观察、补丁大小和 baseline，不携带账号生态或服务器语义。

现有 `ClientVersionSnapshot` 不能继续把 `region/channel_id` 当成版本身份，因为一个
Source 可能同时服务多个区服 Target。实现时应把版本快照改成 source-neutral：

```text
ClientSourceVersion
  source_id: str
  version_text: str
  revision_id: str
  order_key: int | tuple[int, ...] | None
  provider_metadata: typed provider metadata
```

- `revision_id` 用于稳定判断“是否同一版本”；
- `order_key` 只在 provider 能可靠比较前后顺序时使用；
- manifest provider 可以继续把 patch/build 信息保存在 typed metadata 中；
- App Store 等 provider 不需要伪造整数 `patchVersion`。

`ClientUpdateChange` 同样改成 source-level change：携带 `source_id`、previous/current
source version 和可选更新大小；Target 集合由 service 在 Source -> Target 映射阶段附加，
不再把 `region` 或 `channel_id` 塞回版本对象。

如果全球五个服务器共用同一个官方 PC 客户端，则：

```text
global-america-official-pc  ┐
global-europe-official-pc   │
global-asia-official-pc     ├─> global-official-pc-source
global-sea-official-pc      │
global-hmt-official-pc      ┘
```

这样用户仍按真实服务器配置和订阅，但底层只轮询一次客户端版本源。

> 2026-09-08 的只读核验结论与本轮实际登记范围见 `docs/dev/client-update-source-investigation.md`。

## Target 候选目录

实现 PR 必须先核验当前发行事实和真实 Source 映射，再登记最终 Target。

### 国服

账号生态：

- `official`：官方账号系统；官网、TapTap、WeGame 等下载入口不再细分；
- `bilibili`：使用 bilibili 客户端和 B 站账号的独立生态。

候选：

```text
cn-official-pc
cn-official-android
cn-official-ios
cn-bilibili-pc
cn-bilibili-android
cn-bilibili-ios
```

bilibili 的每个平台组合必须在实现期确认当前公开客户端确实存在；不得为了补齐矩阵
而注册不存在的平台。

### 全球服

服务器独立：

```text
global-america
global-europe
global-asia
global-sea
global-hmt
```

账号生态首版为 `official`。Steam / Epic 等只要进入相同 Hero Games 账号生态，
不单独形成 ecosystem。

每个已验证服务器按平台形成：

```text
<region>-official-pc
<region>-official-android
<region>-official-ios
```

若实现期发现某个服务器不支持某平台，则不注册该非法组合。

## Registry 契约

每个 Target 必须满足：

1. `target_id` 唯一；
2. `(region_id, ecosystem_id, platform)` 唯一；
3. `source_id` 指向存在且平台一致的 Source；
4. `display_name` 非空且无歧义；
5. 组合存在当前可验证的发行事实。

每个 Source 必须满足：

1. `source_id` 唯一；
2. provider config 通过 typed 校验；
3. 不混入账号生态或 region 过滤逻辑；
4. 有只读真实上游 smoke probe 能获取当前版本；
5. 不凭命名推测不存在的技术端点。

## 配置设计

当前：

```yaml
client_updates:
  channels:
    - pc_cn
    - android_astc_cn
```

改为：

```yaml
client_updates:
  targets:
    - cn-official-pc
    - cn-official-android
```

规则：

- `_conf_schema.json` options 从 Target registry 生成；
- 用户直接选择完整合法 Target，不提供三个可自由拼接的筛选框；
- 默认值仍只有 CN 官服 PC / Android，升级不会自动启用全球服、B服或 iOS；
- 旧 `channels` 不迁移且不继续出现在生成 schema 中；typed settings 必须将其视为未知字段并明确拒绝；
- 用户升级时必须将配置手工改为 `targets`，其它 `client_updates` 设置语义保持不变。

## 查询与订阅语义

三个命令均为严格无参数命令：

```text
客户端更新
订阅客户端更新
取消订阅客户端更新
```

- `客户端更新` 查询当前配置启用的全部 Target；
- `订阅客户端更新` 只保存当前群的订阅身份，不固化 Target 选择；
- 所有有效订阅在插件按 AstrBot 标准生命周期重载后统一使用当前 `client_updates.targets`；
- 不增加运行中配置热更新监听器；
- 任意平台名、Target ID 或其它尾随参数都不匹配这些命令；
- `取消订阅客户端更新` 仍取消当前群整条客户端更新订阅。

新订阅 `extra_data` 固定为：

```json
{}
```

旧订阅 `{"platforms": [...]}` 在生命周期初始化时幂等清理为 `{}`，保留订阅 identity 与 enabled 状态。损坏元数据必须 warning 后跳过，不能伪装成清理成功。

投递使用当前配置 Target；pending event 仍冻结事件创建时的 `target_ids`，避免后续重载改变已落盘事件语义。

## Source 级观察与 Target 级投递

```text
enabled target_ids
  -> group by source_id
  -> poll each source exactly once
  -> source-level version change
  -> map to affected target_ids
  -> route by subscription target intersection
```

baseline 以 `source_id` 保存，同源 Target 不重复状态。

pending event 固定：

- `source_id`；
- 版本变化；
- 事件创建时受影响的 `target_ids`；
- 每个 pending delivery target 实际匹配的 `target_ids`。

这样配置或订阅在事件创建后变化，也不会改变已落盘事件的投递语义。

消息必须显示完整 Target。多个 Target 共用 Source 时可以合并结果，但要列出该订阅
实际覆盖的 Target，不能退回只显示“国服 PC”或“安卓”。

## VersionList 断档修复

### 移除连续整数假设

禁止继续使用：

```python
range(previous_patch_version + 1, latest.patch_version + 1)
```

正确算法：

1. 解析 `VersionList` 实际存在的全部记录；
2. 按协议稳定顺序排序；
3. 若 baseline 条目仍在窗口中，只读取其后实际存在记录的 manifest；
4. 不因为整数编号缺失而报错；
5. service 层汇总更新大小时也必须直接汇总 transport 返回的实际版本记录，不能再用
   `_sum_new_patch_sizes()` 一类 `range(previous + 1, current + 1)` 逻辑重建连续整数区间。

示例：

```text
baseline = 100
VersionList = [100, 102, 103]
```

这是合法历史，新增记录是 `[102, 103]`，不得要求 `101`。

### history gap

若 baseline 已不在当前 `VersionList`，系统无法证明历史完整：

- 这不是 `contract` error；
- 返回当前版本；
- `history_complete = false`；
- `added_size_bytes = None`；
- 查询显示旧版本、当前版本和“历史窗口不完整，新增大小不可完整计算”。

查询保持只读，不推进 baseline。

定时 poll 遇到 history gap：

1. 生成一次降级 source-level change；
2. 有订阅时可发送“版本已变化，但历史窗口不完整，大小未知”的通知；
3. baseline 与 pending event 按现有原子性要求落盘；
4. 推进到当前版本，避免每轮重复同一 gap；
5. 不伪造 `0 B` 或完整新增大小。

真实 JSON 损坏、HTTP 状态错误、manifest 损坏仍然是错误，不得被 history-gap 容错吞掉。

## Source Provider

### `manifest_cdn`

保留现有 PC / Android 能力，入口改为 source-oriented：

```text
get_observation(source_id, baseline?)
```

provider config 负责 primary/fallback URL、branch、manifest key、User-Agent 和平台特有
资源目录规则。

### `app_store`

iOS 不强行套用 PC / Android 的 manifest 协议。首版只要求可靠获取当前版本和稳定
`revision_id`；如果商店能够提供可比较 build/version key，则填充 `order_key`，否则只做
相等/不等判断，不执行伪造的 rollback 推断。若不能可靠获得差分包大小，则
`added_size_bytes` 为 `None`，但查询和更新通知仍正常。

国服官方、B服和全球服若使用不同商店条目则注册不同 Source；实际共享时复用 Source。

## 状态升级边界

新 schema 固定为 v4，baseline 以 `source_id` 为 key。旧 v1/v2/v3 state 不迁移、不备份：

- load 发现旧 schema 时记录明确 warning，并以空 state 启动；
- 首次成功 poll 以真实 observation 建立新 baseline；
- 第一次写入即持久化为 v4；
- 旧 pending events 不保留，禁止猜测其 Source 或 Target 语义；
- query 始终只读，不因旧 state 或 history gap 建立 baseline；
- 不删除或改写原文件来伪装迁移成功，只有正常 v4 原子写路径才替换 state。

## 错误边界

保留可观察错误分类：

- `network`：网络/超时；
- `status`：非成功 HTTP；
- `contract`：真实结构违反已验证契约；
- `server`：响应/transport 边界异常；
- `history_gap`：成功 observation 的“不完整历史”状态，不是 transport error。

一个 Source 失败不能拖垮其它 Source。部分成功时返回成功 Target；所有目标均失败时
才返回整体 unavailable。

## 测试矩阵

### Registry / 配置

- Target / Source ID 唯一；
- `(region, ecosystem, platform)` 唯一；
- Target -> Source 引用有效且平台一致；
- `_conf_schema.json` options 与 Target registry 一致；
- 非法 Target 配置被拒绝；
- 旧 `channels` 被 typed settings 明确拒绝，不做迁移；
- 默认仅启用 CN 官服 PC / Android。

### 命令 / 订阅

- 三个命令只接受严格无参数形式，任何平台或 Target selector 都不匹配；
- 查询和投递只使用当前配置启用 Target；
- 新订阅保存 `{}`；
- 旧 `platforms` 元数据一次性幂等清理为 `{}`；
- 插件标准重载后，所有有效订阅统一跟随当前配置 Target。

### Source / 去重 / 投递

- 多 Target 共用 Source 时每轮只调用一次 transport；
- Source change 映射到正确 Target 集合；
- 一个 Source 失败不影响其它 Source；
- pending event 固定创建时的 Target 语义。

### 断档回归

至少覆盖：

1. `100 -> [100, 101, 102]` 正常连续；
2. `100 -> [100, 102, 103]` 合法跳号；
3. `100 -> [102, 103]` baseline 掉出窗口；
4. 大跨度真实编号跳跃；
5. 当前版本等于 baseline；
6. 真正版本回滚；
7. manifest 真实缺失/损坏；
8. query gap 不改 baseline；
9. poll gap 只产生一次降级事件并推进 baseline；
10. 下一轮相同版本不重复通知。

### 状态与订阅升级

- v4 source baseline round-trip 与原子写；
- v1/v2/v3 warning 后按空 state 启动，不迁移、不备份；
- 首次成功 poll 建立 baseline；
- 旧 `platforms` 元数据清理后，订阅数量、enabled 状态和身份不丢失。

### 真实上游 smoke

在隔离环境中只读验证每个最终登记 Source：

- 能获取当前版本；
- manifest source 能解析当前 `VersionList`；
- app-store source 能解析当前公开版本；
- 不下载完整补丁正文；
- 不修改生产 baseline / 订阅。

## 单 PR 实施顺序

整个功能在一个 PR 中完成，但使用可回滚的小提交：

1. 协议调查与 Target/Source 事实确认；
2. Target / Source typed registry 与验证器；
3. transport source 化和 history-gap 回归修复；
4. source-level service/state v4 与轮询去重；
5. Target-level command/subscription/routing；
6. 配置严格校验和旧订阅元数据清理，重新生成 schema/commands projection；
7. 用户消息、帮助和必要文档；
8. 真实上游 smoke、完整 pytest、ruff、compileall、plugin lifecycle。

中途不把半完成的 Target/Source 模型部署到生产。

## 验收标准

PR 可合并前必须满足：

1. 配置可选择全部当前验证合法的区服 × 账号生态 × 平台 Target；
2. 下载商店不会被误当成独立账号生态；
3. 不存在的组合不会进入 options；
4. 同 Source 多 Target 每轮只请求一次；
5. 查询和订阅命令不接受 selector，并严格跟随配置中的完整 Target 集合；
6. 消息显示完整 Target；
7. 现有生产旧 baseline 不再导致“客户端更新暂时无法获取”；
8. `100 -> [100, 102, 103]` 正常按实际记录计算；
9. `100 -> [102, 103]` 返回 history-gap，poll 一次性安全 resync；
10. 旧 `channels` 配置被明确拒绝；v1/v2/v3 state warning 后为空；旧订阅元数据清理为 `{}`；
11. `generate_commands_manifest.py` 与 `generate_config_schema.py` 生成投影无漂移；
12. 相关测试、完整 pytest、ruff、compileall 与 AstrBot plugin lifecycle 全部通过；
13. 服务器隔离验证通过后才进入生产部署。

## 设计结论

不再继续把旧 `channel_id` 扩成更多“伪渠道”，而是明确分离：

- **Target**：用户关心的 `服务器 × 账号生态 × 平台`；
- **Source**：客户端版本和补丁的技术更新来源。

Target 负责配置、路由和展示；无参数查询/订阅统一使用配置目标；Source 负责 provider、版本观察、补丁大小和
baseline。该边界既能正确表达国服官服/B服和全球多个数据隔离服务器，也能避免同一
客户端包重复轮询，并为 iOS 等不同更新协议提供扩展点。

同一个 PR 同时移除 VersionList 连续整数假设并处理 history gap，使客户端更新从
“平台伪装成渠道”转为可验证、升级边界明确、可独立测试的 Target/Source 模型。
