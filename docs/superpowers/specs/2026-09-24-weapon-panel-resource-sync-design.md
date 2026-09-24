# 武器面板与资源同步稳定性设计

## 背景

当前插件已经具备角色面板、武器详情 API 适配、武器区块渲染、资源 generation/lease 和玩家缓存能力，但缺少独立的武器面板查询入口。

同时，显式资源同步在校验当前 generation 时会暂时把 `self._current` 置为 `None`。素材目录本身仍存在，但并发面板渲染因此拿不到已发布快照，退化到空资源视图并显示 placeholder。

本设计同时解决：

1. 在现有 `名称 + 面板` 语法中智能区分角色和武器，并生成独立武器面板。
2. 以最小改动修复资源同步期间已发布素材暂时不可见的问题。

## 设计原则

- API 返回的正式角色/武器名称是事实源，资源库 alias 仅作为输入便利层。
- 复用现有 PlayerService、PlayerTransport、PlayerRenderer、PlayerCache 和 ResourceSnapshotCoordinator，不新增平行体系。
- 复用现有武器详情 payload、武器图片解析链路和魔之楔布局。
- 新资源只有在完整校验和发布后才被新请求看到；已有已发布 generation 在普通校验期间继续服务。
- 不为假设需求增加兼容层、额外状态机、额外缓存、Wiki 在线抓取或新的资源同步机制。

## 范围

### 包含

- `<名称>面板` 智能判断角色或武器。
- 正式名称优先，alias 补充匹配。
- 独立武器面板查询和渲染。
- 武器面板数据/图片缓存。
- `刷新<名称>面板` 与 `清理<名称>面板缓存` 同样智能判断角色/武器。
- 资源同步期间 placeholder 的最小修复。
- 对新增行为保留必要回归验证。

### 不包含

- 新的武器 API client。
- `wiki/weapon` Wiki 资料图接入玩家武器面板或在线抓取 Wiki 图片。
- 新的 alias 数据结构。
- 新的缓存目录或缓存管理器。
- 新的 generation 状态机或第二套资源快照机制。
- “刷新全部武器”命令。
- `otherUserId` 跨用户武器查询。
- 未验证的 `type=2` 武器详情语义。
- 对现有角色面板视觉进行无关重构。

## 1. 面板查询智能分流

继续保留现有面板命令入口和语法，例如：

- `伊薇面板`
- `flx面板`
- `希冀的丰稔面板`

不增加必须显式输入“武器面板”的第二套主入口。

现有捕获参数即使内部仍命名为 `char_name`，本次也不为变量命名做大范围重构；在分流处把它视为“面板查询词”。

### 1.1 匹配顺序

先使用 `defaultRoleForTool` 返回的真实玩家数据做直接正式名称匹配：

1. `roleChars[].name`
2. `closeWeapons[].name`
3. `langRangeWeapons[].name`

只有直接名称未命中时，再使用现有 `AliasCatalog`：

- `char_alias` 解析为角色 canonical name，再回查 `roleChars`
- `weapon_alias` 解析为武器 canonical name，再回查武器列表

因此 alias 缺失不会让正式名称查询失效。

### 1.2 分流结果

- 仅命中角色：沿用现有角色面板流程。
- 仅命中武器：进入新增武器面板流程。
- 同时命中角色和武器：返回明确歧义提示，不自动角色优先或武器优先。
- 均未命中：返回统一的“未找到角色或武器”类提示。

当前实际 alias 数据没有已知角色/武器重名冲突；歧义分支仅作为真实冲突时的安全行为。

### 1.3 角色附加武器语法

现有角色面板语法继续支持：

`角色面板 + 近战武器 + 远程武器`

如果主查询对象解析为武器，而请求仍附带 `+...` 参数，则明确提示武器面板不支持附加武器参数，不静默忽略。

## 2. 武器数据流

武器面板复用现有玩家 transport，不新增 API 层。

数据流：

1. 解析当前账号和 UID，沿用角色面板现有隐私和绑定逻辑。
2. 获取 `defaultRoleForTool` / `RoleOverview`。
3. 在 `closeWeapons + langRangeWeapons` 中找到目标 `WeaponItem`。
4. 要求 `unLocked=true` 且 `weaponEid` 存在。
5. 调用现有 `get_weapon_detail(weaponId, weaponEid)`。
6. 使用现有 `WeaponDetail` typed model。
7. 渲染独立武器卡。

当前已验证武器详情请求继续使用 `type=1`。不扩展到未验证的 `type=2`。

成功响应但 `weaponDetail={}` 视为详情不存在，而不是有效的零属性武器。

## 3. 独立武器面板渲染

### 3.1 复用现有武器渲染

现有 `draw_weapon_detail_section()` 已经提供：

- 武器图
- 武器名称
- 等级
- 精通/skill level
- 武器类型
- 攻击
- 暴击率
- 暴击伤害
- 攻击速度
- 触发率
- 魔之楔布局
- 现有武器底板、属性底板、属性图标和 Mod 背景

独立武器卡应复用这些字段和素材，不复制第二套属性/Mod 逻辑。

现有 `cri → 暴击率`、`crd → 暴击伤害` 语义保持不变。

### 3.2 模板复用

推荐把角色详情模板中的武器区块抽成可复用 Jinja macro/partial：

- 角色面板继续使用同一组件。
- 独立武器面板使用同一组件。
- 独立武器模板只负责页面级 wrapper、主视觉和必要头部/收尾。

不通过大量条件分支把整个角色详情模板兼作武器模板，也不复制现有武器区块 CSS/HTML。

### 3.3 主视觉

武器主视觉的可靠事实源继续使用当前玩家图片链路：

1. verified generation：`images/weapon/<weapon_id>.png`
2. L2 动态缓存
3. `WeaponDetail.icon` / 上游武器 CDN URL 下载并写入 L2
4. 仍失败时 placeholder + `incomplete=True`

独立武器面板可以比角色详情中的小武器卡更大地展示同一武器图，但不新增新的在线图片来源。

`wiki/weapon/<武器正式名>.webp` 本次不接入玩家武器面板。该目录属于 Wiki 资料资源，首版不为它增加主视觉判定、在线抓取、Wiki API 或单独缓存逻辑；后续只有在素材语义和展示需求明确后再单独设计。

### 3.4 信息密度

首版展示：

- 武器名称
- 等级
- 精通/skill level
- 武器类型
- 攻击
- 暴击率
- 暴击伤害
- 攻击速度
- 触发率
- 魔之楔

首版不为了“信息更全”额外塞入 `description`、`currentVolume`、`sumVolume` 等当前角色武器区块未消费字段。

## 4. 缓存与刷新

继续使用现有 `PlayerCache` 和统一 `CacheManager`。

### 4.1 武器缓存

增加最小的武器数据/卡片 key 与 tag 组合，包含真实影响结果的字段：

- target user
- UID
- weapon id
- overview digest / weapon detail digest
- resource version
- 隐私相关渲染维度（如实际需要）

建议 tag 使用 `weapon:<weapon_id>`，继续复用 identity/resource/data tag。

不新增武器专用缓存目录或缓存管理器。

`incomplete=True` 的武器卡不作为完整成功卡片写入正常卡片缓存，沿用现有玩家卡语义。

### 4.2 刷新与清缓存

`刷新<名称>面板` 和 `清理<名称>面板缓存` 使用与普通面板相同的角色/武器智能分流。

- 角色：沿用现有行为。
- 武器：只刷新/清理目标武器相关数据和卡片。
- `刷新全部角色面板` 继续只处理角色，不隐式扩展到所有武器。

## 5. 错误处理

用户可见错误保持明确且有限：

- 查询词没有匹配：未找到角色或武器。
- 武器存在但未拥有：当前武器暂未拥有，无法查看。
- `weaponEid` 缺失：武器详情未找到。
- `getWeaponDetail` 返回空 `weaponDetail`：武器详情未找到。
- 角色与武器同时命中：名称存在歧义。
- 武器面板携带角色专属 `+...` 参数：明确提示该参数不适用于武器面板。
- 网络/凭证/服务异常：继续走现有 PlayerTransportError 映射，不向用户暴露服务端原文。

## 6. 资源同步期间 placeholder 最小修复

### 6.1 当前问题

`ResourceSnapshotCoordinator.validate_current()` 在开始完整校验当前 generation 时会主动执行：

`self._current = None`

此时物理素材目录仍存在且此前已经发布验证通过，但新面板请求通过 `optional_lease()/bind_renderer()` 无法取得 current，于是得到空资源视图并触发 placeholder。

### 6.2 修复

仅删除“校验开始前主动撤下 current”的行为。

保留现有：

- 完整校验。
- 校验失败后的 `_current = None`。
- validation failure 记录。
- `_begin_generation_repair()`。
- repair 时禁止新 lease。
- 等待旧 lease 释放后再替换同 commit generation。
- 原子发布新 generation。

预期行为：

`旧 generation 正常服务 → 后台同步/校验 → 旧 generation 继续服务 → 校验/物化成功 → 原子切换`

如果校验真正失败：

`旧 generation 正常服务 → 校验发现损坏 → 撤下 current → 进入现有 repair`

不增加第二套“发布态/校验态”状态机，也不增加额外锁、fallback 或复制 generation。

## 7. 验证策略

只保留能覆盖新增行为和实际回归风险的测试。

### 7.1 智能分流

- 正式角色名进入角色面板。
- 正式武器名进入武器面板。
- 武器 alias 进入武器面板。
- alias 缺失但 API 正式武器名存在时仍能正常查询。
- 角色与武器同时命中时返回歧义提示。
- 武器面板附加 `+...` 参数时明确拒绝。

### 7.2 武器所有权与详情

- 已拥有且存在 `weaponEid` 时调用武器详情。
- 未拥有时返回明确提示。
- `weaponEid` 缺失时返回详情不存在。
- 空 `weaponDetail` 不被当作有效数据。

### 7.3 渲染

- `cri/crd` 字段含义不回归。
- 等级、精通、属性和魔之楔进入独立模板。
- generation 武器图缺失但 API icon 可下载时仍正常渲染。
- 图片最终不可用时才 placeholder + incomplete。
- incomplete 卡不进入完整卡片缓存。

### 7.4 资源同步

- `validate_current()` 执行期间，新请求仍可 acquire 已发布 current。
- 校验失败后才撤下 current。
- 现有 repair lease 等待逻辑保持生效。

### 7.5 缓存

- 相同用户/UID/weapon id/detail/resource version 可命中武器卡缓存。
- 刷新单武器只刷新目标武器。
- 清理单武器只清目标武器。
- “刷新全部角色”不扩大到武器。

## 8. 验收标准

完成后应满足：

1. 用户可以直接发送 `<武器正式名>面板` 查询自己已拥有武器。
2. 已维护的武器 alias 可以使用，但 alias 缺失不会影响正式名称。
3. 原有 `<角色名>面板` 和角色附加武器语法保持兼容。
4. 独立武器面板使用现有武器数据、图片下载链路、属性和魔之楔资源。
5. 武器本地图片缺失时，只要 API icon 可用，卡片仍能正常渲染。
6. 资源同步/校验正常进行时，已发布资源继续被面板正常读取，不再仅因同步进入 placeholder。
7. 只有真正校验失败或真实素材不可用时才进入现有错误/placeholder 路径。
8. 本次不引入额外资源同步状态机、额外缓存体系或在线 Wiki 抓取。
