# 公共资源

角色、武器、图鉴、攻略、日历、字体和兑换码等资料由公共资源仓库提供。运行期资源统一位于
AstrBot 的插件数据目录 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 下，不写入插件源码目录。
插件源码只保留少量明确登记的 bootstrap 资源；完整字体、大型纹理和资料图片不应因为本地
`resources/` Git 缓存存在就被直接使用，必须先进入已验证的资源快照。

公共资源仓库：<https://github.com/FlanChanXwO/astrbot_plugin_dna_resources>

## 资源目录

插件使用两层目录：

- `resources/`：公共资源的 Git 同步缓存。
- `resource_generations/<commit-sha>/`：通过完整校验后发布的只读资源快照。
- `resource_generations/current.json`：指向当前资源快照的指针。
- `rendered/`：玩家、图鉴和通知响应生成的临时图片。
- `cache/`：玩家数据、公告和已校验图片的运行期缓存。

资源快照和缓存都位于插件数据目录。检测到资源根目录、快照、指针或图片缓存是符号链接时，
插件会停止本次读写，避免路径越出数据目录。

## 资源边界与解析顺序

运行期 renderer 只接收逻辑资源 key，不自行判断资源来自插件目录还是资源仓库。解析顺序固定为：

1. **verified snapshot**：`resource_generations/<commit-sha>/` 中通过 manifest、路径安全、文件
   SHA-256、字体文件头和图片解码校验的资源；`resource_generations/current.json` 只指向这类快照。
2. **bootstrap**：插件内明确登记的少量基础资源，例如帮助数据/必要小图标、周报小图标、
   `src/utils/texture2d/` 的装饰素材和 `texture.common.number.0` 至 `texture.common.number.10`。
   bootstrap 不等于完整资料库，未登记的本地文件不会被递归发现或作为隐式 fallback。
3. **placeholder/none**：没有可验证资源时返回可见的简化结果或缺失状态，并在渲染结果中保留
   `incomplete` 标记。`placeholder` 不能写入完整卡片缓存，避免缺失资源被误当作成功快照。

没有 verified snapshot 时，插件仍应完成初始化；帮助和不依赖公共素材的文字命令可以继续使用，
依赖字体、头像、面板、日历、攻略或公告装饰的图片命令按自身 renderer 的语义降级。同步完成后，
新的请求会使用新 generation，正在进行的渲染继续持有开始读取时的 generation lease，因此无需重启 AstrBot
或插件来刷新资源。

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

插件会检查 required directories 是否存在，并拒绝相对路径逃逸资源仓库根目录的声明。manifest
中的文件摘要如果存在，也会逐项校验；校验失败时不会替换当前可用快照。

## 资源内容

- `fonts/`：玩家和资料图片使用的完整字体，来自 verified snapshot。
- `images/`：角色头像、武器、技能、魔之楔和立绘等图片，来自 verified snapshot。
- `panel/`：角色详情使用的面板资源，来自 verified snapshot。
- `alias/`：角色和武器的默认别名。
- `wiki/role/`、`wiki/weapon/`、`wiki/spirit/`：图鉴图片。
- `guide/`：角色攻略图片。
- `weekly_item/`、`calendar/`：周报和活动日历索引。
- `data/redeem_codes.json`：兑换码清单，命令只展示当前有效条目。

资源根目录尚未准备好时，插件仍可以启动；需要图片的命令会返回 `placeholder` 或 `fallback`
状态，图鉴和攻略命令会提示资源未找到，并保留 `incomplete` 结果标记。资源根目录存在但 manifest
不完整、文件摘要不匹配或图片/字体校验失败时，会明确报告同步错误，便于管理员修复资源；插件不会
把 candidate 或未校验的 Git checkout 当作运行期资源。

## 首次安装与首次同步

首次安装后，建议（但不是强制）管理员依次执行 `资源状态` 和 `下载全部资源`。首次同步的目标是
把公共资源仓库 `main` 上的一个完整提交转成 verified snapshot，而不是只把 Git 工作树放在
`resources/` 目录。同步完成后可再次执行 `资源状态`，确认 current generation、`resource_version`
和校验摘要已经更新。

首次同步不是插件安装的硬性前置条件，也不是对真实账号或生产数据的操作；网络不可用时可先使用
bootstrap 和降级结果，修复网络后再同步。插件启动预热只会准备/校验受控资源，不会绕过 manifest
或自动接受未验证的候选版本。

## 同步资源

管理员可以使用以下命令：

- `资源状态`：查看资源仓库、manifest、当前 generation 和最近一次同步状态。
- `下载全部资源`：从规范仓库的 `main` 分支获取候选版本，完成校验后再发布新的资源快照。

同步时会检查仓库来源、分支、目录布局、文件摘要、字体文件头、图片是否可解码以及资源索引。Git 不可用、
网络或 HTTP 状态异常、仓库状态不干净、候选版本不完整或校验失败时，命令会返回明确错误，并
保留原来的资源快照。同步不会自动改走未校验的压缩包或其他来源。

资源仓库先行：必须先把变更合并到规范 `main`，并通过资源契约检查；插件发布或使用新素材前应记录该
资源 commit SHA 与 `resource_version`。插件不消费投稿分支、镜像-only ref 或编辑器工作树。

默认 `resources.github_acceleration` 为 `off`，表示直连公共仓库；也可以选择 `edgeone`、`hk`、
`gh_proxy`、`dpik` 或 `custom`。使用 `custom` 时，只填写不含凭据、查询参数和片段的 HTTP(S)
基础地址。加速地址只改变传输路径，不改变仓库、分支或校验规则。

首次同步可能需要一段时间。插件启动时会在后台准备资源，不会把未完成的同步当作成功；管理员
命令会等待当前同步完成，重复触发不会并发启动多次同步。

## 资源更新与缓存

资源更新成功后，新请求使用新的 generation；正在生成的图片会继续使用开始读取时的资源版本，
旧 generation 会在没有活动读取后回收。重启时只恢复 current 指针指向的已校验快照，并清理资源
同步产生的临时文件。

如果新资源导致视觉或解析回归，先在资源仓库对错误提交创建 `git revert` PR，等待契约检查通过
后合并 `main`，再执行 `下载全部资源`。候选校验失败时插件继续提供上一份 verified snapshot；
不要手工替换 current 指针、把镜像内容直接提升为发布源，或通过删除整个资源目录来“回滚”。

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
3. 修复后执行 `下载全部资源`，确认新的 generation 已完成校验。
4. 若同步仍失败，保留现有资源并查看 AstrBot 日志，不要手工修改资源仓库来源。

资源反馈请附上资源版本、manifest 错误类别和已脱敏日志，不要上传账号数据或整个插件数据目录。
