# 命令

当前 `rewrite/v0.1` 只注册真正实现的 `帮助`。命令声明位于
`src/modules/index.py` 引用的模块中，`commands.json` 是由
`scripts/generate_commands_manifest.py` 生成的可审阅清单；发送 `帮助` 查看同一
registry 的帮助文本。

未迁移的 legacy 命令仍保留在重构区作为参考，但不会被新入口注册或展示。历史完整
清单和原行为见 `legacy-reference` 分支及 `docs/porting/`。

## 清单字段

每条命令由 `CommandSpec` 提供：`id`、`pattern`、`group`、`name`、`description`、
`examples`、`permission`、`use_case`。registry 会校验权限、正则、示例、重复 id/
pattern 和重复模块加载。

## 权限

- `user`：AstrBot `PermissionType.MEMBER`。
- `admin`：AstrBot `PermissionType.ADMIN`。
- `owner`：当前沿用 AstrBot 公共 `ADMIN` 边界；bot-owner 专属语义待对应 use case 迁移时实现。
