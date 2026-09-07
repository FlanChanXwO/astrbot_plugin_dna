# 公共资源

角色、武器、图鉴、攻略、日历、字体和兑换码等资料由公共资源仓库提供。运行期资源统一位于
AstrBot 的插件数据目录 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 下，不写入插件源码目录。

公共资源仓库：<https://github.com/FlanChanXwO/astrbot_plugin_dna_resources>

## 资源目录

插件使用两层目录：

- `resources/`：公共资源的 Git 同步缓存。
- `resource_generations/<commit-sha>/`：通过完整校验后发布的只读资源快照。
- `resource_generations/current.json`：指向当前资源快照的指针。
- `resource_generations/validation.json`：当前 generation 最近一次完整校验失败的错误类型摘要。
- `resource_generations/last_sync.json`：最近一次同步的安全摘要；只保存动作、版本、
  commit SHA 或错误类型，不保存仓库路径、凭据或异常原文。
- `rendered/`：玩家、图鉴和通知响应生成的临时图片。
- `cache/`：玩家数据、公告和已校验图片的运行期缓存。

资源快照和缓存都位于插件数据目录。检测到资源根目录、快照、指针或图片缓存是符号链接时，
插件会停止本次读写，避免路径越出数据目录。

资源仓库根目录需要提供 `resource_manifest.json`。manifest 至少声明格式版本、资源版本和完整
运行期目录，例如：

```json
{
  "format_version": 1,
  "required_dirs": [
    "fonts", "images", "panel", "alias", "data", "schemas",
    "wiki/role", "wiki/weapon", "wiki/spirit", "guide", "weekly_item", "calendar"
  ],
  "resource_version": "2026.08.11"
}
```

显式同步时会检查 required directories 是否存在，并拒绝相对路径逃逸资源仓库根目录的声明。manifest
中的文件摘要如果存在，也会逐项校验；校验失败时不会替换当前可用快照。插件启动不会执行 Git
同步，但会在把已有 current generation 交给业务读取前完成完整校验；损坏的快照不会作为可用资源暴露，
插件仍会继续启动，并通过资源状态命令保留校验失败类型，供管理员执行同步资源修复。

## 资源内容

- `fonts/`：玩家和资料图片使用的字体。
- `images/`：角色头像、武器、技能、魔之楔和立绘等图片。
- `panel/`：角色详情使用的面板资源。
- `alias/`：角色和武器的默认别名。
- `wiki/role/`、`wiki/weapon/`、`wiki/spirit/`：图鉴图片。
- `guide/`：角色攻略图片。
- `weekly_item/`、`calendar/`：周报和活动日历索引。
- `data/redeem_codes.json`：兑换码清单，命令只展示当前有效条目。

资源根目录尚未准备好时，插件仍可以启动；需要图片的命令只会使用显式的空资源视图，返回
`placeholder` 或 `fallback` 状态，图鉴和攻略命令会提示资源未找到。插件不会把 `resources/`
Git checkout 当作未经验证的业务资源源。资源根目录存在但 manifest 不完整时，会明确报告同步错误，
便于管理员修复资源。

## 同步资源

管理员可以使用以下命令：

- `资源状态`：查看资源仓库、manifest、当前 generation 和最近一次同步状态。
- `同步资源`：从规范仓库的 `main` 分支获取候选版本，完成校验后再发布新的资源快照。

`资源状态` 输出固定的 `repository path`、`generation id`、`active pointer`、
`resource_version` 和 `last sync result`。它只读取 pointer、generation metadata、manifest
和最近同步摘要，不触发 Git fetch、完整 validator、PIL 解码或完整 SHA-256；同步失败时
只记录安全错误类型并保留旧 generation。

同步时会检查仓库来源、分支、目录布局、文件摘要、图片是否可解码以及资源索引。Git 不可用、
网络或 HTTP 状态异常、仓库状态不干净、候选版本不完整或校验失败时，命令会返回明确错误，并
保留原来的资源快照。同步不会自动改走未校验的压缩包或其他来源。

默认 `resources.github_acceleration` 为 `off`，表示直连公共仓库；也可以选择 `edgeone`、`hk`、
`gh_proxy`、`dpik` 或 `custom`。使用 `custom` 时，只填写不含凭据、查询参数和片段的 HTTP(S)
基础地址。加速地址只改变传输路径，不改变仓库、分支或校验规则。

首次同步可能需要一段时间。插件不会在启动时后台预热或自动同步资源；管理员命令会等待当前同步
完成，重复触发不会并发启动多次同步。远端 commit 与当前已校验可用的 generation 相同时，命令会快速返回
“资源已是最新”；若同 commit 的 current generation 已损坏，则会重新物化并校验候选快照。

## 资源更新与缓存

资源更新成功后，新请求使用新的 generation；正在生成的图片会继续使用开始读取时的资源版本，
旧 generation 会在没有活动读取后回收。重启时会读取 current 指针指向的 generation metadata，并在暴露资源前
完成完整校验；校验失败时不会阻断插件构造，管理员可用资源状态查看错误类型并通过同步资源重建同一远端 commit
的 generation。在 current 不可用或完整重验期间，业务请求不会回退到 `resources/` Git checkout，
而是得到空资源视图；资源状态和同步修复入口仍然可用。资源状态命令仍只读取轻量 metadata，不触发 Git、
完整 validator 或图片解码。同步物化阶段会
清理 candidate/archive 临时文件。

兑换码从 `data/redeem_codes.json` 读取，只有当前有效条目会由 `兑换码` 命令展示。玩家数据、玩家卡片、
公告列表/详情/源图和密函快照等 `CacheManager` 内容缓存共用 `cache.ttl_hours`：`-1` 表示永久
有效，`0` 表示不读取或写入持久缓存，正整数表示统一的缓存有效小时数；到期后会重新请求并渲染，
不会回退旧内容。资源版本变化会使相关图片自然重新生成。`rendered/` 临时文件仍由内部固定的
24 小时周期清理，资源快照继续由 generation lease 独立管理。单角色主动刷新由
`cache.refresh_send_card` 控制是否在“角色【正式名】面板已刷新”之后发送新图片，默认启用；
关闭时仍然完整刷新、渲染并更新缓存。批量刷新始终只返回成功/失败汇总，不逐张发送图片。

客户端更新的基线与投递状态单独保存在运行期数据目录的 `client_update_state.json`，不属于公共资源缓存；资源快照清理不会删除该文件。

图片下载会先写入同目录临时文件，完成文件头和图片解码检查后再替换目标文件。下载失败不会
生成空文件、透明假图或看似成功的路径；错误回复不会包含完整地址、响应正文或凭据信息。

## 备份与排障

升级插件前，建议备份整个 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 目录，至少确认
数据库、订阅记录、公告状态、客户端更新状态、自定义别名、`resources/` 和 `resource_generations/` 可以恢复。
备份不应提交到 Git、上传到 issue 或粘贴到聊天中。

如果资源状态异常：

1. 先执行 `资源状态`，确认当前 generation 和错误类别。
2. 检查 `resources.github_acceleration` 与网络连接；使用自定义加速时确认地址格式正确。
3. 修复后执行 `同步资源`，确认新的 generation 已完成校验。
4. 若同步仍失败，保留现有资源并查看 AstrBot 日志，不要手工修改资源仓库来源。

资源反馈请附上资源版本、manifest 错误类别和已脱敏日志，不要上传账号数据或整个插件数据目录。
