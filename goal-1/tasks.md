# tasks.md — 武器面板与资源同步稳定性

规则（goal-mode）：

- 一轮只做一个 task，按编号顺序取第一个未完成的 task，不跳序、不合并。
- 每个 task 必须留下可验证证据（命令、输出、diff、测试报告），只凭口头声明不算完成。
- 完成后在对应 task 下填写：实际改动 / 验证证据 / 剩余风险 / 下一步。
- 每完成 3 个 task 后，下一轮必须是集中检查（`C01` / `C02` / `C03` / `C04`），不得跳过。
- 发现问题时在文件末尾追加 `Fxx` 修复 task，再按顺序处理。
- 全部 task 完成后进入终审轮。

工作区：`.worktrees/weapon-panel`，分支 `feat/weapon-panel-resource-sync`。
测试命令：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest`。

---

## 阶段 0

### [x] T01 — 同步 design spec 的新需求
- 范围：`docs/superpowers/specs/2026-09-24-weapon-panel-resource-sync-design.md`
- 动作：删除"不包含：'刷新全部武器'命令"，在包含范围补充 `刷新全部武器面板` 与 `清理全部武器缓存`，并对齐用户 plan 第六/七/八章的批量语义（只处理当前 UID、只处理 owned、只写数据缓存、不发卡片、按 tag 交集清理）。
- 验证：spec 中不再出现"不包含刷新全部武器"，且包含两个新命令的明确语义描述；`git diff` 可复核；纯文档改动无需测试，但需确认不引用不存在的路径/符号。
- 实际改动：4 处编辑——包含范围补两条批量命令；从“不包含”删除 `"刷新全部武器"命令`；新增 `### 4.3 批量武器操作`（命令、权限、owned 过滤、只写数据缓存、失败隔离、tag 交集 `identity:+weapon`、不调用 `invalidate_identity()`、角色批量操作范围不变）；新增 `### 7.6 批量武器操作` 测试项，并把验收标准第 8 条改为批量武器条款、原第 8 条顺延为第 9 条。
- 验证证据：`rg -n "刷新全部武器|清理全部武器"` 命中 8 处语义位置（含 4.3/7.6/8）；反向检索 `不包含.*刷新全部武器` 与 `“刷新全部武器”命令` 均无命中（exit=1）；`git diff --stat` = 1 file changed, 40 insertions(+), 2 deletions(-)；commit `23d43e5`，pre-commit hook `ruff check ... Passed`。
- 剩余风险：spec 现在与实现计划一致，但实现尚未落地（后续 T04–T10 负责）；spec 第 4.3 节的 tag 方案与 T07/T10 的实现必须保持一致，已在 tasks.md T07/T10 写入相同约定。
- 下一步：T02 —— `validate_current()` 去除校验开始前主动撤下 current，并补 Red→Green 回归测试。

### [ ] T02 — `validate_current()` 停止提前撤下已发布 generation（含回归测试）
- 范围：`src/infrastructure/resources/generation.py`、`tests/test_asset_resolver.py` 或 `tests/test_resources.py`
- TDD：先写 Red 测试——`validate_current()` 执行期间（校验未结束）新请求仍能 `acquire()` 到 current；validation 失败后 current 才不可用；已持有 lease 的行为不变。
- 动作：删除校验开始阶段的 `self._current = None`；保留失败路径撤下、`record_validation_failure`、`_begin_generation_repair()`、lease 等待、原子发布。
- 验证：新测试 Red → Green；`python -m pytest tests/test_resources.py tests/test_asset_resolver.py tests/test_player_asset_concurrency.py -q` 全绿；`ruff check .`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T03 — 面板对象智能解析（role / weapon / ambiguous / not_found）
- 范围：`src/modules/player/service.py`（必要时 `contracts.py`）、`tests/test_player.py`
- TDD：先写 Red 测试覆盖：正式角色名→role、正式武器名→weapon、武器 alias→weapon、alias 缺失但 API 正式名→weapon、双重命中→歧义、双未命中→未找到、武器 + `+...`→拒绝。
- 动作：新增最小解析（正式名优先：`role_chars` / `close_weapons` / `ranged_weapons` 按 `.name`；再 `aliases.resolve_char` / `resolve_weapon` 回查）；不建复杂 domain hierarchy，不引入 fuzzy 库。
- 验证：新测试 Red → Green；`tests/test_player.py -q` 全绿。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] C01 — 集中检查（T01–T03）
- 检查：需求是否偏离 `input.md`；死代码/调试残留；类型与 lint；相关测试；错误路径。
- 结论：
- 追加 task：

---

## 阶段 1（单武器面板）

### [ ] T04 — 独立武器面板 use case（查询 + 所有权 + 空详情）
- 范围：`src/modules/player/service.py`、`tests/test_player.py`
- TDD：先写 Red 测试：owned + weaponEid → 调 `get_weapon_detail`；`unlocked=False` → 未拥有且**不调用**详情接口；`weapon_eid=None` → 未拥有；空 `weaponDetail` → 详情未找到（不渲染零属性卡）。
- 动作：复用 `transport.get_weapon_detail`，不新增 client；所有权判断 `not weapon.unlocked or weapon.weapon_eid is None` → `PLAYER_WEAPON_NOT_UNLOCKED`。
- 验证：新测试 Red → Green；`tests/test_player.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T05 — 抽取武器区块 Jinja macro 并支持独立武器模板
- 范围：`src/templates/cards/macros/weapon_section.html.j2`（新）、`src/templates/cards/role_detail.html.j2`、`src/templates/cards/weapon_detail.html.j2`（新）、`src/infrastructure/rendering/player.py`、`tests/test_rendering.py`
- TDD：先写 Red 测试——武器模板渲染包含武器名/等级/精炼等级/6 项属性/魔之楔，且与角色卡共用同一 section HTML 结构（CSS 不重复）。
- 动作：只做一层 macro/partial；独立模板只负责 wrapper + 标题 + 主视觉 + 共用 section + footer；不给角色模板加 `weapon_only` 分支。
- 验证：新测试 Red → Green；`tests/test_rendering.py tests/test_player.py -q`；渲染冒烟（离屏产出 JPEG，尺寸与 `incomplete` 状态可读）。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T06 — 修正武器字段显示语义（`speed` 倍率、精炼等级）
- 范围：`src/infrastructure/rendering/weapon_renderer.py`、`tests/test_weapon_renderer.py`
- TDD：先写 Red 断言：`cri→暴击率百分比`、`crd→暴击伤害百分比`、`trigger→百分比`、`speed=1.0→"1.0"`（不是 `100%`）、精炼等级标签正确、Mod 顺序与 `id=-1` 空槽保留。
- 动作：最小格式化修正，`_mode_order` 与属性转换逻辑不动。
- 验证：Red → Green；`tests/test_weapon_renderer.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] C02 — 集中检查（T04–T06）
- 检查：单武器链路端到端（解析→所有权→详情→渲染）；模板重复度；字段语义；相关测试与 lint。
- 结论：
- 追加 task：

---

## 阶段 2（缓存与刷新）

### [ ] T07 — 单武器缓存 key/tag 与不完整卡语义
- 范围：`src/modules/player/cache.py`、`src/modules/player/service.py`、`tests/test_player.py`
- TDD：先写 Red 测试：相同 detail/resource version 命中；detail 变化或 resource version 变化后重新生成；`incomplete=True` 不写完整卡缓存；key 含 target_user_id/uid/weapon_id/overview_digest/detail_digest/resource_version/uid_hidden。
- 动作：新增 `weapon_data_key` / `weapon_card_key` / `weapon_data_tags` / `weapon_card_tags`；tag = `player_data|player_card` + `identity:<digest>` + `weapon` + `weapon:<id>`（+ `data:`/`resource:`）。
- 验证：Red → Green；`tests/test_player.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T08 — `刷新<名称>面板` / `清理<名称>面板缓存` 的武器分支
- 范围：`src/modules/player/service.py`、`src/modules/player/commands.py`、`tests/test_player.py`
- TDD：先写 Red 测试：`刷新<武器名>面板` 走武器刷新（最新 overview → 覆盖旧详情缓存 → 新卡）；`清理<武器名>面板缓存` 只清 `identity:`+`weapon:<id>`，不影响其它武器与角色。
- 动作：复用现有命令正则（不加重命名），在 refresh/clear use case 内按解析结果分流；角色分支行为保持不变。
- 验证：Red → Green；`tests/test_player.py tests/test_entry_commands.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T09 — `刷新全部武器面板`
- 范围：`src/modules/player/commands.py`、`src/modules/player/service.py`、`src/modules/player/messages.py`、`i18/zh/tip.json`、`commands.json`（生成）、`tests/test_player.py`、`tests/test_entry_commands.py`
- TDD：先写 Red 测试：overview 含 owned A/owned B/unowned C → 只请求 A、B，不请求 C；一把失败不阻断下一把；成功/失败计数正确；失败名汇总正确；不生成武器卡片。
- 动作：新增 `REFRESH_ALL_WEAPON_PATTERN = r"^刷新全部武器面板$"` + 独立 `CommandSpec`，不落入 `REFRESH_ROLE_PATTERN`；行为与 `refresh_all_roles()` 对齐（一次 overview、失败隔离、凭证失败走既有持久化、不新增 retry）。
- 验证：Red → Green；`python3 scripts/generate_commands_manifest.py` 后 `git diff commands.json` 仅含预期新增；`tests/test_entry_commands.py tests/test_player.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T10 — `清理全部武器缓存`
- 范围：`src/modules/player/commands.py`、`src/modules/player/cache.py`、`src/modules/player/service.py`、`i18/zh/tip.json`、`commands.json`、`tests/test_player.py`
- TDD：先写 Red 测试：构造 weapon A、weapon B、role X、overview → 清理全部武器缓存后 A/B 移除，role X 与 overview 保留；不调用 `invalidate_identity()`。
- 动作：`CLEAR_ALL_WEAPON_PATTERN = r"^清理全部武器缓存$"` + 最小 `invalidate_all_weapons(target_user_id, uid)`（tag 交集 `identity:` + `weapon`）。
- 验证：Red → Green；`python3 scripts/generate_commands_manifest.py`；`tests/test_player.py tests/test_entry_commands.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] C03 — 集中检查（T07–T10）
- 检查：批量操作对称性与范围隔离；tag 交集是否误伤；commands.json 与源码一致；失败隔离；lint。
- 结论：
- 追加 task：

---

## 阶段 3（文案与图片链路）

### [ ] T11 — 新增/复用文案并接入 messages
- 范围：`i18/zh/tip.json`、`src/modules/player/messages.py`、`tests/test_player.py`（或文案断言测试）
- 动作：复用 `player.weapon_not_unlocked`、`player.weapon_detail_not_found`；新增最少 key：未找到角色或武器、名称同时匹配角色和武器、武器面板不支持附加武器参数、武器面板已刷新、全部武器刷新完成、武器面板缓存已清理、全部武器缓存已清理。
- 验证：文案 key 存在且可格式化；`messages.*` 常量可导入；相关测试全绿。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T12 — 武器主视觉图片链路回归（generation → L2 → icon 下载 → placeholder）
- 范围：`tests/test_player_image_loader.py`（或 `tests/test_player_asset_provenance.py`）
- TDD：先写 Red 测试：generation miss + API icon 可下载 → 走 download 并 `provided`；下载失败 → placeholder + `incomplete=True`；`incomplete` 卡不写入完整卡缓存。
- 动作：仅在测试需要时做最小实现调整，不接入 `wiki/weapon`，不新增下载器。
- 验证：Red → Green；`tests/test_player_image_loader.py tests/test_player_asset_provenance.py -q`。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] C04 — 集中检查（T08–T12 覆盖项对齐）
- 检查：用户 plan 第十三章 11.1–11.8 是否都有对应测试；是否有遗留未接入分支；lint 与类型。
- 结论：
- 追加 task：

---

## 阶段 4（全量验证与终审）

### [ ] T13 — 全量验证与生成物一致性
- 动作：`python -m pytest`（完整）、`ruff check .`、`python3 -m compileall .`、`scripts/generate_commands_manifest.py` 与 `scripts/generate_config_schema.py` 幂等校验（重跑后无 diff）。
- 验证：完整测试全绿（记录真实数量）；生成物无未提交 diff。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T14 — 真实账号验收（owned 但未装备武器）
- 动作：在可用运行环境（AstrBot + 有效绑定）中验证"已拥有但未装备武器可查询"。**若环境不可用：标记阻塞，记录所需输入，不猜测、不提问。**
- 验证：查询成功并产出完整武器卡（记录命令与结果；阻塞时记录阻塞证据）。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

### [ ] T15 — 终审：对照最终验收清单与 Definition of Done
- 动作：逐条核对用户 plan 第十六章 28 项验收清单与 Definition of Done 11 项；检查是否有越界抽象/依赖/兼容层；确认改动是单一聚焦 feature/fix PR 规模；整理 PR 说明与验证证据（创建 PR 需用户明确要求）。
- 验证：清单逐条打勾或标注阻塞；无未解释的越界改动。
- 实际改动：
- 验证证据：
- 剩余风险：
- 下一步：

---

## 追加的修复 task

（暂无）
