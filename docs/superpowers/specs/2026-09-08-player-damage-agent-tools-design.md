# 角色伤害计算面板恢复与 Agent Tools 结构化增强设计

日期：2026-09-08  
状态：已完成设计讨论，待实现计划  
目标仓库：`FlanChanXwO/astrbot_plugin_dna`

## 1. 背景

当前插件仍保留二重螺旋官方伤害计算链路的大部分实现：

- APP 登录凭据已经能够在 player transport 边界转换为 legacy `DNAUser`；
- `PlayerTransport.calculate_damage()` 已存在；
- `DnaApiPlayerTransport.calculate_damage()` 已能调用现有 `damage_service.calculate_role_damage()`；
- `DamageCalculation` / `DamageSnapshot` 等领域 DTO 已存在；
- 角色详情 renderer 仍保留伤害区渲染入口及旧计算面板样式。

当前真正断开的部分位于角色详情 use case：正常角色详情只读取角色和武器详情，不再调用伤害计算，并且角色详情缓存显式忽略旧伤害字段。因此本次不需要重写本地伤害公式，也不需要引入第三方构筑计算数据，只需要恢复现有 APP 登录态到官方 H5 计算接口的链路，并把同一份领域结果提供给角色卡和 Agent Tool。

## 2. 目标

本次改动只包含两个目标。

### 2.1 恢复角色计算面板

恢复如下链路：

```text
APP 登录态
    ↓
DnaApiPlayerTransport
    ↓
角色 / 武器详情
    ↓
官方 damage config + calculate
    ↓
DamageCalculation
    ↓
PlayerService 统一详情结果
    ↓
PlayerRenderer
    ↓
角色详情卡计算面板
```

伤害计算属于角色详情的附加能力，不得成为角色卡成功渲染的前置条件。

### 2.2 增强现有角色详情 Agent Tool

让现有角色详情 Agent Tool 返回可供 LLM 可靠理解的结构化角色详情和官方伤害计算结果，同时继续支持 `send_image=true` 直接发送角色卡。

LLM 可以基于这些结构化事实做聊天层面的解释和分析，但本次不把任何 LLM 生成的评价、建议、练度结论或构筑分析写入渲染卡片。

## 3. 非目标

以下内容明确不属于本次改动：

- 不实现本地伤害计算器；
- 不接入 `dna-builder` 运行时或数据包；
- 不同步或维护第三方 MOD / 角色 / 武器计算数据库；
- 不实现 AI 自动构筑；
- 不实现候选 MOD / 武器替换收益搜索；
- 不实现 LLM 练度评价卡片；
- 不把 LLM 分析文本写入角色面板；
- 不改造 `dna-resource`；
- 不进行全仓库 `dnaby -> dna` 重命名。

全仓库 `dnaby -> dna` 清理已经确定为独立 PR。本次实现应避免顺手做大范围命名修改。若当前 Agent Tool 对外标识仍为 `dnaby_player_role_detail`，本 PR 继续保持该标识；后续重命名 PR 再统一切换到 `dna_player_role_detail`。

## 4. 设计原则

### 4.1 官方结果优先

本次伤害数字只来自官方现有 H5 计算链路。LLM、renderer 和业务层都不得自行推导或重算伤害。

### 4.2 APP-only

伤害计算只复用用户当前已有 APP 登录状态。不得引入第二套 Web/H5 登录、额外 Cookie 或其它登录渠道。

### 4.3 软失败

只要角色详情本身成功，伤害计算失败不能让整张角色卡或 Agent 角色详情查询失败。

```text
角色详情成功 + H5 成功
→ 正常角色卡 + 计算区

角色详情成功 + H5 不支持/失败
→ 正常角色卡
→ 计算区降级或隐藏
→ Agent 仍返回角色详情，并单独表达 damage 状态
```

### 4.4 单一事实来源

角色卡 renderer 和 Agent Tool 必须消费同一个角色详情领域结果，不能分别调用 H5 或分别转换一套伤害结果。

目标关系：

```text
RoleDetailResult
    ├── Renderer
    └── Agent projection
```

从而保证“用户图片中展示的数字”和“LLM 读取到的数字”来自同一 `DamageSnapshot`。

### 4.5 查询工具少而深

本次不新增 `damage_*`、`build_analysis` 等额外 Agent Tool。能力直接增强现有角色详情工具，避免工具数量膨胀及模型调用路径复杂化。

## 5. 模块边界

### 5.1 `src/infrastructure/http/player.py`

职责：官方玩家 API / H5 伤害计算 transport 边界。

继续使用现有：

```text
DnaApiPlayerTransport.calculate_damage()
    ↓
保存的 APP credential
    ↓
legacy DNAUser
    ↓
damage_service.calculate_role_damage()
```

该层负责：

- 读取 APP 凭据；
- 调用官方 damage config 和 calculate；
- 将外部 API 返回转换为 typed player contracts；
- 将网络、凭据、响应结构错误转换为安全的 transport/domain 状态；
- 不向业务层泄露 token、设备码、内部 URL、原始 traceback 或敏感响应正文。

Renderer 和 Agent Tool 不得直接导入或调用 `dna_api`。

### 5.2 `src/modules/player/service.py`

职责：角色详情的唯一编排层。

当前 `_fetch_detail_bundle()` 已读取：

- 角色详情；
- 同律武器；
- 用户显式选择的近战武器；
- 用户显式选择的远程武器。

恢复后，应在详情流程中 best-effort 调用 `PlayerTransport.calculate_damage()`，并组成共享的角色详情结果。

建议引入明确的内部结果对象，例如：

```text
_RoleDetailResult
├── role_detail
├── weapon_sections
├── damage
├── damage_status
├── damage_digest
└── response/render context
```

具体类名可以在实现阶段按现有代码风格调整，但必须满足“角色卡与 Agent 共用同一领域结果”的约束。

建议形成共享入口：

```text
_role_detail_result()
    ├── role_detail()
    └── role_detail_for_agent()
```

`role_detail()` 只取其渲染响应；`role_detail_for_agent()` 则返回同一快照的结构化数据和可直接发送的图片响应。

### 5.3 `src/modules/player/contracts.py`

职责：稳定表达官方伤害计算结果及计算状态。

现有 `DamageCalculation` 仅能表达“有 data”或“有失败 message”。本次需要能可靠区分至少以下状态：

- `available`：官方正常返回可使用的计算结果；
- `unsupported`：官方明确不支持该角色、等级、技能或当前方案；
- `unavailable`：当前缺少可用计算条件，例如没有有效 APP 登录态或必要数据；
- `failed`：网络异常、服务端异常、解析异常等临时失败。

具体可使用 enum + result dataclass，或扩展现有 `DamageCalculation`。要求：

- 成功时必须有 `DamageSnapshot`；
- 非成功时不得伪造数字；
- 对外只暴露规范化、安全的状态和必要的简短信息；
- 不把外部接口原始错误正文直接透传给 Agent 或图片。

### 5.4 `src/infrastructure/rendering/player.py` 与 damage renderer

职责：只消费领域结果并绘制。

现有角色详情 renderer 已保留伤害区入口，旧 `draw_role_damage_section()` 仍可复用。Renderer 不负责：

- 登录；
- H5 请求；
- 重试策略；
- 缓存策略；
- LLM 分析；
- 本地伤害计算。

规则：

```text
damage available
→ 渲染完整计算区

damage unsupported
→ 不渲染错误数字；允许轻量提示“当前角色暂不支持伤害测算”

damage unavailable / failed
→ 默认隐藏计算区或做极轻量降级
→ 不影响角色卡其它部分
```

图片中不得展示原始 API 错误、内部 URL、凭据相关信息或 traceback。

### 5.5 `src/modules/agent_tools/queries.py`

职责：把共享角色详情快照投影成安全、稳定、可核验的结构化数据。

当前 `player_overview` 已有专门的结构化投影，而 `player_role_detail` 主要直接复用角色详情响应。本次应补齐角色详情的结构化 projection，例如新增：

```text
build_player_role_detail_data(...)
```

并让角色详情 Agent query 返回 `AgentQueryPresentation`：

```text
AgentQueryPresentation
├── data            # structured JSON
└── direct_response # 与用户角色卡相同的图片响应
```

Agent 层不得重新调用伤害接口。

### 5.6 `src/entry/agent_tools/tools.py`

职责：定义工具 schema、描述与图片直发能力。

本次不增加新的角色伤害工具，只增强现有角色详情工具描述，明确：

- 返回当前消息用户绑定 UID 的角色详情；
- 结构化数值以工具结果为准；
- 不要从图片猜测数值；
- 不要自行编造或重算伤害；
- 名称不确定时可先使用角色目录；
- `send_image=true` 时可以直接发送对应角色卡。

## 6. Agent Tool 结构化返回

推荐结构如下，字段名称可按现有序列化约定微调，但语义必须稳定。

```json
{
  "type": "player_role_detail",
  "character": {
    "id": 3104,
    "name": "角色名",
    "level": 80,
    "grade_level": 6,
    "element": "元素"
  },
  "attributes": {
    "atk": 1834,
    "max_hp": 12000,
    "max_es": 0,
    "def": 900,
    "max_sp": 100,
    "skill_intensity": 1.2,
    "skill_range": 1.0,
    "skill_efficiency": 1.0,
    "skill_sustain": 1.0,
    "strong_value": 0.0,
    "enmity_value": 0.0
  },
  "skills": [
    {
      "id": 123,
      "name": "技能名",
      "level": 10
    }
  ],
  "traces": [],
  "mods": [],
  "weapons": {
    "con": null,
    "close": null,
    "ranged": null
  },
  "damage": {
    "status": "available",
    "base_attributes": {},
    "final_attributes": {},
    "skills": [],
    "weapons": {},
    "message": null
  }
}
```

### 6.1 角色数据

至少提供：

- 角色 ID；
- 角色名称；
- 等级；
- 溯源/grade level；
- 元素；
- 当前最终面板属性；
- 技能名称与等级；
- traces；
- 当前角色 MOD。

### 6.2 武器数据

对同律、近战、远程武器，若存在则至少提供：

- ID；
- 名称；
- 等级；
- 技能等级；
- 元素；
- 武器面板属性；
- 当前武器 MOD。

### 6.3 Damage 数据

当 `status = available` 时至少提供：

- `base_attributes`；
- `final_attributes`；
- 技能伤害相关字段；
- 普通技能属性；
- 派生/伤害技能属性；
- 近战武器伤害；
- 远程武器伤害；
- 同律武器伤害；
- 环境条件后的对应伤害字段。

非 `available` 状态时不得填充看似有效的伪造伤害值。

### 6.4 Tool 成功语义

角色详情成功即视为角色详情 Agent Tool 成功。

```text
角色详情成功 + damage available
→ tool.ok = true
→ damage.status = available

角色详情成功 + damage unsupported
→ tool.ok = true
→ damage.status = unsupported

角色详情成功 + damage unavailable
→ tool.ok = true
→ damage.status = unavailable

角色详情成功 + damage failed
→ tool.ok = true
→ damage.status = failed
```

只有角色详情本身失败，如未绑定、角色不存在、角色未拥有、基础详情 transport 失败，才由现有 Agent failure envelope 表达整个查询失败。

## 7. 缓存设计

### 7.1 基础详情缓存与 damage 缓存分离

当前代码刻意不把旧 damage 结果写入/恢复为正常角色详情的一部分。本次不应简单将该逻辑反转，而应承认两类数据生命周期不同。

```text
Detail cache
└── RoleDetail + WeaponDetail

Damage cache
└── 官方伤害计算结果
```

原因：

- 角色/武器详情相对稳定；
- H5 可能临时故障；
- 官方 damage config 可能随版本更新；
- 一次临时失败不应该被详情缓存长期固化。

### 7.2 Damage 缓存策略

建议：

- `available`：允许缓存；
- `unsupported`：允许较短 TTL 缓存；
- `unavailable`：不缓存；
- `failed`：不缓存。

Damage cache key 至少要绑定：

- user / UID identity；
- character identity；
- 当前角色详情 digest；
- 选定武器组合；
- 必要时加入 damage schema / panel version。

不得只按角色名缓存。

### 7.3 角色卡缓存必须感知 damage

恢复计算区后，角色卡 cache key 必须额外感知 damage 结果，否则可能持续命中旧的“无计算区”卡片。

建议纳入：

- `damage_digest`；
- `damage_panel_version`。

对于 `failed` / `unavailable` 造成的“无计算区”卡片，不应长期缓存，从而允许下一次请求重新尝试 H5 并恢复计算面板。

### 7.4 刷新语义

`refresh role` 应使当前角色相关的：

- detail cache；
- damage cache；
- detail card cache

一起失效或自然形成新 key，确保刷新后不会继续展示旧 damage。

## 8. 错误处理

### 8.1 角色详情失败

沿用当前 player transport / service 的安全失败规则，角色详情无法取得时整个角色详情请求失败。

### 8.2 伤害计算失败

伤害计算是 best-effort 附加步骤。

伪代码语义：

```python
base_detail = await load_role_and_weapons()

try:
    damage = await calculate_damage(base_detail)
except damage_specific_failure:
    damage = normalized_nonfatal_damage_status

return unified_role_detail_result(base_detail, damage)
```

严禁使用过宽的异常处理吞掉角色详情、缓存、渲染等其它 bug。只应在伤害调用边界捕获已知 transport/domain 失败并转换状态。

### 8.3 不泄露信息

Agent JSON、用户文本、图片、日志不得暴露：

- APP token；
- device/dev code；
- dNum；
- refresh token；
- 内部 API URL；
- 本地文件路径；
- 原始 H5 错误正文；
- traceback。

日志只记录安全的错误类型、规范化 kind、resource 等信息。

## 9. LLM 行为边界

本次增强只提供事实，不新增 LLM 渲染能力。

允许聊天层基于 Agent Tool 数据回答：

- 当前角色基础练度概况；
- 技能伤害高低比较；
- 当前面板中明显的属性差异；
- 当前武器与技能等级事实；
- 官方计算是否可用。

但 LLM 不得被视为伤害权威计算器；所有具体伤害数字必须来自 `damage.status = available` 的官方结果。

本次不向角色卡中加入：

- “练度评分”；
- “毕业度”；
- “短板建议”；
- “AI 推荐词条”；
- “AI 构筑结论”；
- 任何生成式自然语言评价。

这些能力若要进入渲染卡片，必须另开 PR 设计和实现。

## 10. 测试与验收

### 10.1 角色卡测试矩阵

| 场景 | 预期 |
| --- | --- |
| APP 登录有效 + H5 成功 | 正常角色卡 + 完整计算面板 |
| H5 明确不支持角色 | 正常角色卡，不显示错误数字 |
| H5 不支持当前角色/武器等级 | 正常角色卡，damage 为 unsupported |
| H5 网络超时 | 正常角色卡，计算区软失败 |
| H5 5xx / 响应结构异常 | 正常角色卡，不暴露原始错误 |
| 第一次 H5 失败、第二次恢复 | 第二次重新尝试并恢复计算区 |
| 旧 detail cache 不含 damage | 不能永久阻止计算面板恢复 |
| H5 结果变化 | 旧角色卡 cache 不得继续命中 |

最高优先级验收规则：

> 任何伤害计算失败，都不能把原本能够正常显示的角色详情卡打挂。

### 10.2 Agent Tool 测试

验证角色详情 Agent Tool：

- 角色详情成功时始终 `tool.ok = true`；
- `damage.status` 能可靠区分四种状态；
- `available` 时返回完整结构化 damage；
- 非 available 时不伪造数字；
- `send_image=true` 仍可发送与该快照对应的角色卡；
- 不返回任何凭据、URL、本地路径或 traceback。

### 10.3 同源性测试

必须有测试证明 renderer 和 Agent projection 消费同一 `DamageSnapshot` / 统一详情结果，而不是分别请求或分别计算。

目标断言语义：

```text
renderer input.damage
==
agent structured data damage source
```

无需 OCR 或像素识别图片中的文字。

### 10.4 缓存测试

至少覆盖：

1. 基础详情缓存命中时仍可以获取 damage；
2. damage available 结果可以按策略复用；
3. failed 不被长期缓存；
4. unavailable 不缓存；
5. unsupported 可使用短 TTL；
6. damage digest 变化后旧角色卡不再命中；
7. refresh role 能使相关 damage/card cache 失效。

### 10.5 真实 APP 链路验收

单元测试后使用真实 APP 登录态验证至少：

- 一个普通老角色；
- 一个带同律武器角色；
- 一个指定近战/远程武器的角色；
- 一个 7 溯源角色；
- 一个当前版本新角色。

核对：

```text
角色基础卡正常
    ↓
官方 H5 有结果
    ↓
计算区出现
    ↓
技能/武器伤害非空
    ↓
Agent Tool 返回同源结构化数字
```

若当前新角色官方 H5 尚未支持，则：

```text
角色卡正常
damage.status = unsupported
```

同样视为正确行为，不由插件自行补公式。

## 11. 实现顺序建议

后续 implementation plan 应按以下依赖顺序拆分：

1. 扩展/规范化 damage contract 与状态；
2. 完善 player transport 的状态映射；
3. 在 PlayerService 建立共享 role detail result；
4. 恢复 best-effort damage 调用；
5. 调整 detail / damage / card cache 关系；
6. 恢复 renderer 计算区消费；
7. 增加角色详情 Agent 结构化 projection；
8. 增强 Agent Tool 描述；
9. 补充单元、缓存和同源性测试；
10. 执行真实 APP 链路验证。

## 12. 完成定义

本设计对应的实现满足以下条件时可以认为完成：

- 现有 APP 登录态可驱动官方 H5 伤害计算；
- 角色详情卡再次显示现有计算面板；
- H5 失败不会阻断角色卡；
- Agent 角色详情工具拥有稳定的结构化角色/武器/MOD/技能/伤害数据；
- Agent 与 renderer 使用同一领域结果；
- 无敏感凭据或内部实现信息泄漏；
- 缓存不会长期固化临时 H5 失败；
- 不包含本地计算器、AI 构筑或 LLM 卡片评价；
- 不包含全仓库 `dnaby -> dna` 重命名。
