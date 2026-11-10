# FC27 自主定价 V3

当前支持**智能决策 smart**、**日常运营 daily（备用）**和**冲销售额 revenue_sprint**。执行规则统一读取[当前基线](CURRENT-BASELINE.md)与[三平台合同](../fc-three-platform-20261110/CONTRACT.md)，不从历史验收恢复旧参数。

三种模式均以各平台100K购买、实交100K核未优惠20%与本平台D-9至D-2八日实际优惠后的平均20%采购毛利硬线，财务合同为`fc27_dual20_d9_d2_platform_100k_v4`。PS、Xbox、PC独立核优惠、报价、红线与效果；互通市场可明确共用成本参考，不共用售价。1000K及以上赠送为主动让利，不转嫁到100K硬线；其他档位保留诊断，不构成新增写价门槛。`pricing_scope=100k_package_only`仍有效。

Lootbar是同平台核心无券参考，缺价时使用同轮同平台Arab-UT；PC使用其唯一标准报价，不虚构普通/快速选项。ItemD2R仅辅助，不决定售价或阻塞改价。券后价格须还原无券并按竞品实际交付K换算；缺价与原因明示，不以旧价补位。smart每轮重算P0与合法±3%候选；daily、revenue_sprint及双缺时的财务处理见当前基线，不在本入口重复保存会漂移的规则副本。

同平台跨地区统一全球价，地区系数1，地区配置能力保留但不启用专属优惠。原P0完整常驻链路、60分钟固定网格、唯一writer、原ID/CAS和写后确认保持；正常周期不等待逐轮模型审核。控制台每5分钟刷新不改变改价节拍。历史UNKNOWN按原回执与后续真实现态对账，不冒充旧写入成功，也不让已被覆盖的终态阻塞新报价。

- [完整使用说明](USER-GUIDE.md)：如何建计划、看竞品/成本/红线、暂停与核验。
- [当前业务合同](DUAL20-NO-BUDGET-CHANGE.md)、[参数和Hermes职责](HERMES-OPERATING-CONTRACT.md)、[运行分工](SIMPLIFIED-OPERATING-CONTRACT.md)。
- [历史验收（原scope）](TWO-MODE-SIMPLE-ACCEPTANCE-20261027.md)、[逐文件活动源](SOURCE-MAP.json)、[退役清单](RETIREMENT-MATRIX.md)。
- [日常模式合同](HISTORY-DAILY-CONTRACT.md)、[历史覆盖](HISTORICAL-COVERAGE-20261027.md)、[学习覆盖](LEARNING-COVERAGE-ACCEPTANCE-20261027.md)、[自然与故障证据](NATURAL-AND-FAULT-ACCEPTANCE.md)。

原附件和施工过程见IMPLEMENTATION-SPEC.md、SPRINT-DUAL20-SPEC-v1.2.md及DELIVERY.md，只作历史。冲突五策略、预算、礼包等值、双10或逐轮Hermes规则已失效。旧教材及验收只描述其原时点；当前scope的代码、发布、实际装载和自然周期分别按对应回执核验。
