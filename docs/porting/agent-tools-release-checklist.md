# 第三阶段 Agent Tools 发布与回滚清单

本清单起于 O20 的发布前交付物。O20 完成本地审查、adapter 模拟和版本固定，O21
已完成生产定向 reload，D07 又在生产候选上修复了查询异常和图片路径失败边界；本清单
保留这些阶段的精确恢复点，不能用本地 adapter 结果代替生产验收。

## 固定版本

- 第一阶段功能快照插件 SHA：`a97317e1a8c41112fb0220bca941120010076edf`
- 第一阶段生产生命周期修复基线：`6fda2f16b1ebdf3999b95d36609778bf11de38ce`
- 第二阶段稳定插件 SHA：`d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`
- 第三阶段初始插件候选 SHA：`8c7ac4c8ee0910574d2602e41756400ccef0899a`（已被 D07
  修复候选取代）
- 第三阶段已部署/当前恢复候选 SHA：`cb9996dbb36ccaeaca483035c0cbbbc59a8549c9`
  （D07 查询异常与图片文件可用性修复）。
- 第二阶段稳定树到第三阶段候选不是直接祖先链：第二阶段 `d47d37e` 的直接父提交是
  第一阶段生命周期修复基线 `6fda2f1`；第三阶段候选按阶段树构造并经
  `git diff --name-only d47d37e..cb9996d` 审计，未修改 persistence/Alembic、CacheManager
  或资源 generation 实现。当前工作区中的 `goal-1/plan.md`、`pyrightconfig.json`、`goal-2/`、
  `goal-3/` 和 `docs/superpowers/` 不属于上述候选版本。
- 第二阶段资源版本保持不变：资源仓库 commit
  `5d76860141d9ab5052417df25ccc9f5a929ff06b`，资源内容 SHA
  `92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4`。
- 本地兼容基线为 AstrBot 4.27.1，生产目标为 4.27.4；生产步骤不得记录凭据值。

资源版本有三个不同的摘要语义，不能互换：资源 Git commit 是
`5d76860141d9ab5052417df25ccc9f5a929ff06b`，该 commit 的 Git root tree 是
`6cf9d38b417825a27d63f8ecdc5f924fc3eb04ed`，当前 generation `content_sha256` 是
`92796fd40415375a989154fd762dfa61551d5b03b4c9f491638c576318818bc4`。pointer 中的
`generation` 指向 commit，`content_sha256` 校验生成快照内容；`6cf9...` 不是 pointer 的
`content_sha256`。

## Adapter 模拟矩阵

所有测试使用 fake Context、fake `AstrAgentContext.event` 和 fake transport，不执行真实签到、
真实图片投递或生产 reload。

- [x] `agent_tools.enabled=false` 时不调用 `add_llm_tools` 或注销接口。
- [x] 开启时只注册 16 个只读工具和唯一写工具 `dnaby_sign`，名称、顺序和 schema 固定；
  重复 `initialize()`/`start()` 不重复注册。
- [x] `terminate()`/`stop()` 逐项解除 17 个工具；单项注销失败时保留失败项、继续清理，
  后续 stop/start 可重试，并向调用方暴露真实异常。
- [x] 普通用户、群会话、缺失/非法事件身份和模型提供的 `user_id`、`target_user_id`、
  `bot_id`、`credential_user_id`、`uid` 均覆盖；身份只来自当前事件。
- [x] 16 个查询覆盖合法参数、额外参数、未知查询、未绑定/服务失败和固定
  `ok/kind/data/cache/error` JSON envelope；不接入账号、凭据、隐私、订阅修改、资源或
  管理写入口。
- [x] 支持图片的查询覆盖默认不发送、单图/多图成功、事件不支持发送、转换失败和发送
  失败；失败返回 `ok=false`/`image_sent=false`，JSON 不含本地路径或二进制。
- [x] `dnaby_sign` 覆盖明确肯定短语、否定、疑问、信息询问、示例文本和 prompt 指令；
  不接受 `confirmed`、目标或 UID 参数。
- [x] 同一消息 ID 并发调用只执行一次 fake transport，使用当前事件用户的当前激活 UID；
  已绑定、未绑定、凭据/网络/上游失败结果均保持显式且幂等。

建议的本地门禁：

```bash
/Users/flanchan/Developer/Projects/GithubProjects/astrbot-plugin-dev/.venv/bin/python -m pytest -q \
  tests/test_goal1_o16_agent_tools.py \
  tests/test_goal1_o17_agent_tools.py \
  tests/test_goal1_o18_agent_tools.py \
  tests/test_goal1_d06_agent_tools.py \
  tests/test_config_resources.py \
  tests/test_entry_skeleton.py
```

## O21 生产 reload 前置检查

1. 记录生产当前插件 SHA、clean 状态、activated 状态、日志起点、资源 active pointer 和
   配置摘要；不记录 Cookie、token、JWT 或 Dashboard 密钥。
2. 通过已认证的只读接口确认插件 ID 为 `astrbot_plugin_dnaby`、状态正常且凭据具备
   `plugin` scope；插件 ID、权限或工作树不能确认时停止。
3. 在生产插件仓库非破坏性 fetch 后验证候选 SHA 存在，工作树必须 clean；精确切换到
   `cb9996dbb36ccaeaca483035c0cbbbc59a8549c9`，运行 compile/import 和目标 smoke。
4. 只调用已确认的定向
   `POST /api/v1/plugins/astrbot_plugin_dnaby/reload`，同时核对 HTTP 状态、业务状态和
   插件状态；不默认重启容器。
5. 检查旧实例只终止一次、新实例只初始化一次、17 个工具无重复/残留，且 Agent adapter
   模拟仍通过。真实签到保持禁用或使用 fake transport。

## 阶段三失败回滚

发生任何前置、reload、生命周期、工具枚举、adapter 或日志异常时：

1. 停止继续验收，保留失败版本、日志起点和运行期数据；不得 `git reset --hard`、force
   push、删除分支或递归清理插件数据目录。
2. 在生产仓库确认工作树 clean 后，精确恢复第二阶段稳定 SHA
   `d47d37e7c49e618e42aea5e875d7cc2dbf5c4b04`，再调用同一个定向 reload endpoint。
3. 核对插件重新激活、版本/HEAD 正确、Agent Tools 已无残留、scheduler/handler 无重复、
   无新增 traceback，资源 active pointer、数据库、订阅和公告状态保持可读。
4. 运行第二阶段最小 smoke 并记录 HTTP/业务响应；只有恢复稳定状态后才结束回滚。若需
   再次尝试阶段三，重新从候选 SHA 做预检，不跳过失败原因。

回滚只改变插件代码版本，不删除或覆盖 `plugin_data/astrbot_plugin_dnaby` 下的数据库、
凭据、订阅、公告状态、渲染、资源 generation 或自定义面板；若未来阶段引入 schema/数据
迁移，必须另行按维护文档先备份并制定兼容回滚方案。
