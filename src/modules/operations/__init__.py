"""面板图管理与资源状态 use case 领域。

领域子模块不在包初始化时互相导入，避免通过 contracts 导入本包时形成循环；调用方
按需从 ``contracts`` 或 ``service`` 导入公开类型。
"""
