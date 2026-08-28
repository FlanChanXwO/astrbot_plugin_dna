# 执行任务清单

> **执行中：按 goal-mode 自动推进。** 用户已明确要求启动 `goal-1`，从 O01 顺序推进。每个普通任务只占一个目标轮次；每完成 3 个普通任务，必须执行紧随其后的调试审查任务，不能跳过。

统一完成记录模板（执行时填写到对应任务下）：

- 实际完成：
- Red/Green/Refactor 证据：
- 验证命令与结果：
- 剩余风险：
- 下一步：

## 第一阶段：原版命令行为与帮助

### O01 — 执行前隔离、基线与失败复现 `[completed]`

- 征得用户对 Git worktree/`codex/` 分支的明确同意后建立隔离环境。
- 阅读 `docs/README.md`、`docs/porting/design.md` 及即将修改的确切代码。
- 运行最小测试，复现并记录 `test_help_image_is_tracked_and_cleaned` 当前失败。
- 为第一阶段验收矩阵补充 Red 测试，不写实现。

完成记录：

- 实际完成：确认当前项目根目录是 Git 已注册 worktree（`main`，HEAD `9a33b60ed3545020b97acb11e18b91041c1f80de`），按用户指定目标路径继续执行，未触碰其它 worktree、生产仓库或运行期数据。阅读 `docs/README.md`、`docs/porting/design.md`、帮助 use case、响应边界、命令 registry、事件目标解析及相关测试，并新增 `tests/test_goal1_phase1_red.py`；goal-1 三份状态文件与测试契约已纳入本轮提交。
- Red/Green/Refactor 证据：Red 已实际成立；本 task 只建立行为契约，不写生产实现，因此没有 Green/Refactor 阶段。新增测试锁定：权限过滤、最后一个有效 At、权限枚举收敛为 `user/admin`、移除 `update_log` 命令。
- 验证命令与结果：项目 `.venv/bin/python -m pytest tests/test_generated_image_lifecycle.py::test_help_image_is_tracked_and_cleaned -q` 为 `1 failed`，失败原因为 monkeypatch renderer 不接受 `prefix`；项目 `.venv/bin/python -m pytest tests/test_goal1_phase1_red.py tests/test_generated_image_lifecycle.py::test_help_image_is_tracked_and_cleaned -q` 为 `5 failed, 1 warning`，均为预期 Red/已知基线；项目 `.venv/bin/ruff check tests/test_goal1_phase1_red.py` 通过。
- 剩余风险：当前工作目录虽是已注册 Git worktree，但仍为 `main` 主工作树，未另建 task-specific `codex/` worktree；这是因用户直接指定该项目路径且 goal-mode 禁止交互式停问所作的执行假设，后续 commit 仅纳入本轮明确文件。系统 `python3` 缺少 `astrbot`，验证必须使用项目 `.venv`；帮助图生命周期基线与新增 Red 契约仍待 O02/O03 实现后转绿。
- 下一步：O02，先实现权限快照、registry 帮助过滤、动态前缀/版本缓存及移除更新记录命令。

### O02 — 权限、registry 帮助、动态前缀与版本 `[completed]`

- TDD 实现 user/admin 权限快照和帮助过滤。
- 帮助命令从 registry 构建，纳入角色列表等全部可见命令。
- 移除隐式 `d` 前缀，版本改为单一 metadata 源，按前缀/权限/版本缓存并在生命周期结束时失效。
- 移除更新记录命令与长 Git log 渲染链。

完成记录：

- 实际完成：权限枚举收敛为 `user/admin`，handler 在 `CommandRequest` 中一次快照事件管理员权限；所有原 `owner` 命令统一映射 AstrBot `admin`。帮助卡从 registry 的可见命令构建，保留表现层分组说明/图标，普通用户过滤管理员命令；移除模板隐式 `d` 和硬编码版本，版本统一读取 `metadata.yaml`。帮助缓存按 registry 身份、前缀、权限、版本索引，并在 runtime terminate 的 `finally` 中失效；registry 模式不再生成静态 help fallback。删除聊天“更新记录”命令、资源 service 的 Git log/图片链、模板、脚本调用和静态帮助条目，重新生成 `commands.json`。
- Red/Green/Refactor 证据：先实际运行 O01 Red 契约，权限/帮助/版本缓存与更新日志行为均出现预期失败；新增生命周期失效契约后先以旧实现运行得到 `1 failed`，恢复失效逻辑后 `1 passed`。发现 registry payload 仍带旧静态 `lines` 后补 Red 断言，旧实现实际失败，再改为 registry 模式空 fallback 并转绿。保留 O03 的最后有效 At 红契约，未在本任务越界实现。
- 验证命令与结果：项目 `.venv/bin/python -m pytest` 相关 O02 文件并排除 `test_target_user_uses_the_last_valid_mention` 为 `112 passed, 1 deselected, 5 warnings`；项目 `.venv/bin/python -m ruff check .` 通过；项目 `.venv/bin/python -m compileall -q src main.py scripts` 通过；`git diff --check` 通过；命令清单检查为 60 条、权限集合仅 `admin/user`、无 `update_log`。
- 剩余风险：O03 的 At 目标解析红契约仍失败（当前实现取第一个有效 At），下一任务处理；本任务未执行生产重载或真实平台副作用。
- 下一步：O03，按计划修复最后一个有效 At、机器人/AtAll 过滤与隐私目标边界。

### O03 — 卡片、面板、体力、周报与梦魇残声 At 对齐 `[pending]`

- TDD 实现最后一个有效 At、忽略机器人/全体 At、隐私检查与全局内容身份边界。
- 覆盖 `d卡片@xx`、空格、多 At、权限与未绑定目标等原版行为。
- 统一相关 handler 对目标用户身份的解析方式。

### D01 — 调试审查 O01–O03 `[pending]`

- 审查本轮 diff 是否偏离已确认范围，定位重复/遗漏 handler 与权限绕过。
- 运行第一阶段目标测试、LSP/等效引用核验、ruff 与 compileall。
- 记录阻塞问题；修复前不得进入 O04。

### O04 — 第一阶段文档、投影与完整门禁 `[pending]`

- 更新 usage/project 文档与 CHANGELOG/发行说明约定。
- 重新生成并核对 `commands.json` 与必要 schema。
- 运行完整 pytest、ruff、compileall，修复本阶段问题。

### O05 — 第一阶段审查与独立 SHA `[pending]`

- 自审并使用 `code-review-expert`，处理所有阻塞发现。
- 形成只包含第一阶段的可追溯 commit SHA。
- 记录部署前 SHA、变更摘要和回滚 SHA，不部署。

### O06 — 第一阶段 atri 精确 SHA 热重载验收 `[pending]`

- 严格按 `plan.md §4.2` 完成插件 ID 预检、精确 SHA 切换、定向 reload、生命周期核对和失败回滚。
- 运行权限/帮助/At 行为 adapter 模拟。
- 复制帮助、卡片、周报等产物到本地并由 Agent 实际查看。

### D02 — 调试审查 O04–O06 `[pending]`

- 核对本地 SHA、生产 SHA、插件版本、registry 投影和日志生命周期一致性。
- 检查是否存在重复 handler、残留 scheduler 或无权限命令泄露。
- 阶段一未稳定前不得启动缓存重构。

## 第二阶段：资源、下载、卡片与公告缓存

### O07 — CacheManager 契约与核心状态机 `[pending]`

- 先写 fresh/stale/miss、sidecar metadata、内容哈希、tags、资源版本、租约和并发 Red 测试。
- 实现统一 CacheManager 与可配置 TTL，不接入具体业务。
- 验证失败/空/不可解码内容永不成为成功缓存。

### O08 — ResourceManager 不可变快照与后台预热 `[pending]`

- TDD 实现 staging 下载、manifest/路径/哈希/图片验证、原子 active pointer 和 single-flight。
- 启动后台预热；“下载全部资源”加入并等待同一任务。
- 终止时正确取消后台任务，不残留锁与临时目录。

### O09 — ImageFetcher 重试、原子下载与资源包拆分 `[pending]`

- TDD 实现瞬态错误初次加 2 次重试、1/2 秒退避和 `Retry-After`，明确非重试错误。
- 临时文件写入、PIL 校验、原子替换与 single-flight。
- 整理公共基础资源和账号补充资源边界，禁止秘密进入公共资源仓库。

### D03 — 调试审查 O07–O09 `[pending]`

- 重点检查锁顺序、取消、进程崩溃、原子性、目录穿越、失败缓存与秘密泄露。
- 运行并发/故障注入测试及相关静态检查。
- 记录资源 repo 与插件 repo 的版本耦合方式。

### O10 — 角色数据和卡片缓存接入 `[pending]`

- TDD 接入 30 分钟 fresh、24 小时 retention、stale 刷新与完整旧卡回退。
- 缺图允许本次占位发送，但标记 incomplete 且不写入/覆盖完整缓存。
- 关联数据、面板、素材版本和 tags，确保精准失效。

### O11 — 刷新命令、全量角色缓存清理与渲染租约 `[pending]`

- TDD 实现用户指定角色刷新、管理员 UID+角色刷新、管理员全量角色缓存清理。
- 接入 `cache.refresh_send_card`。
- 清理 `rendered/` 孤儿和过期缓存，同时保护在发送文件；针对已观测 741 MB 增长建立回归测试。

### O12 — 公告完整显示、分页、多图与缓存 `[pending]`

- TDD 修复公告查询参数/hash URL、完整分页、详情与多图同一回复。
- 去除前 20 条等无依据截断。
- 公告卡与源图仅完整时缓存，24 小时 TTL 加 fingerprint 提前失效。

### D04 — 调试审查 O10–O12 `[pending]`

- 检查 incomplete 结果是否可能污染完整缓存、租约是否泄露、精准刷新是否误删他人数据。
- 对公告做分页、URL、部分图片失败、上游变化和缓存过期故障注入。
- 实际打开代表性公告、角色卡、占位图与多图结果。

### O13 — 第二阶段文档、配置、投影与完整门禁 `[pending]`

- 更新 cache/resource/announcement 配置 schema 和文档。
- 重新生成相关投影，运行完整 pytest、ruff、compileall。
- 验证 data_dir 边界、无插件目录运行期写入。

### O14 — 公共资源仓库独立版本与审查 `[pending]`

- 对公共资源仓库做 manifest、许可证/来源、秘密与可解码性审查。
- 形成独立资源 commit SHA；插件只引用已验证版本。
- 使用 `code-review-expert` 审查插件第二阶段改动并修复阻塞项。

### O15 — 第二阶段插件 SHA、atri 热重载与视觉验收 `[pending]`

- 形成第二阶段独立插件 SHA，记录上一稳定 SHA。
- 按 `plan.md §4.2` 部署、定向 reload、核对资源 active pointer 与后台任务单例。
- 运行缓存/刷新/公告 adapter E2E，复制并实际查看所有代表性图片。

### D05 — 调试审查 O13–O15 `[pending]`

- 核对资源 SHA、插件 SHA、生产 active pointer、缓存 metadata 与清理结果一致。
- 检查热重载后 downloader、cleanup loop、公告 scheduler 是否重复。
- 做一次受控失败回滚演练并记录恢复证据。

## 第三阶段：Agent Tools

### O16 — 可复用领域查询层与 AstrBot 工具适配边界 `[pending]`

- 先写工具与聊天命令共享领域 use case 的 Red 测试，避免复制 handler 逻辑。
- 建立 typed request/result 与 `AstrAgentContext.event` 身份提取。
- 验证本地 4.27.1/生产 4.27.4 API 差异并做最小兼容。

### O17 — 纯查询工具、JSON envelope 与可选图片 `[pending]`

- TDD 注册已批准的玩家、角色、体力、周报、日历、wiki、攻略、兑换码、目录、梦魇、公告和订阅查看工具。
- 默认返回 `ok/kind/data/cache/error` JSON。
- `send_image=true` 时直接发给当前用户，工具结果只返回 `image_sent`，不泄露本地路径。

### O18 — 签到工具、明确确认、幂等与生命周期 `[pending]`

- TDD 实现原始消息肯定意图/否定排除、消息 ID 幂等、当前用户当前 UID 限制。
- 使用 fake transport 验证签到，不执行真实签到。
- `agent_tools.enabled` 控制全部注册；initialize/terminate 与热重载无重复工具。

### D06 — 调试审查 O16–O18 `[pending]`

- 针对身份伪造、prompt 注入、模型伪造确认、工具重试和跨用户访问做负向测试。
- 检查所有写工具是否仅剩经批准的签到，且无管理/账号/订阅写操作。
- 核对图片发送失败不会伪装为成功。

### O19 — 第三阶段文档、配置与完整门禁 `[pending]`

- 更新 Agent Tools 列表、参数、返回契约、身份与签到安全说明。
- 更新配置 schema，验证关闭总开关时零工具注册。
- 运行完整 pytest、ruff、compileall。

### O20 — 第三阶段审查与独立 SHA `[pending]`

- 自审并使用 `code-review-expert`，修复阻塞问题。
- 形成第三阶段独立插件 SHA，记录第二阶段稳定 SHA。
- 准备工具 adapter 模拟与回滚清单。

### O21 — 第三阶段 atri 热重载与工具验收 `[pending]`

- 按 `plan.md §4.2` 精确 SHA 部署和定向 reload。
- 验证工具只注册一次、身份来自事件、查询 JSON 正确、可选图片能直接发送。
- 签到只使用 fake transport/模拟，不触发真实副作用。

### D07 — 调试审查 O19–O21 `[pending]`

- 检查生产日志、工具枚举、handler/scheduler 与缓存任务是否重复或残留。
- 运行跨用户、否定意图、重复消息、图片失败与关闭开关回归。
- 阶段三不稳定时回滚第二阶段 SHA。

## 跨阶段收尾

### O22 — 跨阶段兼容与回滚链审计 `[pending]`

- 验证三个插件 SHA 和资源 SHA 均可追溯。
- 验证阶段一←二←三逐级回滚不会破坏配置、数据库、资源 pointer 或缓存 metadata。
- 检查迁移/兼容代码没有静默吞错或伪造空成功。

### O23 — 全量质量与视觉审计 `[pending]`

- 运行完整 pytest、ruff、compileall 与生成物一致性检查。
- 运行全量 adapter 模拟矩阵。
- 打开并检查帮助、公告、角色面板、周报、占位退化和 Agent 发送图片。

### O24 — 最终文档、生产冒烟与交付记录 `[pending]`

- 更新最终用户、管理员、部署、回滚、缓存与 Agent Tools 文档。
- 在 atri 对最终稳定 SHA 做只读状态核验与获授权的最小冒烟。
- 汇总实际完成、测试证据、生产 SHA、已知风险与回滚点。

### D08 — 最终调试审查 O22–O24 `[pending]`

- 逐条对照 `input.md`、`plan.md` 与所有显式验收条件，不能用“未发现问题”代替完成证据。
- 确认没有待修阻塞项、秘密泄露、运行期源码目录写入或未验证的生产假设。
- 只有全部证据成立时才允许将未来的实现目标标记完成。
