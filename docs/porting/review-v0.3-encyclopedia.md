# v0.3 资料查询行为矩阵

> 本文覆盖 Task 14 的读取型能力：便签、周报、活动日历、图鉴、攻略、兑换码和
> 别名列表。参考实现为 `legacy-reference` 中对应的 `dna_*` 模块；真实 gscore
> 账户差异留待 Task 15，只在本地 API/resource fixture 中验证。

## 命令与读取范围

| legacy key | 输入 | 读取范围 | rewrite 输出 |
| --- | --- | --- | --- |
| `stamina` | `每日`、`mr`、`便签`、`体力` 等 | 当前/被允许查询的用户、UID、`shortNoteInfo`、`defaultRoleForTool` | 动态 PNG `ImageResponse`，保留便签进度、锻造和角色统计 |
| `weekly_report_current` | `周报`、`本周周报` | UID、`itemWeeklyReport(weekType=1)`、角色概览 | 动态 PNG `ImageResponse`，保留全部分类和资源项 |
| `weekly_report_last` | `上周周报` | UID、`itemWeeklyReport(weekType=2)`、角色概览 | 动态 PNG `ImageResponse`，保留全部分类和资源项 |
| `calendar` | `日历` | 新活动接口、旧 wiki 日历接口和本地日历素材 | 动态 PNG `ImageResponse`，保留全部活动事件和时间字段 |
| `dna_wiki` | `<名称>图鉴` / `wiki` | 角色、武器、魔灵别名和本地图鉴素材 | 匹配的运行期图片 `ImageResponse` |
| `dna_guide` | `<角色名>攻略` | 角色别名、配置的攻略作者目录和攻略图片 | 单图 `ImageResponse` 或框架无关 `ChainResponse` |
| `dna_code` | `兑换码`、`cdk`、`code` | 注入的兑换码 provider | 含全部有效码及各自截止时间的 `ChainResponse` |
| `alias_list` | `<角色/武器>别名` | 只读 alias JSON；legacy permission 为 owner | `PlainTextResponse` |
| `alias_all_list` | `角色列表`、`武器列表` | 只读 alias JSON | `PlainTextResponse` |

`alias_list` 的 owner 权限是 legacy 契约的一部分；Task 14 不注册别名添加/删除、恢复
或资源下载命令，这些写入能力留在后续任务的隔离测试范围内。

## Typed 与资源边界

- `EncyclopediaService` 先复用隐私解析，再把目标用户作为独立
  `credential_user_id` 传给便签/周报 transport；调用者仍由 `EventActor` 表示。
- API transport 在边界把 legacy Pydantic model 映射为 typed snapshot；网络、状态码、
  服务端和结构错误不把响应原文或 secret 带进用户响应。
- 运行期资源根目录为 `StarTools.get_data_dir("astrbot_plugin_dnaby")/resources/`，
  约定子目录为 `alias/`、`wiki/{role,weapon,spirit}/`、`guide/<provider>/`、
  `weekly_item/` 和 `calendar/`。测试通过注入 `EncyclopediaResourceStore` 素材副本，
  缺失素材记录 placeholder，不从插件源码目录写入或静默伪造下载成功。
- 图片 PNG 写入 `rendered/`，带有非敏感 `dnaby.text`、`dnaby.layout` 和
  `dnaby.resources` 元数据；数据层不按条数、长度或页数截断合法 API 项。

## 已知差异

1. legacy PIL/bytes 发送改为 AstrBot 公共 `ImageResponse` 路径；像素级视觉布局不宣称
   与 legacy 相同，但尺寸、消息类型、布局段、文本和资源语义可通过 metadata fixture
   审核。
2. legacy 攻略/兑换码使用平台转发节点或混合消息链；rewrite 在 response 边界将 typed
   `PlainTextResponse` / `ImageResponse` 转换为 AstrBot 公共 `Plain` / `Image` 链，完整
   保留文本和图片顺序，不伪造 forward node。
3. legacy 兑换码 URL 固定在 handler 内；rewrite 将 provider 注入 transport，默认实现
   才使用同一只读 URL，fixture 不联网。网络或 JSON 结构错误以可见失败文案表达。
4. legacy 某些素材缺失时会返回空列表或抛出底层图片错误；rewrite 对缺失资源给出明确
   未找到/placeholder 语义，不把空结果当作成功资料。
5. legacy 兑换码只展示第一个有效码的截止时间；当 provider 返回不同截止时间时，rewrite
   将每个码与其截止时间放在同一条消息链项中。人工审查结论为接受：否则会丢失合法
   provider 数据，且该差异已有逐码 fixture 回归测试。
