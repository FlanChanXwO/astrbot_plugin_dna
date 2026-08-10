# 配置

插件配置在 AstrBot Dashboard 插件配置页（schema 见 `_conf_schema.json`）。配置键源自原 DNAUID 的 `config_default.py` / `config_sign.py`，读法保持 `DNAConfig.get_config("Key").data`。

## 主要项
- 登录：`DNALoginTransport`(local/http_poll/sse/ws)、`DNALoginUrl`、`DNALoginBindHost`、`DNALoginPort`、`DNALoginSecret`、`DNAQRLogin`、`DNALoginForward`。
- 密函：`MHSubscribe`、`MHPushSubscribe`(分钟:秒)、`MHCache`、`MHSimplePicture`。
- 签到：`DNASignin`、`DNABBSSignin`、`DNABBSLink`、`SigninMaster`、`DNASchedSignin`、`SignTime`。
- 公告：`DNAAnnOpen`、`AnnMinuteCheck`。
- 其它：`MaxBindNum`、`Guide`、`RoleInfoCard`、`RoleOriginalImage`、`AllowAtQuery`、`DNAUrlProxyUrl` 等。
