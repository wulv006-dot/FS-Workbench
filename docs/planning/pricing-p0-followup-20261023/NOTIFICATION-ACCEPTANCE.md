# 即时告警真实通知验收

已上线watch SHA为 `b1851faa087108b249d38591442ffe7a2ca638986c775d4bc8ba42eba4e218c4`。主任务用原发送入口，在隔离验收状态目录中完成一次明确标注“演练、非生产事故、未进行业务写价”的故障与恢复通知，目标是原群。子Agent随后只读调用官方GET，独立核对两个原消息ID，没有新增发送或生产修改。

| 通知 | 原消息ID | 官方读回 |
| --- | --- | --- |
| 演练故障 | `om_x100b629b81a3313cde62ed55d4659ef` | code0、原群、text、含演练标识、FC/RPG问题码及不写价声明 |
| 演练恢复 | `om_x100b629bab84d0b0c1db6c6a3df98d4` | code0、原群、text、含演练和恢复语义、FC/RPG问题码及不写价声明 |

主任务的原 `accept_recovery.py` 执行结果中，重复即时检查与完整巡检均为 `unchanged_quiet`，未增加outbox。子Agent只读复验验收目录：两个结果文件均为sent，outbox恰好两条且均sent，两个message_id与官方GET一致。本次只读复验没有重跑会写状态的检查入口；去重调用结果与独立outbox读回分别记在JSON中。

原历史事件 `ecc824cd838da232ee8c5e5326f3efc99ab06582245fb7266da94bd914363159` 仍为UNKNOWN，checked_at及文件mtime保持10月22日原时点，没有message_id。旧cron失败通知不等于原业务正文投递证明；此前群历史列表因权限被拒，最终验收没有再次查询或扩权。该旧事件没有重放，也不阻断不同的新故障范围。

这证明真实原群的演练故障、恢复和跨模式去重已验收。它不等于对真实业务写入注入故障后的自然告警验收，也不把历史UNKNOWN改判为成功。业务价格写入0；后续真实故障继续按原工单、回执和实际状态处理。

完整脱敏字段见 [NOTIFICATION-ACCEPTANCE.json](NOTIFICATION-ACCEPTANCE.json)，不含群ID、凭据、会话或完整消息正文。
