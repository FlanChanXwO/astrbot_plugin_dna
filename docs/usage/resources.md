# 公共资源

运行期资源位于 AstrBot 的插件数据目录下：
`StarTools.get_data_dir("astrbot_plugin_dnaby") / "resources"`。插件源码目录的
`data/` 不承担运行期资源写入。

资源内容由公共 Git 仓库 `FlanChanXwO/astrbot_plugin_dna_resources` 提供。仓库根目录必须有：

```json
{
  "format_version": 1,
  "required_dirs": [
    "fonts", "images", "panel", "alias", "wiki/role", "wiki/weapon",
    "wiki/spirit", "guide", "weekly_item", "calendar"
  ],
  "resource_version": "2026.08.11"
}
```

`required_dirs` 必须包含上述运行期布局；插件会校验目录均存在且不能通过相对路径逃逸仓库
根目录。同步器和 bootstrap 都会拒绝已有但缺少/未声明该布局的资源根，不能把一次不完整
同步当作可用资源。`resource_version` 只作为经过校验的资源版本返回。

目录约定如下：

- `fonts/dna_fonts.ttf`：玩家和资料 renderer 共用的字体；缺失时图片 metadata 标为
  `fallback`，而不会回退读取插件源码字体。
- `images/<kind>/<key>.<ext>`：玩家角色头像、武器、技能、魔之楔和立绘；renderer 以
  `kind:key` 查找，并在缺失时记录 `placeholder`。
- `panel/<角色 ID>.<ext>`：角色详情关联的原始面板资源；它只提供资源路径，不等同于
  已实现平台回复引用。
- `alias/`、`wiki/{role,weapon,spirit}/`、`guide/<作者>/`、`weekly_item/` 与 `calendar/`：
  分别供别名、图鉴、攻略、周报和日历索引使用。

资源根不存在时，插件仍可启动：图片 renderer 会明确输出 `placeholder`/`fallback` metadata，
资料命令对缺失图鉴或攻略返回未找到。资源根存在但 manifest 不完整时则显式失败，便于部署者
修正同步结果。

同步规则：

- 规范 origin 始终是 `https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git`；
  镜像只通过当前 Git 子进程的 `url.*.insteadOf` 配置替换请求，不改写本地 origin。
- 目标目录不存在时执行 `git clone --depth 1 --single-branch --branch main --no-tags`。
- 目标目录存在时先确认当前 checkout 为 `main`、origin 和
  `git status --porcelain --untracked-files=all`，再执行
  `git pull --ff-only --no-tags origin main`；不会抓取 tags 或其他投稿分支。
- Git 缺失、认证/远端错误、origin 不一致、非快进、manifest 无效或本地有修改时直接报告失败。
- 加速镜像不支持 Git smart HTTP 时直接报告失败，不改走 ZIP、不静默直连；本地修改必须由部署者自行处理。

资源仓库为公开仓库；插件仍只通过 manifest + Git fast-forward-only 同步接口读取，
不在资源仓库中保存账号凭据或其他运行期私有数据。

## 运行期数据目录边界

除 `resources/` 外，插件运行期数据目录还包含（均不可提交到 Git）：

- `dnaby.sqlite3` — SQLAlchemy 2 async 数据库（账号绑定、凭据、隐私、签到记录）。
- `subscriptions.json` — 订阅存储；`ann_state.json` — 公告轮询已知 id。
- `scheduler_state.json` — 内置任务永久删除 tombstone；`alias_custom.json` — 角色自定义别名覆盖层。
- `rendered/` — 玩家/资料/通知 renderer 生成的临时 PNG。
- `panel_custom/` — admin 上传的自定义面板图（WebP，按内容 sha1 去重）；它是本地数据
  目录，与资源仓库的 `panel/`（只读原始面板）分离。

玩家和资料 renderer 生成的 `rendered/*.png` 会在响应边界确认其位于受控渲染目录后，交给
AstrBot 当前事件的临时文件生命周期清理。`panel/`、`wiki/`、`guide/` 等资源文件不会被
登记为临时文件，也不采用无依据的保留时长或数量限制。
