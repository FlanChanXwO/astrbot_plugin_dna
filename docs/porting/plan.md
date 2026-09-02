# 实施计划（plan.md）

> superpowers Implementation Planning 交付物。每任务 2–5 分钟粒度，TDD：先红后绿。分阶段见下；**当前进度与已知问题见 [progress.md](progress.md)**。

## Phase 0 — 脚手架（完成）
- 插件骨架、metadata/requirements/README/LICENSE/.gitignore、AGENTS.md/CLAUDE.md、docs/、复制源码与素材、design.md。

## Phase 1 — 核心基建（完成）
1. `dnaby/utils/logger.py` 或改用 `astrbot.api.logger`（全局替换 17 处 `gsuid_core.logger`）。
2. `dnaby/utils/session.py`：`EventContext` + `Sender`（test_session）。
3. `dnaby/utils/resource.py`：数据目录 + init_dir + 模板 env（替换 `RESOURCE_PATH` 的 `get_res_path`）。
4. `dnaby/utils/image_utils.py`：convert_img/tint_image/crop_center_img/download/get_qrcode_base64/get_event_avatar/change_ev_image_to_bytes（本地 PIL+qrcode+httpx）。
5. `dnaby/utils/database/base.py`：引擎/with_session/BaseIDModel/Bind/User + 迁移 runner；`models.py` 去 gsucore base（test_database）。
6. `dnaby/utils/subscriptions.py`：订阅存储 + 推送（test_subscriptions）。
7. `src/infrastructure/config/`：Pydantic typed settings + `_conf_schema.json` 生成；`src/infrastructure/resources/`：私有 Git manifest 校验与 fast-forward-only 同步（test_config_resources）。
8. `dnaby/utils/msgs/notify.py`：适配 Sender/EventContext。
9. `CommandSpec` 显式 registry、独立正则 handler 和权限 decorator，生成 `commands.json`（test_command_registry/test_commands）。
10. 帮助 use case 读取同一 registry，未实现命令不展示。

## Phase 2 — 信息查询（免登录，完成）
角色基础卡片/面板、图鉴、攻略、日常、日历、周报、兑换码、公告查看。正常角色详情不再调用
伤害接口或渲染伤害区块；伤害数据结构、renderer、模板和 CSS 作为显式复用资源保留。历史更新记录命令已由
`goal-1` 第一阶段移除，长期更新历史改由仓库根目录 `CHANGELOG.md` 承担。每命令 test 起步。

## Phase 3 — 账号与隐私（完成）
绑定/切换/删除/查看、App token 登录、短信命令登录、退出、凭据状态查询、隐私 12 条；
Web 凭据与 Web fallback 不属于当前契约。

## Phase 4 — App 登录页（完成）
`LoginFlowCoordinator` 管理 App 登录页、进程内 TTL 会话、QR 和外置 `http_poll/sse/ws` transport；
local 模式由 `LocalLoginServer` 随插件生命周期启动和释放，Web 登录页与凭据字段已移除。

## Phase 5 — 订阅与定时（完成）
签到（手动/自动/日历/全部/结果订阅）、密函（查看/列表/订阅/周期/图片/文本/测试/推送）、公告轮询、记录清理。

## Phase 6 — 高级/外围（完成）
别名、面板图、下载资源、原图、状态。

## Phase 7 — 收尾（代码验收完成，外部冒烟待授权）
全量 pytest/ruff/compileall、reload 重载、NapCat 真机冒烟、review.md、final_report.md。

已完成：全量离线测试、插件目录与 runtime 严格 Ruff、源码级 Pyright、compileall、顶层/命名空间动态导入、AstrBot Dashboard 重载、审查报告和最终报告。

未执行：真实验证码、第三方登录/API 业务请求和 NapCat 真机冒烟；这些需要真实账号、外部服务和用户授权，不属于本地离线验收证据。

Phase 6 中的 `dna_status` 仅保留统计函数，不注册原 gsucore Dashboard 指标；设计文档将该能力定义为可选项，当前按可选项关闭处理。
