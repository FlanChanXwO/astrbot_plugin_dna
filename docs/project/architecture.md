# 架构

## `rewrite/v0.1` 当前骨架

- 入口：`main.py` 仅实现 AstrBot `Star` 适配，以及 `initialize()/terminate()` 对 `src.bootstrap` runtime 的转发。
- 组装：`src/bootstrap.py` 创建一个插件实例的 `PluginRuntime`，不在入口文件编排数据库、网络或业务。
- 生命周期：`src/entry/lifecycle.py` 按声明顺序启动、逆序停止扩展点；异常向上暴露，不伪造成功。
- Web 边界：`src/entry/web.py` 将 `WebRoute` 转换为 `Context.register_web_api`；当前 v0.1 没有业务路由，因此不会注册 Web API。
- 事件/响应边界：`src/entry/event.py` 暂只提供显式空入口；`src/entry/response.py` 集中调用 AstrBot 原生结果构造方法。命令 registry 和 handler 在后续阶段加入。
- 当前阶段：`rewrite/v0.1` 只验证插件加载、空能力初始化/终止、生命周期扩展点和 Web route 适配；旧功能不会在新入口中隐式注册。

## `legacy-reference` 迁移参考

- 旧命令入口：`dnaby/dispatch.py` 的 `MASTER_PATTERN` 与全局分发，后续迁移到显式 `CommandSpec` registry。
- 旧业务包：`dnaby/dna_*/` 与 `dnaby/utils/` 保留在重构区作为分阶段迁移参考；不应由新的 `main.py` 直接编排。
- 旧配置、数据库、订阅和登录模块的迁移边界见 [design.md](../porting/design.md) 与 `goal-1/tasks.md`。
