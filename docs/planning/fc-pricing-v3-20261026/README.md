# FC27 自主定价 V3

当前只保留**日常运营**和**冲销售额**，每小时采集改价，可配置；结束时间可选、无预算、正常周期不等Hermes。每轮只选一套价格方案，基础价最多更新一次，地区系数各必要更新一次。daily与revenue_sprint统一以100K购买+赠5K档核未优惠及D-9至D-2八完整日真实优惠金额结构平均双20；小额、其他档位及全整数K不再作为写价硬门槛。冲额5–10%竞争带与本档双20无交集时取本档最低合法价；新证明显式标记pricing_scope=100k_package_only。

ItemD2R按实际100K，无礼包估算；Lootbar无券，Saudi只比Arab-UT普通发货，对应平台缺价时授权系数1跟全球。每日02:20影子只运行这两模式，不补采、不写价。Saudi原优惠系数使基准档破线时自动归1继承全球；英国旧0.91已取消、当前系数1；旧加权、钉价、回摆与重复tick/observer退出生产，历史证据保留。

2026-10-30竞品缺价规则：冲额两家有效取较低可比价、单缺用另一家当轮有效价、双缺取本档双20最低合法基价；daily在Lootbar有效时保留原计划候选，缺而ItemD2R有效时按其当轮实际交付价换算我方105K套餐售价（双20底价优先，未达Item目标需标），双缺按八日真实优惠后平均毛利率30%求本档最低合法基价，原双20硬线不减。每家缺价与原因都展示，不以旧价补位。实际代码和生产验收须按版本及发布回执另核。

- [完整使用说明](USER-GUIDE.md)：如何建计划、看竞品/成本/红线、暂停与核验。
- [当前业务合同](DUAL20-NO-BUDGET-CHANGE.md)、[参数和Hermes职责](HERMES-OPERATING-CONTRACT.md)、[运行分工](SIMPLIFIED-OPERATING-CONTRACT.md)。
- [历史验收（原scope）](TWO-MODE-SIMPLE-ACCEPTANCE-20261027.md)、[逐文件活动源](SOURCE-MAP.json)、[退役清单](RETIREMENT-MATRIX.md)。
- [历史与每日合同](HISTORY-DAILY-CONTRACT.md)、[历史覆盖](HISTORICAL-COVERAGE-20261027.md)、[学习覆盖](LEARNING-COVERAGE-ACCEPTANCE-20261027.md)、[自然与故障证据](NATURAL-AND-FAULT-ACCEPTANCE.md)。

原附件和施工过程见IMPLEMENTATION-SPEC.md、SPRINT-DUAL20-SPEC-v1.2.md及DELIVERY.md，只作历史。冲突五策略、预算、礼包等值、双10或逐轮Hermes规则已失效。旧教材及验收只描述其原时点；当前scope的代码、发布、实际装载和自然周期分别按对应回执核验。
