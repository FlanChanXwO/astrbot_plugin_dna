# 更新日志

## [Unreleased]

## v0.5.5 — 2026-09-17

### 改进

- 运行时角色、武器、MOD 与技能图片下载改为可配置的快速失败策略：新增 `resources.image_download_timeout_seconds` 与 `resources.image_download_max_attempts`，默认由原先约 `30s × 3` 收敛为 `5s × 2`，同时保留相同 URL 的 inflight 合并、缺图 provenance 与不完整卡片不缓存语义；并修复默认图片下载器跨 event loop 重试时的生命周期问题。（[#81](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/81)）
- 公共资源 manifest 增加 v2 契约：用 `required_files` 显式声明发布必需文件，`file_hashes` 只负责已声明文件的完整性校验，并移除插件内重复维护的资源目录必需性规则；继续兼容 manifest v1，便于滚动升级。（[#87](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/87)）

### 修复

- 帮助卡片顶部品牌图标统一使用仓库根目录 `logo.png`，不再错误使用登录页专用的 `textures/common/title_logo.png`，使 AstrBot 插件信息、帮助卡与登录界面的主品牌标识保持一致。（[#85](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/85)）
- 修复插件市场评审指出的运行期问题：源码日志统一经插件 logger 适配层接入 `astrbot.api.logger`；请求签名链路把同步 WebSocket readiness 等待移出事件循环线程；登录未知异常不再输出异常正文或 traceback，避免凭证及上游敏感正文进入日志；同时将已有公开等价入口迁移到 `astrbot.api`。（[#86](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/86)）
- 角色面板按完整资源别名组匹配玩家 API 返回名：当资源 canonical 与 API 实际名称不同但属于同一 alias group 时仍能正确定位角色，修复 `艾达 -> 艾达（？？）` 后因 API 返回 `伊薇` 而提示“角色未找到”的问题，并让同类角色别名组按统一语义生效。（[#88](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/88)）

### 维护

- 删除插件源码内置的公共资源树及 `RESOURCE_PATH.py` 兼容投影，运行期动态目录统一由 `RuntimeDataLayout` 管理，公共静态资源只从已验证的 `dna-resource` generation 读取；资源缺失继续使用既有 placeholder / `incomplete=True` 降级语义。（[#82](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/82)）
- 清理仅服务历史内部实现的渲染 facade、旧登录服务、旧通知/订阅转发及内部 alias/compatibility projection；仓库内调用者全部迁移到当前正式边界，用户持久化数据、已发布配置格式和真实上游适配仍保留兼容。（[#83](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/83)）
- 更新 README 的插件使用与资源维护说明，并加入仓库标准 PR skill，约束后续自动化修改按当前模板、真实 diff 与验证证据创建和复查 Pull Request。（[#80](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/80)、[#84](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/84)）

### 升级注意

- 插件包不再携带公共静态资源副本，也不会回退读取旧源码资源目录；升级后应确保存在已验证的 `dna-resource` generation，必要时执行一次 `dna同步资源`。未准备完整资源时文字功能仍可工作，依赖静态素材的图片输出会按现有规则降级并标记为不完整。（[#82](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/82)）

**完整变更**：[`v0.5.4...v0.5.5`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.5.4...v0.5.5)

## v0.5.4 — 2026-09-16

### 修复

- 统一玩家角色查询与资源仓库角色别名解析：角色详情、刷新角色面板和清理指定角色缓存现在都会使用当前 resource generation 的 `AliasCatalog`，并在资源 generation 切换后同步刷新别名视图；修复 `d典狱长别名` 能识别 `典狱长 -> 海尔法`、但 `d典狱长面板` 仍返回“角色未找到”的问题，同时让其他公共角色别名在玩家面板链路中按同一契约生效。（[#78](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/78)）

**完整变更**：[`v0.5.3...v0.5.4`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.5.3...v0.5.4)

## v0.5.3 — 2026-09-16

### 修复

- 插件启动/重载不再对已经成功发布的 current resource generation 重复执行全量 SHA-256、图片解码与 manifest 校验；现在只快速恢复已验证快照，避免重载期间长时间阻塞并导致帮助卡等资源退化为 placeholder。完整校验仍只在显式资源同步流程执行。（[#73](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/73)）
- 修复玩家接口首个请求可能早于 WebSocket 业务身份握手完成而触发 `code=220 / userId不能为空` 的竞态；同时将 220 正确归类为凭证失败、补齐角色详情魔之楔底板的 current generation 解析，并修正 OneBot 合并转发消息链格式。（[#74](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/74)）
- 修正角色详情武器属性中暴击率/暴击伤害字段映射颠倒的问题：`cri` 显示为暴击率，`crd` 显示为暴击伤害。（[#75](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/75)）
- 玩家查询确认凭证失效后会立即把对应 App 凭证状态持久化为“无效”，后续查询在本地凭证边界直接停止，不再重复请求上游；同时修复兼容图片下载器跨 event loop 复用旧 HTTP client 时可能触发 `Event loop is closed` 的问题。（[#76](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/76)）

### 维护

- 更新登录动态背景、自动签到与玩家渲染相关的过期测试契约，并补充玩家凭证失效持久化与跨 event loop 图片下载的确定性回归测试。（[#76](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/76)）

**完整变更**：[`v0.5.2...v0.5.3`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.5.2...v0.5.3)

## v0.5.2 — 2026-09-16

### 修复

- 修复插件经部分安装/解包链路部署后，中文帮助图标文件名被转换为 `#Uxxxx` 形式时无法被 `StaticAssetResolver` 命中的问题；解析器现在优先使用原始文件名，并在原文件不存在时兼容部署后的 Unicode 转义文件名，恢复帮助菜单命令图标正常渲染。（[#70](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/70)）
- 修正活动日历的资源完整性记录：成功下载并使用的远程活动图记为 `provided`，上游本身未提供图片的活动记为 `omitted`，仅真正无法解析的非空资源引用继续记为 `placeholder`，避免正常日历被误判为 `incomplete`。（[#71](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/71)）

### 文档

- 清理当前 README 中仅用于描述旧 namespace 的遗留字面量，使现行文档保持新的 `dna` namespace 契约；历史变更记录仍保留在 CHANGELOG 中。（[#69](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/69)）

**完整变更**：[`v0.5.1...v0.5.2`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.5.1...v0.5.2)

## v0.5.1 — 2026-09-16

### 变更

- 完成旧 `dnaby` namespace 的破坏性清理：插件入口与配置类型统一为 `DNAPlugin` / `DNASettings`，Scheduler Task ID、Agent Tool ID、异步任务名与临时文件前缀统一改为 `dna_*`，渲染 artifact metadata 统一改为 `dna.*`，并删除旧 symbol alias、fallback 与双读兼容。（[#67](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/67)）
- 清理插件自身的 `[dnaby]`、`[DNA登录]`、`[订阅]` 等人工日志前缀，日志来源交由 AstrBot 平台层标识，保留必要的结构化上下文。（[#67](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/67)）

### 升级注意

- 本版本不再识别 pre-v0.5 旧运行期布局；升级前应先完成 v0.5.0 布局整理，数据库位于 `db/dna.sqlite3`，状态位于 `state/`，公共资源位于 `resources/`。
- Scheduler Task ID 已切换为 `dna_*` 且旧 scheduler 状态不迁移；升级前应删除 `state/scheduler.json`，接受暂停/删除状态重置。
- 旧配置字段 `sign_in.scheduled_enabled`、`sign_in.game_enabled`、`sign_in.community_enabled` 已零兼容，残留会导致配置校验失败，升级前必须删除。
- 如外部 Alembic/运维脚本仍使用 `DNABY_DATABASE_URL`，请改为 `DNA_DATABASE_URL`；旧渲染缓存中的 `dnaby.*` metadata 可直接清理后重新生成。
- 升级后建议重新加载插件、刷新 Agent Tool discovery，并执行一次 `dna资源状态` / `dna同步资源` 验证公共资源 generation。

**完整变更**：[`v0.5.0...v0.5.1`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.5.0...v0.5.1)

## v0.5.0 — 2026-09-14

### 新增

- 客户端更新体系改为 Target / Source 注册表模型，覆盖国服官服 PC / Android / iOS、Bilibili PC / Android、好游快爆 Android，以及全球服独立客户端 PC / App Store iOS 共 8 个目标；同一 Source 每轮只观察一次，并补齐稀疏版本、同版本修订和 history-gap 恢复语义。（[#48](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/48)）
- 新增 `dna检查凭证`，通过 typed `AccountTransport` 实时校验当前凭证并区分有效、失效与暂时无法验证；「获取ck / 获取Token」统一为「获取凭证」，仅允许私聊返回当前保存的真实 token，群聊不会泄露原始凭据。（[#65](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/65)）

### 变更

- 引入 generation-first 公共资源布局和 `AssetResolver`：运行期目录统一为 `db/`、`state/`、`resources/`、`cache/` 与 `backups/`，每个 runtime 独立持有下载器和资源解析器，角色图片、百科、签到与公告等链路统一按当前 generation 解析资源。（[#58](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/58)）
- 将字体、角色/详情/签到/日常/周报/密函/公告/日历等大型静态渲染素材外置到 `dna-resource`，新增 `StaticAssetResolver`、generation lease 与 `incomplete` 降级语义；插件源码包由约 169 MiB 缩减至约 5 MiB。（[#50](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/50)）
- 重组帮助菜单为普通用户 10 个分组、管理员追加 3 个管理分组；分组、展示名、图标与排序改用稳定 command id 显式映射，删除旧 `help.json` 数据源和中文命令名猜图标逻辑。（[#65](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/65)）
- 客户端更新配置由 `client_updates.channels` 切换为 registry 驱动的 `client_updates.targets`，状态升级为 v4，并将查询、订阅与取消订阅命令收敛为无参数入口，目标选择统一交给配置。（[#48](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/48)）
- `cache.refresh_send_card` 拆分为基础卡片与角色面板两个独立开关 `refresh_send_info_card` / `refresh_send_role_panel`，旧配置只迁移到角色面板开关。（[#65](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/65)）

### 修复

- 动态登录背景改为在 HTML 解析阶段直接预加载并自动播放，首屏等待视频进入播放状态后再揭开页面，避免首次打开先看到静态背景再切换视频；加载失败或减少动态效果时仍会回退静态背景。（[#62](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/62)）
- `主角` / `光主` / `暗主` 按玩家实际拥有的男女主席位解析，修复男主账号无法使用通用主角称呼的问题；同时补齐角色 `elementIcon` 缺失时的空值保护，并删除已失效的 legacy 别名链路。（[#63](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/63)）
- 同步命令不再自行插入针对当前命令用户的 `At`，普通回复重新交由 AstrBot 平台层处理 `reply_with_mention` / `reply_with_quote`；主动推送和明确业务目标的 `At` 保持原行为。（[#64](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/64)）
- 凭证实时校验的状态写回绑定实际校验的 token 与 device code，避免检查期间重新登录后旧结果覆盖新凭证；成功校验会恢复历史误标的无效状态，网络与服务端异常不会误判为凭证失效。（[#65](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/65)）

### 升级注意

- 本版本的运行期资源布局存在破坏性调整：检测到旧数据布局时会 fail-fast，不自动迁移、不双读旧目录；升级前请按文档备份并人工迁移。已废弃的 `custom/` 自定义素材能力不再迁移。（[#58](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/58)）
- 完整图片渲染现在依赖已验证的 `dna-resource` generation；升级后应执行一次 `dna同步资源`。未同步时文字命令仍可工作，图片命令会使用 placeholder 并标记为不完整。（[#50](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/50)）
- `client_updates.channels` 不会自动迁移到 `client_updates.targets`，旧 state v1/v2/v3 也不会迁移；使用客户端更新订阅的管理员需要重新检查目标配置。（[#48](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/48)）
- 删除独立 `token登录`、`dna原图` 占位命令以及管理员“刷新指定 UID 角色面板”命令；token 登录仍可通过 `dna登录<token>` 使用。（[#65](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/65)）

**完整变更**：[`v0.4.0...v0.5.0`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.4.0...v0.5.0)

## v0.4.0 — 2026-09-11

### 新增

- 重做内置登录页视觉与媒体体验：加入可配置的静音动态背景、移动端居中布局与「狩月终端」标题标识，并在资源缺失、加载失败或开启减少动态效果时自动回退到静态背景。（[#49](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/49)）
- 支持 Windows PC 浏览器直接完成验证码登录：内置 `*.alicaptcha.com` 白名单反代，将验证码会话请求转换为已验证可用的 Android UA 画像，并通过 Service Worker 与页面内 hook 覆盖安全上下文和局域网 HTTP 场景。（[#56](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/56)）
- 登录页状态提示改为悬浮 Toast，区分成功、失败和处理中状态，避免表单高度随状态文本变化而跳动；同时补充未预期异常的错误详情与堆栈日志。（[#60](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/60)）

### 修复

- 修复角色概览中武器 `elementIcon` 缺失时整张卡片渲染失败的问题；该装饰图标现在按可选字段处理，其余武器信息继续正常展示。（[#57](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/57)）
- 统一全部登录链路的登录提示文案，普通直链、外置 transport、腾讯文档、二维码、fallback 与 legacy 路径均复用同一 formatter，避免不同配置下提示内容漂移。（[#59](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/59)）
- 移除验证码 SDK 人为设置的 15 秒固定加载超时，改由真实脚本加载错误、SDK 错误与初始化异常决定失败，避免弱网环境下提前误判登录失败。（[#49](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/49)）

### 文档

- 更新登录与配置文档，补充动态背景配置及 PC / 手机浏览器直接验证码登录说明。（[#49](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/49)、[#56](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/56)）

**完整变更**：[`v0.3.6...v0.4.0`](https://github.com/FlanChanXwO/astrbot_plugin_dna/compare/v0.3.6...v0.4.0)

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
- 精简根目录开发配置，移除不再需要的开发期文件并降低仓库维护噪音。（[#34](https://github.com/FlanChanXwO/astrbot_plugin_dna/pull/34)）

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
