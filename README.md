# astrbot_plugin_dnaby

二重螺旋（DNA）Bot 插件 —— AstrBot 原生移植版。由 GsCore 插件 [DNAUID](https://github.com/tyql688/DNAUID)（私有镜像 `FlanChanXwO/DNAUID`）全面移植而来。

> 重构说明：`rewrite/v0.1` 当前只提供新的入口骨架和空能力 runtime。下方功能清单描述 legacy-reference/目标能力，不代表该重构阶段已经在新入口注册；完整迁移按 `goal-1/tasks.md` 分阶段完成。

## 功能

- **皎皎角登录**：Web/App 短信登录页、token 登录、短信验证码命令登录、QR 二维码、退出登录、获取 token
- **账号绑定**：绑定/切换/删除/查看 UID，隐私控制（开偷窥/防偷窥/隐藏UID + 群管理）
- **签到服务**：游戏签到、皎皎角社区任务、签到日历、自动签到、签到结果订阅
- **信息查询**：角色信息卡片、角色面板 + 伤害计算、攻略、日常（体力便笺）、日历、周报
- **密函**：当前密函、密函列表、指定密函订阅与推送周期、图片/文本订阅
- **公告**：官方公告查看与群推送订阅
- **图鉴 / 攻略 / 兑换码**：角色/武器/灵核图鉴、攻略组图片、兑换码
- **管理**：别名管理、自定义面板图上传/管理、更新记录、全部签到、下载资源

## 安装

将本插件目录放入 AstrBot 的 `data/plugins/` 后，在 Dashboard 启用并重启；或在 AstrBot 插件市场中搜索安装。

## 使用

所有命令为自然语言正则触发，命令清单见 `commands.json` 与 [docs/usage/commands.md](docs/usage/commands.md)。发送 `帮助` 可查看命令卡片。

## 配置

插件配置在 Dashboard 的插件配置页（`_conf_schema.json`），含登录方式、密函推送时间、签到时间、公告轮询间隔等。

## 开发

- [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) —— 开发约定
- [docs/](docs/README.md) —— 文档索引（含移植设计 `docs/porting/` 与原 GsCore 登录排查档案 `docs/legacy/`）

## License

[GPL-3.0](LICENSE)（源自 DNAUID 的 GPL-3.0 许可证）。仅供学习使用。
