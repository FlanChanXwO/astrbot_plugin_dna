# astrbot_plugin_dnaby 文档

索引页，只放目录与阅读路径，不展开内容。每个概念只在一个最具体文档里出现。

## 阅读路径

- **从零了解** → [porting/design.md](porting/design.md)（移植设计 + 决策）
- **开发流程** → [dev/setup.md](dev/setup.md)、[dev/testing.md](dev/testing.md)、[dev/maintenance.md](dev/maintenance.md)
- **命令、配置与资源** → [usage/commands.md](usage/commands.md)、[usage/configuration.md](usage/configuration.md)、[usage/resources.md](usage/resources.md)、[usage/login.md](usage/login.md)
- **架构与数据** → [project/architecture.md](project/architecture.md)、[project/data-model.md](project/data-model.md)
- **移植过程交付物** → [porting/progress.md](porting/progress.md)（当前进度/已知问题）、[porting/plan.md](porting/plan.md)、[porting/review-v0.1.md](porting/review-v0.1.md)（当前重构阶段审查）、[porting/review-v0.2-debug.md](porting/review-v0.2-debug.md)（账号/隐私阶段集中审查）、[porting/review-v0.3-player.md](porting/review-v0.3-player.md)（玩家查询行为矩阵）、[porting/review.md](porting/review.md)（legacy 审查存档）、[porting/final_report.md](porting/final_report.md)（legacy 最终报告存档）
- **原 GsCore 登录排查档案** → [legacy/](legacy/README.md)（01..09 + 安全设计-存档，来自上游 DNAUID）

## 目录结构

```
docs/
  README.md        # 本索引
  porting/         # 移植设计、计划、评审、最终报告（superpowers 交付物）
  dev/             # 过程：setup / testing / maintenance
  usage/           # 使用：commands / configuration / resources / login
  project/         # 事实：architecture / data-model
  legacy/          # 原 DNAUID 登录排查档案
```
