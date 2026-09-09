# 开发环境

## 基本要求

插件要求的最低 AstrBot 版本以根目录 `metadata.yaml` 为准；当前声明为 AstrBot `>=4.26.0`。Python 依赖以 `requirements.txt` 为准。

在仓库根目录安装依赖：

```bash
python3 -m pip install -r requirements.txt
```

如果 AstrBot runtime 已负责同步插件依赖，可以使用 runtime 的依赖管理方式，不需要维护第二份依赖清单。

## 常用检查

从插件仓库根目录执行：

```bash
python3 -m compileall .
python3 -m pytest
ruff check .
```

只修改单一领域时可以先运行对应测试文件；准备提交前，应至少运行受影响测试和 `ruff check .`。跨入口、配置、持久化、生命周期或公共资源的改动建议运行完整 pytest。

## 生成文件

命令或配置模型发生变化时，不要手工编辑对应投影：

```bash
python3 scripts/generate_commands_manifest.py
python3 scripts/generate_config_schema.py
```

生成后检查 `commands.json` / `_conf_schema.json` 的差异，并同步更新相关测试与 `docs/usage/`。

## AstrBot 中运行

插件应安装在 AstrBot 的 `data/plugins/astrbot_plugin_dna` 下，并通过 AstrBot 自己的启动、重载或 Dashboard 入口运行。运行期数据库、缓存、登录信息和渲染产物属于 AstrBot 插件数据目录，不应复制回仓库。

图片能力依赖 AstrBot 的全局 HTML/T2I 能力；涉及图片的修改需要在可用的 AstrBot runtime 中额外做一次实际渲染检查。

进一步阅读：[架构](architecture.md) · [测试](testing.md) · [维护](maintenance.md)。
