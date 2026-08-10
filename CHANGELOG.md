# Changelog

## v0.1.0 — 2026-08-11

### Changed

- 建立 `src/` 分层入口、显式 `CommandSpec` registry 和真正的异步生成器命令方法。
- 帮助命令从代码 registry 读取，只展示当前已经实现的命令。
- 配置改为按登录、网络、签到、通知和显示分组的 Pydantic typed settings，并由同一份定义生成 `_conf_schema.json`。
- 增加私有 `dnaby_resources` Git 仓库的 manifest 校验和安全同步接口：首次浅克隆，后续只允许 `git pull --ff-only`。
- 增加 SQLAlchemy 2 async + `sqlite+aiosqlite` 五表持久化骨架与 Alembic `0001_initial` revision；新数据库文件为 `dnaby.sqlite3`，凭据 ORM 表示提供脱敏边界。

### Breaking changes

- 这是重构 v0.1 的新入口，历史 55 项命令尚未注册，不会出现在帮助或 `commands.json` 中。
- 不迁移旧 DNAUID/legacy-reference SQLite 数据；新 schema 不会打开旧 `dnaby.db`，请在后续迁移阶段使用新的数据结构。
- 资源仓库需要由部署者在私有 Git 权限可用时提供；本版本不会创建、推送或公开资源仓库。
- 资源同步发现 Git、认证、远端、非快进、manifest 或本地修改错误时会直接失败，不会强制覆盖本地文件。

### Verification boundary

- 本版本仅使用 AstrBot 4.27.x 本地 SDK、fixture 和 staging runtime 验证；不执行真实 NapCat 或真实账号写入操作。
