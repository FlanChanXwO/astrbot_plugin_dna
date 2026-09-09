# 客户端更新 Target / Source 只读调查

调查日期：2026-09-08。

## 调查边界

本次只读取官方网页、应用商店元数据、现有公开 `VersionList.json` 与当前版本对应的两个小型 manifest JSON。未下载 EXE、APK、IPA、pak、sig 或完整补丁，未创建或修改 baseline、订阅、插件运行数据和生产配置。

登记原则：Target 必须同时具备现实发行证据、明确的区服/账号生态语义，以及可稳定只读获取当前版本的 Source。仅证明存在下载入口，不足以登记 Target；无法确认 Source 契约的候选项保持未登记。

## 本轮确认登记的 Target / Source

| Target | Source | Provider | 2026-09-08 当前版本证据 | 结论 |
| --- | --- | --- | --- | --- |
| `cn-official-pc` | `cn-official-pc-manifest` | `manifest_cdn` | `VersionList.json` 7 条，最新 `1510198` / `1.6.198.1` | 登记 |
| `cn-official-android` | `cn-official-android-astc-manifest` | `manifest_cdn` | `VersionList.json` 7 条，最新 `1410193` / `1.6.193.1` | 登记 |
| `cn-official-ios` | `cn-official-ios-app-store` | `app_store` | Apple Lookup：track `6470771372`，bundle `com.hero.dna.ios`，版本 `1.6.0`，发布时间 `2026-09-08T00:27:25Z` | 登记 |

默认配置仍仅启用 `cn-official-pc` 与 `cn-official-android`；iOS 是已验证可选 Target，不因升级自动启用。

### CN PC manifest Source

- primary base：`http://pan01-1-eo.shyxhy.com`
- fallback base：`http://pan01-1-hs.shyxhy.com`
- branch：`Patches/FinalPatch/CN/Default/WindowsNoEditor/PC_OBT_CN_Pub`
- `PakFilesInfo.json` key：`WindowsNoEditor`
- `ResDiscreteInfo.json` key：`WindowsNoEditor`
- VersionList primary/fallback 均返回相同 ETag 与 7 条记录。
- 最新目录 `1510198` 的 `PakFilesInfo.json` 为 956 bytes、4 条文件记录，去重合计 `3,038,986` bytes；`ResDiscreteInfo.json` 为 106 bytes、空列表。

### CN Android ASTC manifest Source

- primary base：`https://pan01-1-hs.shyxhy.com`
- fallback base：`http://pan01-1-eo.shyxhy.com`
- branch：`Patches/FinalPatch/CN/Default/Android_ASTC/Android_OBT_CN_Pub`
- `PakFilesInfo.json` key：`Android_ASTC`
- `ResDiscreteInfo.json` 当前真实 key：`WindowsNoEditor`
- VersionList primary/fallback 均返回 7 条记录，最新版本一致。
- 最新目录 `1410193` 的 `PakFilesInfo.json` 为 941 bytes、4 条文件记录，去重合计 `3,841,495` bytes；`ResDiscreteInfo.json` 为 106 bytes，只有空的 `WindowsNoEditor` 列表。

当前 provider config 已分别表达 Pak 与 Res key，可按真实协议解析
`ResDiscreteInfo.json`；维护时不得重新合并为单一 key，也不能用静默跳过掩盖
协议差异。

### CN iOS App Store Source

- 官方商店：`https://apps.apple.com/cn/app/id6470771372`
- 只读版本接口：`https://itunes.apple.com/lookup?id=6470771372&country=cn`
- App Store 页面和 Lookup 元数据均指向英雄游戏中国大陆发行主体。
- `revision_id` 使用 App Store track ID 与版本组合；若没有可靠可比较 build number，则 `order_key=None`，不伪造 rollback 或差分大小。

## 已核实发行存在、但本轮不登记

### CN bilibili

- bilibili 游戏中心条目 `https://www.biligame.com/detail?id=111015` 可确认 Android 渠道包和 PC 下载入口存在。
- Android 页面在调查时暴露的包文件名包含 `1.6.186.1`，但未发现稳定、公开、结构化的当前版本 API 或可验证 manifest Source。
- PC 下载由页面脚本触发，未取得独立包 URL或版本 Source。
- 未发现二重螺旋 B 服专属 App Store 条目。
- 未找到一手资料证明官服与 bilibili 的账号、角色或服务器互通，也不能证明其更新 Source 与官服共享。

结论：`cn-bilibili-pc/android/ios` 均不登记。后续只有在取得稳定只读版本源并确认账号/服务器语义后才能加入。

### 全球服 America / Europe / Asia / SEA / HMT

- 官方 Twitch Drops 页面 `https://duetnightabyss.dna-panstudio.com/twitchdrops/en/` 明确要求 `Select Server + UID`，证明服务器是角色/奖励定位维度。
- Apple 全球版使用统一 track `6744096826`；2026-09-08 Lookup 当前版本为 `1.6.0`，bundle 为 `com.panstudio.duetnightabyss.arpg.global`。
- Google Play 全球版 package 为 `com.panstudio.gplay.duetnightabyss.arpg.global`；Steam App ID 为 `3950020`。
- 公开资料能支持全球产品线和多个服务器存在，但未取得官方公开的完整服务器枚举/稳定 region ID，也未取得全球 PC/Android manifest 或其它结构化版本 Source。

结论：本轮不登记任何 `global-*-official-*` Target。仅有共享全球 iOS App Store 条目仍不足以构造带可靠 `region_id` 的 Target；不得用 `global` 伪装一个服务器。

### 下载商店与云游戏入口

官网的 TapTap、WeGame、好游快爆等入口没有证据表明形成不同账号生态或服务器，不作为独立 Target。`云·二重螺旋` 是独立云产品，也不属于本次本地客户端更新 Target 范围。

## Source 共享结论

- 本轮三个已登记 CN 官方 Target 分属 PC manifest、Android ASTC manifest 与 CN App Store 三个 Source，不共享 Source。
- 全球服同平台很可能共享客户端产品，但由于完整 region 身份和 PC/Android 技术 Source 未完成一手核验，本轮不把该推断写入 registry。
- bilibili 与 CN 官服的发行入口不同；在没有协议证据前既不共享 Source，也不登记猜测 Source。

## 实现约束增量

1. `ManifestCdnProviderConfig` 需要分别保存 `pak_manifest_key` 与 `res_manifest_key`，以覆盖 Android 当前真实协议。
2. `AppStoreProviderConfig` 至少保存 `track_id` 与 `country`；只返回当前版本和稳定 revision，不承诺差分大小。
3. T03 registry 仅登记本文件“本轮确认登记”的三个 Target/Source。
4. T13 的 registry-driven smoke 必须复核所有登记 Source；任何新增 Target 必须先更新本调查证据。

## 长期复核入口与传输边界

运行 `python3 scripts/smoke_client_update_sources.py` 可按当前 registry 只读检查全部
Source。该入口固定不传 baseline：manifest provider 只读取 `VersionList.json`，
App Store provider 只读取公开 Lookup；不会读取完整补丁、写 state 或改订阅。

CN PC 当前两个已验证端点均为 HTTP。现有结构校验只能证明响应符合预期 JSON
契约，不能提供 TLS 来源认证或链路完整性。除非取得官方/一手证据并重新完成隔离
只读核验，不得擅自把它们猜成 HTTPS，也不得用未验证镜像静默替代。
