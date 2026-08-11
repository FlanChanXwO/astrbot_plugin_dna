# Changelog

## rewrite Task 16.1 — 运行期资源与临时图片生命周期

### Fixed

- 资源 manifest 现要求玩家/百科实际消费的完整目录布局；同步器和 bootstrap 均拒绝已有但
  不完整的资源根。玩家与百科 renderer 从同一私有运行期根加载字体、图片、面板、wiki、攻略、
  别名、周报和日历资源，不再从插件源码读取 legacy 字体。
- 合成 `rendered/*.png` 通过 `ImageResponse.temporary` 交给 AstrBot 当前事件的临时文件
  生命周期；响应边界只登记受控渲染目录内的已生成文件，原图/wiki/攻略资源不会被删除。

### Verification boundary

- 使用隔离资源目录、Pillow、AstrBot 本地 SDK 和 event fixture 验证 manifest、bootstrap、
  provided/placeholder metadata 与事件清理；未创建/同步外部私有资源仓库，未执行真实 NapCat
  或真实账户。
- 资源接线完成不代表实际私有资源或图像视觉差异已经验收；这些结论仍留待 Task 30。

## rewrite Task 14 — 资料读取

### Added

- 增加日常便笺、本周/上周周报、日历、角色/武器/魔灵图鉴、角色攻略、兑换码和只读别名共 9 条
  显式 registry 命令；未迁移的别名写入命令不注册、不展示。
- 增加 `EncyclopediaService`、typed 资料 DTO、legacy API transport、运行期资源索引和动态 PNG
  renderer。便签、周报和日历完整遍历合法资料项，PNG 元数据仅用于离线布局/资源语义审查。
- 兑换码 provider 的每个有效码保留独立截止时间；当日期不同，响应链逐码显示对应截止时间，避免
  只展示首项造成数据丢失。

### Verification boundary

- Task 14 只使用隔离 SQLite、fake transport、临时运行期资源、Pillow 和 AstrBot 本地 SDK 验证；
  未执行真实 gscore 账户读取、真实 NapCat 或任何写入型别名操作。
- 所有资料图片写入运行期 plugin data 的 `rendered/`，资源从运行期 `resources/` 索引读取；不写入
  插件源码目录、参考区或 Git。

## rewrite Task 13 — 玩家角色查询、详情/伤害和原图

### Added

- 增加 `role_info_card`、`role_detail_card` 和 `role_original_image` 三条显式 registry
  命令；角色详情正则、可选武器参数和原图输入保持 legacy 语义。
- 增加 `PlayerService`、typed role/weapon/damage contracts、可注入 fixture transport 和
  legacy 纯 API 适配器；读取链路按隐私策略解析目标用户并从新 SQLAlchemy schema 读取
  当前 UID。
- 增加运行期 PNG renderer、完整列表遍历、动态画布和 `OriginalImageCache`；图片通过
  AstrBot `ImageResponse`/`image_result` 返回，PNG 元数据为离线布局与资源语义审查服务。

### Verification boundary

- Task 13 使用隔离 SQLite、fake player transport、临时图片资源和 AstrBot 本地 SDK 验证；
  未执行真实 gscore 账户读取。真实账户只读命令矩阵由 Task 15 处理。
- 生成图片写入运行期 plugin data 的 `rendered/`；未写入插件源码目录、参考区或 Git。

## rewrite Task 12 — 阶段 3 集中检查-debug

### Fixed

- 登录参数清理恢复 legacy 对空格、换行、制表符和双引号的处理；重复登录收到服务端
  默认角色时会切换到该默认 UID，并在成功文案中优先展示。
- 绑定、切换和删除命令保留 legacy 缺少参数时的 handler 路由，由业务层返回明确错误，
  不再静默无响应。
- SQLite 隐私全局设置增加部分唯一索引，并让同一 runtime 的写事务串行化，避免并发
  upsert 产生重复 `(user_id, bot_id, group_id=NULL)` 记录。
- legacy account transport 将响应结构的 `AttributeError`、`KeyError` 和 `TypeError`
  归类为服务端错误；异常字符串和 repr 仍不包含原始 detail。

### Verification boundary

- 新数据库仍须部署者通过 Alembic 初始化；本地环境未安装 Alembic，migration round-trip
  继续显式 skip，不能把测试 schema 当作生产迁移。

## rewrite Task 11 — 个人/群组隐私 use case

### Added

- 增加个人开关、群强制开关和指定目标隐私命令，共 14 条；群管理员命令由
  AstrBot `PermissionType.ADMIN` 过滤器保护。
- 增加 `PrivacyService` 的个人/群组策略查询、AT 查询解析、目标绑定校验和显式事务写入；
  群强制值按字段优先于个人设置，取消后恢复个人设置。
- 命令 handler 使用 AstrBot 公开消息链的 `At` 组件提取目标，不依赖 legacy `ctx.at`。

### Security

- 指定隐私写入要求群聊、有效 `@` 和目标已有 UID 绑定；个人写入遇到群强制设置时会拒绝且不改变个人记录。
- 隐私写入只在隔离 SQLite 测试中执行；用户可见文案集中在 privacy message 层，未把
  Cookie、token、UID 查询目标或旧消息段类型带入新入口。

## rewrite Task 10 — 账号 use case

### Added

- 增加 typed actor/login/role/credential DTO、可注入账号 transport 和显式错误类别。
- 增加登录、退出、UID 绑定/切换/删除/列表及凭据状态命令；命令清单与帮助均由同一
  registry 生成。
- 增加 normalized account repository CRUD；登录、退出、删除和凭据更新均使用显式
  SQLAlchemy async transaction。

### Security

- 用户响应、异常字符串、DTO repr 和凭据状态查询不返回 Cookie、token、refresh token、
  设备码或 d_num。
- 账号写入只在隔离 SQLite/fake transport 测试中验证；默认 runtime 未配置真实登录页
  provider 时显式报错，不发送伪造地址。

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
