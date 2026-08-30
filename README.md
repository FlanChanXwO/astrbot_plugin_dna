# astrbot_plugin_dnaby

二重螺旋（DNA）Bot 插件 —— AstrBot 原生移植版。由 GsCore 插件 [DNAUID](https://github.com/tyql688/DNAUID)（私有镜像 `FlanChanXwO/DNAUID`）全面移植而来。

> 重构说明：`rewrite/v0.1` 已提供新的薄入口、显式 `CommandSpec` registry、帮助、账号、隐私、
> 玩家查询和资料读取 use case；下方未列入当前命令清单的能力仍是 legacy-reference/目标能力。完整迁移按
> `goal-1/tasks.md` 分阶段完成。

## 功能

- **皎皎角登录**：Web/App 短信登录页、token 登录、短信验证码命令登录、QR 二维码、退出登录、获取 token
- **账号绑定**：绑定/切换/删除/查看 UID，隐私控制（开偷窥/防偷窥/隐藏UID + 群管理）
- **签到服务**：游戏签到、皎皎角社区任务、签到日历、自动签到、签到结果订阅
- **信息查询**：角色信息卡片、角色面板 + 伤害计算、攻略、日常（体力便笺）、日历、周报
- **密函**：当前密函、密函列表、指定密函订阅与推送周期、图片/文本订阅
- **公告**：官方公告查看与群推送订阅
- **图鉴 / 攻略 / 兑换码**：角色/武器/灵核图鉴、攻略组图片、兑换码
- **管理**：只读别名查询、自定义面板图上传/管理、全部签到、下载资源

## 安装

当前 v0.1 仅面向私有源码 checkout：将本插件目录放入 AstrBot 的 `data/plugins/` 后，在 Dashboard 启用并重启。暂不发布 Marketplace 或公开 Release。

## 使用

已迁移命令使用独立的自然语言正则 handler；当前包括 `帮助`、登录/退出、UID 绑定/
切换/删除/查看、脱敏凭据状态查询、个人隐私开关和群管理员隐私控制，以及角色卡片/详情、
日常便笺、周报、日历、图鉴、攻略、兑换码和只读别名查询，游戏/社区签到、签到日历、
管理员全部签到与签到结果订阅（每日 `sign_in.sign_time` 计划任务推送），密函、公告读取
及其订阅推送（密函自动推送固定为每小时 `HH:30`，订阅级时间窗口仍可设置；
`announcement_check_minutes` 轮询公告），以及管理员面板图管理（上传/列表/删除/压缩）、
资源状态与资源下载。
玩家和资料素材已从公共运行期
资源根加载；三仓契约与本地跨仓回归已覆盖，但真实公共资源内容和生产视觉输出仍需单独验收。`原图` 因 AstrBot 4.27.x 公开
结果边界没有已发送消息 ID 交付点，显式标记为暂不支持，不作可用平台功能宣称。签到写操作
与推送只在离线 fixture 验证，未对真实账户执行。命令清单见 `commands.json` 与
[docs/usage/commands.md](docs/usage/commands.md)。

## 配置

插件配置在 Dashboard 的插件配置页（`_conf_schema.json`），由 `src/infrastructure/config` 的 Pydantic 定义生成，按登录、网络、签到、通知、显示和资源分组。资源仓库默认直连，也可使用 GitHub 加速前缀；首次同步只克隆 `main`，后续只允许 `main` 的 fast-forward 更新；资源契约、迁移、镜像信任和回滚详见 [docs/usage/resources.md](docs/usage/resources.md) 与 [docs/dev/maintenance.md](docs/dev/maintenance.md)。资源编辑使用独立的 [dna-resource-editor](https://github.com/FlanChanXwO/dna-resource-editor)，不把编辑器代码放入资源仓库。

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
