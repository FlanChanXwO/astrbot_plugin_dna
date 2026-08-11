# 命令

当前 `rewrite/v0.1` 注册 `帮助`、账号/UID、玩家查询、资料读取和隐私 use case。命令声明位于
`src/modules/index.py` 引用的模块中，`commands.json` 是由
`scripts/generate_commands_manifest.py` 生成的可审阅清单；发送 `帮助` 查看同一
registry 的帮助文本。

## 当前账号命令

- `登录`、`dna登录`、`DNA登录`、`login`：调用注入的登录页 transport。
- `登录` 加 40 个字符以上 token：执行 token 登录；例如 `登录<token>`。
- `登录手机号,验证码`：执行手机号验证码登录，例如 `登录13800138000,1234`。
- `退出登录`、`登出`、`logout`：退出当前 active UID 的登录。
- `绑定<13位UID>`、`切换<13位UID>`、`删除<13位UID>`：管理单个 UID。
- `删除全部UID`、`查看UID`：删除全部或查看当前作用域的绑定。
- `获取ck`、`获取Token` 等别名：只查询 App/Web 凭据保存状态，严格不返回原始凭据。

默认 runtime 的账号 transport 没有内置登录页 provider 时，`登录` 会返回明确的
服务未配置错误；不会发送一个不存在的链接。测试使用 fake transport，部署集成需注入
实际的页面/外部登录服务。

## 玩家查询命令

- `查询`、`卡片`、`角色`、`信息`：读取当前 UID 的角色、近战武器和远程武器总览。
- `<角色名>面板`、`<角色名>信息`、`<角色名>详情`、`<角色名>面包`、`<角色名>🍞`：读取
  角色属性、技能、溯源、魔之楔、武器和伤害结果；可追加一把近战和一把远程武器，
  例如 `角色名面板 +近战名 +远程名`。
- `原图`：设计上引用角色详情图后读取对应的原始面板图。私有资源根可提供
  `panel/<角色 ID>.png`，但 AstrBot 公共结果边界仍没有已发送消息 ID 的登记点；它目前
  只有离线缓存契约，不能作为可用的平台回复功能。详见
  [v0.3 集中审查](../porting/review-v0.3-debug.md)。

玩家图片由 `ImageResponse` 交给 AstrBot 公共 `image_result`，实际 PNG 写入
`StarTools.get_data_dir("astrbot_plugin_dnaby")/rendered/`。概览/详情渲染保留所有
合法角色、武器、技能、魔之楔和伤害字段；图片 PNG 元数据只用于离线布局/资源语义回归。
合成 `rendered/*.png` 只会在本次事件中登记到 AstrBot 的临时文件生命周期；运行期资源中的
原图、wiki 和攻略图片不会被登记为临时文件。
真实账户只读矩阵留待后续阶段，见 [v0.3 玩家行为矩阵](../porting/review-v0.3-player.md)。

## 资料读取命令

- `每日`、`mr`、`便笺`、`体力`、`日常` 等：读取实时便笺和锻造状态。
- `周报`、`本周周报`、`上周周报`：读取对应周期的资源获取统计。
- `日历`：读取活动日历；它不读取或修改账号数据。
- `<名称>图鉴`、`<名称>wiki`：按角色、武器或魔灵的运行期资源索引返回图鉴图片。
- `<角色名>攻略`：按已配置的攻略作者返回单图，或每位作者一条文案后跟随其全部图片的消息链。
- `兑换码`、`cdk`、`code`：读取 provider 中所有有效兑换码；不同截止时间会与各自兑换码一同显示。
- `<角色/武器名>别名`：查看只读别名列表，沿用 legacy 的 `owner` 权限。
- `角色列表`、`武器列表`：查看运行期资源中已索引的 canonical 名称，使用 `user` 权限。

资料读取的图片与索引只使用
`StarTools.get_data_dir("astrbot_plugin_dnaby")/resources/` 和 `rendered/`，不从插件源码目录
写入或下载素材。图像语义、已知差异和 fixture 边界见
[v0.3 资料查询行为矩阵](../porting/review-v0.3-encyclopedia.md)。

资源同步后的完整目录已接入玩家与百科 renderer；metadata 会把实际读取到的素材标为
`provided`，缺失素材标为 `placeholder` 或 `fallback`。这仍不等于真实私有资源或视觉输出
已验收，Task 30 必须保留该差异结论。

## 隐私控制命令

个人命令（`user` 权限）：

- `开偷窥`、`关闭偷窥防护`：允许他人查看自己的游戏信息。
- `防偷窥`、`开启偷窥防护`：禁止他人查看自己的游戏信息。
- `隐藏UID`、`隐藏uid`：隐藏自己的 UID。
- `显示UID`、`显示uid`：显示自己的 UID。

群管理员命令（`admin` 权限，必须在群聊使用）：

- `指定开偷窥`、`指定防偷窥`：对消息中被 `@` 且已绑定 UID 的目标设置偷窥权限。
- `全体开偷窥`、`全体防偷窥`、`取消全体偷窥`：设置、关闭或取消群组偷窥强制策略。
- `指定隐藏UID`、`指定显示UID`：对被 `@` 且已绑定 UID 的目标设置 UID 显示策略。
- `全体隐藏UID`、`全体显示UID`、`取消全体UID隐藏`：设置、关闭或取消群组 UID 强制策略。

群强制策略按字段优先于个人设置；个人命令在相应强制策略存在时会返回原因且不写入。
未迁移的 legacy 命令仍保留在重构区作为参考，但不会被新入口注册或展示。历史完整清单
和原行为见 `legacy-reference` 分支及 `docs/porting/`。

## 清单字段

每条命令由 `CommandSpec` 提供：`id`、`pattern`、`group`、`name`、`description`、
`examples`、`permission`、`use_case`。registry 会校验权限、正则、示例、重复 id/
pattern 和重复模块加载。

## 权限

- `user`：AstrBot `PermissionType.MEMBER`。
- `admin`：AstrBot `PermissionType.ADMIN`。
- `owner`：当前沿用 AstrBot 公共 `ADMIN` 边界；bot-owner 专属语义待对应 use case 迁移时实现。
