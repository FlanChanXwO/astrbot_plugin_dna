# 更新日志

## v0.3.6 — 2026-09-10

### 修复

- 修复本群社区签到报告在社区主签到已经成功、但浏览、点赞、分享、回复等附加社区任务失败或发生网络异常时，仍把账号判定为失败并批量 `@` 的问题；群报告现在以社区主签到状态作为主要成功判定，附加任务的真实失败仍保留在整体自动任务结果中。（[#54](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/54)）

### 维护

- 精简 #54 的回归测试，复用现有签到测试设施，并保留“附加任务普通失败”和“主签到成功后附加任务发生 `CheckinTransportError`”两条历史回归场景，移除重复的独立群报告测试框架。（[#54](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/54)）

**完整变更**：[`v0.3.5...v0.3.6`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.5...v0.3.6)

## v0.3.5 — 2026-09-09

### 修复

- 修复“日常/每日”卡片的布局与视觉问题：进度条重新对齐底图凹槽并消除挤压、截断和双轨重影；锻造清单改为自顶向下排列的独立容器，避免内容坠入角色区域；底部品牌标识统一使用卡片页脚图片。（[#53](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/53)）

**完整变更**：[`v0.3.4...v0.3.5`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.4...v0.3.5)

## v0.3.4 — 2026-09-09

### 修复

- 将按名称订阅的密函刷新通知压缩为单行：同一类型的多个密函合并展示，多个类型之间以分号分隔；保留现有群聊 `@`、订阅匹配、推送时间窗口、图片密函与全量文本密函行为。（[#51](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/51)）

### 回退

- 回退客户端更新 Target / Source 重构；本版本继续沿用 `client_updates.channels` 以及现有国服 PC / 安卓查询与订阅语义，不包含该 PR 引入的 Target registry、state v4 与 iOS 目标。（[#41](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/41)、[`7e69a54`](https://github.com/FlanChanXwO/astrbot_plugin_dna/commit/7e69a546b1dc47ec538769222d4de659950048ba)）

### 维护

- 将根 `CHANGELOG.md` 收敛为全部历史 GitHub Release 的统一事实源，统一 `v0.2.0` 至 `v0.3.3` 的中文发布说明格式，并扩展发布脚本与 workflow，使更新日志变更时能够同步现有 Release。（[#47](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/47)）

**完整变更**：[`v0.3.3...v0.3.4`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.3...v0.3.4)

## v0.3.3 — 2026-09-09

### 变更

- 管理面板的任务、投递目标、账号、角色别名和成员探测结果改为紧凑表格，并加入服务端分页、搜索和任务筛选；账号预览、账号编辑、详情卡和角色别名编辑统一为居中模态框，同时补充移动端折行、键盘焦点和 `Esc` 关闭支持。（[#45](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/45)）
- 本群签到报告调整为只统计成功账号，真实失败用户使用平台 `@` 提醒；自动签到仅处理具备可用 App 凭证的绑定，避免历史绑定被误报为签到失败。（[#46](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/46)）

### 修复

- 完善 7 命角色详情渲染并展示角色拥有的全部武器精通；恢复角色伤害与构筑计算数据链路及缓存，上游计算器不支持当前角色时会静默隐藏可选计算区块。（[#42](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/42)）
- 修复兑换码标题、奖励、区服与下一条兑换码直接拼接的问题，相邻纯文本消息组件现在会正确换行。（[#43](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/43)）
- 将上游身份校验失败及 HTTP 401/403 正确识别为登录凭证失效，并兼容字段较少的签到日历响应，使登录失效、网络错误和服务器异常得到区分处理，减少无意义的“服务异常”提示。（[#46](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/46)）

### 文档

- 修正 README 中的参考项目链接，确保公开文档指向正确来源。（[#44](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/44)）

**完整变更**：[`v0.3.2...v0.3.3`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.2...v0.3.3)

## v0.3.2 — 2026-09-08

### 变更

- 插件品牌资源统一收敛到根目录 `logo.png`：登录页、登录失败与 404 页图标、README、帮助卡和图片工具均使用同一 Logo，并移除重复遗留的 `ICON.png`。（[#37](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/37)）
- 帮助菜单补齐密函图片、密函文本、签到结果和本群签到报告的取消订阅示例；“订阅密函时间”更名为“设置密函推送时间”，明确该命令只负责设置已有订阅的推送时间窗口。（[#38](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/38)）

### 维护

- 增加品牌资源和帮助订阅回归测试，防止旧头像、`ICON.png` 引用及取消订阅入口缺失再次出现。（[#37](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/37)、[#38](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/38)）

**完整变更**：[`v0.3.1...v0.3.2`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.1...v0.3.2)

## v0.3.1 — 2026-09-08

### 变更

- 帮助图片标题、登录页浏览器标题、品牌标签、登录主标题以及日历图片中的产品标识统一为“狩月终端”，收敛用户可见品牌展示。（[#35](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/35)）

### 维护

- 增加品牌文案回归测试，避免用户可见界面重新退回旧标识。（[#35](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/35)）
- 精简根目录开发配置，移除不再需要的开发期文件并降低仓库维护噪音。（[#34](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/34)）

**完整变更**：[`v0.3.0...v0.3.1`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.0...v0.3.1)

## v0.3.0 — 2026-09-08

### 新增

- 新增国服 PC 与安卓客户端更新查询，以及按群聊目标管理的订阅与取消订阅；独立轮询任务按 channel 保存版本、清单、大小、基线与投递状态，支持未完成目标重试、取消清理以及 OneBot 合并转发降级。（[#17](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/17)）
- 角色信息卡支持随机头图背景，增强角色面板的视觉表现。（[#24](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/24)）
- 恢复全局签到报告与本群签到报告，补齐自动签到后的结果汇总能力。（[#25](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/25)）

### 变更

- 插件正式标识由 `astrbot_plugin_dnaby` 更名为 `astrbot_plugin_dna`，同步运行期数据目录、Web 与登录路由、日志标识、插件查找和 AstrBot CI；公共资源仓库同时切换到 `FlanChanXwO/dna-resource`。（[#29](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/29)）
- 默认命令前缀由 `kk` 调整为 `dna`；登录页移除已经失去实际选择意义的单标签登录方式切换，短信验证码登录直接作为主流程展示，并清理旧品牌文案。（[#31](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/31)、[#33](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/33)）
- 完成主要架构迁移，统一 App 网络访问、资源加载与同步、生命周期和运行期边界，收敛插件长期维护结构。（[#27](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/27)）
- 客户端更新配置统一使用 `client_updates.enabled`、`client_updates.check_minutes`、`client_updates.channels` 和 `client_updates.merge_forward`，更新轮询周期与公告轮询相互独立。（[#17](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/17)）

### 修复

- 移除密函推送链路中的硬编码开关，避免合法订阅被错误阻断。（[#15](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/15)）
- 修复角色面板命令匹配重叠，避免相关查询命令互相抢占。（[#19](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/19)）
- Agent Tools 的玩家概览改为返回权威玩家数据，避免使用不完整投影。（[#13](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/13)）

### 文档

- README 重构为公开发布首页，补充项目能力、安装与配置入口，并统一 Issue 与 Pull Request 模板；随后修正文档中的插件信息与功能描述。（[#29](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/29)、[#30](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/30)）
- README 增加第三方项目免责声明，明确非官方关系、素材权利归属、服务规则和使用风险边界。（[#31](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/31)）
- 文档目录收敛为 `docs/dev` 与 `docs/usage`，删除迁移阶段与一次性资料，并重写 AI 开发指引和长期维护说明。（[#32](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/32)）

### 维护

- 长期测试套件收敛到核心业务域，删除阶段性 `goal-*` 测试与仓库根目录目标目录，并使用确定性的内存渲染替身降低环境依赖。（[#28](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/28)）
- 插件加载检查升级为完整生命周期验证，同时覆盖加载、初始化与清理过程。（[#18](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/18)）

**完整变更**：[`v0.2.0...v0.3.0`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.2.0...v0.3.0)

## v0.2.0 — 2026-09-03

### 新增

- 提供 AstrBot 原生插件入口，可由官方插件加载器发现、实例化并管理生命周期。
- 提供全局账号能力，支持登录、UID 绑定管理、账号切换和严格脱敏的状态查询。
- 提供管理面板、任务与成员探测，以及角色和武器别名管理。
- 提供角色面板图、角色详情、图鉴、攻略、日历、周报和兑换码查询。
- 提供游戏签到、社区任务、自动签到、签到日历、密函和公告订阅。
- 提供个人与群聊隐私控制，包括查询权限和 UID 展示设置。

### 变更

- 统一配置、数据库、公共资源和缓存的运行期边界，配置由 Dashboard schema 驱动；图片渲染、资源同步和临时文件清理也统一写入 AstrBot 分配的插件数据目录。
- 统一命令注册、权限与生命周期管理，使插件初始化和终止过程可观测并可清理；Agent Tools 作为独立可选能力提供，默认关闭，不改变聊天命令行为。
- 支持 AstrBot 4.26.0 及以上版本，并复用 AstrBot 的全局 HTML 与 T2I 服务。

### 修复

- 修复登录展示配置未作用于当前登录入口的问题，二维码、腾讯文档链接和合并转发模式会按配置作用于 `dna登录` 命令。

### 维护

- 增加 Pull Request 专用 AstrBot 插件加载 CI，使用官方插件加载器检查导入、注册、初始化和终止，并同时验证官方稳定版与 `master` 分支。

**完整变更**：[`v0.2.0`](https://github.com/FlanChanXwO/astrbot_plugin_dna/commits/v0.2.0)
