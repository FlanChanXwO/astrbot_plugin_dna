# 公共资源

角色、武器、图鉴、攻略、日历、字体和兑换码等公共资料由独立仓库维护：

<https://github.com/FlanChanXwO/dna-resource>

插件运行时把资源缓存、经过校验的资源快照和渲染产物放在 AstrBot 分配的插件数据目录，不把同步内容写进插件源码目录。

## 同步模型

管理员可使用：

- `dna资源状态`：查看当前资源/快照与最近同步结果；
- `dna同步资源`：从规范资源仓库获取候选内容，校验后再切换为可用版本。

精确命令匹配和权限以 [`commands.json`](../../commands.json) 为准。

资源同步遵循“候选 → 校验 → 发布”的边界。manifest、路径、声明的摘要和需要解码的图片等校验未通过时，不应把候选版本发布为当前资源；已有可用快照会尽量继续保留。当前实现细节以 `src/infrastructure/resources/` 为准。

## 现行运行期数据布局

以下路径都相对于“插件数据根目录”。插件源码目录不是运行期数据目录。

| 区域 | 内容 |
| --- | --- |
| `db/dna.sqlite3` | 账号、业务和迁移所需的 SQLite 数据库。 |
| `state/` | 订阅、调度、公告投递、客户端更新和别名等需要恢复的状态；别名文件位于 `state/aliases/`。 |
| `resources/repository/` | `dna-resource` 的工作树。 |
| `resources/generations/` | 经过校验的公共资源 generation 及其 current、同步和校验状态。 |
| `cache/assets/` | 游戏素材和用户头像等可重建动态缓存。 |
| `cache/api/`、`cache/rendered/`、`cache/media/` | API 响应、渲染产物以及签到、公告、日历和登录二维码等媒体缓存。 |
| `backups/` | 管理员人工迁移或维护时保留的备份根目录。 |
| `backups/database/` | 数据库人工备份。 |

公共资源的当前 generation 是已校验的发布物，不应当当作普通缓存删除后再手工拼装。动态素材、API 响应、渲染产物和媒体文件均可在需要时重新获取或生成；同步后新请求会使用新的 generation，旧动态副本不会自动清理，也不会覆盖公共资源快照。

资源仓库承担的公共资源包括：

- 动态素材：角色头像、角色立绘、武器图（由 #58 引入的 `AssetResolver` 按 generation 解析）；
- 静态渲染素材：`fonts/`（正文字体与 Unicode fallback）、`textures/`（角色总览/详情、日常便签、周报、签到、密函、公告、帮助等卡片纹理）、`calendar/`（活动日历底图与装饰）；
- 资料：`wiki/`、`guide/`、`weekly_item/`、`data/`、`alias/` 等图鉴与文本资源。

静态渲染素材由 `StaticAssetResolver`（`src/infrastructure/rendering/static_assets.py`）从 verified generation 解析；插件包内仅保留少量显式 bootstrap 资源（帮助命令图标、logo 与 `utils/texture2d/` 中的通用装饰图），且只有列入显式 allowlist 的路径才会在无 snapshot 时回退本地。静态素材缺失时渲染降级为可见 placeholder，并标记 `incomplete=True`。

其他动态素材仍按需写入 `cache/assets/`。资源仓库的 `resource_manifest.json` 仍是资源布局、文件摘要与版本的事实源。

## manifest 与目录

资源仓库自己的 `resource_manifest.json` 是资源布局与版本的事实源。本仓库文档不复制 `required_dirs`、文件哈希或某个 commit 的固定快照，避免资源仓库更新后出现两份不一致的清单。

需要确认资源内容时，直接查看 `dna-resource` 当前 `main` 分支及 manifest。

## GitHub 加速

`resources.github_acceleration` 与相关自定义地址字段控制资源同步的传输路径。可选值和默认值以当前 [`_conf_schema.json`](../../_conf_schema.json) 为准。自定义地址不要包含凭据、查询参数或私密信息。

传输加速只改变获取方式，不改变规范仓库或校验规则。

## 资源不可用时

先执行 `dna资源状态` 获取安全摘要，再检查网络/加速配置，最后执行 `dna同步资源`。不要通过手工替换 current 指针、跳过 manifest 校验或直接把未经验证的 Git checkout 当作业务资源来“修复”。

排障反馈只需要资源版本、错误类别和脱敏日志；不要上传插件数据目录。

## 旧版本手动迁移

v0.5.1 起插件不再检测、读取、迁移或提示如何转换 pre-v0.5 旧数据布局（旧数据库文件、旧 `resource/`、`resource_generations/` 等）。

支持的升级基线是**已经在 v0.5.0 当前数据布局上正确运行的实例**。如果仍处于更旧的布局，必须先升级或整理到 v0.5.0 的运行期布局（迁移步骤见 v0.5.0 对应版本文档），或执行全新安装；直接跳到 v0.5.1 时旧路径不会被识别，也不会得到迁移提示。

## 缓存与备份

公共资源 generation 不等同于普通缓存；迁移或清理它前必须先确认仍有可用的公共资源来源。`cache/assets/`、`cache/api/`、`cache/rendered/` 和 `cache/media/` 属于可重建缓存，可以在空间不足或迁移时跳过。数据库、订阅/调度/公告状态、客户端更新状态和用户别名不是普通缓存，若需要保留用户数据就必须按上表迁移并备份。

需要迁移实例时，应按照实际部署环境的备份策略处理整个数据目录，并限制备份访问权限。
