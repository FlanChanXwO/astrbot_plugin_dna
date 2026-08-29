# 公共资源

运行期资源位于 AstrBot 的插件数据目录下：
`StarTools.get_data_dir("astrbot_plugin_dnaby")`。插件源码目录的 `data/` 不承担运行期资源
写入；`resources/` 只作为 Git 增量传输缓存，已发布运行期快照位于同级的
`resource_generations/<commit-sha>/`，当前 generation 由 `resource_generations/current.json`
原子指针标识。

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
- 首次同步先执行 `git clone --depth 1 --single-branch --branch main --no-tags`，再显式
  `fetch --no-tags origin main`；已有 checkout
  先确认当前为 `main`、origin、干净状态，再只 fetch `origin/main`。
- fetch 得到的 `FETCH_HEAD` 会先导出为临时 archive，校验 manifest、别名、兑换码及 schema、
  图片/字体文件头和完整运行期索引；候选通过后才以 `merge --ff-only FETCH_HEAD` 更新缓存，
  并原子发布对应的 `resource_generations/<commit-sha>/`。
- Git 缺失、认证/远端错误、origin 不一致、非快进、候选无效或本地有修改时直接报告失败，
  当前已验证 generation 保持不变。
- 加速镜像不支持 Git smart HTTP 时直接报告失败，不改走 ZIP、不静默直连；本地修改必须由部署者自行处理。

## Generation 与无停机热刷新

发布成功后 bootstrap 会一次性替换玩家、图鉴、签到、密函和别名的读取资源视图，新请求无需
重启即可使用新版本。renderer 在一次读取开始时取得 generation lease，并在渲染结束后释放；
热刷新期间旧 generation 会保留到最后一个 lease 释放。Wiki/攻略的直出图片会在 lease 内复制到
受控 `rendered/`，再交给事件生命周期清理，避免响应返回后源 generation 被删除。

进程重启时只加载 `current.json` 指向的已验证 generation，并清理同目录下未被当前指针引用的
generation、candidate 和 archive 临时物；不会扫描、删除或迁移 `panel_custom/`、数据库和订阅文件。

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
AstrBot 当前事件的临时文件生命周期清理。generation 内的 `panel/`、`wiki/`、`guide/` 等源
资源不会直接登记为临时文件；需要直出时复制出的响应图片属于 `rendered/` 临时物。
