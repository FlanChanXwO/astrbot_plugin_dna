"""便签、周报、日历和静态资料查询领域。

领域子模块不在包初始化时互相导入，避免 rendering/http 通过 contracts 导入本包时
形成循环；调用方按需从 ``contracts`` 或 ``service`` 导入公开类型。
"""
