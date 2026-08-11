"""玩家查询模块。

实现类通过 ``src.modules.player.service`` 显式导入，避免渲染基础设施为了读取
typed contracts 时触发 service ↔ renderer 循环依赖。
"""
