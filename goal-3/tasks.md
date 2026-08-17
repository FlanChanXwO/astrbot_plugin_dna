# Goal 3 任务清单：AstrBot T2I 渲染高保真复刻 GScore PIL 视觉

## 任务概览

- [x] Task 1: 验证 T2I 服务 (localhost:8999) 与 `ssh atri` 远端 GScore 数据库连接，导出完整真实数据 Payload
- [x] Task 2: 在 rewrite-v0.1 建立统一 HTML/T2I 渲染基础设施与内联资源加载管线
- [ ] Task 3: 迁移并校准通用与通知类卡片模板（帮助、更新记录、公告列表、公告详情、密函简图与卡片）
- [ ] Task 4: [集中检查-debug 循环 1] 复查 Task 1-3 基础设施、资源内联与简单/通知卡片契约
- [ ] Task 5: 迁移并校准资料与签到类卡片模板（活动日历、签到日历、签到报告、实时体力便签）
- [ ] Task 6: 迁移并校准角色与周报类复杂卡片模板（角色总览、角色详情、本周/上周周报）
- [ ] Task 7: 对齐 `src/infrastructure/rendering/` 全量渲染器接入 T2I 渲染层与元数据生成
- [ ] Task 8: [集中检查-debug 循环 2] 复查 Task 5-7 全部 14 类卡片渲染管线、接口兼容与单测
- [ ] Task 9: 执行真实账号全量 14 类卡片 T2I 渲染并输出至 `output/real/astrbot/`
- [ ] Task 10: 针对性微调 HTML/CSS 样式与布局细节，消除视觉差异与布局瑕疵
- [ ] Task 11: 生成接触图 (contact sheets)、差异对比图与更新真实数据验收报告
- [ ] Task 12: [集中检查-debug 循环 3 / 终审] 全量门禁校验 (compileall/ruff/pyright/pytest) 与交付核验

---

### Task 1: 验证 T2I 服务与 `ssh atri` 数据提取
- **目标**：验证 `localhost:8999` T2I 接口连通性；从 `ssh atri` GScore 容器中的 `/gsuid_core/data/GsData.db` 提取真实 `dnauser` 账号信息与全套 14 种卡片真实 Payload，生成结构化本地 fixture。
- **状态**：已完成
- **预留回写**：
  - 实际做了什么：验证了 `http://localhost:8999/text2img/generate` 服务连通性与 PNG 渲染能力；验证了 `ssh atri` 上 `gsuid_core` 容器数据库 `/gsuid_core/data/GsData.db` 连接；执行武器详情导出脚本成功获取 `weapon-detail.json`；将覆盖 14 类卡片的真实 payload 与武器详情固化到 `tests/fixtures/`。
  - 验证证据：`curl` 测试 T2I 服务成功生成 `/tmp/test_t2i.png` (PNG image data, 1280x720)；`tests/fixtures/live-payload.json` (75KB) 与 `tests/fixtures/weapon-detail.json` 校验通过，包含完整角色、便签、周报、签到、日历、公告和密函字段。
  - 剩余风险：无。真实数据已在本地固化为离线测试 fixture。
  - 下一步：执行 Task 2，在 `rewrite-v0.1` 建立统一 HTML/T2I 渲染基础设施与内联资源加载管线。

---

### Task 2: 建立统一 HTML/T2I 渲染基础设施
- **目标**：在 `rewrite-v0.1` 的 `src/infrastructure/rendering/` 中建立 Jinja2 模板加载、`RenderSpec` 规格定义、`HtmlRenderer` T2I 客户端适配、字体内联（`MiSansVF.woff2`, `dna_fonts.woff2` 等）与 `data:` URI 资源编码管线。
- **状态**：已完成
- **预留回写**：
  - 实际做了什么：集成了 `dnaby/rendering/`（`HtmlRenderer`, `RenderSpec`, `assets`, `spec`, `errors`, `payloads`, `qr`）；补充了 `MiSansVF.woff2`, `dna_fonts.woff2`, `arial-unicode-ms-bold.woff2` 等 WOFF2 内联字体；在 `src/infrastructure/rendering/__init__.py` 中完成统一导出；更新了 `dnaby/dna_sign/sign.py` 的签到报告渲染实现。
  - 验证证据：Pyright 0 错误 0 警告；`tests/test_html_renderer.py` 与 `tests/test_rendering_assets.py` 16 个单元测试全部通过；`tests/test_t2i_integration.py` 真实 T2I 集成测试通过。
  - 剩余风险：无。
  - 下一步：执行 Task 3，迁移并校准通用与通知类卡片模板。

---

### Task 3: 迁移与校准通用/通知类卡片模板
- **目标**：实现/迁移帮助卡 (`help`)、更新记录 (`update_log`)、公告列表 (`ann_list`)、公告详情 (`ann_detail`)、委托密函简图 (`mh_simple`) 与委托密函卡片 (`mh_card`) 的 Jinja2 模板与样式，确保像素宽度与结构对齐。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 4: [集中检查-debug 循环 1]
- **目标**：集中复查 Task 1-3 的代码质量、模板转义安全、资源内联无死链、T2I 客户端单测覆盖，运行 ruff 与 pyright 检查。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 5: 迁移与校准资料/签到类卡片模板
- **目标**：实现/迁移活动日历 (`calendar`)、签到日历 (`sign_calendar`)、签到报告 (`sign_report`)、实时体力便签 (`stamina`) 的 Jinja2 模板，精准还原双栏布局、日历格子、进度条与魔之楔锻造状态。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 6: 迁移与校准角色/周报类复杂卡片模板
- **目标**：实现/迁移角色总览 (`role_overview`)、角色详情 (`role_detail`，含武器、同律武器、技能、溯源、魔之楔、伤害计算区块) 与本周/上周周报 (`weekly_current`, `weekly_last`) 模板，复刻复杂多网格卡片布局。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 7: 对齐 `src/infrastructure/rendering/` 全量渲染器
- **目标**：重构 `PlayerRenderer`, `CheckinRenderer`, `EncyclopediaRenderer`, `NoticesRenderer`，使其完全通过 T2I 渲染层产出图片，保留 typed snapshot 接口与 `dnaby.text`/`dnaby.layout`/`dnaby.resources` 审查元数据。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 8: [集中检查-debug 循环 2]
- **目标**：集中复查 Task 5-7 的所有渲染器与模板，验证 14 类卡片的端到端契约测试，检查是否有遗留 PIL 绘制、内存泄漏或缺失字段。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 9: 批量执行真实账号 T2I 渲染
- **目标**：使用 Task 1 提取的真实数据与固定时钟/背景，通过本地 `localhost:8999` T2I 服务批量生成全套 14 张真实 AstrBot 图片到 `output/real/astrbot/`。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 10: 针对性微调 HTML/CSS 样式与高保真复刻
- **目标**：根据 GScore PIL 原版图片 (`output/real/gscore/`) 与 AstrBot T2I 渲染图逐张比对，调优字体抗锯齿、内边距、字间距、行高、背景图定位、徽标阴影和边框圆角，实现真正的视觉等价复刻。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 11: 生成拼版接触图与验收报告
- **目标**：重新生成 `astrbot_contact.jpg`、`gscore_contact.jpg`、`diff_contact.jpg` 并更新 `output/real/acceptance-report.md`，记录各卡片画布尺寸、字节数、MAD 指标与视觉审查结论。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：

---

### Task 12: [集中检查-debug 循环 3 / 终审]
- **目标**：执行全量测试套件（pytest）、编译检查（compileall）、代码规范（ruff）与类型检查（pyright 0 errors / 0 warnings），核对所有文档与交付物，完成最终验收。
- **状态**：待开始
- **预留回写**：
  - 实际做了什么：
  - 验证证据：
  - 剩余风险：
  - 下一步：
