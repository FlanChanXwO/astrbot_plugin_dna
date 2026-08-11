# 命令

当前 `rewrite/v0.1` 注册 `帮助`、账号/UID 和隐私 use case。命令声明位于
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
