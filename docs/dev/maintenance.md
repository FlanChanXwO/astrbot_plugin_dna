# 维护约定

## 同步规则

代码是事实源，文档只保留用户或维护者无法从单个文件直接读出的稳定说明。

- 命令变化：修改 registry 后运行 `python3 scripts/generate_commands_manifest.py`，同步 `tests/test_entry_commands.py` 和 `docs/usage/commands.md` 中受影响的使用说明。
- 配置变化：修改 `src/infrastructure/config/` 后运行 `python3 scripts/generate_config_schema.py`，同步 `tests/test_config.py` 和 `docs/usage/configuration.md`。
- 客户端更新 Target / Source 变化：先更新只读证据与 registry，再运行 `python3 scripts/smoke_client_update_sources.py`；随后重新生成命令和配置投影。
- 登录、Dashboard、Agent Tools、公共资源等行为变化：只更新对应的 `docs/usage/` 主题，不在多个文档重复完整清单。
- 数据库 schema 变化：使用 Alembic revision，更新持久化测试；只有用户/部署者需要采取动作时才补充文档。
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

客户端更新使用两层身份：Target 表达用户侧“区服 × 账号生态 × 平台”，Source
表达版本读取协议。新增 Target 前必须同时确认现实发行、账号/服务器语义和稳定
只读 Source；下载页面或商店入口本身不足以证明应新增 Target。调查证据集中在
[`client-update-source-investigation.md`](client-update-source-investigation.md)，
registry 位于 `src/modules/client_updates/registry.py`。

长期只读检查入口：

```bash
python3 scripts/smoke_client_update_sources.py
```

工具按 registry 检查全部 Source，只读取 manifest Source 的 `VersionList.json`
或 App Store Lookup。它固定不传 baseline，因此不会读取版本补丁 manifest、下载
完整补丁、建立 baseline、修改订阅或写入插件运行数据。任一 Source 失败时退出码
非零；输出只包含 Source ID、provider、版本或 typed 失败分类。HTTP fallback 日志
使用 `endpoint_role=primary/fallback`，不得加入 URL、响应正文或凭据。

### HTTP 完整性边界

当前 CN PC manifest 的已验证 primary/fallback 都是 HTTP。代码能校验状态码和
JSON/manifest 结构，但 HTTP 本身不提供 TLS 的来源认证或链路完整性；结构校验
不能替代传输层真实性保证。不要因为主机名看似支持 HTTPS 就把 registry URL
机械替换为 `https://`，也不要在失败时静默猜测其它域名、branch 或 key。只有在
官方客户端或一手公开资料提供证据，并完成隔离只读 smoke、primary/fallback
一致性及契约测试后，才能提交端点变更。

### state v4 与回滚

`client_update_state.json` v4 以 Source 保存 baseline 和待投递事件。v1/v2/v3
只会 warning 后按空状态启动，不迁移、不自动备份。回滚到旧插件版本前必须停止
插件并移走 v4 state，或恢复部署者在升级前保存的旧 state；不要添加基于旧
channel/platform 字段的猜测迁移层。

## 文档结构

`docs/` 顶层长期只保留：

- `dev/`：架构、开发、测试、维护；
- `usage/`：用户与管理员使用说明。

新增文档前先判断是否能并入现有主题。历史设计、迁移过程、review 记录和一次性调查结论不进入长期 `docs/`。
