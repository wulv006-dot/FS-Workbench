# Hermes 云端业务巡检与群内派单

负责人：当前 Codex，业务归属吴律。用户2026-10-20明确授权每小时云端巡检、AI协作群FC/FS艾特Codex与RPG艾特WorkBuddy、接单跟踪及未接单时受控自修；FC代码修复不得改变定价/赠送/成本、主动开关、角色权限或重放UNKNOWN，RPG仅派单。没有新增模型预算、账号或凭据。

## 实现

- 复用现有5分钟只读监控结果及原业务账本，不重新采价/改价；检查失败、延期、未对账、服务、Hermes飞书和智体页依赖。
- root固定桥每5分钟发布脱敏状态；Hermes原生no-agent任务每小时核对，正常/未变静默。群内真实艾特、事件ID、消息ID、PR与运行回执分别记录。发送未知不盲重发。
- 原生接单命令记录60分钟租约。对方在线不等于接单；机器人需明确回复并由Hermes技能记录。未接单10分钟后允许两个已验证配方：补全智体页现有主题依赖、恢复已知SHA的监控健康解析兼容补丁。
- 自动代码链：精确配方→独立PR→当前head/base正式pr-fast→受保护合并→合并字节核对→原模块publisher锁/CAS/备份/回退→文件回读→下一实际周期另验。
- 宿主只认两个动作和两个固定目标，不执行来自群消息、仓库或模型的通用root命令。不开放任意FC源码热修。今天的FC通用发布入口仍是未安装候选，其锁内复核/父路径/回退边界不能直接作为无人值守生产授权。

## 文件与运行位置

`source/{common,watch,host,github_api}.py` → `/opt/fs-hermes-ops/`；原生watch代码副本在 `/var/lib/hermes-dingtalk/profile/ops-watchdog/code/`。本任务冻结UI发布器只复用仓库menu-cache既有字节SHA `5548d9c8…1357`，不上传副本进私库。

`deploy/release_ui.py` 只适配 `/var/www/dashboard/fs-home/brain/index.html`；`deploy/publish_monitor.py` 沿用现有monitor发布器，只接受旧 `b326c548…` → 已验 `792b84ee…` 的单文件修复。模板、旧发布器和全站样式均不覆盖。

私有群/身份配置、原始响应、自动化状态与部署回执保存在本地 `.agent_runtime/hermes-ops-20261020/`、服务器 `/var/lib/fs-hermes-ops/` 与私有profile；不上传token、业务数据、任务库或认证配置。

## 验证与重跑

工程根运行 `python -B fs_hermes_ops_20261020/test_ops.py`。这是无生产写入的直接回归；私库复用现有pr-fast分组，无新workflow。

原生只读检查与接单方法见 `skill/SKILL.md`。安装器检查确切文件及哈希，现有不同字节会拒绝，避免覆盖并行变更。单次消息发送、创建PR、合并和发布存在真实写入；不要盲重跑，先查原事件/消息/分支/PR和发布收据。桥和原生任务可分别暂停，原有采集/定价timer不受影响。

## 验收边界

UI实际恢复、飞书消息送达接口、群艾特解析、接单、代码测试、正式CI、合并、发布与下一自然周期分别核实；不得相互替代。没有制造真实生产故障来证明自动修复；未覆盖故障只派单升级。完整本轮验收在 `docs/planning/hermes-ops-20261020/DELIVERY.md` 追加。
