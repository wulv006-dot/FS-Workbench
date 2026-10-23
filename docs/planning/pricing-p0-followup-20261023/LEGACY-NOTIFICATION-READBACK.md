# 原UNKNOWN通知只读对账

2026-10-23使用Hermes主profile原凭据和原群权限，只读查询官方消息API。没有发送、重试、改写outbox、添加凭据来源或更改权限；token仅在进程内存中使用。

## 原事件

- outbox：`ecc824cd838da232ee8c5e5326f3efc99ab06582245fb7266da94bd914363159.json`。
- 原状态unknown，checked_at为2026-10-22T00:00:40.459863Z，文件mtime为北京时间08:00:43。没有message_id、error或created_at，缺少原业务正文发送成功的回执。
- 原作业 `0018aa8c8439` 在 `cron/output/0018aa8c8439/2026-10-22_00-00-43.md` 记录脚本exit1，输出“Feishu notification result unknown; preserve outbox, do not blindly resend.”。
- 同分钟 `logs/agent.log.1` 确有cron原适配器的投递成功记录，消息ID `om_x100b62a16c1cc4a4dff88667d0cd016`。

## 官方API读回

GET上述消息ID返回code0，属于原群，类型post；正文是cron脚本失败通知，包含发送结果未知与exit1，未包含原业务故障巡检正文。因此不能用该消息ID把旧业务outbox改为sent。

GET主任务新演练消息 `om_x100b629b81a3313cde62ed55d4659ef` 返回code0，属于原群，类型text，正文含演练标识；这能证明新演练送达，不能证明旧业务正文送达。

原群2026-10-22北京时间07:59—08:02历史列表GET返回HTTP400/code230027，明确原因：`Lack of necessary permissions, ext=need scope: im:message.group_msg`。没有更换凭据、扩大权限或绕过限制。[官方历史消息文档](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/message/list)亦将230027列为必要权限缺失。

结论：原业务正文是否已发送仍然未知，旧事件应原样保留UNKNOWN且不重放。不同的新故障和之后真实确认的恢复属于独立通知范围，不能被该旧事件永久冻结；相同通知范围跨即时/完整巡检仍需去重，不能借更换事件ID重复原正文。

## 候选处理

watch候选已改为在原outbox记录 `notification_scope`，仅发送新增问题码和明确恢复项。新的独立范围可以发送；原未知问题正文不重复出现，旧event通过 `unknown_notification_events` 保留审计，即使新范围已sent也不丢失。无scope的历史unknown仅保护原event，不阻断不同新事件；不将其改写为成功或未发送。

当前候选SHA `b1851faa087108b249d38591442ffe7a2ca638986c775d4bc8ba42eba4e218c4`；Linux24项测试通过，包括同范围跨模式unknown不重发、独立新告警不中断、旧UNKNOWN审计保留与恢复事实独立通知。上线由主任务统一协调，本子任务未改生产watch。
