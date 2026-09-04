# 原始用户输入

> 使用 [$brainstorming](/Users/flanchan/.cc-switch/skills/brainstorming/SKILL.md) 技能规划“订阅客户端更新”和"客户端更新"命令。参考API文档`/Users/flanchan/Developer/Projects/GithubProjects/DNA-analysis/docs/update-api/update-contract.md`。目的是实现像公告那样的定时推送和查询能力，支持多个平台的更新推送。

> 使用 [$using-git-worktrees](/Users/flanchan/.cc-switch/skills/using-git-worktrees/SKILL.md) 技能创建独立的工作树，并使用 [$goal-mode](/Users/flanchan/.cc-switch/skills/goal-mode/SKILL.md) 技能进行初始化。初始化完成后立马停止实施，不完成目标

# 需求澄清中的用户原话

> 主要是查询版本，以及本次的更新大小有多少，就行了

> 只查最新，每次订阅客户端更新时，会从之前查到的历史做对比，然后告知版本变化，以及本次新版本新增大小，所以主要是储存区服，新旧版本号，新版本更新大小

> 国服 PC + 安卓 (Recommended)

> 群聊管理员订阅 (Recommended)

> 默认全部，可选平台 (Recommended)

> 两次检查之间新增补丁总和 (Recommended)

> 只建立基线 (Recommended)

> 失败平台静默跳过

> 仅日志记录

> 只显示这五项 (Recommended)

> 查询只读，定时检查维护基线 (Recommended)

> 每个平台一条

> 关于之前的问题，如果是onebot平台，可以选择开启合并转发的模式，如果目前不是ob，则开启后也没有效果。当前选项选择展示历史对比

> 插件配置开关，默认开启

> 采用方案 A (Recommended)

> 接口好像是会直接给出本次更新的大小的，如果给出了，就别自己计算了

> 独立开关和独立周期，默认开启的时间比较长，一般为1小时一次

> 保留订阅，下一次成功检查只建基线 (Recommended)
