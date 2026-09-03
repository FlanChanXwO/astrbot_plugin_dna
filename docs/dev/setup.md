# 开发环境与运行

本页面向贡献者和维护者。命令使用占位路径，避免依赖某一台机器的目录结构。

## 目录约定

- **当前项目根目录**：本文件所在插件仓库，记为 `PLUGIN_DIR`。
- **AstrBot 根目录**：包含 `data/plugins/` 的运行时目录，记为 `ASTRBOT_ROOT`。
- **插件目录**：`$ASTRBOT_ROOT/data/plugins/astrbot_plugin_dnaby`。
- **运行期数据**：由 `StarTools.get_data_dir("astrbot_plugin_dnaby")` 返回，不入 Git。

如果从仓库根目录操作，可以先设置：

```bash
export PLUGIN_DIR="$(pwd)"
export ASTRBOT_ROOT="/path/to/astrbot"
```

## 依赖与基础检查

在当前项目根目录执行：

```bash
python3 -m pip install -r requirements.txt
python3 -m compileall .
python3 -m pytest
ruff check .
```

如果 AstrBot runtime 会自动同步插件依赖，可以跳过手动安装。修改命令、配置或渲染代码后，至少
运行受影响测试和 `ruff check .`。

## 启动与重载

启动和重载方式取决于 AstrBot runtime 的安装方式。使用 runtime 提供的启动脚本或 Dashboard
完成操作，不要在插件目录中复制运行期数据库、缓存或登录信息。

重载后先发送当前命令前缀加 `帮助`，再检查 Dashboard 中的插件状态和 AstrBot 日志。

## HTML/T2I 图片

运行时要求 AstrBot 4.26.0 或更高版本，并使用 AstrBot 的全局 HTML/T2I 能力。插件不会启动
私有渲染服务，也不会覆盖 AstrBot 的全局设置；服务不可用时，图片命令会返回统一失败提示。

## 相关文档

- [测试说明](testing.md)
- [维护说明](maintenance.md)
- [配置说明](../usage/configuration.md)
- [公共资源](../usage/resources.md)
