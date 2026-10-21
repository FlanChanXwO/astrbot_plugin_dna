# 维护约定

## 同步规则

代码是事实源，文档只保留用户或维护者无法从单个文件直接读出的稳定说明。

- 命令变化：修改 registry 后运行 `python3 scripts/generate_commands_manifest.py`，同步 `tests/test_entry_commands.py` 和 `docs/usage/commands.md` 中受影响的使用说明。
- 配置变化：修改 `src/infrastructure/config/` 后运行 `python3 scripts/generate_config_schema.py`，同步 `tests/test_config.py` 和 `docs/usage/configuration.md`。
- 客户端更新 Target / Source 变化：先核对 `src/modules/client_updates/registry.py` 中的稳定协议参数，再运行 `python3 scripts/smoke_client_update_sources.py`；随后重新生成命令和配置投影。
- 登录、Dashboard、Agent Tools、公共资源等行为变化：只更新对应的 `docs/usage/` 主题，不在多个文档重复完整清单。
- 数据库 schema 变化：使用 Alembic revision，更新持久化测试；只有用户/部署者需要采取动作时才补充文档。
- 数据库初始化：Alembic 是生产 schema 的唯一事实来源，启动期 `DatabaseMigration` 自动执行 `upgrade head`；不要在生产路径引入 `Base.metadata.create_all()`，也不要为缺失的 alembic 资产添加回退 schema 路径。迁移失败会让插件启动失败，这是预期行为。
- 发布历史：写入根目录 `CHANGELOG.md`，不要在 `docs/` 保存阶段报告、迁移日志或某次生产环境快照。

## 用户文案

当前运行期中文文案位于 `i18/zh/tip.json`，加载与校验逻辑位于 `src/infrastructure/i18n/`。新增或修改用户可见提示时：

1. 优先修改文案目录中的模板；
2. 动态排序、条件判断和业务数据格式化保留在 Python；
3. 确认模板 key、参数与对应测试一致；
4. 不在 handler 中复制同一段长期用户文案。

不要为仓库中不存在的国际化目录维护说明；若目录结构未来变化，以实际代码和文件布局为准再更新本页。

## 运行期数据与敏感信息

运行期数据库、订阅状态、缓存、资源快照和渲染结果都应位于 AstrBot 分配的插件数据目录。仓库、Issue、PR 和测试 fixture 中不得加入真实 Cookie、token、验证码、Dashboard 密钥、SQLite 数据库或包含这些内容的日志。

涉及破坏性数据库迁移或生产升级时，备份与回滚步骤应由实际部署环境的 runbook 管理，不把机器路径、容器名、某次 SHA 或临时状态固化进通用仓库文档。

## 公共资源

资源行为以 `src/infrastructure/resources/` 和公共 `dna-resource` 当前 manifest 为准。插件侧文档只描述同步、校验和失败回退的用户可见语义，不复制资源仓库的完整目录/哈希清单。

## 客户端更新 Source

客户端更新使用两层身份：Target 表达玩家订阅的发行渠道（区服 × 发行渠道
× 平台），Source 表达一个可独立观察的 release stream。Source 的唯一共享
准则是发布事件使用同一 revision 序列且发布时间一致；游戏内容、安装包内容、
版本号或“同属官服”都不能作为共享 Source 的依据。新增 Target 前必须先确认
稳定只读 Source；下载页面或商店入口本身不足以证明应新增 Target。Source 的
固定协议参数集中在 `src/modules/client_updates/registry.py`，不要把某次
版本号、条数或响应大小等瞬时观察结果写入长期文档。

Manifest Source 的 `PakFilesInfo.json` 和 `ResDiscreteInfo.json` key 是 registry
配置的一部分，两个 key 不一定相同；`fallback_base_url` 只在存在已验证镜像时
填写。App Store Source 只读取 Apple Lookup 的当前版本。B 站与好游快爆 Source
没有逐版本历史，以渠道 APK MD5 或安装器文件名作为 revision，不提供更新大小，
部分渠道没有公开版本号。账号登录生态如果其他模块需要，应在那里独立建模，
不并入客户端更新 Target。

长期只读检查入口：

```bash
python3 scripts/smoke_client_update_sources.py
```

工具按 registry 检查全部 Source，读取 manifest Source 的 `VersionList.json`、
App Store Lookup、B 站 gameinfo 或好游快爆详情页。它固定不传 baseline，因此
不会读取版本补丁 manifest、下载完整补丁、建立 baseline、修改订阅或写入插件
运行数据。任一 Source 失败时退出码非零；输出包含 Source ID、provider、绑定的
Target、当前 revision 与展示版本（渠道没有公开版本号时显示 `none`）或 typed
失败分类。HTTP fallback 日志使用 `endpoint_role=primary/fallback`，不得加入
URL、响应正文或凭据。

### HTTP 完整性边界

当前 CN PC manifest 的已验证 primary/fallback 都是 HTTP。代码能校验状态码和
JSON/manifest 结构，但 HTTP 本身不提供 TLS 的来源认证或链路完整性；结构校验
不能替代传输层真实性保证。不要因为主机名看似支持 HTTPS 就把 registry URL
机械替换为 `https://`，也不要在失败时静默猜测其它域名、branch 或 key。只有在
官方客户端或一手公开资料提供证据，并完成隔离只读 smoke、primary/fallback
一致性及契约测试后，才能提交端点变更。

### 下载计划与补丁统计

`added_size_bytes` 始终表示新增补丁清单统计；历史窗口不完整时仍为空。独立的
`download_plan` 保存必需传输字节、选配标签、计算依据及基础包路径，不受
`history_complete` 单独决定。文件按官方版本目录和文件名去重，同一路径的内容
标识冲突必须失败，不能静默选择较小值。

官服 PC 通过 `Packages/.../VersionManifest.json` 和原生启动器路径规则选择
`HPatchDiffMd5.json`，只采用 `hdiff_file.size`；`new_size` 是解压后的占用。
换基础包时仅使用新发行系列的热更，不能把旧系列已被替换的文件重复计入。
同系列基础包切换缺少已核验的热更边界时拒绝计算。协议依据见
`DNA-security-analysis` 的 `game-client/api/update/game-update.md`。

安卓跨基包计划复用 manifest transport 与文件归并，另读取 `PakJumpUrl.json` 的
官网 APK 地址。只通过 HTTP Range 读取 ZIP 中央目录及 `AndroidManifest.xml`，
核对包名、版本、`versionCode` 与完整包的传输长度，不下载 APK 正文或安装程序。
服务端不支持 Range 时直接失败；httpx 兼容路径也使用流式响应，不能先缓冲整包。
`PakJumpUrl` 的 JSON 当前使用 `application/octet-stream`，仅该调用跳过 MIME
限制，仍执行 JSON 和渠道身份校验。

基包内置边界必须先从官方包核验，再由运行期校验 APK 身份、完整起始补丁、文件
目录/内容标识、选配标签及 `ExamineFile.json` 的跨路径复用信息。当前实现只接受
已核验的基包转换；不能仅删除历史窗口检查、推测版本公式或对未知复用映射求和。
`provider_metadata.package_version` 保存 PC 基础包 ID；安卓 APK 的
`versionCode` 保存在 `apk_and_patch` 计划的 `package_to`，不混用两种版本身份。

区域和语音分别保留标签，报告明确官网整包直更及资源档位，不套用应用商店差分。
未知基包、补丁边界缺失或选项集合变化时，查询与定时轮询使用相同错误边界，保留
baseline 和已有待投递事件，交给后续检查重试；新增基包需先扩展已核验边界。

### state v5 与回滚

`client_update.json` v5 以 Source 保存 baseline、下载计划和待投递事件。
读取 v4 时保留基线、目标和投递标记，旧记录的下载计划为空，不重新解释旧统计，
不自动重发历史事件。v1/v2/v3 仍只会 warning 后按空状态启动，不迁移、不自动
备份。回滚到只支持 v4 的插件前必须停止插件并恢复升级前备份的状态；旧插件不
识别 v5，不要直接降级后启动调度。

## 文档结构

`docs/` 顶层长期只保留：

- `dev/`：架构、开发、测试、维护；
- `usage/`：用户与管理员使用说明。

新增文档前先判断是否能并入现有主题。历史设计、迁移过程、review 记录和一次性调查结论不进入长期 `docs/`。
