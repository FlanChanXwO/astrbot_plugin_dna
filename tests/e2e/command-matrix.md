# Task 15 gscore 只读命令差异矩阵

> 采集日期：2026-08-12。此文记录 Task 15 的可复现证据，不把未运行的真实平台链路、
> 未接入的私有资源或未人工审查的视觉差异标为通过。完整只读验收仍属于 Task 30。

## 只读边界与探测结论

- gscore 运行在容器化的 GsCore 环境中，DNAUID 数据库类型为 SQLite；本轮仅确认
  DNAUID 的用户、绑定、签到和隐私表结构，以及 App 读取所需的非空 `uid`、`cookie`
  和 `dev_code` 字段。没有导出表记录、UID、Cookie、token 或刷新凭据。
- 候选账户记为 `candidate-A`，只在独立进程内通过 SQLite `mode=ro` 选取。筛选条件为
  App 凭据字段非空且状态不是无效；本轮的原插件与 rewrite 都从同一选择条件获得该
  进程内对象。
- rewrite 验证通过受保护的标准输入把最小 App 凭据流传给临时 staging Python 进程。
  凭据没有写入 worktree、临时 JSON、数据库、日志或 Git；进程结束前显式关闭 HTTP
  session 和签名 WebSocket。
- 没有执行登录、退出、签到、绑定、订阅、隐私修改、面板管理、资源更新或任何真实
  平台消息发送。`原图` 依赖消息引用缓存，因本计划禁止真实 NapCat 而只保留离线契约。

## 状态约定

| 状态 | 含义 |
| --- | --- |
| `结构已实测` | 原插件真实只读 API 与 rewrite transport 都成功运行，且此表列出的结构计数一致。 |
| `差异待审查` | 可见差异已记录，但尚未作人工接受结论。 |
| `fixture/待实测` | 仅有本地 fixture、源码或资源语义证据，不能视为真实行为回归。 |

## 账户读取矩阵

| 命令 ID / 代表输入 | 读取范围 | DNAUID 只读证据 | rewrite 只读证据 | 结论 |
| --- | --- | --- | --- | --- |
| `role_info_card` / `卡片` | `defaultRoleForTool` 角色、近战与远程武器展柜 | `200`，`DNARoleForToolRes`：角色 31（解锁 19）、近战 30（解锁 18）、远程 34（解锁 16）、参数 9 | `RoleOverview` 的同四组计数一致 | `结构已实测`；图片布局见下表，仍为 `差异待审查`。 |
| `role_detail_card` / `<已拥有角色>面板` | 展柜内首个有 `charEid` 的已拥有角色详情 | `200`，`DNARoleDetailRes`：属性字段 12、技能 3、溯源 6、魔之楔 9、无同律武器 | `RoleDetail` 的同五项结构一致 | `结构已实测`；没有运行伤害计算、武器组合和详情图完整链路。 |
| `role_original_image` / `原图` | 回复消息 ID 与原图缓存 | 原实现依赖已发送面板图与引用消息 | rewrite `OriginalImageCache` 已有 fixture 契约 | `fixture/待实测`；禁止真实平台消息，不能声明缓存命中等价。 |
| `stamina` / `日常` | `shortNoteInfo` 与角色概览 | `200`，`DNARoleShortNoteRes` 有 9 个顶层字段和 `draftInfo` | `PlayerShortNote` 成功映射，角色概览存在，进行中锻造槽位为 0 | `结构已实测`；进度值、时间文本和完整视觉内容未做逐字接受。 |
| `weekly_report_current` / `周报` | `itemWeeklyReport(weekType=1)` 与角色概览 | `200`，`DNAItemWeeklyReportRes`：周类型匹配、分类 1、资源项 5 | `WeeklyReport`：周类型 1、分类 1、资源项 5、角色概览存在 | `结构已实测`；图片布局见下表。 |
| `weekly_report_last` / `上周周报` | `itemWeeklyReport(weekType=2)` 与角色概览 | `200`，`DNAItemWeeklyReportRes`：周类型匹配、分类 1、资源项 5 | `WeeklyReport`：周类型 2、分类 1、资源项 5、角色概览存在 | `结构已实测`；图片布局见下表。 |

读取期间原插件与 rewrite 均显式关闭本进程创建的连接。原插件端的成功响应只被转换为
类型模型和计数；没有把 `data` 原文写入矩阵或终端记录。

## 临时图片资料

临时 PNG 都在 worktree 外、权限为仅当前用户可读写的目录中生成，未纳入 Git。为避免
legacy handler 下载缺失头像/图标或向平台发送消息，legacy 图片使用真实只读 API payload，
但将头像、图标下载、头像标题和 `Bot.send` 替换为内存实现。因而这些资料适合核对画布、
动态高度和区域数量，不适合主张像素等价。两侧都对 UID 使用显式 mask。

| 图片命令 | legacy 结构图 | rewrite 临时图 | 已记录的差异 |
| --- | --- | --- | --- |
| `role_info_card` | `1200 x 7410`，legacy 配置 `RoleInfoCard=true` | `1200 x 2854`，3 个区域、111 行文本、95 个资源 placeholder | rewrite 使用紧凑列表布局与占位素材；不是像素等价，`差异待审查`。 |
| `stamina` | `2000 x 1100` | `1200 x 796`，3 个区域、19 行文本 | 框架/布局和画布宽高不同；进度与角色概览读取成功，视觉接受结论待 Task 16/30。 |
| `weekly_report_current` | `1200 x 820` | `1200 x 570`，2 个区域、5 个资源 placeholder | 同一分类和资源项计数，但卡片布局与素材状态不同，`差异待审查`。 |
| `weekly_report_last` | `1200 x 820` | `1200 x 570`，2 个区域、5 个资源 placeholder | 同上；不比较动态日期、时间或像素 hash。 |

rewrite 临时图保留 `dnaby.text`、`dnaby.layout` 与 `dnaby.resources` 元数据，供后续在不
暴露账户内容的前提下检查文本、区域和素材语义。legacy 结构图由 gscore 容器中的受限
临时目录保存；两组目录均不在源码树、运行期数据目录或版本控制范围内。

## 非账户读取与静态命令

| 命令 ID / 代表输入 | 当前证据 | 状态与后续要求 |
| --- | --- | --- |
| `help` / `帮助` | registry/帮助 fixture；rewrite 为文本响应，legacy 为帮助卡片 | `差异待审查`，需在 Task 30 明确文本、分组和可见格式结论。 |
| `calendar` / `日历` | Task 14 API fixture 覆盖活动接口、旧日历接口和动态 PNG | `fixture/待实测`；活动数据会随时间变化，应在 Task 30 用明确时间/动态字段 mask 复核。 |
| `dna_wiki` / `<名称>图鉴` | 本地资源索引、别名与图片 fixture | `fixture/待实测`；私有资源仓库未接入 staging，不能声称真实素材等价。 |
| `dna_guide` / `<角色名>攻略` | 作者分组、图片顺序与 chain fixture | `fixture/待实测`；需在私有资源可用时对图片顺序和作者文本复核。 |
| `dna_code` / `兑换码` | provider 与逐码截止时间 fixture | `fixture/待实测`；真实 provider 是时间敏感外部来源，后续需记录响应日期与失败语义。 |
| `alias_list` / `<角色/武器>别名` | alias JSON fixture；`owner` 权限已在 registry 测试 | `fixture/待实测`；私有 alias 资源未装载。 |
| `alias_all_list` / `角色列表` | alias JSON fixture | `fixture/待实测`；同上。 |

## 未接受差异与下一步

1. 原插件与 rewrite 的 API 数据投影已对照，但图片是不同的渲染系统；画布尺寸、布局和
   placeholder 素材差异没有人工接受结论。
2. 角色详情还缺少真实伤害计算、武器组合、完整详情图和原图引用缓存的只读/离线联合
   审查。原图的真实平台路径继续受“不得执行 NapCat”约束。
3. 日历、图鉴、攻略、兑换码和别名尚未进行真实资源/时间敏感双侧比较；其 fixture
   覆盖不应被解释为线上输出已验证。
4. Task 16.1 已修复资源目录/renderer 接线和合成图片生命周期；私有资源内容、图片视觉差异
   与时间敏感输出仍未接受。原图发送映射和伤害失败输出继续由 Task 16.2 修复，Task 30 才能
   完成全量只读验收与人工结论。
