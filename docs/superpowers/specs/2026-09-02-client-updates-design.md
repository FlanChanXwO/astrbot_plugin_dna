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

### 订阅命令

- `订阅客户端更新`：订阅 PC 与安卓。
- `订阅客户端更新 PC`：只订阅 PC。
- `订阅客户端更新 安卓`：只订阅安卓。
- `取消订阅客户端更新`：取消当前群的客户端更新订阅。
- 订阅和取消订阅仅允许群聊管理员执行；私聊和普通用户不创建订阅。
- 首次订阅时，若对应平台没有基线，尝试立即建立基线；查询失败仍保留订阅，下一次成功检查只建立基线，不推送无法确认时间范围的历史变化。
- 同一群、同一订阅类型只保留一条记录；重复订阅应幂等。

### 定时推送

- 客户端更新检查任务独立于公告任务。
- 默认启用，默认每小时检查一次，可通过 typed 配置单独关闭或调整周期。
- 版本未变化不推送。
- 一次轮询中 PC 与安卓均发生变化时，普通消息每个平台独立一条。
- OneBot 且合并转发开关开启时，将同轮次的多平台结果组织为合并转发；非 OneBot 或关闭开关时按普通消息发送。
- 一个平台注册失败不阻断另一个平台；失败平台不推进基线。按产品选择，失败平台不进入用户消息，但日志必须记录真实失败类别和原因，不能把失败解释成“无更新”。

## 3. API 契约映射

参考：`/Users/flanchan/Developer/Projects/GithubProjects/DNA-analysis/docs/update-api/update-contract.md`。

### 平台路径

| 领域平台 | 资源分支 | 版本清单 |
| --- | --- | --- |
| `pc` | `Default/WindowsNoEditor/PC_OBT_CN_Pub` | `VersionList.json` |
| `android` | `Default/Android_ASTC/Android_OBT_CN_Pub` | `VersionList.json` |

基础主机使用契约验证过的 `shyxhy.com` 更新源常量。查询只访问公开 JSON/资源清单，不执行补丁下载。请求应沿用契约要求的 User-Agent：PC 使用 `EMLauncher/... Windows/...`，安卓使用 `EM/... Android/...`。

### 版本解析

`VersionList.json` 的 `versionList` key 是字符串形式的 `patchVersion`。实现必须按整数比较，不能按字符串排序。展示版本由 `major.minor.revamp.patchKey` 组成，例如 `1.5.192.1`；内部同时保留原始整数 `patchVersion` 用于比较和状态键。

启动器专属字段（如 `bBaseVersion`、`LauncherMD5`）不纳入首版领域结果。

### 更新大小

更新大小的比较范围是：`previous_patch_version < patch_version <= current_patch_version` 的新增补丁。

- 如果实际接口返回了已经验证、明确表示“本次更新大小”的字段，transport 在边界层优先采用该值。
- 当前契约文档明确给出的是补丁文件清单中的 `fileSize`，未定义统一总量字段；因此在没有可验证直接总量时，按新增补丁的 `PakFilesInfo.json` 与 `ResDiscreteInfo.json` 清单汇总 `fileSize`。
- 两类清单的条目按规范化文件名去重后求和；空的 `ResDiscreteInfo` 贡献 0。
- 大小统一保存为字节，用户消息层转换为易读单位；不能截断或静默吞掉无法解析的条目。
- 首次基线、无新增补丁或版本未变化不生成“本次更新大小”事件。

## 4. 领域与基础设施边界

### `src/modules/client_updates/`

- `contracts.py`：`ClientPlatform`、国服区服标识、版本/补丁/快照/变化 DTO、transport 协议和失败类别。
- `service.py`：查询、订阅、取消订阅、基线初始化、轮询编排和推送事件生成。只接收框架无关 request/actor 值对象。
- `messages.py`：命令结果、查询结果、推送结果和固定失败文案。
- `commands.py`：`CommandSpec`、正则、权限、examples 与 use case 绑定。
- `state.py`：`client_update_state.json` 的 typed 读写和原子更新边界。

### `src/infrastructure/http/client_updates.py`

- 实现 `ClientUpdateTransport`。
- 负责主机/路径映射、HTTP 方法、User-Agent、JSON 解码、字段校验和失败分类。
- 负责把直接大小字段或资源清单归一化为领域可消费的大小数据。
- 不把 URL、原始响应、服务端原文或请求细节带进用户响应。
- 复用现有请求并发门禁和项目 HTTP 错误处理风格；不新增没有契约依据的固定超时、重试次数或响应截断。

### 状态文件

运行期状态写入 `StarTools.get_data_dir(self.name)` 下的 `client_update_state.json`，不写插件源码目录 `data/`。

每个 `region + platform` 至少保存：

- `patch_version`：最近成功观察版本。
- `version_text`：最近成功观察的展示版本。
- `last_change`：最近一次版本变化的旧版本、新版本、新增大小。
- `observed_at`：最近成功观察时间。

状态文件带显式 schema 版本。写入使用临时文件替换；JSON 损坏或字段结构非法时显式失败，不能静默清空或回到默认空状态。

### 订阅存储

复用 `src/infrastructure/subscriptions/store.py`，新增独立订阅类型，例如 `订阅DNA客户端更新`。群聊订阅使用空 `uid`，平台筛选以规范化 JSON 放入 `Subscription.extra_data`，至少包含 `platforms: ["pc", "android"]` 的有序值。

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

合并转发只在 OneBot 目标且配置开启时构造节点；节点内容仍使用上述平台消息。OneBot 能力不可用、组件构造失败或目标不是 OneBot 时，安全降级为普通消息并记录原因，不影响版本状态和其他目标推送。

## 6. 配置与生命周期

在 `NotificationSettings` 中增加独立字段：

- `client_update_enabled: bool = True`
- `client_update_check_minutes: int = 60`
- `client_update_merge_forward: bool = True`

检查周期必须使用项目既有配置校验方式；不合法值显式报告，不静默改成另一个周期。配置 schema 和使用文档必须同步。

bootstrap 负责创建状态存储、transport、service、scheduler，并将 scheduler 的 `start`/`stop` 接入插件生命周期。scheduler 应具备幂等启动/停止、任务状态记录和错误日志，与公告任务互不覆盖。

## 7. 错误与一致性策略

- PC 与安卓查询使用独立结果槽位；一个失败时保留另一个成功结果。
- 查询成功但版本清单结构非法，归类为服务端结构错误，不得当作“无更新”。
- 查询失败的平台不更新状态；状态写入失败必须暴露给 scheduler 日志，并不能声明该平台已确认。
- 多目标推送逐目标处理；单目标失败不回滚已成功目标，失败目标在后续轮询仍有机会重试。
- 版本变化检测和状态落盘需要避免同一轮并发任务重复推进；至少通过 scheduler 单实例和状态存储锁保证串行写入。
- 取消订阅后不再发送后续事件；重新订阅不补发取消期间历史变化。

## 8. 验收与测试

必须先 Red 再 Green，再做最小 Refactor。至少覆盖：

1. 版本展示和 `patchVersion` 数值排序。
2. PC/安卓资源路径和 User-Agent 映射。
3. 直接大小字段优先、清单后备、条目去重和空清单。
4. malformed JSON、状态码错误、网络错误和平台独立失败。
5. 首次基线不推送、版本未变化不重复推送、跨多个补丁累计大小。
6. 手动查询只读且正确展示已有历史；无历史时不伪造旧版本。
7. 群聊管理员权限、私聊/普通用户拒绝、平台筛选和订阅幂等。
8. 首次订阅查询失败时保留订阅，下一次成功只建基线。
9. 独立 scheduler 的默认值、启停、关闭开关和任务错误。
10. OneBot 合并转发开启/关闭、非 OneBot 无效果、合并失败普通消息降级。
11. `commands.json` 与 registry 一致、配置 schema 与文档同步。
12. 既有公告、密函和订阅测试回归。

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
- OneBot 合并转发失败只影响消息形态，不影响普通消息、状态确认和其他平台。

## 10. 明确假设

- `shyxhy.com` 契约主机和国服 PC/安卓路径作为首版固定 provider 配置，不开放用户任意填写 URL。
- “本次更新大小”优先使用真实且经测试确认的直接字段；如果实际返回没有该字段，则使用契约公开的补丁清单求和。
- 只保存每个平台最近成功观察基线和最近一次变化摘要，不建立无界的完整历史事件归档；用户需要的历史对比由这份基线提供。
- 用户选择“失败平台仅日志记录”不改变错误的内部分类、日志记录和基线一致性要求。
