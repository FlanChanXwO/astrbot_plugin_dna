# 私有资源

运行期资源位于 AstrBot 的插件数据目录下：
`StarTools.get_data_dir("astrbot_plugin_dnaby") / "resources"`。插件源码目录的
`data/` 不承担运行期资源写入。

资源内容由私有 Git 仓库 `FlanChanXwO/dnaby_resources` 提供。仓库根目录必须有：

```json
{
  "format_version": 1,
  "required_dirs": ["fonts", "wiki", "guide", "panel", "images"],
  "resource_version": "2026.08.11"
}
```

`required_dirs` 由资源仓库 manifest 声明，插件会校验目录均存在且不能通过相对路径
逃逸仓库根目录。`resource_version` 只作为经过校验的资源版本返回。

同步规则：

- 目标目录不存在时执行 `git clone --depth 1`。
- 目标目录存在时先检查 `origin` 和 `git status --porcelain --untracked-files=all`，再执行 `git pull --ff-only`。
- Git 缺失、认证/远端错误、origin 不一致、非快进、manifest 无效或本地有修改时直接报告失败。
- 不执行 force checkout、强制覆盖、自动删除或静默降级；本地修改必须由部署者自行处理。

本阶段只提供同步接口和 fixture 契约测试，不创建或推送外部私有仓库，也不在真实
NapCat 或真实账号上执行资源更新。

