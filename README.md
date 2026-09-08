<div align="center">

<img src="./ICON.png" alt="狩月终端 Logo" width="180" />

# 狩月终端


**面向 AstrBot 的《二重螺旋》游戏助手插件**

<img src="https://count.getloli.com/@astrbot_plugin_dna?name=astrbot_plugin_dna&theme=rule34&padding=7&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" alt="Moe Counter" />

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)
[![AstrBot](https://img.shields.io/badge/AstrBot-%E2%89%A54.26.0-green.svg)](https://github.com/AstrBotDevs/AstrBot)
[![Resource](https://img.shields.io/badge/Resource-dna--resource-orange.svg)](https://github.com/FlanChanXwO/dna-resource)

角色面板 · 图鉴攻略 · 签到服务 · 密函公告

</div>

---

## ✨ 项目简介

**狩月终端**（`astrbot_plugin_dna`）是面向 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的《二重螺旋》游戏助手插件。

插件围绕账号、角色与公共游戏资料提供一套原生 AstrBot 使用体验：既可以在聊天中查询角色、图鉴、攻略、签到与公告，也提供面向管理员的资源同步、订阅与管理能力。

> [!IMPORTANT]
> 当前插件要求 **AstrBot 4.26.0 或更高版本**。图片卡片依赖 AstrBot 提供的全局 HTML/T2I 能力；未启用时，纯文字能力仍可正常使用，但部分图片命令无法渲染卡片。

## 🚀 核心能力

- 👤 **账号管理**：登录、退出登录、UID 绑定、切换与删除，并提供严格脱敏的登录状态查询。
- 🧬 **角色与玩家信息**：基本信息卡片、角色详情、角色面板刷新、卡片缓存管理、日常便笺、周报与日历。
- 📚 **图鉴与攻略**：角色 / 武器列表、角色图鉴、别名查询、角色攻略与当前可用兑换码。
- ✅ **签到服务**：手动签到、签到日历、按 UID 控制的自动签到，以及可独立订阅的签到汇总与群聊报告。
- 📢 **密函与公告**：密函、公告查询与会话级订阅推送，管理员可管理群聊公告订阅。
- 🔐 **隐私控制**：限制其他成员查询个人信息，并可单独控制卡片中的 UID 展示。
- 🛠️ **管理员工具**：批量签到、角色 / 武器别名维护、公共资源状态检查与资源同步。
- 🤖 **可选 Agent Tools**：按配置注册结构化查询工具，默认关闭，不改变聊天命令行为。

## 📦 安装

### 手动安装

在 AstrBot 根目录执行：

```bash
git clone https://github.com/FlanChanXwO/astrbot_plugin_dna.git data/plugins/astrbot_plugin_dna
python3 -m pip install -r data/plugins/astrbot_plugin_dna/requirements.txt
```

随后重启 AstrBot 或在 Dashboard 中重载插件。

> [!NOTE]
> 如果 AstrBot 已自动同步插件依赖，可跳过手动安装 `requirements.txt`。公开发布并进入 AstrBot 插件市场后，以市场页面显示的安装入口为准。

## ⚡ 快速开始

默认命令前缀为 `dna`。如果修改了 `general.command_prefixes`，请同步替换下列示例中的前缀。

| 场景 | 示例 | 说明 |
| --- | --- | --- |
| 帮助 | `dna帮助` | 查看当前可用命令 |
| 登录 | `dna登录` | 发起账号登录流程 |
| UID 管理 | `dna查看UID` | 查看当前账号绑定情况 |
| 信息卡片 | `dna卡片` | 查询当前 UID 的基本信息卡片 |
| 角色面板 | `dna菲娜面板` | 查询指定角色详情 |
| 日常信息 | `dna日常` / `dna周报` / `dna日历` | 查看便笺、周报与日历 |
| 图鉴攻略 | `dna菲娜图鉴` / `dna菲娜攻略` | 查看角色图鉴或攻略 |
| 签到 | `dna签到` | 执行当前 UID 签到 |
| 资源状态 | `dna资源状态` | 检查公共资源版本与状态 |
| 同步资源 | `dna同步资源` | 管理员同步公共资源 |

完整命令、参数和权限请查看 [`commands.json`](commands.json)；使用边界见 [命令说明](docs/usage/commands.md)。

## ⚙️ 配置

推荐通过 **AstrBot Dashboard → 插件配置** 完成设置。配置主要覆盖：

- 通用命令前缀与查询行为；
- 登录方式与账号绑定上限；
- Agent Tools 开关；
- 自动签到与签到报告；
- 公告、密函与客户端更新通知；
- 图鉴 / 攻略显示策略；
- API 网络、代理与并发限制；
- 公共资源同步与 GitHub 加速；
- 卡片与数据缓存策略。

完整字段、类型、默认值和使用说明见：

- [`_conf_schema.json`](_conf_schema.json)
- [配置说明](docs/usage/configuration.md)

修改配置后建议重载插件。

## 🧰 公共资源

角色、武器、图鉴、攻略、日历、字体和兑换码等公共资料由独立仓库维护：

**[`FlanChanXwO/dna-resource`](https://github.com/FlanChanXwO/dna-resource)**

插件不会在启动时强制同步资源。已有资源会先完成完整校验后再暴露给业务读取，新的资源同步也会在候选内容通过 manifest、目录、摘要和图片等校验后才切换为当前可用版本。

管理员可通过以下命令处理资源：

- `dna资源状态`：查看当前 generation、资源版本与最近同步结果；
- `dna同步资源`：从 `dna-resource` 的 `main` 分支同步并发布经过校验的新资源快照。

详细资源结构、同步规则与排障方式见 [公共资源说明](docs/usage/resources.md)。

## 📖 文档导航

`docs/` 只维护当前版本需要的 `usage/` 与 `dev/` 两类文档：

| 文档 | 内容 |
| --- | --- |
| [命令说明](docs/usage/commands.md) | 命令入口、权限/登录边界与事实源 |
| [配置说明](docs/usage/configuration.md) | Dashboard 配置分组与维护方式 |
| [账号登录](docs/usage/login.md) | 登录方式、UID 与排障 |
| [公共资源](docs/usage/resources.md) | 资源同步、校验与排障 |
| [Agent Tools](docs/usage/agent-tools.md) | Agent 工具启用与安全边界 |
| [管理页面](docs/usage/admin-pages.md) | Dashboard 管理能力 |
| [项目架构](docs/dev/architecture.md) | 当前模块边界与事实源 |
| [开发环境](docs/dev/setup.md) | 本地开发与运行环境 |
| [测试说明](docs/dev/testing.md) | 测试范围与验证方式 |
| [维护约定](docs/dev/maintenance.md) | 生成物、文案与文档维护规则 |

## 🔐 安全与隐私

账号凭据与运行期数据不会作为仓库内容提交。反馈问题时请避免上传 Cookie、token、数据库、完整插件数据目录、Dashboard 密钥或其他个人信息。

涉及登录、账号和隐私问题时，建议只提供：

- AstrBot 与插件版本；
- 可复现的最小操作步骤；
- 已脱敏的日志或错误类别；
- 预期结果与实际结果。

## 🧪 开发与测试

在插件目录中可以执行：

```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

贡献涉及命令、配置、数据结构或资源契约时，请同步更新对应文档与测试。

## 🐛 问题反馈与贡献

欢迎通过 [GitHub Issues](https://github.com/FlanChanXwO/astrbot_plugin_dna/issues) 提交 Bug 或功能建议，也欢迎提交 Pull Request 改进代码、测试与文档。

提交前请确认：

- 已使用对应 Issue / PR 模板补充必要信息；
- 日志与截图已经脱敏；
- 没有提交运行期账号数据或凭据；
- 与代码行为相关的文档和测试已经同步更新。

## ⚠️ 免责声明

- 本项目是非官方第三方开源项目，与《二重螺旋》及其开发、发行或运营方不存在隶属、授权、合作或官方认可关系。
- 项目中涉及的游戏名称、商标、角色、图片及其他相关素材，其权利归原权利人所有；本项目仅在实现插件功能所需范围内引用或链接相关内容。
- 使用本插件时，请遵守《二重螺旋》及相关平台、接口与服务的用户协议和适用规则。因使用本插件产生的账号、网络、平台或数据风险由使用者自行承担。
- 本项目代码依照 [GNU General Public License v3.0](LICENSE) 发布；本免责声明不限制或改变该许可证已经授予的权利。

## 📄 License

本项目代码使用 [GNU General Public License v3.0](LICENSE) 许可证。

## 🙏 参考与致谢

- 原插件 / 参考实现：[tyql688/DNAUID](https://github.com/tyql688/DNAUID)
