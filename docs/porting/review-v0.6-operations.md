# v0.6 运维与面板阶段集中审查

> 覆盖 Task 25-27（`f369e14..0446508`）。复核面板/资源更新的安全性、路径和 Git 边界、
> 日志脱敏、配置契约、文档同步与全量门禁；本轮修复问题见「修复」小节。

## 审查范围

- 面板图管理（`src/modules/operations/`）：上传/列表/删除/压缩、`原图删除` 不支持边界。
- 资源更新（`ResourceUpdateService` + `ResourceSynchronizer`）：浅克隆/`pull --ff-only`、
  Git 缺失/认证/远端/非快进/本地修改不自动覆盖。
- 路径安全：自定义面板目录是否可能逃逸 `panel_custom/`。
- 日志脱敏：`ResourceSyncError` 文案经 `git.py` `_redact_git_detail` 脱敏。
- 配置契约：`_conf_schema.json` 与 settings 定义一致。
- 文档同步：AGENTS.md/CLAUDE.md（≤100 行镜像）、docs 索引与资源数据目录边界。

## 修复（本轮集中检查发现）

1. **面板目录路径越界守卫缺失**：`PanelService._char_panel_dir` 原直接用
   `panel_root / panel_dir_for(char_id)`，若 `resolve_char_id`/`panel_dir_for` 返回含
   `../` 的 CharId 可逃逸 `panel_custom/`。现对解析结果 `.resolve()` 并校验必须位于
   `panel_root` 内，越界返回不可用（防御性拒绝）；新增回归测试
   `test_upload_rejects_path_escaping_char_id`。

## 复查结论

- 资源同步 Git 边界与凭据脱敏由既有 `test_config_resources.py` 覆盖（origin 校验、本地
  修改拒绝、URL token 脱敏）；`ResourceUpdateService` 把各失败类别映射为可见文案。
- 配置契约：`scripts/generate_config_schema.py` 后 `_conf_schema.json` 无 diff。
- 文档：AGENTS.md 61 行、CLAUDE.md 1 行（`@AGENTS.md` 镜像指针），均 ≤100；docs 索引已
  收录 review-v0.4/v0.5 与 offline-write-contracts。
- 写操作（面板上传/删除/压缩、资源同步）只操作隔离 fixture/目录，未操作真实账户或参考区。

## 未解决问题（留待后续）

- 私有资源仓库创建/推送与真实同步仍是独立外部步骤（需用户授权）。
- `dna_status` Dashboard 指标按设计保留统计函数不注册。

## 门禁证据

- staging runtime 全量 pytest：`289 passed, 1 skipped, 1 warning`。
- `ruff check .`、`pyright --project pyrightconfig.json`（0/0/0）、runtime `compileall`、
  `pre-commit run --all-files`、`git diff --check` 均通过。
- 参考区 `legacy-reference` 冻结在 `664b677`；未检出 `gsuid_core`/`gsucore` import。
