# 知识读取入口

本索引和消费代码当前为**候选，未发布到Hermes生产**。正式业务文件本身的既有状态不因索引施工改变。FC策略、利润程序、教学和调度由原会话负责，本次只引用其原文件与版本，不修改或接管。

先读本页与[index.json](index.json)的条目标识、模块、状态、版本和来源，再按任务读取对应原文件；不要全读Notion、日报或历史经验。五层是逻辑分类，不要求搬迁目录：

| 层 | 内容与权威来源 | 默认消费 |
|---|---|---|
| current | Git中已确认的正式业务口径和操作方法，索引只指向唯一原文 | 同模块、有效条目 |
| decision | Git中带日期和来源的已确认决定 | 解释原因或历史问题时按需 |
| experience | 来源可核的验证、条件、限制和失败记录 | 明确适用且需要该经验时 |
| candidate | 想法、模型建议、Notion新条目、未审经验 | 审核使用，不进入生产上下文 |
| archive | 旧日报、退役规则、旧版本与历史验收 | 明确历史查询时 |

Notion项目页负责当前状态、决策摘要、关键待办和每日复盘，链接Git的固定提交；不是第二份可写正式规则。现有服务器经验账本仍是“发布/撤销/实际使用”的运行事实源，未经来源核验和批准不自动变成Git正式经验。程序仍是改价等强制校验的执行入口，文本与模型不能豁免。

索引条目至少含稳定id、revision、layer、status、modules、effective_at、owner、authority、provenance、source_commit、source与supersedes。source为原文路径和内容哈希，可选唯一段落边界；不复制规则全文。日期精度不足时不推定具体小时。两个有效版本冲突、文件缺失、哈希漂移或范围不符时返回冲突/缺项，不能按mtime猜版本。

索引source.sha256采用UTF-8原文、CRLF规范为LF的内容哈希，hash_basis明确写utf8_lf；服务器发布CAS和原发布器仍核原始文件字节，两者不混比较。release_state=candidate只能显式preview；生产加载要求published及确切索引哈希。任务固定自己的选择与内容，不在执行中重新读“最新”。

[完整施工与验收](../docs/planning/knowledge-layering-20261023/README.md) · [自动收尾入口](../docs/planning/knowledge-layering-20261023/CLOSEOUT.md) · [候选区](CANDIDATES.md)
