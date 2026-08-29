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

## 三仓本地开发

公共资源、编辑器和插件必须保持独立 checkout：

- 资源仓库：[`astrbot_plugin_dna_resources`](https://github.com/FlanChanXwO/astrbot_plugin_dna_resources)，只放
  manifest、素材、schema 和兑换码 JSON。
- 编辑器：[`dna-resource-editor`](https://github.com/FlanChanXwO/dna-resource-editor)，在其目录执行
  `npm ci`、`npm test`、`npm run typecheck`、`npm run build` 和 `npm run deploy:dry-run`。
- 插件：本目录；资源同步只认规范 GitHub origin 的 `main`，不把本地编辑器代码或任意投稿分支
  放入运行期 generation。

跨仓契约回归由插件的 `tests/test_goal3_task19.py` 创建临时 bare Git 和内容 fixture，并以
`DNA_TASK19_FIXTURE` 调用编辑器的 `npm run test:task19`；它不需要真实 GitHub 写入，也不能替代
真实 App、Turnstile、Webhook 和 required Check 验收。生产发布顺序、权限和回滚见
[维护说明](maintenance.md)及编辑器的 [operations runbook](https://github.com/FlanChanXwO/dna-resource-editor/blob/main/docs/operations.md)。

## HTML/T2I 图片渲染

运行时要求 AstrBot 4.27.1 或更高版本，并启用全局 HTML/T2I 服务。插件通过
`src/infrastructure/rendering/` 将模板和素材交给 `astrbot.core.html_renderer`；不会启动私有渲染服务，
也不会覆盖 AstrBot 已配置的 T2I 地址。T2I、模板、素材或返回值异常会记录完整内部原因，并向命令用户
返回统一的图片渲染失败提示。
