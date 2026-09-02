# astrbot_plugin_dnaby

二重螺旋（DNA）Bot 插件 —— AstrBot 原生移植版。由 GsCore 插件 [DNAUID](https://github.com/tyql688/DNAUID)（私有镜像 `FlanChanXwO/DNAUID`）全面移植而来。

> 当前 `v0.2.0` 已完成 `goal-1` 三阶段的命令、缓存、公告/密函、管理页和 Agent Tools 代码交付；
> 具体行为以 `commands.json`、`_conf_schema.json` 和下方当前文档为准。生产状态、精确 SHA 与回滚证据见
> [发布与回滚清单](docs/porting/agent-tools-release-checklist.md)。

## 功能

- **皎皎角登录**：App 短信登录页、token 登录、短信验证码命令登录、QR 二维码和退出登录
- **账号管理**：登录后自动建立绑定，可切换/删除/查看 UID，并查询脱敏的 App 凭据状态
- **签到服务**：游戏签到、皎皎角社区任务、签到日历、自动签到、签到结果订阅
- **信息查询**：角色信息卡片、角色基础面板、角色/全部角色刷新与缓存清理、攻略、日常（体力便笺）、日历、周报
- **密函**：当前密函、密函列表、指定密函订阅与推送周期、图片/文本订阅
- **公告**：官方公告查看与群推送订阅
- **图鉴 / 攻略 / 兑换码**：角色/武器/灵核图鉴、攻略组图片、兑换码
- **管理**：公告和隐私管理、全部签到、角色/武器别名维护、资源下载

## 安装

当前 v0.2.0 仅面向私有源码 checkout：将本插件目录放入 AstrBot 的 `data/plugins/` 后，先按
[维护说明](docs/dev/maintenance.md)完成数据库/资源前置检查，再在 Dashboard 启用。生产更新必须固定到
已验收的插件 SHA，并通过已认证的 AstrBot 定向插件 reload；不要用重启容器替代 reload。暂不发布
Marketplace 或公开 Release。

## 使用

已迁移命令使用独立的自然语言正则 handler；当前包括普通用户可用的帮助、登录/退出、UID
切换/删除/查看、脱敏凭据状态、角色卡片/详情、角色刷新和缓存清理、日常便笺、周报、日历、
图鉴、攻略、兑换码、别名查看、游戏/社区签到、自动签到开关、签到日历、密函及公告读取和
订阅。AstrBot `ADMIN` 权限命令提供公告/隐私管理、全部签到、签到结果订阅、角色/武器别名
维护与资源下载；每日自动签到由 `sign_in.sign_time` 计划任务执行，密函默认在每小时整点推送，
公告按 `announcement_check_minutes` 轮询。
玩家和资料素材已从公共运行期
资源根加载；三仓契约与本地跨仓回归已覆盖。O24 已对 `atri` 做插件/资源/容器/日志的只读核验；真实 CDN/T2I
仍可能因外部服务不可用而失败，不能把本地 fixture 或状态核验当作真实图片成功。公开命令不提供
角色原图、绑定 UID 或自定义面板图管理；正常角色详情不调用伤害计算 API。签到写操作
与推送只在离线 fixture 验证，未对真实账户执行。命令清单见 `commands.json` 与
[docs/usage/commands.md](docs/usage/commands.md)。

## 配置

插件配置在 Dashboard 的插件配置页（`_conf_schema.json`），由 `src/infrastructure/config` 的 Pydantic 定义生成，按登录、网络、签到、通知、缓存、显示和资源分组。资源仓库默认直连，也可使用 GitHub 加速前缀；首次同步只克隆 `main`，后续只允许 `main` 的 fast-forward 更新；资源契约、迁移、镜像信任和回滚详见 [docs/usage/resources.md](docs/usage/resources.md) 与 [docs/dev/maintenance.md](docs/dev/maintenance.md)。资源编辑使用独立的 [dna-resource-editor](https://github.com/FlanChanXwO/dna-resource-editor)，不把编辑器代码放入资源仓库。

生成型图片卡片统一使用 AstrBot 4.27.1 及以上版本的全局 HTML/T2I 服务；插件不会覆盖全局
T2I 地址。模板和素材由 `src/infrastructure/rendering/` 统一处理，渲染失败时记录内部原因并向用户
返回通用提示。

## 开发

- [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) —— 开发约定
- [docs/](docs/README.md) —— 文档索引（含移植设计 `docs/porting/` 与原 GsCore 登录排查档案 `docs/legacy/`）

## License

[GPL-3.0](LICENSE)（源自 DNAUID 的 GPL-3.0 许可证）。公共资源仓库不对第三方素材授予统一许可，
请按 [资源仓库说明](https://github.com/FlanChanXwO/astrbot_plugin_dna_resources#resource-contract)
核对来源与上游条款。
