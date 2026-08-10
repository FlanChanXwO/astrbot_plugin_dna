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
