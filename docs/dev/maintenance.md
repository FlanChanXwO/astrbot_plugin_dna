# 维护

## 改动同步

改命令清单（`commands.json`）、配置（`src/infrastructure/config/`）、登录链路
（`src/modules/account/`）、数据结构（`src/infrastructure/persistence/`）或管理页时，
同步更新最具体的 `docs/usage/`、`docs/project/` 文档。`docs/porting/` 与 `docs/legacy/`
是历史移植/排查存档；判断当前行为时以 `docs/project/` 和 `docs/usage/` 为准。

## Agent Tools 热重载

Agent Tools 只由 `agent_tools.enabled` 控制。启用后由插件生命周期在初始化时注册、终止时
解除注册，不要在 Dashboard 或聊天命令中手工重复注册；关闭开关后应确认 Context 中没有
DNABY 工具。若注销某个工具失败，生命周期会保留失败项，下一次终止或启动先重试残留并继续
暴露错误，维护时应查看 AstrBot 日志中的工具名和错误类型，不要用重启容器掩盖问题。

`dnaby_sign` 是唯一写工具，仅允许当前事件原始消息明确确认签到；生产排查和测试不得使用真实
签到副作用。其余工具为查询或当前用户订阅查看，不能作为账号、凭据、隐私、订阅或管理配置的
写入口。完整 schema 与返回边界见 [Agent Tools 使用说明](../usage/agent-tools.md)；阶段三
发布前模拟和精确回滚见 [Agent Tools 发布与回滚清单](../porting/agent-tools-release-checklist.md)。

## 运行期数据与备份

插件运行期数据必须位于
`StarTools.get_data_dir("astrbot_plugin_dnaby")`，重点文件包括：

- `dnaby.sqlite3`：账号绑定、凭据、隐私和签到记录；其中凭据是明文敏感数据。
- `subscriptions.json`、`ann_state.json`、`ann_delivery_state.json`：订阅、公告兼容 ID 列表与按
  目标投递状态。
- `scheduler_state.json`：任务永久删除 tombstone。
- `alias_custom.json`、`panel_custom/`：角色自定义别名与自定义面板图。

在首次执行 `0003_global_identity` 或 `0004_app_credentials_only`、升级插件版本、执行全局账号删除，或需要执行永久任务/面板
删除前，应先停止 AstrBot 或至少停止 DNABY 的写入，再把 SQLite 和需要保留的 JSON/目录复制到
受控备份目录。备份目录必须限制权限，因为其中可能包含 Cookie、token、refresh token、设备码
和 d_num；备份文件名、日志和工单不得复制这些值。

可按实际部署路径执行以下检查式流程（`DATA_DIR` 和 `BACKUP_DIR` 仅为占位符，不能照抄到生产）：

```bash
test -f "$DATA_DIR/dnaby.sqlite3"
mkdir -p -- "$BACKUP_DIR"
cp -p -- "$DATA_DIR/dnaby.sqlite3" "$BACKUP_DIR/dnaby.sqlite3"
for item in subscriptions.json ann_state.json ann_delivery_state.json scheduler_state.json alias_custom.json; do
  test ! -e "$DATA_DIR/$item" || cp -p -- "$DATA_DIR/$item" "$BACKUP_DIR/$item"
done
test ! -d "$DATA_DIR/panel_custom" || cp -a -- "$DATA_DIR/panel_custom" "$BACKUP_DIR/panel_custom"
```

上述命令只建立副本，不代表备份已经可恢复；部署者还应记录代码版本、迁移前 schema 版本、
备份路径和校验结果，并在受控环境验证副本可读。不要把备份提交 Git、上传到 issue 或粘贴到
聊天记录。

## 破坏性迁移与回滚

`0003_global_identity` 会删除并重建 `account_bindings`、`credential_records`、
`privacy_settings`、`group_privacy_settings` 四张旧表；旧账号、凭据、个人隐私和群隐私行
不会迁入，新迁移只保留 `sign_records`。`0004_app_credentials_only` 再从当前凭据表物理
删除五个 Web 列，保留 App 字段和其它业务表。因此：

1. 先停写并完成 `dnaby.sqlite3` 备份，再审查旧 `0002` schema 的重复全局隐私行。
2. 使用与插件版本匹配的 Alembic 配置执行 `upgrade head`；迁移失败时保留原错误并停止部署，
   不把旧 `dnaby.db` 改名后交给新 schema，也不把 `create_schema_for_tests()` 当作生产迁移。
3. 升级后检查新 schema（确认五个 Web 列不存在）、App 记录数、插件启动和最小管理/命令路径；
   不要期待四张被清空的表或已删除的 Web 凭据自动恢复。
4. 若必须回退，停止新版本，使用普通 revert 或部署旧版本代码，并同时恢复与旧代码匹配的迁移前
   `dnaby.sqlite3` 备份；不能只回退代码、只执行 `downgrade`，或让旧代码直接读取新 schema。
5. 恢复后重新检查任务、订阅、别名和面板目录。回退数据库会丢失迁移后写入，需在变更记录中明确。

`downgrade` 只恢复旧的空表结构，并为 `credential_records` 创建空 Web 列，不恢复被 `0003` 或
`0004` 丢弃的数据。代码回滚禁止 `reset --hard`、
force push 或删除分支；应保留失败版本、备份和回滚记录，便于复盘。

## Dashboard 管理操作

管理页只通过已认证的 AstrBot Dashboard 入口使用。账号详情会显示全部 App 明文凭据，
属于高风险操作：使用受控管理员浏览器，避免截图、录屏、剪贴板复制和浏览器扩展采集；操作完成
后关闭编辑器并确认页面不再保留 secret。`no-store` 只约束管理 HTTP 响应缓存，不能防止屏幕或
宿主环境记录。

全局账号删除前必须保存删除预览并完成成员扫描；扫描结果为 `unknown`、平台不支持或任一群仍
为 `present` 时不得强行绕过安全门禁。全局删除会移除用户绑定、凭据、个人隐私、个人密函订阅
和关联 UID 的签到历史，但不级联群级隐私、群订阅、群结果或通知资源；跨 SQLite/JSON 的部分
失败应按响应中的逐项状态重试。

角色面板图的全删、账号全局删除和任务永久删除均不可通过页面撤销。角色默认别名来自只读资源，
恢复默认只删除 `alias_custom.json` 的自定义追加；需要保留自定义内容时，应在写操作前备份对应
JSON/目录。

## 生产插件发布、只读核验与回滚

生产目标为 `atri`，插件目录为 `/srv/AstrBot/data/plugins/astrbot_plugin_dnaby`，运行容器为
`astrbot`。发布或回滚必须固定到可追溯的插件 SHA，并遵循以下边界：

1. 先只读记录当前插件 `HEAD`、`git status --porcelain`、`metadata.yaml` 版本、资源
   `resource_generations/current.json` 摘要、容器 running/restart count 和日志起点；不读取或输出凭据。
2. 通过已认证 Dashboard GET 确认插件 ID 唯一、`activated=true` 且凭据有 `plugin` scope。未认证
   GET 的 `401/403` 只能说明认证保护存在，不能作为插件状态。
3. 在 clean 的生产仓库中非破坏性 fetch 并验证目标 SHA；容器内用 `python -B` 做入口/registry/schema
   只读 smoke。任何失败都停止，不覆盖生产现场改动。
4. 只有在得到该版本的部署授权后，才调用
   `POST http://127.0.0.1:6185/api/v1/plugins/astrbot_plugin_dnaby/reload`；必须同时核对 HTTP、
   业务响应、插件状态、日志和容器 restart count。不得用容器重启替代定向 reload。
5. 若失败，停止继续验收，保留失败版本与日志；在 clean 前提下检出已记录的上一稳定 SHA，调用同一
   reload endpoint，再重复状态和最小 smoke。代码回滚不等于数据库回滚，破坏性 schema 必须按上文备份恢复。

O24 的只读结果（2026-08-30）为：生产插件 `cb9996dbb36ccaeaca483035c0cbbbc59a8549c9`、
`v0.2.0`、detached/clean；命令 registry 61 条；资源 generation/content SHA 与
[资源说明](../usage/resources.md)一致；`agent_tools.enabled=false`；容器运行、restart count 为 0，
容器内 import/schema smoke 通过。O24 未调用 reload、未切换 SHA、未修改生产配置或运行期数据。

## 任务 tombstone 恢复边界

`dnaby_sign_daily`、`dnaby_mh_push`、`dnaby_ann_poll` 可永久删除；
`dnaby_sign_cleanup` 只能暂停/恢复，不能永久删除。永久删除会把任务 ID 原子写入
`scheduler_state.json`，重启后隐藏并跳过该任务，管理 API 不提供恢复。

若误删且确有删除前备份，停止插件后仅能由部署者审核并恢复备份的
`scheduler_state.json`，再重启并核对任务；这属于运维回退，会覆盖该文件之后的 tombstone 变更，
不是页面恢复功能。没有可验证备份时，按不可恢复处理。

## 已知运行限制

- 离群成员扫描和删除前复核只支持 `aiocqhttp`/OneBot V11；其他平台前端按钮预先禁用，后端也
  返回 `unsupported`，不会把能力缺失伪装成用户 `absent`。
- 没有真实账号凭据、可用上游或 T2I 服务时，玩家预览不能作为生产图片验收；离线测试使用隔离
  SQLite、fake transport、fake aiocqhttp 和临时数据目录。
- `subscriptions.json`、SQLite、任务状态和文件目录没有跨存储物理事务；恢复和重试都必须依照
  管理响应逐项核对，不能仅凭“请求返回”推断全部成功。

## 三仓发布顺序

1. 在资源仓库通过编辑器表单投稿；检查 `resource_manifest.json`、声明的文件 SHA-256、兑换码
   schema/语义、路径、图片可由 PIL 解码、文件头和素材来源说明，等待 `resource-contract` Check
   后合并 `main`。
2. 记录资源 `main` 的 commit SHA 与 `resource_version`，再运行插件跨仓契约回归和目标资源
   generation 测试。
3. 编辑器部署/配置按其 [operations runbook](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/operations.md)
   执行；GitHub App、Turnstile、Webhook 和 required ruleset 未真实验收前，不宣称公众投稿可用。
4. 最后发布插件；默认 `resources.github_acceleration=off`，完成一次资源下载、热刷新和兑换码
   读取冒烟，再向用户开放镜像选项。

禁止插件直接消费资源投稿分支、镜像-only ref 或未进入 `main` 的 commit。资源仓库不放编辑器
源码、依赖、构建产物、凭据或数据库；第三方素材也没有统一许可，发布前必须核对各自上游条款。

## 资源升级与迁移

升级插件前备份整个 `data/plugin_data/astrbot_plugin_dnaby/`，至少确认
`dnaby.sqlite3`、`subscriptions.json`、`ann_state.json`、`ann_delivery_state.json` 和 `panel_custom/`
可恢复。资源更新
本身只在 `resources/` 使用 Git 增量缓存，并在 `resource_generations/<commit-sha>/` 生成已验证
快照；快照保存完整文件树 SHA-256，`resource_generations/current.json` 同时保存 commit 和摘要。
启动预热不阻塞插件初始化，管理员下载会等待同一同步任务；终止时会排空该任务。没有摘要的旧
指针会在校验后补写；启动或下载过程不会删除/迁移面板图、数据库、订阅或公告状态。

### 共享下载器旧缓存的一次性清理

从旧共享下载器迁移到 `ImageFetcher` 时，部署者可在停写、完成备份并核对目录归属后，人工清理
以下两个旧图片缓存范围。typed 公告 renderer 的当前缓存位于
`data/plugin_data/astrbot_plugin_dnaby/cache/announcement/`，由 `CacheManager` 按公告绝对保留期
和租约管理，不属于下面这次 legacy 清理范围：

- `data/plugin_data/astrbot_plugin_dnaby/resource/`
- `data/plugin_data/astrbot_plugin_dnaby/other/ann_card/`

清理只针对上述公告/资源图片缓存；不得递归删除整个插件数据目录，也不得删除
`dnaby.sqlite3`、`subscriptions.json`、`ann_state.json`、`scheduler_state.json`、账号凭据、
`panel_custom/`、`resources/` 或 `resource_generations/`。清理后由下一次受控图片请求重新下载，
空响应、非图片或解码失败会显式失败而不会留下透明假文件。该步骤不在插件启动时自动执行，
避免把缓存迁移误当成账号或订阅数据清理。

旧 GitCode 兑换码的 `end_at` 只能在资源仓库迁移阶段转换成带时区的 `expires_at`；未知奖励、
平台、区服和起始时间保持缺失。资源仓库成为唯一事实源后，插件不回退旧 GitCode。

## 三类回滚

### 资源数据

对错误资源在资源仓库创建 `git revert` PR，等待 Check 通过后合并；不 force-push、不删除坏
commit、不把镜像内容直接提升为发布源。插件候选校验失败时继续提供上一份已验证 generation，
成功回滚后再执行 admin `下载全部资源`。

### 编辑器 Worker

记录 Worker version 与资源 SHA，按编辑器 runbook 执行 `npx wrangler deployments status`
和 `npx wrangler rollback <VERSION_ID>`。Worker 代码回滚不会自动恢复 Cloudflare secrets；
若事故伴随密钥轮换，须经授权重新写入兼容旧值并重新验证 `/api/health`、登录和 webhook。

### 插件发布/镜像

安装上一份已验收的插件 revision，保留整个 runtime data 目录；镜像故障将
`resources.github_acceleration` 切回 `off`，确认规范 origin 后重试。不要删除
`panel_custom/`、`dnaby.sqlite3`、订阅或公告文件；generation 可由可信 `main` 重建。

## 备份与安全

备份存放在插件数据目录之外并限制权限；不把 Cookie、token、SQLite、日志或 Dashboard 密钥
提交到任一仓库。错误消息保留稳定错误类别，诊断时记录资源 commit、manifest/resource version
和配置模式，不记录上传内容或凭据。完整公共资源/编辑器运维步骤见
[公共资源说明](../usage/resources.md)和[编辑器运维文档](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/operations.md)。
