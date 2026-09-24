# plan.md — 武器面板与资源同步稳定性

## 0. 输入与事实源

- 原始输入：`goal-1/input.md`（逐字保留用户 prompt）。
- 用户计划全文：`goal-1/plan-source.md`（`/Users/flanchan/Downloads/武器面板与资源同步稳定性实施计划.md` 的完整副本）。
- 设计 spec：`docs/superpowers/specs/2026-09-24-weapon-panel-resource-sync-design.md`（已存在于基线分支）。
- 硬约束优先级：`AGENTS.md`（仓库级）> 用户计划 > 本 plan 的默认假设。

## 1. 隔离工作区（using-git-worktrees）

- Step 0 检测：原 checkout 为普通仓库（`GIT_DIR == GIT_COMMON`，非 submodule）。
- 已存在 project-local 目录约定：`.gitignore` 第 19 行忽略 `.worktrees/`（`git check-ignore` 通过）。
- 未使用嵌套 worktree；工作区：
  - 路径：`.worktrees/weapon-panel`
  - 分支：`feat/weapon-panel-resource-sync`
  - 基线：`origin/docs/weapon-panel-resource-sync-design` @ `b4d553c`（= `main` @ `0fb62d6` + 4 个 spec 文档 commit）
  - 之所以基于该分支：用户计划要求的 design spec 只存在于该分支，阶段 0 需要修改它。
- Step 2 项目 setup：本仓库无 `package.json` / `Cargo.toml`，Python 依赖已由 runtime `.venv` 提供，无需额外安装。
- Step 3 基线验证：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest` → **505 passed**，工作区干净。

## 2. 当前实现事实（已读代码确认）

| 关注点 | 事实 |
| --- | --- |
| 命令声明 | `src/modules/player/commands.py`：`ROLE_DETAIL_PATTERN`、`REFRESH_ROLE_PATTERN`、`REFRESH_ALL_ROLE_PATTERN`、`CLEAR_ROLE_PATTERN`、`CLEAR_ALL_ROLE_PATTERN`；`commands.json` 为生成投影 |
| 面板入口 | `PlayerService.role_detail()` → `_role_detail_from_overview()`，参数名 `char_name` + `weapon_name_1/2` |
| 查找 | `_find_role()`（含 `_MASTER_ALIASES`、`_MASTER_AMBIGUOUS_ALIASES`、alias、包含匹配）、`_find_weapon()`（按 slot 顺序，"近战武器"/"远程武器"）、`_select_weapons()` |
| 详情获取 | `_fetch_detail_bundle()` 已调用 `transport.get_weapon_detail(actor, uid, weapon_id, weapon_eid, credential_user_id=...)`；无需新 API 层 |
| 所有权语义（现状） | `_select_weapons()`：`unlocked=False` → `PLAYER_WEAPON_NOT_UNLOCKED`；`weapon_eid is None` → `PLAYER_WEAPON_DETAIL_NOT_FOUND` |
| 缓存 | `PlayerCache`（`src/modules/player/cache.py`）：`player_data` / `player_card`；tag 有 `identity:`、`data:`、`resource:`、`role:<id>`、`overview`、`detail`；key 有 overview/detail data+card；**无 weapon tag/key** |
| 失效 | `invalidate_role_only()`（不含 overview）、`invalidate_role()`、`invalidate_identity()`（全量）、`invalidate_all()` |
| 渲染 payload | `src/infrastructure/rendering/weapon_renderer.py::draw_weapon_detail_section()`：已含武器图/名称/等级/skill_level/类型/攻击/暴击率/暴击伤害/攻击速度/触发率/魔之楔 |
| 现状字段缺陷 | 该函数 `speed` 用 `{speed:.0%}`（`1.0 → 100%`），与 spec 要求的倍率显示冲突；`trigger` 已是百分比语义 |
| 模板 | `src/templates/cards/role_detail.html.j2`（74 行）内联了武器 section 的 CSS + HTML，无独立 macro；`cards/macros/` 已有 `components.html.j2` / `layout.html.j2` 模式可复用 |
| 渲染入口 | `PlayerRenderer.render_detail()` → `_draw_role_detail_card()`；`PlayerRenderer` 通过 `resource_snapshots.bind_renderer()` 绑定 generation |
| 静态资源 | `_static_image()` / `_static_font()` + `StaticAssetResolver`；`static_records` 进入 artifact metadata |
| 图片链路 | `PlayerImageLoader.weapon()`：`AssetResolver.resolve("weapon", id, url)` → generation `images/weapon/<id>.png` → L2 → downloader → placeholder + `incomplete=True` |
| generation | `src/infrastructure/resources/generation.py::validate_current()`：开头 `if snapshot is self._current: self._current = None` 主动撤下已发布 current（**问题根因**）；失败路径已有 `_current = None` + `record_validation_failure`；`_begin_generation_repair()` 有 repairing 门禁与 lease 等待 |
| 文案 | `i18/zh/tip.json` → `player.*`；`src/modules/player/messages.py` 通过 `get_tip` / `get_tip_template` 读取；已有 `player.weapon_not_unlocked`、`player.weapon_detail_not_found` |
| 测试 | `tests/`（505 项）；相关：`test_player.py`、`test_weapon_renderer.py`、`test_resources.py`、`test_asset_resolver.py`、`test_player_asset_concurrency.py`、`test_entry_commands.py`、`test_config.py` |
| 生成物 | `scripts/generate_commands_manifest.py`、`scripts/generate_config_schema.py` |
| 工具链 | 运行测试用 `/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest`；`ruff check .`、`python3 -m compileall .` 同仓库约定 |

## 3. 范围与执行策略

阶段顺序（按用户计划"推荐执行顺序"，也符合风险从低到高）：

```text
0  spec 同步 → 1  generation 最小修复 → 2  智能解析 → 3  单武器 use case
→ 4  renderer/模板 → 5  单武器缓存 → 6  单武器 refresh/clear
→ 7  refresh all weapons → 8  clear all weapon cache → 9  文案
→ 10 最小测试 + 真实账号验收 → 终审
```

### ponytail 阶梯（本目标的默认解法取向）

1. 复用 `PlayerService` / `PlayerCache` / `PlayerRenderer` / `draw_weapon_detail_section()` / `PlayerImageLoader.weapon()`，不新建 Service、Client、Cache、generation。
2. 智能解析用现有 `_find_role` / `_find_weapon` + `AliasCatalog`，不引入 fuzzy-search 库。
3. 批量清理用 tag 交集（`identity:` + `weapon`）而不是逐 id 失效。
4. 模板抽取只做一层 macro/partial，不给角色模板加 `weapon_only` 分支。
5. 批量刷新只写数据缓存，不渲染卡片。
6. 修复 `speed` 显示为最小格式化改动（`1.0 → "1.0"`）。

### 不做（超出范围即拒绝）

- 新武器 API transport/client、`otherUserId`、`type=2`、`wiki/weapon` 抓取。
- 新缓存目录/管理器/generation/状态机/兼容层。
- 大范围重命名 `char_name`、重写角色面板、重写 `draw_weapon_detail_section()`。
- 无依据的 retry/timeout、新第三方依赖。
- "刷新全部武器"逐张渲染发送卡片。

## 4. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 智能解析改变现有角色查询行为 | 角色面板回归 | 角色命中路径保持现有 `_find_role` 结果；新增分流只在"角色未命中"后尝试武器；每步跑 `tests/test_player.py` |
| 双重命中（角色/武器同名） | 静默错误结果 | 明确歧义文案，不设优先级；仅在真实冲突时触发 |
| `validate_current()` 去掉撤下后，损坏目录在校验期间被读取 | 短窗口读到坏资源 | 校验仍在锁外完整执行；失败路径保留撤下 + `_begin_generation_repair()` 门禁；`_repairing` 阻止同 commit 新 lease |
| 武器卡片缓存 key 维度不足 | 脏缓存命中 | key 含 target_user_id / uid / weapon_id / overview_digest / detail_digest / resource_version / uid_hidden；tag 加 `weapon` + `weapon:<id>` |
| `speed` 语义修正影响既有卡面 | 角色面板武器区块显示变化 | spec 明确要求修正；同步更新 `test_weapon_renderer.py` 断言 |
| 宏抽取破坏角色详情卡布局 | 视觉回归 | macro 只搬移现有 CSS/HTML，不改类名与尺寸；跑 `test_rendering.py` / `test_player.py` 渲染用例 |
| 真实账号验收依赖运行期环境 | 无法自动验证 | 若无可用环境则标记该 task 阻塞并记录所需输入，不猜测、不提问循环 |

## 5. 验证方式

- 每个实现 task：先写/改最小回归测试并观察失败（Red），再实现（Green）。
- 分层检查：
  - 单点：`python -m pytest tests/test_player.py tests/test_weapon_renderer.py -q` 等目标文件。
  - 跨模块（本目标涉及入口/命令/渲染/缓存/资源）：结束时跑完整 `python -m pytest`。
  - 静态：`ruff check .`、`python3 -m compileall .`。
  - 生成物：命令变化后 `python3 scripts/generate_commands_manifest.py`。
- 每 3 个 task 一次集中检查（见 `tasks.md` 中的 `C0x` 项）。
- 最终终审对照用户计划"最终验收清单"与 Definition of Done 逐条核对。

## 6. 回滚方案

- 全部改动在独立 worktree + feature 分支上，`main` 未受影响；回滚 = 丢弃分支或 revert 单一 commit。
- 每个 task 独立 commit（message 带 task 编号），可逐个 `git revert`。
- 无 schema 变更、无持久化数据格式变更、无生产配置/密钥改动，因此不需要数据回滚。
- generation 修复若出现无法解释的回归，可单独 revert 该 commit（阶段 1 与其他阶段无耦合）。

## 7. 默认假设（后续会话不得回头提问，按此推进）

- **A1**：真实账号验收需要运行中的 AstrBot + 有效绑定凭据；若本会话不可用，该 task 标记"阻塞（需用户提供运行环境）"，跳到下一个未阻塞 task，终审统一汇报。
- **A2**：测试与 lint 统一使用 runtime `.venv`：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest`、`.../bin/ruff`。
- **A3**：所有用户可见新增文案写入 `i18/zh/tip.json` 的 `player.*`，并通过 `messages.py` 常量暴露；不硬编码中文。
- **A4**：`commands.json` 由 `scripts/generate_commands_manifest.py` 生成，不手工编辑。
- **A5**：武器面板命令沿用现有 `ROLE_DETAIL_PATTERN` 入口（`<名称>面板`），不为武器新增第二套主入口。
- **A6**：`刷新全部武器面板` 只更新武器详情数据缓存，不发送任何卡片；`清理全部武器缓存` 只按 `identity:` + `weapon` tag 交集删除 `player_data` / `player_card`。
- **A7**：magic 标签取 `weapon`（全部武器）+ `weapon:<weapon_id>`（单武器）；单武器清理用 `identity:` + `weapon:<id>`。
- **A8**：`speed`、`cri`、`crd`、`trigger` 的显示：`cri/crd/trigger` 百分比（`{v:.0%}`），`speed` 倍率（去尾零的 `str(float(v))`，`1.0 → "1.0"`）。
- **A9**：武器面板模板命名 `cards/weapon_detail.html.j2`；武器区块抽为 `cards/macros/weapon_section.html.j2`，角色模板改为 import 该 macro（CSS 仍留在 `role_detail.html.j2` 内并复制到武器模板需要的部分——若发现重复不可控，改为共享 macro 内的 `<style>`）；该项以"CSS 只出现一次"为验收条件。
- **A10**：不新增任何第三方依赖；不修改 `requirements.txt`。
- **A11**：`goal-1/` 目录随实现提交（沿用仓库历史中 goal 目录入库的先例）。
- **A12**：PR 创建不在本目标内自动执行；终审交付一份可直接使用的 PR 说明与验证证据清单（创建 PR 需用户明确要求，且需读 `.agents/skills/pr/SKILL.md`）。
