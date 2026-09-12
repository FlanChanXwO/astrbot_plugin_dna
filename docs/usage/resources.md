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

资源仓库当前只承担已接入的角色头像、角色立绘和武器图等公共资源；其他动态素材仍按需写入 `cache/assets/`。资源仓库的 `resource_manifest.json` 仍是资源布局与版本的事实源。

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

现行布局是一次不兼容的运行期目录变更。旧版本升级必须由管理员**停机、备份、人工复制或移动、验证、清理旧标记**；启动门禁发现旧布局时会直接报错。插件不会自动复制、移动、双读旧数据，也不会在失败时替管理员回滚。

### 停机与备份

1. 停止插件及其宿主进程，等待正在进行的同步、下载、渲染和数据库写入结束；不要在任务仍运行时复制数据。
2. 备份整个旧插件数据根目录，使用能保留文件内容、目录结构和必要权限的工具。备份应放在独立且受限的位置，并记录所对应的旧插件版本。
3. 迁移前先确认备份可读取。迁移过程优先复制而不是直接删除旧文件，待新布局验证通过并经过回滚观察期后再清理旧目录。
4. 如果旧目录同时存在 `dnaby.db` 和 `dnaby.sqlite3`，不要合并或互相覆盖；先确认旧版本实际使用的数据库文件，无法确认时保留备份并暂停迁移。

### 旧路径到新路径

表中“复制内容”指复制目录内的内容，而不是把旧父目录再套一层。不存在的旧项无需创建空文件。

| 旧版本路径 | 新版本路径 | 说明 |
| --- | --- | --- |
| `dnaby.db` 或 `dnaby.sqlite3` | `db/dna.sqlite3` | 只能迁移旧版本实际使用的数据库；不要合并两个数据库。 |
| `subscriptions.json` | `state/subscriptions.json` | 保留订阅状态。 |
| `scheduler_state.json` | `state/scheduler.json` | 保留调度状态。 |
| `ann_state.json` | `state/announcements/seen.json` | 保留公告已见状态。 |
| `ann_delivery_state.json` | `state/announcements/delivery.json` | 保留公告投递状态。 |
| `client_update_state.json` | `state/client_update.json` | 保留客户端更新基线和投递状态。 |
| `resource/alias/char_alias.json` | `state/aliases/char.json` | 只迁移用户自定义项，避免覆盖新版本内置别名。 |
| `resource/alias/weapon_alias.json` | `state/aliases/weapon.json` | 只迁移用户自定义项，避免覆盖新版本内置别名。 |
| `alias_custom.json` | `state/aliases/char.json` | 旧文件若存在，合并其用户自定义角色别名；不要把两个 JSON 文件直接拼接。 |
| `weapon_alias_custom.json` | `state/aliases/weapon.json` | 旧文件若存在，合并其用户自定义武器别名。 |
| `resource/id2name.json` | `state/aliases/id2name.json` | 迁移后仍由资源/别名逻辑校验；无法确认格式时保留备份并重新生成。 |
| `resource/avatar/` | `cache/assets/game_avatar/` | 可选迁移；这是动态游戏头像缓存，不是公共资源 generation。 |
| `resource/weapon/`、`resource/paint/`、`resource/skill/`、`resource/attr/`、`resource/mod/`、`resource/weapon_attr/`、`resource/weekly_item/` | `cache/assets/<对应目录>/` | 可选迁移动态素材；只复制目录内容，不要把它们当作已校验公共快照。 |
| `resource_generations/` | `resources/generations/` | 可复制整个 generation 树，但启动后必须执行 `dna资源状态` 验证；校验失败时恢复备份并重新同步，不要手工改 current 指针。 |
| 旧 `resources/` 工作树及 `resources/.git` | `resources/repository/` | 复制完整仓库工作树到新位置，不要只复制 `.git`；无法确认工作树与 generation 兼容时，保留备份并使用 `dna同步资源` 获取新快照。 |
| `rendered/` | `cache/rendered/` | 可选迁移渲染产物；不迁移也不会丢失业务状态。 |
| `other/` | `cache/media/` | 可选迁移其他媒体；其中 `sign/`、`ann_card/`、`calendar/` 分别对应新目录下的同名子目录。 |
| `login_qr/` | `cache/media/login_qr/` | 临时登录二维码，可不迁移。 |
| `custom/` | 无目标 | 自定义素材功能已移除，不迁移到新布局；升级前如有需要仅保留在人工备份中。 |
| `cache/player_data/` | `cache/api/player_data/` | 可选迁移 API 缓存内容。 |
| `cache/player_card/` | `cache/rendered/player_card/` | 可选迁移玩家卡渲染缓存。 |
| `cache/mh/` | `cache/api/mh/` | 可选迁移密函 API 缓存。 |
| `cache/announcement/` | `cache/media/announcement/` | 可选迁移公告媒体缓存。 |
| `players/` | 无直接目标 | 不要臆造新的玩家数据目录；保留在备份中，运行期缓存按需重建。 |
| `config.json`、`sign_config.json` | 无直接目标 | 这些不是新布局的运行期状态文件；按当前 AstrBot 配置/Dashboard 重新录入需要的设置，不要原样复制。 |

角色/武器别名是需要保留的用户数据，迁移时应合并到 `state/aliases/char.json` 和 `state/aliases/weapon.json`，而不是因为它们看起来像缓存就删除。相反，`cache/` 下的动态素材、API、渲染和媒体内容可以全部不迁移；缺失项会在后续请求中按现行资源优先级重新获取。

### 清理、启动与验证

1. 完成复制后，检查 `db/dna.sqlite3`、`state/`、别名文件和需要保留的资源 generation 是否可读。
2. 删除或移走旧布局中的文件和非空目录，尤其是旧数据库、`resource/`、`resource_generations/`、旧 `resources/.git`、旧状态文件及旧缓存入口。不要只留下一个旧 `.git` 标记；它仍会阻止启动。
3. 启动新版本前，确保旧目录不再包含待检测的实际数据。启动门禁只读检测，不会替你搬运数据。
4. 启动后执行 `dna资源状态`，确认当前 generation、最近同步结果和校验状态正常；再执行一个不改变数据的查询命令，确认数据库和别名可用。
5. 若资源 generation 无法验证，停止新版本，恢复迁移前备份，随后重新执行人工迁移或 `dna同步资源`。不要在同一数据根目录混用新旧版本。
6. 保留旧备份和新布局备份直到回滚观察期结束，再按部署环境的保留策略清理旧文件。清理前不要删除唯一的数据库、状态或别名备份。

### 回滚

1. 停止新版本，并将当前新布局完整保留为故障排查副本；不要把它与旧备份混合覆盖。
2. 将迁移前的旧数据备份原样恢复到旧版本使用的数据根目录，确认旧目录结构完整。
3. 启动旧插件版本验证业务；旧版本和新版本不要同时操作同一份数据，也不要让旧版本读取混合了新目录的根目录。
4. 若需要再次升级，先停止旧版本，重新制作工作副本，按本节步骤迁移并清理旧标记。代码不提供自动降级或自动回滚。

## 缓存与备份

公共资源 generation 不等同于普通缓存；迁移或清理它前必须先确认仍有可用的公共资源来源。`cache/assets/`、`cache/api/`、`cache/rendered/` 和 `cache/media/` 属于可重建缓存，可以在空间不足或迁移时跳过。数据库、订阅/调度/公告状态、客户端更新状态和用户别名不是普通缓存，若需要保留用户数据就必须按上表迁移并备份。

需要迁移实例时，应按照实际部署环境的备份策略处理整个数据目录，并限制备份访问权限。
