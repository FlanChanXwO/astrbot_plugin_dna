# 架构

## `rewrite/v0.1` 当前入口

- 入口：`main.py` 仅实现 AstrBot `Star` 适配、从显式模块索引加载命令，以及
  `initialize()/terminate()` 对 `src.bootstrap` runtime 的转发。
- 组装：`src/bootstrap.py` 创建一个插件实例的 `PluginRuntime`，不在入口文件编排数据库、网络或业务。
- 命令：`src/entry/commands/` 定义 `CommandSpec`、只读 `CommandRegistry` 和 handler
  生成器；`src/modules/index.py` 是唯一显式模块索引。每个 spec 都成为一个独立的
  async-generator class method，并应用 AstrBot 公开的 `filter.regex` 与权限 decorator。
- 输入/输出：handler 将自己的正则 named groups 封装成 `CommandRequest`；use case
  返回框架无关 DTO；`src/entry/response.py` 再转换为 AstrBot 原生 text/chain/image result。
- 清单/帮助：`commands.json` 由 `scripts/generate_commands_manifest.py` 从代码 registry
  生成，帮助 use case 读取同一 registry。未迁移命令不会注册，也不会出现在帮助中。
- 生命周期：`src/entry/lifecycle.py` 按声明顺序启动、逆序停止扩展点；异常向上暴露，不伪造成功。
- Web 边界：`src/entry/web.py` 将 `WebRoute` 转换为 `Context.register_web_api`；当前 v0.1 没有业务路由，因此不会注册 Web API。
- 事件边界：`src/entry/event.py` 暂只保留非命令事件的显式空入口；消息命令由每个
  动态 handler 的 AstrBot 正则过滤器接管。
- 当前阶段：`rewrite/v0.1` 只注册真正实现的 `帮助` use case；旧功能不会在新入口中隐式注册。

## `legacy-reference` 迁移参考

- 旧命令入口：`dnaby/dispatch.py` 的 `MASTER_PATTERN` 与全局分发，后续迁移到显式 `CommandSpec` registry。
- 旧业务包：`dnaby/dna_*/` 与 `dnaby/utils/` 保留在重构区作为分阶段迁移参考；不应由新的 `main.py` 直接编排。
- 旧配置、数据库、订阅和登录模块的迁移边界见 [design.md](../porting/design.md) 与 `goal-1/tasks.md`。
