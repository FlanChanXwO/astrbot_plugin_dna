# 维护

## 改动同步
改命令清单（`commands.json`）、配置（`dnaby/dna_config`）、登录链路（`dnaby/dna_user`）、数据结构（`dnaby/utils/database`）时，同步更新 `docs/usage/`、`docs/project/`。

## 回滚
登录/API 相关改动保留 `.bak-<date>` 备份习惯；DB 数据在 `data/plugin_data/`，改动前建议备份。
