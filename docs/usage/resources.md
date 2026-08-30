# 公共资源

运行期资源位于 AstrBot 的插件数据目录下：
`StarTools.get_data_dir("astrbot_plugin_dnaby")`。插件源码目录的 `data/` 不承担运行期资源
写入；`resources/` 只作为 Git 增量传输缓存，已发布运行期快照位于同级的
`resource_generations/<commit-sha>/`，当前 generation 由 `resource_generations/current.json`
原子指针标识。

资源 checkout、generation 根目录和当前指针都必须是运行期数据目录中的普通路径；检测到根目录、
generation、指针或图片缓存目录/文件是符号链接时会显式失败，不跟随链接读写目录外内容。

资源内容由公共 Git 仓库 `FlanChanXwO/astrbot_plugin_dna_resources` 提供。仓库根目录必须有：

```json
{
  "format_version": 1,
  "required_dirs": [
    "fonts", "images", "panel", "alias", "data", "schemas",
    "wiki/role", "wiki/weapon", "wiki/spirit", "guide", "weekly_item", "calendar"
  ],
  "resource_version": "2026.08.11",
  "file_hashes": {
    "alias/char_alias.json": "<64 位十六进制 SHA-256>"
  }
}
```

`required_dirs` 必须包含上述运行期布局；插件会校验目录均存在且不能通过相对路径逃逸仓库
根目录。同步器和 bootstrap 都会拒绝已有但缺少/未声明该布局的资源根，不能把一次不完整
同步当作可用资源。`file_hashes` 是可选的逐文件 SHA-256 声明；声明的路径和摘要任一不匹配
都会拒绝候选。`resource_version` 只作为经过校验的资源版本返回。

目录约定如下：

- `fonts/dna_fonts.ttf`：玩家和资料 renderer 共用的字体；缺失时图片 metadata 标为
  `fallback`，而不会回退读取插件源码字体。
- `images/<kind>/<key>.<ext>`：玩家角色头像、武器、技能、魔之楔和立绘；renderer 以
  `kind:key` 查找，并在缺失时记录 `placeholder`。
- `panel/<角色 ID>.<ext>`：角色详情关联的原始面板资源；它只提供资源路径，不等同于
  已实现平台回复引用。
- `alias/`、`wiki/{role,weapon,spirit}/`、`guide/<作者>/`、`weekly_item/` 与 `calendar/`：
  分别供别名、图鉴、攻略、周报和日历索引使用。
- `data/redeem_codes.json`：兑换码 v1 清单，保留计划中、当前有效和已过期条目；插件只
  展示当前有效项。每项必须有 `code`，可选 `reward`、带时区的 `valid_from`/`expires_at`、
  `platforms`（`pc`/`android`/`ios`）和 `servers`（`cn`/`global`）。

资源根不存在时，插件仍可启动：图片 renderer 会明确输出 `placeholder`/`fallback` metadata，
资料命令对缺失图鉴或攻略返回未找到。资源根存在但 manifest 不完整时则显式失败，便于部署者
修正同步结果。

同步规则：

- 规范 origin 始终是 `https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git`；
  镜像只通过当前 Git 子进程的 `url.*.insteadOf` 配置替换请求，不改写本地 origin。
- 首次同步先执行 `git clone --depth 1 --single-branch --branch main --no-tags`，再显式
  `fetch --no-tags origin main`；已有 checkout
  先确认当前为 `main`、origin、干净状态，再只 fetch `origin/main`。
- fetch 得到的 `FETCH_HEAD` 会先导出为临时 archive，校验 manifest、声明的文件哈希、别名、
  兑换码及 schema、图片的文件头与 PIL 完整解码、字体签名和运行期索引；同时计算候选完整
  文件树的 SHA-256。候选通过后才以 `merge --ff-only FETCH_HEAD` 更新缓存，并原子发布对应
  的 `resource_generations/<commit-sha>/`。
- Git 缺失、认证/远端错误、origin 不一致、非快进、候选无效或本地有修改时直接报告失败，
  当前已验证 generation 保持不变。
- 加速镜像不支持 Git smart HTTP 时直接报告失败，不改走 ZIP、不静默直连；本地修改必须由部署者自行处理。

## Generation 与无停机热刷新

发布成功后 bootstrap 会一次性替换玩家、图鉴、签到、密函和别名的读取资源视图，新请求无需
重启即可使用新版本。renderer 在一次读取开始时取得 generation lease，并在渲染结束后释放；
热刷新期间旧 generation 会保留到最后一个 lease 释放。Wiki/攻略的直出图片会在 lease 内复制到
受控 `rendered/`，再交给事件生命周期清理，避免响应返回后源 generation 被删除。

进程重启时只加载 `current.json` 指向的已验证 generation，并清理同目录下未被当前指针引用的
generation、candidate 和 archive 临时物；不会扫描、删除或迁移 `panel_custom/`、数据库和订阅文件。

`current.json` 同时保存 `generation` 和 `content_sha256`。重启恢复时会重新校验 generation 并
比对完整文件树摘要；摘要不一致时拒绝激活，避免指针指向被篡改的内容。没有摘要字段的旧指针
只在完成同样的 generation 校验后自动补写摘要。

插件启动阶段会在后台发起一次资源预热，不阻塞生命周期初始化；管理员命令“下载全部资源”
会等待同一个 single-flight 同步任务，不会并发重复执行 Git。预热失败保留真实异常并写入日志，
不会返回伪成功；终止阶段取消预热协程，并等待底层同步线程完成后再释放数据库。候选物化的
`.candidate-*`、`.archive-*` 临时物仍由同步流程的 `finally` 清理。

兑换码读取默认使用该仓库的 Raw URL，并沿用配置的 GitHub 加速前缀；网络、HTTP 状态码和
契约解析失败分别对外报告稳定类别，不把 URL、响应原文或凭据带入消息。资源仓库为公开仓库；
插件仍只通过 manifest + Git fast-forward-only 同步接口读取，不在资源仓库中保存账号凭据或
其他运行期私有数据。

## 运行期数据目录边界

除 `resources/` 外，插件运行期数据目录还包含（均不可提交到 Git）：

- `dnaby.sqlite3` — SQLAlchemy 2 async 数据库（账号绑定、凭据、隐私、签到记录）。
- `subscriptions.json` — 订阅存储；`ann_state.json` — 兼容旧版的公告已知 id 列表；
  `ann_delivery_state.json` — 版本化的公告按目标投递状态。
- `scheduler_state.json` — 内置任务永久删除 tombstone；`alias_custom.json` — 角色自定义别名覆盖层。
- `cache/` — 玩家数据 JSON、完整 PNG 卡片以及公告列表/详情缓存；公告缓存还包含已校验的源图，
  缓存 key 和身份 tag 只保存 SHA-256 摘要。
- `rendered/` — 玩家/资料/通知 renderer 生成的临时 PNG。
- `panel_custom/` — admin 上传的自定义面板图（WebP，按内容 sha1 去重）；它是本地数据
  目录，与资源仓库的 `panel/`（只读原始面板）分离。

玩家和资料 renderer 生成的 `rendered/*.png` 会在响应边界确认其位于受控渲染目录后，交给
AstrBot 当前事件的临时文件生命周期清理，同时登记到进程内 rendered 租约表。后台维护任务按
`cache.retention_ttl_hours` 扫描已知生成文件前缀，删除过期孤儿；仍有活动租约的发送文件会跳过，
不在受控前缀内的 `panel_custom/` 等文件不会被扫描。generation 内的 `panel/`、`wiki/`、`guide/`
等源资源不会直接登记为临时文件；需要直出时复制出的响应图片属于 `rendered/` 临时物。

## 玩家数据与卡片缓存

玩家概览和角色详情分别缓存已校验的 JSON 数据与 PNG 卡片，均位于运行期根目录的 `cache/`
下。默认 fresh 时间为 30 分钟，硬保留期为 24 小时；超过 fresh 仍在保留期内的条目会先
尝试向 transport 刷新。刷新失败时，如果存在完整旧卡，会附带“可能已过期”提示发送；没有
旧卡则用旧数据渲染本次响应，但不会把它重新写成完整卡片。

渲染结果带有 `placeholder` 素材时标记为 `incomplete`，允许本次发送占位图，但不会写入或
覆盖完整 PNG 卡片。卡片 key 同时关联查询身份、角色/武器参数、隐私显示选项、数据摘要和
当前 generation 的 commit/content/resource version；资源切换后会自然 miss 并重新渲染，旧
条目等待硬保留期清理。缓存失效接口支持 cache type、完整 tag 集合、资源版本或精确 key
组合筛选，只删除无活动租约的普通条目，不会越过运行期目录边界。

O11 新增三条玩家缓存操作：普通用户可用 `刷新<角色名>面板` 强制刷新自己的角色，管理员可用
`刷新<游戏UID>的<角色名>面板` 指定 UID，管理员还可用 `清理全部角色缓存` 仅清除玩家数据和完整
卡片。角色刷新先精准失效该身份的概览与指定角色 tags，再重新读取并按
`cache.refresh_send_card` 决定返回新卡片或仅返回成功文案；指定 UID 的 transport 凭据仍由当前
操作者作用域提供。维护任务启动时先执行一次清理，随后复用 `cache.fresh_ttl_minutes` 作为扫描
周期；若该配置为合法的 `0`（所有缓存立即视为 stale），则复用硬保留期作为扫描周期，避免零秒
忙循环，不增加无产品语义的固定间隔配置。

## 公告列表、详情与缓存

公告列表由 `NoticesTransport` 按服务端分页读取，不设前 20 条的展示上限；详情响应在 transport
边界解包 `postDetail`，缺少有效 `postContent` 时显式失败。公告正文保留所有文本和图片块，
图片 URL 不因 query/hash 或无扩展名而被过滤；详情渲染产生多页时由 `MultiImageResponse` 在同一
条回复中发送。

运行期 `cache/announcement/` 使用统一 `CacheManager`：列表卡、详情页、详情 manifest 和已
通过解码校验的源图均按 `announcement` 类型保存，绝对保留期默认 24 小时。列表或详情内容的
SHA-256 fingerprint 纳入缓存 key，上游内容变化会自然 miss；详情任一正文图片或渲染步骤失败时，
完整卡片和 manifest 不会写入，手动查询返回固定失败文案且不生成占位图。自动订阅在详情、渲染或
图片发送失败时跳过本轮，不发送标题文本；`ann_delivery_state.json` 固定首次观察目标集合，成功
目标不重发，失败目标在后续轮询重试。旧 `ann_state.json` ID 只迁移为已处理，不补发历史公告。

## 图片下载与资源分层

公共基础资源与运行期补充资源是两个边界：`resources/` Git 增量缓存和
`resource_generations/<commit-sha>/` 只接收公共仓库 `main` 的已校验内容；legacy 兼容图片目录
`resource/{avatar,weapon,paint,skill,attr,mod,weapon_attr,weekly_item}/` 以及
`other/ann_card/`、`other/sign/`、`other/calendar/` 是插件数据目录内的运行期缓存或补充资源，
不属于公共资源仓库，也不会被上传或提交。typed 公告 renderer 使用统一的
`cache/announcement/` 保存已校验源图、列表卡和详情页；上述 legacy 目录只为旧的直接调用路径
保留。`panel_custom/` 继续由面板服务独立维护。

`ImageFetcher` 是共享图片下载边界。调用方必须把目标限制在上述运行期目录；它会对已有文件做
PIL 完整解码校验，下载先写同目录临时文件，校验通过后才原子替换。连接/超时、429 和 5xx
按 1 秒、2 秒退避重试并遵循 `Retry-After`；404、鉴权失败、空响应和非图片响应直接失败。
失败不会生成透明假图、空文件或伪成功路径，同一 URL/目标的并发请求共享一次下载。失败日志不
记录完整 URL、响应正文或凭据；缓存根、子目录和目标文件的符号链接也不会被复用或写入。

账号相关的私有补充资源只能落在插件运行期数据目录，不能复制到公共资源 checkout、manifest
或 generation；公共资源仓库不得保存 Cookie、token、签名 URL、SQLite、订阅和其他账号状态。

## 三仓发布与迁移

资源仓库、编辑器和插件是三个独立边界。资源投稿应使用独立的
[dna-resource-editor](https://github.com/FlanChanXwO/dna-resource-editor) 类型化表单；编辑器
源码、依赖和构建产物不能进入资源 checkout。编辑器 webhook 的 `resource-contract` Check
通过后，维护者才合并资源仓库 `main`。发布插件前记录资源 `main` commit SHA 与
`resource_version`，再运行插件的跨仓契约回归；禁止引用投稿分支或仅存在于镜像的 ref。

旧 GitCode 兑换码源使用 `end_at` Unix 秒数。迁移时只把它转换为带时区的 ISO 8601
`expires_at`（初始迁移归一到 `Asia/Shanghai`），可信字段之外的奖励、平台、区服和起始时间
保持缺失；保留旧 JSON 作为仓库外审计 fixture。新资源仓库一旦发布，`data/redeem_codes.json`
是唯一事实源，插件不再回退旧 GitCode 或读取 `end_at`。完整数据字段见编辑器的
[resource contract](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/resource-contract.md)。

## 镜像信任与切换

加速前缀只是 Git/Raw 传输路径：规范 origin 仍为
`https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git`，信任边界仍是资源仓库
`main` 的 commit、manifest、schema 和完整 generation 校验。镜像不能改变 remote、分支或
资源版本，也不能作为只存在于镜像的发布源。

切换前执行 owner 命令 `资源状态`，记录 origin、main HEAD、manifest/resource version、加速
模式和最近刷新结果；修改 `resources.github_acceleration` 后执行 `下载全部资源` 并核对
状态。`off` 为默认直连；内置模式为 `edgeone`、`hk`、`gh_proxy`、`dpik`，`custom` 只接受
安全 HTTP(S) 基础 URL。镜像不支持 Git smart HTTP、返回错误或候选校验失败时会直接报告；
不会静默直连、改走 ZIP、伪造成功或截断合法资源。故障时切回 `off`，不要手工把 origin 改成
镜像地址。

## 资源升级、备份与回滚

升级插件前备份整个 `StarTools.get_data_dir("astrbot_plugin_dnaby")`，至少包含
`dnaby.sqlite3`、`subscriptions.json`、`ann_state.json`、`ann_delivery_state.json` 和
`panel_custom/`。已有
`resources/` 仍作为 Git 增量缓存；`resource_generations/current.json` 缺失时启动只保留
旧缓存并等待下一次下载，下载成功后从 `FETCH_HEAD` 生成新的已验证快照。启动清理只针对孤立
generation/candidate/archive，不删除面板图、数据库、订阅或公告状态。

三类回滚分别执行：

1. **资源数据**：对错误的 `main` commit 创建 `git revert` PR，等待 `resource-contract`
   Check 后合并；不 force-push、删 commit 或提升镜像-only 内容。
2. **编辑器 Worker**：在编辑器 runbook 中以 `npx wrangler deployments status` 找到版本，再
   执行 `npx wrangler rollback <VERSION_ID>`；Worker 代码回滚不自动恢复 secrets。
3. **插件或镜像**：安装上一份已验收插件 revision，把 `github_acceleration` 切回 `off`，
   保留 runtime data 和当前 generation；确认 canonical origin 后再下载。

编辑器的完整部署、GitHub App/Turnstile、required ruleset、密钥轮换和事故 runbook 见
[operations.md](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/operations.md)。
