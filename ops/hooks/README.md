# FC Coins / 经营快照 Hook 增量

唯一执行规则：[HOTFIX](../../docs/ops/HOTFIX.md)。这是单模块增量，精确映射见 [SOURCE-MAP](SOURCE-MAP.json)，禁止用本目录或 main 整包覆盖 FC。

已启用：原五分钟巡检的错误、worker 心跳、数据新鲜度、任务时限检测；自动发送前按平台读取独立控制，过期/不可读则拒绝新自动写入。原队列、业务锁、来源验证、账本、操作 ID 与人工入口保留。快照沿用实际 atomic_snapshot.validate 与原子切换，失败保留合法旧完整版本，缺失不补零，不串日期或权限。

固定恢复只有有界重读和解除本系统暂停原因：用户仍启用、当前配置版本、两次正常观察、无 UNKNOWN、独立安全检查全部满足；先标 AWAITING_CYCLE。已错价而无法保护售卖时标 ESCALATED 和 sales_protection_status=UNAVAILABLE，不宣称风险已隔离。

2026-10-08 北京16:24:08，原定自然操作 86e39e89-e96a-4bf8-af02-f187fc0c573f 三平台 confirmed，公开读回 verified。没有手动触发改价，业务节拍与服务 PID 保留。Linux直接30检查/0 skip通过。首次FC发布因旧任务专用球员条件自动回退四代码文件；限定 --hooks 验收后重新发布，原发布分支条件和失败证据保留。

机器人仅配在阿里云控制台，服务器无配置；outbox 与 DingTalk 适配仅隔离验证，没有真实收件证明。无可用无头 AI，AUTO_PATCH_ARMED=false，额外预算0美元。整机失联、前端DOM/日期脚本、准确区间逐查询事件、浏览器/缓存/worker修复、SKU停购/价格补偿未覆盖。

直接复查：python3 -B -m unittest discover -s ops/hooks -p 'test_*.py'。pr-fast 复用 hooks 分组。CI为隔离检查，对root所有权用合成输入；实际 UID11027/group11028 和只读控制绑定已用原 writer 镜像另验。

机器人缺项：由有权限的人保存服务器 /etc/fc-ops-readonly-monitor/hooks-bot.json，root:root 0600。字段为 approved=true、group=服务器及Github报警、activated_at=带时区时间、webhook=现有机器人地址、secret=现有密钥。凭据不进Git、报告或聊天。每轮最多两条，未知写入告警携带原操作 ID，区分排队、provider accepted 与用户实收；仍需真实检测到群收件验收。签名按[钉钉官方接口](https://open.dingtalk.com/document/robots/custom-robot-access)，不挪用 Aion2 机器人。

RPG共享接口：collector.persist（状态/去重/outbox）、hooks_notifier.deliver_bot（已有渠道）、hooks.can_resume（纯恢复条件）。陈超按第二份方案接自己的 scope、writer/锁、来源、原 ID、读回、publisher、售卖保护。本次没有安装或修改 RPG 业务规则，FC路径和价格规则不能套用。

生产重跑先核现场SHA与原操作 ID，发布不能盲重放；只沿原锁/CAS回退代码，保留DB、价格、队列、锁、回执与暂停状态。
