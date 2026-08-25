# 开发环境与运行

## 前置
- AstrBot runtime：`/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev`（Python 3.12 venv）。
- 插件目录：`data/plugins/astrbot_plugin_dnaby`。

## 依赖
`requirements.txt` 会被 runtime 的 `scripts/astrbot/sync-plugin-requirements.sh` 自动同步安装到 `.venv`。手动安装：
```bash
.venv/bin/pip install -r data/plugins/astrbot_plugin_dnaby/requirements.txt
```

## 启动 / 重载
```bash
scripts/astrbot/start.sh 6196
scripts/astrbot/reload-plugins.sh 6196 astrbot_plugin_dnaby
```

## 数据目录
运行期数据落在 `data/plugin_data/astrbot_plugin_dnaby/`（`StarTools.get_data_dir`），不入 Git。

## HTML/T2I 图片渲染

运行时要求 AstrBot 4.27.1 或更高版本，并启用全局 HTML/T2I 服务。插件通过
`src/infrastructure/rendering/` 将模板和素材交给 `astrbot.core.html_renderer`；不会启动私有渲染服务，
也不会覆盖 AstrBot 已配置的 T2I 地址。T2I、模板、素材或返回值异常会记录完整内部原因，并向命令用户
返回统一的图片渲染失败提示。
