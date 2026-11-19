# 知识读取入口

FC26 / FC27 负责人专项日、周、月及自定义复盘从 [FC 项目经营复盘入口](../docs/planning/fc-project-review-20261119/README.md) 进入。查看全站总盘，再按商品、客户、国家、支付、投放、自然搜索、价格和交付追查变化。

订单用户邮箱筛选、跨月多游戏和 XLSX 下载见[订单邮箱导出](order-email-export.md)（`fs.orders.email_export`）。FS 页面提供订单进度、状态、产品类型和逐游戏区服。「全部游戏」使用 Admin 的 `gid=0`，区服筛选适用于具体游戏。连接器的现行操作以本人可见目录为准。

当前知识版本与实际发布状态见各条目的原文及交付记录；FC报告知识的最新收口见[交付验收](reporting/fc27-monthly/DELIVERY.md)。历史首次发布或待验收状态不作为所有入口的当前状态。原生FS对话的知识读取、报告/定价任务的执行入口及自然周期分别核验，不能因一条入口通过就宣称全部已接通。

先读本页与[index.json](index.json)的条目标识、模块、状态、版本和来源，再按任务读取对应原文件；不要全读Notion、日报或历史经验。五层是逻辑分类，不要求搬迁目录：

| 层 | 内容与权威来源 | 默认消费 |
|---|---|---|
| current | Git中已确认的正式业务口径和操作方法，索引只指向唯一原文 | 同模块、有效条目 |
| decision | Git中带日期和来源的已确认决定 | 解释原因或历史问题时按需 |
| experience | 来源可核的验证、条件、限制和失败记录 | 明确适用且需要该经验时 |
| candidate | 想法、模型建议、Notion新条目、未审经验 | 审核使用，不进入生产上下文 |
| archive | 旧日报、退役规则、旧版本与历史验收 | 明确历史查询时 |

长期记忆只保存用户偏好、稳定知识入口和使用原则。Hermes按任务读取现行规则与Skill，自主决定补查、计算、分析及表达；不把旧报告全文、旧方案或固定章节复制成每次执行指令。真实身份、数据范围、金额单位、执行权限、幂等及写后核验由工具边界负责。软件发布器只负责软件安装和回退，不规定Agent的推理步骤或报告结构。

FC27 Coins 任务从 `fc.pricing.constraints`、`fc.pricing.v3` 进入现行合同，结合实际计划修订和已确认价格识别阶段。日报、周报、月报涉及定价复盘时读取 `fc.reporting.business` 和 `fc.reporting.data`。长期记忆保留这些稳定入口，平台目标、走廊、时段及生效时间从计划和原回执读取。

Notion项目页负责当前状态、决策摘要、关键待办和每日复盘，链接Git的固定提交；不是第二份可写正式规则。现有服务器经验账本仍是“发布/撤销/实际使用”的运行事实源，未经来源核验和批准不自动变成Git正式经验。程序仍是改价等强制校验的执行入口，文本与模型不能豁免。

索引条目至少含稳定id、revision、layer、status、modules、effective_at、owner、authority、provenance、source_commit、source与supersedes。source为原文路径和内容哈希，可选唯一段落边界；不复制规则全文。日期精度不足时不推定具体小时。两个有效版本冲突、文件缺失、哈希漂移或范围不符时返回冲突/缺项，不能按mtime猜版本。

索引source.sha256采用UTF-8原文、CRLF规范为LF的内容哈希，hash_basis明确写utf8_lf；服务器发布CAS和原发布器仍核原始文件字节，两者不混比较。本仓`index.json`是可审查的发布输入，release_state=candidate只能显式preview；发布工具派生不可变published索引，生产加载要求该确切索引哈希。是否已部署须核发布回执，不能仅改源索引状态冒充上线。任务固定自己的选择与内容，不在执行中重新读“最新”。

[完整施工与验收](../docs/planning/knowledge-layering-20261023/README.md) · [自动收尾入口](../docs/planning/knowledge-layering-20261023/CLOSEOUT.md) · [候选区](CANDIDATES.md)
