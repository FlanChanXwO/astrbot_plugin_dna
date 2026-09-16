---
name: pr
description: 为本仓库创建、更新和验收 Pull Request 的标准流程。用户要求创建、提交、更新、修复 PR，推送分支供审查，修正 PR 模板或检查清单，或确认 PR 是否准备好合并时使用。强制读取目标分支当前 PR 模板，核对实际 diff 与验证证据，按模板生成正文，并在创建后复查 GitHub 上的实际 PR、可合并状态和 CI。
---

# PR

把 PR 当作可验证的交付物，不是 `git push` 的附带步骤。始终 template-first：正文结构来自目标分支当前 `.github/PULL_REQUEST_TEMPLATE.md`，事实来自实际 diff 和实际验证结果。

## 1. 固定 base、head 与范围

1. 读取适用的 `AGENTS.md`，再确认用户要求、目标分支、当前分支和工作区状态。
2. 默认以仓库主分支为 base；只有用户明确要求 stacked PR，或当前改动确实依赖尚未合并的分支时才使用其他 base。
3. 检查 `base...HEAD` 的 commits、完整 diff、diff stat 和未提交文件，移除与本次目标无关的改动。

完成条件：能明确说出 `base <- head`、本 PR 的单一目标，以及所有 changed files 为什么属于该目标。

## 2. 读取目标分支 PR 模板

在写 PR 正文前读取 **目标分支当前版本**的 `.github/PULL_REQUEST_TEMPLATE.md`。不要复制旧 PR 正文，不要把本 skill 当作模板缓存。

- 保留模板的标题顺序、非破坏性 checkbox 和完整 Checklist。
- 可以删除纯指导用途的 HTML comment，也可以保留；不能删除其对应的结构。
- 不用自定义的同义标题替换模板标题，也不要把模板 section 改造成另一套报告格式。
- 需要补充依赖关系、迁移说明或风险时，放进最接近的模板 section 内；除非模板本身要求，不新增平行的顶层 section。

完成条件：正文骨架与目标分支模板一一对应。

## 3. 验证实际改动

先验证，再写“验证结果”。至少执行：

1. `git diff --check`。
2. `AGENTS.md` 针对该类改动要求的最具体测试和 lint。
3. 涉及入口、配置、持久化、生命周期、公共资源或跨领域行为时，运行完整 pytest。
4. 检查依赖变化、生成文件、凭据/日志/数据库等敏感内容，以及与范围无关的文件。

测试存在失败时，区分 **本 PR 新增失败** 与 **base 已存在失败**。只有在干净 base 上复现，或已有同一基线证据时，才能称为 pre-existing；正文列出准确失败用例或检查项，不用“应该无关”代替证据。

完成条件：每一项准备写入 PR 的验证声明都有实际命令、检查或可复查证据支持。

## 4. 提交并推送

- commit 只包含本 PR 范围内的改动。
- 标题与仓库现行惯例一致，优先使用 `type: concise summary`，如 `feat:`、`fix:`、`refactor:`、`docs:`、`test:`、`chore:`、`release:`。
- 推送正确 head branch；不要为了开 PR 顺手改写不相关共享分支历史。

完成条件：远端 head 与本地待提交状态一致，工作区没有漏掉的本次改动。

## 5. 按模板填写正文

正文只能陈述已验证事实：

- 模板第一段写动机和问题，不直接从改动列表开始。
- `Modifications / 改动点` 对应实际 diff，避免写计划中但未实现的内容。
- `Screenshots or Test Results / 运行截图或测试结果` 写实际 Verification Steps、命令和结果；没有截图时直接提供测试/检查证据，不伪造截图。
- 非破坏性 checkbox 只反映用户支持的契约。删除或重命名**私有内部实现**本身不是 breaking change；用户持久化数据、已发布配置格式或明确公开契约不兼容才属于 breaking change。
- Checklist 每一项都必须保留。条件不适用时可勾选并写明 `N/A` 原因；测试项没有证据时不得勾选。
- 不把“CI 之后会跑”写成“CI 已通过”。

在创建 PR 前，把候选正文送入校验器：

```bash
python3 .agents/skills/pr/scripts/validate_pr_body.py \
  --template .github/PULL_REQUEST_TEMPLATE.md \
  --body /path/to/pr-body.md
```

若目标分支模板与当前 checkout 不同，先把目标分支模板取到临时文件，再通过 `--template` 指向它。

完成条件：校验器返回 0，且所有 checkbox 的勾选状态与实际证据一致。

## 6. 创建 PR 后复查实际 GitHub 对象

使用可用的 GitHub integration/API；只有缺少原生集成时才退回 `gh`。

创建后立即重新读取 PR，而不是把 create 命令成功当作完成：

1. 核对 title、base、head、draft 状态和正文。
2. 再次用目标分支模板检查实际 PR body；发现模板缺项就直接更新 PR。
3. 等 GitHub 完成 mergeability 计算后检查是否存在真实冲突。
4. 查看已触发的 CI/checks；区分 queued、in progress、success、failure，不提前宣称通过。
5. stacked PR 要在正文中明确依赖和合并顺序，并在上游 PR 合并后重新检查 base。

完成条件：GitHub 上的实际 PR 与本地意图一致，模板完整，当前 mergeability/CI 状态已核验。

## 7. 汇报

最终至少给出：

- PR URL 与编号；
- `base <- head`；
- changed files / additions / deletions；
- 已执行验证与结果；
- 尚在运行或失败的 CI；
- 已证明的 base 既有失败；
- stacked PR 或其他合并依赖。

没有核验到的信息就写“未核验”或当前状态，不做推测。
