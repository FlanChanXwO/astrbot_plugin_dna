# 客户端更新查询与订阅推送设计

> 日期：2026-09-02
> 状态：已完成需求澄清，待实现
> 目标工作树：`codex/client-updates-goal`

## 1. 目标与边界

为 AstrBot 插件增加“客户端更新”查询和“订阅客户端更新”定时推送。首版以公开更新 API 为数据源，支持国服 PC 与国服安卓的游戏客户端/资源版本变化检测，并告知版本变化和本次新增更新大小。

### 包含

- 查询 PC、安卓当前公开的最新资源版本。
- 保存每个平台/区服上次成功观察到的版本基线。
- 计算两次成功观察之间新增补丁的更新大小。
- 群聊管理员订阅、取消订阅，并按平台筛选推送。
- 独立的每小时定时检查任务。
- OneBot 合并转发输出开关；非 OneBot 平台不受该开关影响。

### 不包含

- 客户端安装包下载、安装、自动升级或分片下载。
- `PakJumpUrl.json` 渠道跳转地址展示。
- Android Zeus SDK 插件更新。
- PC/安卓以外的平台、非国服区服和未经契约验证的渠道路径。
- 下载地址、MD5、强制更新、重启标记等扩展元数据的默认展示。

## 2. 已确认的产品行为

### 查询命令

- `客户端更新`：查询 PC 与安卓。
- `客户端更新 PC`：只查询 PC。
- `客户端更新 安卓`：只查询安卓。
- 已有定时观察基线时，展示：区服、平台、上次版本、当前版本、新增更新大小。
- 没有历史基线时，只展示当前最新版本，并明确没有可比较的上次版本。
- 手动查询只读，不推进或覆盖定时推送基线。
- 手动查询和定时检查都按平台独立处理：某个平台失败时隐藏该平台结果并记录日志；若本次选择的所有平台都失败，返回固定的“客户端更新暂时无法获取”错误，不把空结果解释为无更新。

### 订阅命令

- `订阅客户端更新`：订阅 PC 与安卓。
- `订阅客户端更新 PC`：订阅 PC。
- `订阅客户端更新 安卓`：订阅安卓。
- `取消订阅客户端更新`：取消当前群的客户端更新订阅。
- 订阅和取消订阅仅允许群聊管理员执行；私聊和普通用户不创建订阅。
- 首次订阅时，若对应平台没有基线，尝试立即建立基线；查询失败仍保留订阅，下一次成功检查只建立基线，不推送无法确认时间范围的历史变化。
- 同一群、同一客户端更新订阅类型只保留一条记录；重复订阅应幂等。再次订阅只更新平台筛选，不创建重复目标。

### 定时推送

- 客户端更新检查任务独立于公告任务。
- 默认启用，默认每小时检查一次，可通过 typed 配置单独关闭或调整周期。
- 版本未变化不推送。
- 一次轮询中 PC 与安卓均发生变化时，普通消息每个平台独立一条。
- OneBot 且合并转发开关开启时，将同轮次的多平台结果组织为合并转发；非 OneBot 或关闭开关时按普通消息发送。
- 一个平台注册失败不阻断另一个平台；失败平台不推进基线，不生成更新事件。日志必须记录失败类别和安全原因，不能把失败解释成“无更新”。

### 事件投递与重试

为了保持“像公告一样”的投递语义，版本变化事件在独立状态中保存待投递目标：

- 事件键为 `region + platform + previous_patch_version + current_patch_version`。
- 事件首次生成时固定当时已启用且匹配平台的订阅目标集合；后续新增订阅者不补收历史事件。
- 单目标发送成功后标记 delivered；失败目标保留 pending，在后续轮询重试。
- 取消/停用订阅时从所有待投递事件移除该目标；重新订阅不加入旧事件。
- 事件在所有目标成功或被移除后清理；不建立无界的已完成事件历史。

## 3. API 契约映射

参考：`/Users/flanchan/Developer/Projects/GithubProjects/DNA-analysis/docs/update-api/update-contract.md`，并结合其来源证据 `work/pc-2026-08-31/更新接口文档.md` 与 `work/archive-docs/sdk-update-api/game-update-api.md`。

### 固定主机与完整路径

首版使用契约中已实测的两个公开资源主机，不允许用户配置任意 URL：

| 领域平台 | 主请求主机 | 失败回退主机 | 资源版本清单完整 URL |
| --- | --- | --- | --- |
| `pc` | `http://pan01-1-eo.shyxhy.com` | `http://pan01-1-hs.shyxhy.com` | `http://pan01-1-eo.shyxhy.com/Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub/VersionList.json` |
| `android` | `https://pan01-1-hs.shyxhy.com` | `http://pan01-1-eo.shyxhy.com` | `https://pan01-1-hs.shyxhy.com/Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub/VersionList.json` |

资源补丁清单 URL 模板：

```text
{base}/Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub/{patch_version}/PakFilesInfo.json
{base}/Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub/{patch_version}/ResDiscreteInfo.json

{base}/Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub/{resource_version_dir}/PakFilesInfo.json
{base}/Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub/{resource_version_dir}/ResDiscreteInfo.json
```

- PC 的 `{patch_version}` 使用 `VersionList` 条目的 `patchVersion` 十进制字符串。
- 安卓的 `{resource_version_dir}` 使用 `VersionList` 条目的资源目录字段；若条目只提供契约中的数字版本 key，则使用该 key 原样。不得通过字符串拼接或猜测把 `patchVersion` 转成另一个目录号。目录号与展示版本的映射必须来自同一条 `VersionList` 条目中的 `major`、`minor`、`revamp`、`patchKey` 字段。
- 如果安卓响应没有可确定的资源目录字段/数字 key，归类为服务端结构错误；不进行连续目录探测，也不使用无界的“猜最新目录”逻辑。
- 主请求网络失败或 5xx 时允许切换一次契约已验证的回退主机；4xx、JSON 结构错误和清单内容错误不切换主机，直接按对应失败类别报告给 service。
- 查询只读取 JSON，不请求 `.pak`、`.sig` 或大文件正文。

### 请求头与版本解析

按契约设置请求 User-Agent：

```text
PC      EMLauncher/++UE4+Release-4.27-CL-0 Windows/10.0.26100.1.256.64bit
Android EM/++UE4+Release-4.27-CL-0 Android/12
```

`VersionList.json` 的 `versionList` key 是字符串形式的 `patchVersion` 或资源目录号。实现必须按整数比较，不能按字符串排序。展示版本由条目的 `major.minor.revamp.patchKey` 组成，例如 `1.5.192.1`；内部同时保留原始整数版本键和安卓资源目录号。

启动器专属字段（如 `bBaseVersion`、`LauncherMD5`）和 `PakJumpUrl.json` 不纳入首版领域结果。

### 更新大小

更新大小的比较范围是：`previous_patch_version < patch_version <= current_patch_version` 的新增补丁。

- 参考契约没有定义稳定、明确的“本次更新总大小”字段；因此 v1 不读取或猜测任何未在契约中命名的直接大小字段。
- 每个新增补丁都必须成功读取 `PakFilesInfo.json` 与 `ResDiscreteInfo.json`；文件缺失、非 2xx、JSON 非对象、目标 `pakFilesMap`/`pakFileInfos` 缺失或条目结构非法时，整个平台本轮失败且基线不变。
- 两类清单中的条目以原始非空 `fileName` 作为去重键，不做大小写、路径或版本号改写。相同文件名且 `fileSize` 相同只计一次；相同文件名但大小冲突归类为结构错误。
- 空的 `pakFileInfos` 合法并贡献 0；清单文件存在但目标列表为空不视为失败。
- `fileSize` 必须是非负整数，单位为字节；所有新增补丁清单去重后求和。大小保存为字节，消息层转换为易读单位。
- 若未来要支持直接总量字段，必须先补充 API 契约字段路径、类型、单位、平台适用范围和 fixture，再作为独立变更加入；本规格不为未知字段预留隐式回退。

## 4. 领域与基础设施边界

### `src/modules/client_updates/`

- `contracts.py`：`ClientPlatform`、国服区服标识、版本/补丁/快照/变化 DTO、transport 协议和失败类别。
- `service.py`：查询、订阅、取消订阅、基线初始化、轮询编排、事件生成和待投递状态协调；只接收框架无关 request/actor 值对象。
- `messages.py`：命令结果、查询结果、推送结果和固定失败文案。
- `commands.py`：仅定义该领域的 `CommandSpec` 和 use case 绑定，不直接安装 handler。
- `state.py`：`client_update_state.json` 的 typed 读写、schema 版本、基线和 pending delivery 原子更新边界。

命令模块必须加入 `src/modules/index.py` 的 `COMMAND_MODULES`。随后由 `src/entry/commands` registry 统一生成独立 async-generator handler、权限过滤和 `commands.json` 投影。handler 仍须遵循入口约束：在组内重新 `re.match` 自己的正则，named groups 转为 typed request；查询命令声明 `user` 权限，订阅/取消订阅命令声明 `admin` 权限。

### `src/infrastructure/http/client_updates.py`

- 实现 `ClientUpdateTransport`。
- 负责固定主机/完整路径映射、HTTP 方法、User-Agent、JSON 解码、字段校验和失败分类。
- 负责把版本条目和补丁清单归一化为领域 DTO；不把 URL、原始响应、服务端原文或请求细节带进用户响应。
- 复用现有请求并发门禁和项目 HTTP 错误处理风格；仅使用契约明确的单次回退主机，不新增无依据的固定超时、重试次数或响应截断。

### 状态文件

运行期状态写入 `StarTools.get_data_dir(self.name)` 下的 `client_update_state.json`，不写插件源码目录 `data/`。

每个 `region + platform` 至少保存：

- `patch_version`：最近成功观察版本。
- `resource_version_dir`：实际用于资源清单路径的目录号（安卓必须保存）。
- `version_text`：最近成功观察的展示版本。
- `observed_at`：最近成功观察时间。
- `last_change`：最近一次版本变化的旧版本、新版本、新增大小。
- `pending_events`：待投递事件及固定目标集合、pending/delivered 状态。

状态文件带显式 schema 版本。写入使用临时文件替换；JSON 损坏或字段结构非法时显式失败，不能静默清空或回到默认空状态。

### 订阅存储

复用 `src/infrastructure/subscriptions/store.py`，新增独立订阅类型，例如 `订阅DNA客户端更新`。群聊订阅使用空 `uid`，平台筛选以规范化 JSON 放入 `Subscription.extra_data`，至少包含按固定顺序保存的 `platforms: ["pc", "android"]` 子集。

客户端更新状态与公告状态完全分离，不复用 `ann_state.json`、`ann_delivery_state.json` 或公告兼容 ID 配置。

## 5. 推送与 OneBot 适配

业务层返回框架无关的更新推送 DTO。推送入口根据订阅目标和平台筛选生成平台事件，再交给 bootstrap 注入的发送适配器。

普通消息内容固定包含：

```text
国服 PC 客户端更新
版本：1.5.192.1 → 1.5.193.1
新增更新：123.45 MB
```

首次无历史时使用当前版本和“暂无上次版本/暂无可比较大小”的明确语义，而不是制造旧版本。

合并转发只在目标 `bot_id == "onebot"` 且配置开启时构造节点；节点内容仍使用上述平台消息。OneBot 能力不可用、组件构造失败或目标不是 OneBot 时，安全降级为普通消息并记录原因，不影响版本状态和其他目标推送。

## 6. 配置、调度与生命周期

### 配置

在 `NotificationSettings` 中增加独立字段：

- `client_update_enabled: bool = True`
- `client_update_check_minutes: int = 60`，必须为正整数。
- `client_update_merge_forward: bool = True`

检查周期不与公告周期共享；不合法值通过现有 typed 配置校验显式报告，不静默改成另一个周期。配置 schema 和使用文档必须同步。

### 调度器实现选择

采用独立的 `ClientUpdatesScheduler` 类，而不是把客户端更新逻辑塞入 `NoticesScheduler`。它复用现有 `SchedulerRegistry`、`SchedulerTaskDefinition` 和 `parse_scheduler_schedule`，但只管理一个独立任务：

- 任务 ID：`dnaby_client_update_poll`
- 名称：`客户端更新轮询`
- schedule：`interval@{client_update_check_minutes}m`
- targets：`("client_update_subscriptions",)`
- registry 可与现有 scheduler 共享 `scheduler_state.json`；任务 ID、启停和 tombstone 独立，不覆盖公告/签到任务。
- `start()` 幂等创建任务并激活 registry；`stop()` 取消并等待任务、停用 registry。
- 配置值在 bootstrap 创建时确定；本规格不新增运行期配置热更新入口。
- `bootstrap.py` 创建该 scheduler，并在 `initialize()` 任务启动 hook 中启动；在 `terminate()` 停止 hook 中逆序取消，确保任务不在 transport/state 释放后继续运行。

## 7. 错误与一致性策略

- PC 与安卓查询使用独立结果槽位；一个失败时保留另一个成功结果。
- 查询成功但版本清单结构非法，归类为服务端结构错误，不得当作“无更新”。
- 查询失败的平台不更新状态；状态写入失败必须暴露给 scheduler 日志，并不能声明该平台已确认。
- 事件先把新基线和固定观察目标写入状态，再逐目标投递；单目标失败只保留该目标 pending，不回滚已成功目标。
- 轮询时先处理既有 pending 事件，再生成当前新版本事件；同一事件键不得重复创建。
- 取消订阅/停用订阅会清除其 pending 目标；重新订阅不接收旧事件。
- 版本回退不按“新更新”处理；作为服务端状态异常记录日志并保持当前基线，避免生成负向大小或伪造升级事件。

## 8. 验收与测试

必须先 Red 再 Green，再做最小 Refactor。至少覆盖：

1. 版本展示、整数排序、PC patch 目录和安卓资源目录保存。
2. PC/安卓完整 URL 与 User-Agent 映射；主机失败回退规则。
3. 两类清单读取、空清单、文件名去重、大小冲突和 `fileSize` 校验。
4. malformed JSON、状态码错误、网络错误和平台独立失败。
5. 首次基线不推送、版本未变化不重复推送、跨多个补丁累计大小。
6. 手动查询只读、已有历史对比、无历史提示、部分失败和全失败文案。
7. 群聊管理员权限、私聊/普通用户拒绝、平台筛选和订阅幂等。
8. 首次订阅查询失败时保留订阅，下一次成功只建基线。
9. pending delivery 的固定目标、成功标记、失败重试、取消清理和不补发新目标。
10. 独立 scheduler 的任务 ID、默认 60 分钟、启停、关闭开关和任务错误。
11. OneBot 合并转发开启/关闭、非 OneBot 无效果、合并失败普通消息降级。
12. `commands.json` 与 registry 一致、配置 schema 与文档同步。
13. 既有公告、密函和订阅测试回归。

完成后执行：

```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

## 9. 回滚与迁移

- 客户端更新实现、独立 scheduler、配置字段和 bootstrap 接线应保持为可独立回滚的提交边界。
- 新增 `client_update_state.json` 不修改既有公告/密函状态；删除或停用功能不会删除用户订阅文件中的其他类型记录。
- 状态 schema 后续变更必须带版本迁移或安全失败路径，不得静默清空用户状态。
- OneBot 合并转发失败只影响消息形态，不影响普通消息、状态确认和其他目标推送。
- 如果新状态文件已写入但新版本代码回滚，旧代码不会读取该文件；恢复功能时必须保留 schema 兼容或明确人工清理步骤，不得误删其他运行期数据。

## 10. 明确假设

- `pan01-1-eo.shyxhy.com` 与 `pan01-1-hs.shyxhy.com` 是首版固定更新源；PC/安卓的主机选择和一次回退顺序按本规格执行。
- 参考契约没有直接“本次更新大小”字段，v1 只使用清单 `fileSize`；未知字段不参与计算。
- 安卓 `VersionList` 必须提供可确定的资源目录号；若实际响应不满足该前提，本轮安卓检测显式失败，不猜目录、不扩大探测范围。
- 只保存每个平台最近成功观察基线、最近变化摘要和未完成投递事件；已完成事件清理，不建立无界历史归档。
- 用户选择“失败平台仅日志记录”不改变错误的内部分类、日志记录和基线一致性要求；全平台失败时仍返回固定错误，避免空响应造成误判。
