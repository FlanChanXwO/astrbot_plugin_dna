# v0.3 玩家查询行为矩阵

> 本文只覆盖 Task 13：角色概览、角色详情/伤害和引用原图。参考实现为
> `legacy-reference` 中的 `dnaby/dna_role`、`dnaby/dna_detail` 与其纯 API/model
> 逻辑；本阶段不读取真实 gscore 账户。

## 命令与读取链路

| legacy key | 输入 | 读取范围 | 输出语义 | rewrite 边界 |
| --- | --- | --- | --- | --- |
| `role_info_card` | `查询`、`卡片`、`角色`、`信息` | 当前/被允许查询的用户、当前 UID、`defaultRoleForTool` | 角色总览图；角色、近战武器、远程武器按配置显示已拥有或完整展柜 | `PlayerService.role_overview` → typed snapshot → `ImageResponse` |
| `role_detail_card` | `<角色名>(面板\|信息\|详情\|面包\|🍞)`，可追加 0–2 个 `+<武器名>` | 展柜、角色详情、同律武器、选定武器、伤害配置/计算接口 | 动态高度详情图，包含属性、技能、魔之楔、武器和伤害结果 | `PlayerService.role_detail` → typed detail/loadout/damage → `ImageResponse` |
| `role_original_image` | `原图` | 引用消息 ID、面板图原图缓存、配置开关 | 返回详情图使用的原始面板图文件 | `OriginalImageCache` → `ImageResponse` |

角色详情的正则、可选武器参数和上述 key 与 legacy 保持一致；`commands.json` 由
rewrite registry 生成，不从旧 `dispatch.py` 扫描。

## 数据与完整输出约束

- `RoleOverview` 保留 API 返回的完整角色、近战武器、远程武器和 `params` 列表。
  `show_unowned_roles=False` 只改变展示过滤，不改变 transport 数据；开启时完整展柜
  都进入渲染。
- `RoleDetail` 保留全部属性、技能、溯源、魔之楔和同律武器标识；详情渲染遍历全部
  合法技能/魔之楔，不沿用 legacy 中为视觉布局写死的 `[:3]` 或固定索引截取。
- `DamageData` 保留服务端返回的全部技能属性、伤害字段和最终/基础属性；伤害接口
  失败以可见文本区块表达，不伪造成功图或吞掉响应原因。
- 每张 rewrite 生成图都写入运行期 `StarTools.get_data_dir(PLUGIN_NAME)` 下的
  `rendered/`，不写插件源码目录。PNG 的 `dnaby.*` 文本块记录画布、布局段、绘制
  文本和资源语义，供测试与后续差异审查使用；这不是用户可见的敏感数据通道。

## 与 legacy 的已知差异

1. AstrBot `image_result` 的公共 API 接收文件路径；rewrite 把图片落到插件运行期
   数据目录后返回路径，替代 legacy `Sender.send(PIL.Image)`。
2. 入口只传递 `EventActor`、目标用户和引用消息 ID；不再把 `EventContext`、`Sender`
   或 `MessageSegment` 传入业务层。服务层把隐私解析出的目标用户作为独立的
   `credential_user_id` 传给 transport，调用者身份仍保留在 `EventActor` 中。原图缓存提供显式 `remember(message_ids, path)`
   接口，后续发送回调可用平台返回的消息 ID登记；未登记的引用会给出可见“未找到”
   响应，不把详情图误当原图。
3. rewrite 默认 transport 只复用 legacy 的纯请求签名、API/model 和伤害计算逻辑，
   真实账户行为留给 Task 15 的只读矩阵；fixture transport 覆盖成功、完整输出和
   服务端失败路径。
4. legacy 对同律武器详情读取失败会继续渲染并省略该段；rewrite 为避免静默丢失合法
   输出，遇到该 transport 错误会返回可见服务错误，不生成可能缺少伤害输入的详情图。

## 图像验证记录格式

Task 13 测试至少核对：

- 响应是 `ImageResponse`，交给 AstrBot 边界的是运行期 PNG 路径；
- PNG 画布尺寸与动态段高度一致，详情布局顺序为角色头部 → 属性/技能 → 武器 →
  魔之楔 → 伤害 → 页脚；
- `dnaby.text` 包含角色名、等级、属性名、技能名、武器名、伤害/错误文案及全部
  合法列表项；
- `dnaby.resources` 记录每个实际请求或使用的角色/武器/技能/面板资源语义；没有
  资源时使用明确的 placeholder 语义，而不是伪造已下载成功。
