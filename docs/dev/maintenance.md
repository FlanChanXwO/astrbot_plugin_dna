# 维护

## 改动同步

改命令清单（`commands.json`）、配置（`src/infrastructure/config/`）、登录链路
（`src/modules/account/`）、数据结构（`src/infrastructure/persistence/`）或管理页时，
同步更新最具体的 `docs/usage/`、`docs/project/` 文档。`docs/porting/` 与 `docs/legacy/`
是历史移植/排查存档；判断当前行为时以 `docs/project/` 和 `docs/usage/` 为准。

## 运行期数据与备份

插件运行期数据必须位于
`StarTools.get_data_dir("astrbot_plugin_dnaby")`，重点文件包括：

- `dnaby.sqlite3`：账号绑定、凭据、隐私和签到记录；其中凭据是明文敏感数据。
- `subscriptions.json`、`ann_state.json`：订阅与公告轮询状态。
- `scheduler_state.json`：任务永久删除 tombstone。
- `alias_custom.json`、`panel_custom/`：角色自定义别名与自定义面板图。

在首次执行 `0003_global_identity`、升级插件版本、执行全局账号删除，或需要执行永久任务/面板
删除前，应先停止 AstrBot 或至少停止 DNABY 的写入，再把 SQLite 和需要保留的 JSON/目录复制到
受控备份目录。备份目录必须限制权限，因为其中可能包含 Cookie、token、refresh token、设备码
和 d_num；备份文件名、日志和工单不得复制这些值。

可按实际部署路径执行以下检查式流程（`DATA_DIR` 和 `BACKUP_DIR` 仅为占位符，不能照抄到生产）：

```bash
test -f "$DATA_DIR/dnaby.sqlite3"
mkdir -p -- "$BACKUP_DIR"
cp -p -- "$DATA_DIR/dnaby.sqlite3" "$BACKUP_DIR/dnaby.sqlite3"
for item in subscriptions.json ann_state.json scheduler_state.json alias_custom.json; do
  test ! -e "$DATA_DIR/$item" || cp -p -- "$DATA_DIR/$item" "$BACKUP_DIR/$item"
done
test ! -d "$DATA_DIR/panel_custom" || cp -a -- "$DATA_DIR/panel_custom" "$BACKUP_DIR/panel_custom"
```

上述命令只建立副本，不代表备份已经可恢复；部署者还应记录代码版本、迁移前 schema 版本、
备份路径和校验结果，并在受控环境验证副本可读。不要把备份提交 Git、上传到 issue 或粘贴到
聊天记录。

## 破坏性迁移与回滚

`0003_global_identity` 会删除并重建 `account_bindings`、`credential_records`、
`privacy_settings`、`group_privacy_settings` 四张旧表；旧账号、凭据、个人隐私和群隐私行
不会迁入，新迁移只保留 `sign_records`。因此：

1. 先停写并完成 `dnaby.sqlite3` 备份，再审查旧 `0002` schema 的重复全局隐私行。
2. 使用与插件版本匹配的 Alembic 配置执行 `upgrade head`；迁移失败时保留原错误并停止部署，
   不把旧 `dnaby.db` 改名后交给新 schema，也不把 `create_schema_for_tests()` 当作生产迁移。
3. 升级后检查新 schema、插件启动和最小管理/命令路径；不要期待四张被清空的表自动恢复。
4. 若必须回退，停止新版本，使用普通 revert 或部署旧版本代码，并同时恢复与旧代码匹配的迁移前
   `dnaby.sqlite3` 备份；不能只回退代码、只执行 `downgrade`，或让旧代码直接读取新 schema。
5. 恢复后重新检查任务、订阅、别名和面板目录。回退数据库会丢失迁移后写入，需在变更记录中明确。

`downgrade` 只恢复旧的空表结构，不恢复被 `0003` 丢弃的数据。代码回滚禁止 `reset --hard`、
force push 或删除分支；应保留失败版本、备份和回滚记录，便于复盘。

## Dashboard 管理操作

管理页只通过已认证的 AstrBot Dashboard 入口使用。账号详情会显示全部 App/Web 明文凭据，
属于高风险操作：使用受控管理员浏览器，避免截图、录屏、剪贴板复制和浏览器扩展采集；操作完成
后关闭编辑器并确认页面不再保留 secret。`no-store` 只约束管理 HTTP 响应缓存，不能防止屏幕或
宿主环境记录。

全局账号删除前必须保存删除预览并完成成员扫描；扫描结果为 `unknown`、平台不支持或任一群仍
为 `present` 时不得强行绕过安全门禁。全局删除会移除用户绑定、凭据、个人隐私、个人密函订阅
和关联 UID 的签到历史，但不级联群级隐私、群订阅、群结果或通知资源；跨 SQLite/JSON 的部分
失败应按响应中的逐项状态重试。

角色面板图的全删、账号全局删除和任务永久删除均不可通过页面撤销。角色默认别名来自只读资源，
恢复默认只删除 `alias_custom.json` 的自定义追加；需要保留自定义内容时，应在写操作前备份对应
JSON/目录。

## 任务 tombstone 恢复边界

`dnaby_sign_daily`、`dnaby_mh_push`、`dnaby_ann_poll` 可永久删除；
`dnaby_sign_cleanup` 只能暂停/恢复，不能永久删除。永久删除会把任务 ID 原子写入
`scheduler_state.json`，重启后隐藏并跳过该任务，管理 API 不提供恢复。

若误删且确有删除前备份，停止插件后仅能由部署者审核并恢复备份的
`scheduler_state.json`，再重启并核对任务；这属于运维回退，会覆盖该文件之后的 tombstone 变更，
不是页面恢复功能。没有可验证备份时，按不可恢复处理。

## 已知运行限制

- 离群成员扫描和删除前复核只支持 `aiocqhttp`/OneBot V11；其他平台前端按钮预先禁用，后端也
  返回 `unsupported`，不会把能力缺失伪装成用户 `absent`。
- 没有真实账号凭据、可用上游或 T2I 服务时，玩家预览不能作为生产图片验收；离线测试使用隔离
  SQLite、fake transport、fake aiocqhttp 和临时数据目录。
- `subscriptions.json`、SQLite、任务状态和文件目录没有跨存储物理事务；恢复和重试都必须依照
  管理响应逐项核对，不能仅凭“请求返回”推断全部成功。
