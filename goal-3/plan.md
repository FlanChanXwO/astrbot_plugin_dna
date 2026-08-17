# Goal 3 计划：AstrBot T2I 渲染高保真复刻 GScore PIL 视觉与真实数据对比

## 目标与范围

本任务的目标是在重构工作树 `.worktrees/rewrite-v0.1` 中，建立并完善 Jinja2 HTML + AstrBot T2I 渲染管线，替代原有的纯 PIL 绘制逻辑，使 AstrBot 输出的 14 类业务卡片在布局、字体、色彩、间距和素材结构上高度复刻 GScore PIL 的经典视觉样式；并通过 `ssh atri` 远端 GScore 容器的 `dnauid` 数据库提取真实账号数据，生成完整真实渲染数据，在 `output/real/` 下与 GScore PIL 原版图片进行逐图高精度像素与布局比对和验收。

### 覆盖的 14 类业务卡片

1. 帮助卡 (`help`)
2. 更新记录卡 (`update_log`)
3. 公告列表卡 (`ann_list`)
4. 公告详情卡 (`ann_detail`)
5. 活动日历卡 (`calendar`)
6. 签到日历卡 (`sign_calendar`)
7. 签到报告卡 (`sign_report`)
8. 委托密函简图 (`mh_simple`)
9. 委托密函卡片 (`mh_card`)
10. 实时体力便签 (`stamina`)
11. 角色总览卡 (`role_overview`)
12. 角色详情卡 (`role_detail`)
13. 本周周报卡 (`weekly_current`)
14. 上周周报卡 (`weekly_last`)

## 现状与上下文

1. **分支结构**：
   - `legacy-reference` 分支（Goal 2）已在 `dnaby/rendering/` 与 `dnaby/templates/` 中实现了基于 Jinja2 + HTML 的原型模板，并生成了初步的对照报告。
   - `rewrite/v0.1` 工作树采用 DDD 架构（`src/modules/`, `src/infrastructure/rendering/`），当前渲染器（`PlayerRenderer`, `CheckinRenderer`, `EncyclopediaRenderer`, `NoticesRenderer`）仍主要通过 legacy PIL 或简易 Pillow 绘制调用。
2. **渲染服务环境**：
   - 本地 `http://localhost:8999` 提供 AstrBot T2I (FastAPI + Playwright HTML to Image) 服务，支持标准 `render_custom_template` 契约或 POST 渲染。
   - 远端服务器 `ssh atri` 运行 `gsuid_core` 容器，内含 `DNAUID` 插件和 `/gsuid_core/data/GsData.db`（`dnauser` 真实绑定数据）。
3. **真实对比目标**：
   - 目标路径 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/data/plugins/astrbot_plugin_dnaby/output/real` 保存 GScore 原版基准图片与 AstrBot T2I 渲染图，需产出高清晰度接触表（contact sheets）与差异评估。

## 风险与挑战

1. **字体与排版差异**：PIL 文本渲染与 Chromium 浏览器排版引擎在行高、字间距、抗锯齿（subpixel rendering）、基线对其上存在固有差异，需精细校准 CSS（如 `letter-spacing`, `line-height`, `font-feature-settings`）。
2. **离线与内联资源要求**：T2I 渲染请求需将所有字体、背景纹理、本地素材和动态网络图片（头像、武器、技能图标）安全转换为 `data:` URI，严禁模板对外部发起不受控的网络请求或容器内本地文件系统读取。
3. **真实账号凭据脱敏**：从 `ssh atri` 提取真实数据时，必须保护用户敏感 token、cookie 与隐私，仅使用业务字段进行渲染比对。
4. **架构兼容性**：`src/infrastructure/rendering` 需保持与服务层（`PlayerService`, `CheckinService`, `EncyclopediaService`, `NoticesService`）的 typed snapshot 接口解耦，同时提供完整的元数据（`dnaby.text`, `dnaby.layout`, `dnaby.resources`）以支持自动化回归测试。

## 执行方案

1. **数据源与基础设施准备**：
   - 探测 `localhost:8999` T2I 服务与 `ssh atri` 容器连通性。
   - 编写安全数据导出脚本，从 `ssh atri` 获取真实 `DNAUser` 账号与 `RoleOverview` / `RoleDetail` / `Stamina` / `Weekly` / `Calendar` / `Ann` 等真实 payload，存为测试 fixture。
2. **HTML/T2I 渲染基础设施迁移与统一**：
   - 将成熟的 Jinja2 模板架构、`RenderSpec`、`HtmlRenderer`、资源内联工具（`data:` URI 转换、字体内联、图片转 Base64）集成到 `rewrite-v0.1` 的 `src/infrastructure/rendering/` 中。
   - 确保字体包含 `MiSansVF.woff2`、`dna_fonts.woff2` 及 Arial Fallback 字体。
3. **分批迁移与样式复刻**：
   - **Batch 1 (通用/简单卡片)**：帮助卡、更新日志、公告列表、公告详情、密函简图与密函卡片。
   - **Batch 2 (资料与签到卡片)**：活动日历、签到日历、签到报告、实时体力便签。
   - **Batch 3 (角色与周报复杂卡片)**：角色总览、角色详情（含同律武器、魔之楔、伤害计算区块）、本周与上周周报。
4. **CSS 与布局高保真打磨**：
   - 对齐卡片尺寸（如 help 2020 宽、role_overview 1200 宽、sign_calendar 1300 宽、stamina 2000 宽等）。
   - 校准背景渐变、半透明毛玻璃卡片、边框弧度、阴影、图标对齐与网格排列，最大程度复刻 GScore PIL 视觉。
5. **端到端真实比对与验收**：
   - 生成 AstrBot T2I 渲染结果并保存至 `output/real/astrbot/`。
   - 计算与 `output/real/gscore/` 对应图片的 RGB 差异（MAD）与视觉结构对比。
   - 生成拼版接触图 `astrbot_contact.jpg`、`gscore_contact.jpg` 和 `diff_contact.jpg`，更新 `acceptance-report.md`。
6. **门禁与测试回归**：
   - 运行全量单元测试与模板契约测试，确保 compileall、ruff、pyright 全部 0 错误 0 警告。

## 默认假设

1. 本地 `localhost:8999` 为 T2I 渲染服务可用端口，当服务未启动或不可用时，单测支持 mock 校验，离线渲染脚本进行友好诊断。
2. `ssh atri` 为授权测试节点，从中导出的测试 payload 不包含明文密码或未经授权的生产密钥，仅用作渲染比对。
3. 渲染以视觉等价（布局、内容、层级、关键元素位置一致）为验收标准，因浏览器与 PIL 抗锯齿算法差异导致的微小单像素差属于正常物理现象。

## 验证与回滚

- 每个 task 完成后执行相关单元测试和静态检查。
- 每 3 个 task 进行集中复查。
- 遇重大破坏性问题，可通过 git commit 逐步回滚对应 task 的改动。
