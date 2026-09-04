# astrbot_plugin_dnaby 文档

这里按使用任务组织文档。普通用户从安装和配置开始即可完成插件使用；贡献者与维护者再阅读开发、架构和历史资料。

## 普通用户

1. [插件 README](../README.md)：安装、首次配置、常用命令和常见问题。
2. [命令说明](usage/commands.md)：完整命令分组、权限和触发规则。
3. [配置说明](usage/configuration.md)：Dashboard 配置项、默认值和调整建议。
4. [账号登录](usage/login.md)：登录方式、transport 选择和排障。
5. [公共资源](usage/resources.md)：资源目录、同步、缓存和缺失资源处理。
6. [Dashboard 管理页](usage/admin-pages.md)：管理员可用的账号、任务、探测和别名操作。
7. [Agent Tools](usage/agent-tools.md)：可选的结构化查询工具与签到安全边界。

## 贡献者与维护者

- [开发环境](dev/setup.md)：本地目录约定、依赖安装和基础检查。
- [测试说明](dev/testing.md)：测试范围、运行方式和 AstrBot 集成边界。
- [维护说明](dev/maintenance.md)：运行期数据、备份、升级和回滚操作。
- [运行期用户文案](dev/i18n.md)：文案目录、兼容层和加载失败约束。
- [项目架构](project/architecture.md)：入口、模块和基础设施边界。
- [数据模型](project/data-model.md)：持久化实体和状态关系。

## 维护者历史资料

以下内容记录历史设计、迁移决策和专项审计，不是普通用户的安装或配置指南；判断当前使用行为时，以根目录 README 和“普通用户”部分的文档为准。

- [移植设计](porting/design.md)
- [移植计划与进度](porting/plan.md)、[进度记录](porting/progress.md)
- [阶段评审记录](porting/review.md)、[版本与领域评审](porting/review-v0.1.md)、[账号与隐私评审](porting/review-v0.2-account.md)、[调试评审](porting/review-v0.2-debug.md)
- [玩家领域评审](porting/review-v0.3-player.md)、[图鉴领域评审](porting/review-v0.3-encyclopedia.md)、[签到评审](porting/review-v0.4-checkin.md)、[通知评审](porting/review-v0.5-notices.md)、[运维与面板评审](porting/review-v0.6-operations.md)
- [离线写入契约](porting/offline-write-contracts.md)、[渲染对比记录](porting/render-compare-mh.md)、[Agent Tools 发布清单](porting/agent-tools-release-checklist.md)、[最终报告](porting/final_report.md)
- [原登录问题排查档案](legacy/README.md)

## 目录结构

```text
docs/
  README.md        # 本索引
  usage/           # 普通用户使用说明
  dev/             # 贡献者与维护者文档
  project/         # 当前架构与数据模型
  porting/         # 历史设计、迁移和审计资料
  legacy/          # 原登录问题排查档案
```
