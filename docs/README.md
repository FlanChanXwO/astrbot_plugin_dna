# astrbot_plugin_dnaby 文档

索引页，只放目录与阅读路径，不展开内容。每个概念只在一个最具体文档里出现。

## 阅读路径

- **从零了解** → [porting/design.md](porting/design.md)（移植设计 + 决策）
- **开发流程** → [dev/setup.md](dev/setup.md)、[dev/testing.md](dev/testing.md)、[dev/maintenance.md](dev/maintenance.md)
- **命令、配置、Agent Tools 与资源** → [usage/commands.md](usage/commands.md)、[usage/configuration.md](usage/configuration.md)、[usage/agent-tools.md](usage/agent-tools.md)、[usage/resources.md](usage/resources.md)、[usage/login.md](usage/login.md)、[usage/admin-pages.md](usage/admin-pages.md)
- **架构与数据** → [project/architecture.md](project/architecture.md)、[project/data-model.md](project/data-model.md)
- **移植过程交付物** → [porting/progress.md](porting/progress.md)（当前进度/已知问题）、[porting/plan.md](porting/plan.md)、[porting/review-v0.1.md](porting/review-v0.1.md)、[porting/review-v0.2-debug.md](porting/review-v0.2-debug.md)（账号/隐私集中审查）、[porting/review-v0.3-player.md](porting/review-v0.3-player.md)（玩家矩阵）、[porting/review-v0.3-encyclopedia.md](porting/review-v0.3-encyclopedia.md)（资料矩阵）、[porting/review-v0.3-debug.md](porting/review-v0.3-debug.md)、[porting/review-v0.4-checkin.md](porting/review-v0.4-checkin.md)（签到集中审查）、[porting/review-v0.5-notices.md](porting/review-v0.5-notices.md)（通知集中审查）、[porting/review-v0.6-operations.md](porting/review-v0.6-operations.md)（运维/面板集中审查）、[porting/offline-write-contracts.md](porting/offline-write-contracts.md)（写入型离线契约）、[porting/render-compare-mh.md](porting/render-compare-mh.md)（本地离线渲染对比：密函）、[porting/agent-tools-release-checklist.md](porting/agent-tools-release-checklist.md)（Agent Tools 发布/回滚）、[porting/review.md](porting/review.md)（legacy 审查存档）、[porting/final_report.md](porting/final_report.md)（legacy 最终报告存档）
- **原 GsCore 登录排查档案** → [legacy/](legacy/README.md)（01..09 + 安全设计-存档，来自上游 DNAUID）

资源编辑器的 Cloudflare/GitHub App/Turnstile、required Check、密钥轮换与跨仓回滚 runbook
位于独立编辑器仓库的 [`docs/operations.md`](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/operations.md)，
公共资源数据契约位于 [`docs/resource-contract.md`](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/resource-contract.md)。

## 目录结构

```
docs/
  README.md        # 本索引
  porting/         # 移植设计、计划、评审、最终报告（superpowers 交付物）
  dev/             # 过程：setup / testing / maintenance
  usage/           # 使用：commands / configuration / agent-tools / resources / login / admin-pages
  project/         # 事实：architecture / data-model
  legacy/          # 原 DNAUID 登录排查档案
```
