# 导航恢复与 Hermes 接入核对

2026-10-15（Asia/Shanghai）。负责人：本聊天 Codex；范围：共享导航与模块目录，仅恢复既有入口。当前为本地候选，发布状态见本文件后续记录。

- 顶层仅首页、数据分析、LV决策大脑、球类工作区、RPG游戏改价系统、机器人管理、协作工具，账号工具保持原角色判断。
- FC 捆绑包回到球类的 FC 分类，目标 `/dashboard/modules/sports/bundles/`；RPG 同页提供 `/d4/` 与 `/g2g/`；机器人模块页进入已有 `/bots/` 控制台。
- 现有业务服务、价格公式、开关、权限、采集和机器人配置保持。只读实测三个服务200，真实管理员捆绑包页有当前配置、写价按钮和历史日志；本轮未操作这些写入口。
- 生产导航基线 `workspace-native-20261006-261bedcc395a`，139资产逐SHA与上次发布源一致。新不可变版本 `workspace-native-20261006-fa9eaad37a21`，138资产仅允许版本引用替换；功能变更只在navigation.json。共享UI四目标：registry、hubnav、RPG目录与新机器人目录。沿原publisher锁内CAS、备份、失败还原，不覆盖旧不可变版本。
- 本地4项发布范围/资产检查通过；Windows未验证Linux所有权，Linux CI将实际核验。合成浏览器21项通过，涵盖6大类、三个模块入口、活动大类、手机菜单、普通角色及登录失效；不能代替真实页面验收。
- GitHub读取基线 `d68224d7b566df35a082006283228b38d4414628`：机器人源码PR147已合并，G2G源码纳管PR125已合并。源码纳管不能单凭PR证明部署，本轮另读现场服务与路由。无改动大超模块的业务代码。

## Hermes

官方Hermes Desktop支持持续会话、任务活动、配置、技能/记忆与定时任务管理；远程接入要求可达且有认证的 `hermes serve`。参考：https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/desktop.md 。

当前生产 `fs-hermes-fc.service` 使用固定镜像内 `/opt/pilot/hermes_worker.py`，属于FS专用只读研究进程，不能把FS URL直接填成Desktop的标准远程后端。现有LV页提供独立调查/报告/任务观察，持续追问与可修订的长期策略尚未接入。本轮只核对，不安装桌面、不开放端口、不改生产模型或工作进程。

建议保留服务器持续运行，让Desktop连接同一受控业务身份与数据；长期策略应保存为有版本的业务目标、指标口径、允许/禁止动作及修订记录，再给Hermes加载，不能把随口聊天等同于永久执行授权。该接入为后续独立实现范围。

## 复核与回退

本地检查：`python docs/planning/fs-navigation-recovery-20261015/test_recovery.py`，`node docs/planning/fs-navigation-recovery-20261015/verify.cjs`。`inspect.ps1`只读，会更新本轮基线；更新后不得直接重建并重发旧候选，须重新评估现场。

真实发布先native再ui，回滚先ui再native，使用各publisher的backup与本次approved manifest SHA。已成功发布的同一release-id不可重复apply；unknown先核原账本。禁止触发价格、采集、机器人启停或新模型任务来验证导航。
