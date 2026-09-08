# 命令使用

插件默认命令前缀为 `dna`；实例实际使用的前缀由 Dashboard 配置 `general.command_prefixes` 决定。

完整、可机器验证的命令正则、示例与权限以根目录 [`commands.json`](../../commands.json) 为准。该文件由代码 registry 生成，因此本页不再复制全部命令清单或命令数量。聊天中发送当前前缀加 `帮助` 可以查看实例当前帮助信息。

## 常用入口

以下示例使用默认前缀：

| 场景 | 示例 |
| --- | --- |
| 帮助 | `dna帮助` |
| 登录 | `dna登录` |
| 查看绑定 | `dna查看UID` |
| 玩家卡片 | `dna卡片` |
| 角色详情 | `dna菲娜面板` |
| 日常/周报/日历 | `dna日常` / `dna周报` / `dna日历` |
| 图鉴/攻略 | `dna菲娜图鉴` / `dna菲娜攻略` |
| 签到 | `dna签到` |
| 公共资源 | `dna资源状态` / `dna同步资源` |

具体角色名、别名、可选参数和管理员命令请直接查 `commands.json` 或帮助卡片。

## 功能分类

当前命令覆盖账号与 UID、玩家/角色信息、图鉴与攻略、签到、密函与公告、客户端更新、隐私、别名以及公共资源等领域。某个命令是否存在、如何匹配、需要什么权限，以当前 registry 投影为准。

## 权限与登录是两件事

`user` / `admin` 表示 AstrBot 命令权限；DNAUID 账号是否已经绑定/登录是另一个业务条件。公开资料类命令可能不需要游戏账号，而玩家数据、签到等命令会要求有效绑定。管理员命令也不会因为调用者已经登录就自动获得 AstrBot 管理权限。

涉及他人玩家数据时还会经过隐私与目标解析规则。不要根据命令名称自行绕过这些检查。

## Agent Tools

Agent Tools 是 AstrBot Agent 的结构化工具，不是聊天命令，不使用命令前缀，也不进入 `commands.json`。启用和安全边界见 [Agent Tools](agent-tools.md)。

## 相关说明

- 登录与 UID：[账号登录](login.md)
- Dashboard 配置：[配置](configuration.md)
- 公共资源：[公共资源](resources.md)
- Dashboard 管理页：[管理页](admin-pages.md)
