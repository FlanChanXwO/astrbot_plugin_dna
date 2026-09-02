# Goal 3 计划：客户端更新查询与订阅推送

## 目标

在独立工作树中实现“客户端更新”和“订阅客户端更新”能力：基于更新 API 契约查询国服 PC/安卓最新版本，保存定时观察基线，比较版本变化和本次新增更新大小，并向群聊订阅目标定时推送。按 TDD 与 goal-mode 节奏推进，每轮只执行 tasks.md 中的一个 task。

## 当前上下文

- 工作树：`.worktrees/codex-client-updates-goal`
- 分支：`codex/client-updates-goal`
- 基线提交：创建工作树时的 `b49475a36f02e33752fc74aad2cf6f6bca637994`
- 已有公告模式：`src/modules/notices/`、`src/infrastructure/notices_scheduler.py`、`src/infrastructure/subscriptions/store.py`。
- 命令事实源：`src/entry/commands/` registry，`commands.json` 为投影。
- 运行期状态必须位于 `StarTools.get_data_dir(self.name)` 对应目录；不得写插件源码目录的 `data/`。
- API 参考：`/Users/flanchan/Developer/Projects/GithubProjects/DNA-analysis/docs/update-api/update-contract.md`。

## 已确认的产品决策

1. 只做游戏客户端/资源更新查询，不做下载、安装或自动升级；Android Zeus SDK 插件暂不纳入。
2. 首版只支持国服 PC 与国服安卓：
   - PC：`WindowsNoEditor/PC_OBT_CN_Pub`
   - 安卓：`Android_ASTC/Android_OBT_CN_Pub`
3. 查询默认返回全部平台，可选指定 PC 或安卓。
4. 群聊管理员可以订阅/取消订阅；订阅按当前会话目标保存。
5. 默认每个平台独立推送一条消息；OneBot 且配置开启时，可把同轮多个平台结果放入合并转发；非 OneBot 时该开关无效果。
6. 定时任务独立于公告，默认开启，默认约每小时检查一次，并有独立开关与周期配置。
7. 手动查询只读，不推进定时基线；已有基线时展示历史对比，没有历史时只展示当前版本。
8. 首次订阅只建立基线；首次建立失败时仍保留订阅，下一次成功检查只建基线，不推送无法确认时间范围的历史更新。
9. 参考 API 契约未提供经过验证的直接更新总大小字段；v1 仅按两次成功观察之间新增补丁清单中的 `fileSize` 去重汇总。未来若新增直接大小字段，必须先补充契约、类型、单位、适用平台和 fixture，再作为独立变更接入。
10. 用户可见的最小业务字段为：区服、平台、旧版本、新版本、新增更新大小；不默认展示 URL、MD5、强制更新、重启标记。
11. 一个平台注册失败不阻断另一个平台；按用户选择，失败平台只记录日志。但消息不得宣称失败平台“无更新”，日志必须保留失败类别和真实原因。

## 预期架构

### 领域模块

新增独立 `src/modules/client_updates/`：

- `contracts.py`：平台、区服、版本快照、版本变化、transport 协议和可观察失败类型。
- `service.py`：手动查询、订阅/取消订阅、基线初始化、定时轮询和事件生成；不依赖 AstrBot event。
- `messages.py`：命令及推送文案。
- `commands.py`：`CommandSpec` 与 use case 绑定。
- `state.py` 或等价状态边界：基线和最近变化的持久化模型。

### 基础设施

- `src/infrastructure/http/client_updates.py`：按 API 契约读取 `VersionList.json` 及必要的资源清单，使用现有 HTTP/并发门禁风格；不把原始响应泄露给用户。
- `src/infrastructure/client_updates_scheduler.py`：独立 `ClientUpdatesScheduler`，复用 `SchedulerRegistry`，管理任务 `dnaby_client_update_poll`，周期使用 `interval@{client_update_check_minutes}m`。
- `src/bootstrap.py`：组装 transport、state、service、scheduler 和推送函数。
- `src/entry/response.py` 或专用推送适配边界：为 OneBot 合并转发保留框架无关 DTO，普通平台走现有 `MessageChain`。
- `src/infrastructure/config/settings.py` 与 `_conf_schema.json`：新增客户端更新开关、检查周期、OneBot 合并转发开关。

### 订阅与事件

- 新订阅类型独立于公告，例如 `订阅DNA客户端更新`；平台选择以规范化 JSON 存入 `Subscription.extra_data`。
- 订阅按 `type + unified_msg_origin + uid` 去重，群聊订阅使用空 `uid`。
- 独立使用 `client_update_state.json`，不复用 `ann_state.json` 或 `ann_delivery_state.json`。
- 每个平台状态按 `region + platform` 建立全局观察基线；订阅目标只保存平台筛选，避免每个群复制版本历史。

## 命令语义

- `客户端更新`：查询 PC 与安卓；显示已有基线的历史对比。
- `客户端更新 PC`：只查询 PC。
- `客户端更新 安卓`：只查询安卓。
- `订阅客户端更新`：订阅全部平台。
- `订阅客户端更新 PC` / `订阅客户端更新 安卓`：订阅指定平台。
- `取消订阅客户端更新`：取消当前群的客户端更新订阅。

具体正则、别名和命令投影必须遵守现有 registry 规范，并补充命令测试。

## 数据流

1. 查询或轮询 transport 获取平台最新 `VersionList`，按数值 `patchVersion` 选择最新版本，展示版本由 `major.minor.revamp.patchKey` 组成。
2. service 读取对应平台的上次基线；无历史时返回当前版本并建立基线（定时流程写入，手动查询不写入）。
3. 有历史且版本变化时，读取两次观察之间新增补丁的大小；v1 仅按 `PakFilesInfo.json` 与 `ResDiscreteInfo.json` 的 `fileSize` 去重汇总，未知直接总量字段不参与计算。
4. 定时流程成功确认后原子保存新的平台基线及最近一次变化摘要，再按订阅平台筛选目标。
5. 目标推送成功后记录可观测结果；推送失败只影响目标，不回滚其他平台或其他目标的成功结果。

## 风险与约束

- 更新契约当前明确了版本清单和文件清单，但没有稳定定义所有平台的“直接总大小”字段；解析器必须严格校验响应，不能把未知字段当成功。
- `PakJumpUrl.json` 的渠道下载链接不属于首版输出，避免把渠道枚举和链接安全策略引入当前范围。
- `ResDiscreteInfo.json` 可能为空；若作为清单后备，需要避免与 `PakFilesInfo.json` 重复统计。
- 手动查询不推进基线，可能反复看到同一变化；这是已确认的只读语义，不应通过隐式写入修正。
- 合并转发能力与 OneBot/AstrBot 适配器有关，必须通过组件能力和测试确认，不能对非 OneBot 平台强制发送转发节点。
- 不新增第三方依赖；不把网络异常吞成空结果；不新增无依据的超时、截断或重试上限。

## 验证计划

- 先写失败测试（Red），再实现（Green），最后最小重构（Refactor）。
- 目标测试：版本解析、大小归一化、状态原子持久化、首次基线、变化检测、订阅筛选、命令 registry、独立 scheduler、部分平台失败、OneBot 合并转发。
- 完成功能后按项目要求运行：
  - `python3 -m compileall .`
  - `python3 -m pytest`
  - `ruff check .`
- 跨模块/公共配置变更完成后补充代码审查和文档核对，至少检查 `docs/usage/commands.md`、`docs/usage/configuration.md`、`docs/project/data-model.md`、`commands.json`、`_conf_schema.json`。

## 回滚方案

- 业务实现通过独立 commit 分阶段提交；每个 commit 只对应一个 tasks.md task。
- 若更新 API 解析或状态模型出现问题，可回滚客户端更新模块、独立 scheduler、配置字段和 bootstrap 接线，不触碰公告状态文件及既有公告命令。
- 若运行期状态格式需要调整，只允许增加明确版本字段并提供向前兼容/安全失败策略；禁止删除用户现有订阅或静默清空损坏状态。
- 若 OneBot 合并转发不可用，保留配置但在实现中安全降级为普通文本消息，并保留错误日志；不得影响普通平台推送。

## 当前执行边界

Task 01 已完成规格固化与独立审查，Task 02 已提交版本模型与大小归一化 Red 测试，Task 03 已实现对应 typed contract 与纯解析逻辑并通过 Green 验证。后续每轮只执行 `tasks.md` 中第一个未完成 task；继续遵循先 Red、再 Green、最后最小 Refactor。
