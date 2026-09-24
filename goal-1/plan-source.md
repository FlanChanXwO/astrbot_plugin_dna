# 武器面板与资源同步稳定性实施计划

## 目标

在 `astrbot_plugin_dna` 中完成两项改动：

1. 基于现有 `/role/getWeaponDetail` 接口链路，为 `<名称>面板` 增加角色 / 武器智能分流，并提供完整的独立武器面板查询、缓存、刷新能力。
2. 修复资源同步 / 校验期间 `current generation` 被提前撤下，导致并发面板渲染出现 placeholder 的问题。

同时补齐与角色面板对称的批量操作：

```text
刷新全部武器面板
清理全部武器缓存
```

设计依据：

`docs/superpowers/specs/2026-09-24-weapon-panel-resource-sync-design.md`

> 本计划对已确认设计作一处需求修正：原设计中“不增加刷新全部武器”被本次明确需求取代。实施前应同步更新 design spec，避免 spec 与实现计划冲突。

---

# 一、实施约束

必须遵守以下决策：

- 不新增武器 API transport/client。
- 直接复用：
  - `dna_api.get_weapon_detail()`
  - `DnaApiPlayerTransport.get_weapon_detail()`
  - `WeaponDetail`
  - `RoleOverview.close_weapons`
  - `RoleOverview.ranged_weapons`
- 游戏 API 返回的正式名称优先，alias 仅作为补充输入方式。
- 不要求武器必须装备在角色身上，只要求账号拥有该武器。
- `unLocked=false` 或 `weaponEid` 为空时视为未拥有。
- `weaponDetail={}` 视为详情不存在。
- 武器详情继续使用已经验证的 `type=1`。
- 不使用未验证的 `otherUserId`。
- 不接入 `wiki/weapon` 作为玩家武器面板主视觉。
- 不新增 Wiki 网络抓取逻辑。
- 不新增武器专用缓存系统、目录或 generation。
- 不进行与本功能无关的角色面板重构。
- 资源同步问题只做最小修复，不新建状态机或兼容层。
- 增加：
  - `刷新全部武器面板`
  - `清理全部武器缓存`

---

# 二、阶段 0：同步设计文档

由于需求发生了一处明确变化，实施前先修改：

`docs/superpowers/specs/2026-09-24-weapon-panel-resource-sync-design.md`

删除原来的：

```text
不包含“刷新全部武器”命令
```

补充：

```text
刷新全部武器面板
清理全部武器缓存
```

批量刷新行为与现有 `刷新全部角色面板` 对齐：

- 只处理当前用户当前 UID。
- 获取一次最新 `RoleOverview`。
- 只处理 `unLocked=true && weaponEid != null` 的武器。
- 批量获取 / 写入武器详情数据缓存。
- 不逐张发送全部武器卡，避免消息轰炸。
- 最终只返回成功 / 失败数量及必要失败名称汇总。

批量清理：

- 只清当前 UID 的所有武器详情数据与武器卡片缓存。
- 不清角色详情缓存。
- 不清基本信息卡片缓存。
- 不清公告、签到等其它模块缓存。

---

# 三、阶段 1：修复资源同步期间 placeholder

这是最独立、风险最低的一项，应优先完成。

## 1.1 修改 `validate_current()`

目标文件：

`src/infrastructure/resources/generation.py`

定位：

`ResourceSnapshotCoordinator.validate_current()`

当前问题：

```python
if snapshot is self._current:
    self._current = None
```

该逻辑在**校验开始前**主动撤下已经发布且此前有效的 generation。

修改原则：

- 删除校验开始阶段主动执行的 `self._current = None`。
- 保留校验失败后的 current 撤下逻辑。
- 保留：
  - `_validation_lock`
  - `_state_lock`
  - `_begin_generation_repair()`
  - lease 计数
  - retired generation
  - repair 等待旧 lease
  - 新 generation 原子发布

成功路径：

```text
旧 generation 正常服务
        ↓
开始 validate_current
        ↓
旧 generation 仍可 acquire
        ↓
校验成功
        ↓
继续正常服务 / 原子发布新 generation
```

失败路径：

```text
旧 generation 正常服务
        ↓
校验发现实际损坏
        ↓
撤下 current
        ↓
进入现有 repair
```

## 1.2 最小回归测试

优先修改现有 generation / asset resolver 测试。

至少验证：

- `validate_current()` 未结束时，新请求仍能取得 current snapshot。
- validation 失败后 current 才不可用。
- 已持有 lease 行为保持不变。

不重复已有 generation A → B pinning 等测试。

---

# 四、阶段 2：补齐面板对象智能解析

主要文件：

- `src/modules/player/service.py`
- 必要时 `src/modules/player/commands.py`
- `src/modules/player/messages.py`
- `i18/zh/tip.json`

## 2.1 保留现有普通面板命令正则

继续使用：

```python
ROLE_DETAIL_PATTERN
```

例如：

```text
伊薇面板
flx面板
希冀的丰稔面板
```

全部进入同一 use case。

不要求用户另外输入：

```text
希冀的丰稔武器面板
```

现有 `char_name` 参数可以保留，避免无意义重命名。

## 2.2 增加统一查询对象解析

输入：

```text
query_name
RoleOverview
AliasCatalog
```

内部解析结果只需要表达：

```text
role
weapon
ambiguous
not_found
```

不要为此建立复杂 domain hierarchy。

### 正式名称优先

直接查询：

```python
overview.role_chars
overview.close_weapons
overview.ranged_weapons
```

按 `.name` 匹配。

### alias 补充

直接匹配未命中时再调用：

```python
aliases.resolve_char(query)
aliases.resolve_weapon(query)
```

得到 canonical 后回查 `RoleOverview`。

因此：

```text
alias 未更新
+
API 已返回正式名称
=
正式名称仍然可查询
```

## 2.3 双重命中

角色和武器同时命中：

```text
名称同时匹配角色和武器，请使用更完整的名称
```

不得自动设置优先级。

## 2.4 未命中

角色和武器都找不到时：

```text
未找到该角色或武器
```

避免角色 lookup 提前截断武器查询。

---

# 五、阶段 3：新增独立武器面板 use case

主要文件：

`src/modules/player/service.py`

## 3.1 查询流程

```text
resolve UID
    ↓
load RoleOverview
    ↓
智能解析 query
    ↓
WeaponItem
    ↓
判断 ownership
    ↓
get_weapon_detail()
    ↓
WeaponDetail
    ↓
render weapon panel
```

## 3.2 所有权判断

以下任一成立：

```python
not weapon.unlocked
weapon.weapon_eid is None
```

返回：

```text
当前展柜武器暂未拥有，无法查看
```

不得继续调用详情接口。

## 3.3 获取详情

直接复用：

```python
self.transport.get_weapon_detail(
    actor,
    uid,
    weapon.weapon_id,
    weapon.weapon_eid,
    credential_user_id=...,
)
```

不要增加新的 API client。

## 3.4 空详情

如果没有有效 `WeaponDetail`：

```text
武器详情未找到
```

不得渲染全 0 面板。

## 3.5 `+ 武器` 参数

例如：

```text
希冀的丰稔面板 + 无声的嘶吼
```

主对象已经是武器时直接拒绝：

```text
武器面板不支持附加武器参数
```

---

# 六、阶段 4：独立武器卡渲染

主要文件：

- `src/infrastructure/rendering/player.py`
- `src/infrastructure/rendering/weapon_renderer.py`
- `src/templates/cards/role_detail.html.j2`
- 一个最小独立武器模板
- 必要的 weapon section macro / partial

## 4.1 复用现有 payload

继续使用：

```python
draw_weapon_detail_section()
```

作为以下内容的事实源：

- 武器图
- 名称
- 等级
- 精炼等级
- 武器类型
- 攻击
- 暴击率
- 暴击伤害
- 攻击速度
- 触发率
- 魔之楔

不要复制 `_mode_order` 或属性转换逻辑。

## 4.2 抽取 Jinja 组件

把 `role_detail.html.j2` 已有完整武器 section 抽成可复用 macro / partial。

消费者：

```text
角色详情卡
独立武器卡
```

避免：

- 复制两份 CSS / HTML。
- 把整个角色模板做成大量 `if weapon_only` 分支。

## 4.3 独立武器模板

独立模板只负责：

- 页面 wrapper
- 武器标题
- 较大的武器主视觉
- 共用 weapon section
- footer

## 4.4 主视觉

复用：

```text
images/weapon/<weapon_id>.png
        ↓ miss
L2 dynamic cache
        ↓ miss
WeaponDetail.icon
        ↓
download
        ↓ fail
placeholder
```

使用现有：

```python
PlayerImageLoader.weapon()
```

本次不接 `wiki/weapon`。

## 4.5 字段显示修正

正确语义：

```text
atk      → 整数
cri      → 百分比
crd      → 百分比
trigger  → 百分比
speed    → 倍率
```

例如：

```text
speed = 1.0
```

显示：

```text
1.0
```

而不是：

```text
100%
```

## 4.6 精炼等级

`skillLevel` 显示：

```text
精炼等级
```

不写成“精通”。

---

# 七、阶段 5：增加武器缓存能力

主要文件：

`src/modules/player/cache.py`

## 5.1 继续使用现有缓存基础设施

复用：

```python
PlayerCache
CacheManager
PLAYER_DATA_CACHE_TYPE
PLAYER_CARD_CACHE_TYPE
```

不新建 `WeaponCache`。

## 5.2 单武器数据 key

增加类似：

```python
weapon_data_key(...)
```

至少包含：

```text
target_user_id
uid
weapon_id
overview_digest
```

## 5.3 单武器卡片 key

至少包含：

```text
target_user_id
uid
weapon_id
overview_digest
weapon_detail_digest
resource_version
必要的隐私显示状态
```

## 5.4 武器 tag

复用：

```text
player_data
player_card
identity:<digest>
data:<digest>
resource:<digest>
```

增加：

```text
weapon:<weapon_id>
```

这样既支持单武器失效，也支持全部武器失效。

## 5.5 incomplete 卡

当图片最终：

```text
placeholder + incomplete=True
```

允许发送本次结果，但不得作为完整成功卡写入正常缓存。

---

# 八、阶段 6：单武器刷新 / 清缓存

## 6.1 `刷新<名称>面板`

例如：

```text
刷新伊薇面板
刷新希冀的丰稔面板
```

流程：

```text
刷新 overview
    ↓
智能解析角色 / 武器
    ↓
角色 → 现有 refresh_role
武器 → refresh_weapon
```

单武器刷新：

1. 最新获取一次 overview。
2. 找到目标 `WeaponItem`。
3. 确认拥有。
4. 清理 / 覆盖该武器旧详情缓存。
5. 获取最新 `WeaponDetail`。
6. 重新生成武器面板。
7. 按现有刷新行为返回刷新提示 + 卡片。

## 6.2 `清理<名称>面板缓存`

例如：

```text
清理伊薇面板缓存
清理希冀的丰稔面板缓存
```

武器分支只清：

```text
identity:<id>
+
weapon:<weapon_id>
```

对应的：

```text
player_data
player_card
```

不得影响其它武器或角色。

---

# 九、阶段 7：新增“刷新全部武器面板”

主要文件：

- `src/modules/player/commands.py`
- `src/modules/player/service.py`
- `src/modules/player/cache.py`
- messages / i18

## 7.1 命令

新增明确命令：

```text
刷新全部武器面板
```

建议正则：

```python
REFRESH_ALL_WEAPON_PATTERN = r"^刷新全部武器面板$"
```

单独注册 `CommandSpec`。

不要让它落入：

```python
REFRESH_ROLE_PATTERN
```

## 7.2 权限

行为与：

```text
刷新全部角色面板
```

保持一致：

- 只允许刷新自己的当前 UID。
- 不允许通过 @ / target 刷新他人数据。

## 7.3 数据流程

只获取一次最新 overview：

```text
resolve current UID
       ↓
fetch fresh RoleOverview once
       ↓
closeWeapons + langRangeWeapons
       ↓
过滤 owned weapons
       ↓
逐把 getWeaponDetail
       ↓
写入 weapon detail cache
       ↓
返回汇总
```

拥有条件：

```python
weapon.unlocked and weapon.weapon_eid is not None
```

未拥有武器直接跳过，不计为失败。

## 7.4 不批量渲染所有卡片

与现有：

```text
刷新全部角色面板
```

保持一致。

批量刷新只更新数据缓存，不应生成并向群聊连续发送几十张武器图。

返回类似：

```text
全部武器刷新完成：成功 34，把失败 0 把
```

若存在失败：

```text
失败武器：A、B
```

具体措辞沿用现有角色批量刷新风格。

## 7.5 失败隔离

一把武器失败不能中断其它武器刷新。

行为参考现有 `refresh_all_roles()`：

```text
weapon A success
weapon B API fail
weapon C success
```

最终汇总：

```text
success=2
failed=1
```

凭证类失败仍应走现有 credential failure 持久化逻辑。

不要新增 retry。

---

# 十、阶段 8：新增“清理全部武器缓存”

## 8.1 命令

新增：

```text
清理全部武器缓存
```

建议：

```python
CLEAR_ALL_WEAPON_PATTERN = r"^清理全部武器缓存$"
```

## 8.2 缓存 tag

为全部武器缓存增加共同 tag：

```text
weapon
```

单武器同时具有：

```text
weapon
weapon:<weapon_id>
```

这样：

单武器：

```text
identity + weapon:<weapon_id>
```

全部武器：

```text
identity + weapon
```

无需遍历所有 weapon id。

这是比逐把查 overview 再失效更简单的方案。

## 8.3 清理范围

`清理全部武器缓存` 应删除当前 UID：

```text
所有 weapon detail data
所有 weapon rendered card
```

但保留：

```text
RoleOverview 数据
基本信息卡
角色详情数据
角色面板卡
公告等其它缓存
```

因此不要调用：

```python
invalidate_identity()
```

因为范围过大。

增加一个最小：

```python
invalidate_all_weapons(target_user_id, uid)
```

按：

```text
identity tag + weapon tag
```

处理即可。

---

# 十一、阶段 9：保持现有全部角色命令语义

以下继续只处理角色：

```text
刷新全部角色面板
清理全部角色缓存
```

不要因为加入武器功能而改变其范围。

最终形成明确对称：

```text
刷新伊薇面板
刷新希冀的丰稔面板

刷新全部角色面板
刷新全部武器面板

清理伊薇面板缓存
清理希冀的丰稔面板缓存

清理全部角色缓存
清理全部武器缓存
```

角色和武器批量操作相互独立。

---

# 十二、阶段 10：错误文案

优先复用已有：

```text
player.weapon_not_unlocked
player.weapon_detail_not_found
```

新增最少文案：

```text
未找到角色或武器
名称同时匹配角色和武器
武器面板不支持附加武器参数
武器面板已刷新
全部武器刷新完成
武器面板缓存已清理
全部武器缓存已清理
```

网络、HTTP、凭证错误继续走：

```python
PlayerTransportError
```

---

# 十三、阶段 11：最小测试补充

## 11.1 智能分流

覆盖：

- 正式角色名 → role
- 正式武器名 → weapon
- 武器 alias → weapon
- alias 缺失 + 正式名 → weapon
- 双重命中 → ambiguity
- 无命中 → not found
- 武器 + `+...` → reject

## 11.2 武器查询

覆盖：

```text
owned + weaponEid → detail
unLocked=false → 未拥有
weaponEid=None → 未拥有
empty detail → not found
```

## 11.3 renderer

扩展：

`tests/test_weapon_renderer.py`

验证：

- `cri → 暴击率`
- `crd → 暴击伤害`
- `trigger → 百分比`
- `speed=1.0 → "1.0"`
- 精炼等级
- Mod 顺序
- `id=-1` 空槽保留

## 11.4 图片 fallback

验证：

```text
generation miss
+
API icon
→ download
→ provided
```

下载失败：

```text
→ placeholder
→ incomplete
```

## 11.5 单武器缓存

验证：

- 相同 detail / resource version 命中。
- detail 变化后重新生成。
- resource version 变化后重新生成。
- incomplete 不写完整卡缓存。
- 清理单武器不影响其它 weapon / role。

## 11.6 全部武器刷新

至少验证：

```text
overview:
  owned A
  owned B
  unowned C
```

只请求：

```text
A
B
```

不请求：

```text
C
```

以及：

- 一把失败不阻断下一把。
- 成功 / 失败数量正确。
- 失败名称汇总正确。
- 不生成几十张卡片。

## 11.7 全部武器缓存清理

构造：

```text
weapon A
weapon B
role X
overview
```

调用：

```text
清理全部武器缓存
```

结果：

```text
weapon A removed
weapon B removed
role X preserved
overview preserved
```

## 11.8 generation 回归

只增加核心测试：

```text
current=A
validate_current(A) running
new acquire
→ A
```

以及：

```text
validation fail
→ current removed
```

---

# 十四、推荐执行顺序

```text
0. 更新 design spec
        ↓
1. generation 最小修复
        ↓
2. 面板对象智能解析
        ↓
3. 单武器 panel service
        ↓
4. weapon renderer/template
        ↓
5. 单武器 cache
        ↓
6. 单武器 refresh / clear
        ↓
7. refresh all weapons
        ↓
8. clear all weapon cache
        ↓
9. 文案
        ↓
10. 最小测试与真实账号验收
```

---

# 十五、重点避免事项

实施过程中不要：

- 新建 `WeaponService` 只为包装现有 PlayerService。
- 新建 `WeaponApiClient`。
- 新建 Weapon 专用 CacheManager。
- 新建 generation 类型。
- 给 `wiki/weapon` 增加 downloader。
- 给 alias 增加数据库。
- 引入 fuzzy-search 库。
- 大范围重命名 `char_name`。
- 重写现有角色面板。
- 重写 `draw_weapon_detail_section()`。
- 猜测 `type=2`。
- 增加无依据 retry / timeout。
- “刷新全部武器”时逐张渲染并发送几十张图片。
- “清理全部武器缓存”时粗暴调用 `invalidate_identity()` 清空全部玩家缓存。
- 为每一个内部 helper 补测试。

---

# 十六、最终验收清单

- [ ] `<角色名>面板` 原行为正常。
- [ ] 角色 alias 正常。
- [ ] `<武器正式名>面板` 正常。
- [ ] 武器 alias 正常。
- [ ] alias 缺失不影响正式武器名。
- [ ] 已拥有但未装备武器可查询。
- [ ] 未拥有武器不调用详情接口。
- [ ] `weaponEid=None` 提示未拥有。
- [ ] 空 `weaponDetail` 不渲染零属性卡。
- [ ] 武器图片缺失时可以通过 API icon 下载。
- [ ] 最终失败时才使用 placeholder。
- [ ] incomplete 卡不进入完整缓存。
- [ ] `speed=1.0` 显示 `1.0`。
- [ ] `skillLevel` 显示“精炼等级”。
- [ ] 魔之楔空槽位置保持。
- [ ] `刷新<武器名>面板` 正常。
- [ ] `清理<武器名>面板缓存` 正常。
- [ ] `刷新全部武器面板` 只刷新已拥有武器。
- [ ] `刷新全部武器面板` 不批量发送武器卡片。
- [ ] 单把武器刷新失败不会中断其它武器。
- [ ] `清理全部武器缓存` 只清当前 UID 的武器数据 / 卡片。
- [ ] `清理全部武器缓存` 不删除角色缓存。
- [ ] `清理全部武器缓存` 不删除 overview。
- [ ] `刷新全部角色面板` 仍然只处理角色。
- [ ] `清理全部角色缓存` 仍然只处理角色。
- [ ] 资源同步期间正常面板不因校验出现 placeholder。
- [ ] validation 真正失败后仍进入现有 repair。
- [ ] 没有新增多余 API client、缓存系统、资源状态机或 Wiki 抓取。

# Definition of Done

以下全部满足才算完成：

1. design spec 已同步新需求。
2. 武器面板与角色面板智能分流实现完成。
3. 单武器查询、刷新、清缓存均正常。
4. 全部武器刷新与全部武器缓存清理正常。
5. 真实账号已拥有但未装备武器能够成功查询。
6. 批量刷新只刷新 owned weapons，且失败隔离。
7. 批量清缓存不会误伤角色及 overview。
8. 资源同步并发 placeholder 问题完成最小修复。
9. 相关现有测试与新增最小回归测试通过。
10. 未引入超出范围的新抽象、依赖或兼容层。
11. 最终改动保持为一个聚焦的 feature/fix PR。