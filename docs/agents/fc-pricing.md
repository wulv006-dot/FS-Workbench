# FC27 定价

<a name="pricing-contracts"></a>

## FC27 Coins 定价合同入口

先按实际计划的写入协议选择合同。`fc27_curve_v6` 使用[FC27 V6.1 合同](../../docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md)，三平台旧标量计划和历史原操作使用[对应旧合同](../../docs/planning/fc-three-platform-20261110/CONTRACT.md)。部署、计划激活、真实执行及自然周期分别核验。共享 Sol 接入由原任务维护，FC 继续消费 `pricing_review_v3`。周报、经营管理台和已暂停的日报／月报仍按各自配置运行。

<a name="pricing-p0"></a>

<!-- fc-pricing-p0-availability-20261101 -->
## FC 自动改价 P0 可用性（2026-11-01 用户确认）

FC 自动改价及必要依赖属于 P0 核心常驻链路，豁免全局节省资源、闲置回收、按需休眠及优化性停用、降频或节流。范围包括调度器、API、worker、当轮采集、Order 会话/浏览器、Admin 数据通道及原操作对账；不能只豁免主进程而回收依赖。正常任务结束的临时进程释放与防错价、幂等、超时原 ID 对账保护继续保留。改变现有自动化能力前须证明完整链路不受影响并完成真实入口与自然周期验收，不能以优化为由先降级后观察。

<a name="current-pricing"></a>

<!-- fc-three-platform-current-20261110 -->
## FC27 Coins 当前定价：三平台独立、两段全球价（2026-11-14）

使用 `fc27_curve_v6` 的计划遵循[FC27 V6.1 经营与执行合同](../../docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md)。PS、Xbox、PC 分别核算优惠、成本、价格、试验及实际效果。各平台全球统一价，主站 MMOEXP 为基准，继承同一商品模型的站点跟随主站。SBC、Players、Packs、捆绑包和进化继续读取请求平台的实际 Coins 美元 rate。

2026-11-17 市场定位锚按实际计划版本生效：`market-anchor-v1` 两段分别取 Lootbar/U7Buy 定位目标，替代三小时 A/B/C；旧策略与影子观察期继续原逻辑。初始参数、报价缺失、保险和回退见 V6.1 合同；Git／部署／策略修订分别取证。2026-11-27 用户确认，同平台以 1000K 分段，预测成本取各段近三小时有效成交的数量加权中位数。列表快速路径按本笔实发量（含赠送）归段和加权，拆单等例外沿原订单详情校验。不足六笔扩大时间窗取最近六笔，各段不足三笔走同平台合并估计并标明依据。历史真实成本按原记录解释。短期验收通过即推进下一阶段，24 轮、48 小时及自然周长期验收并行记录，不阻断施工。

启用 `margin_band` 的计划按实际修订的北京时间决策小时及平台目标判断两量段价格，00:00 至 00:15 前保持经营价。每小时继续核安全底线。周阶梯按两段合计实际毛利额和订单量评估目标利润率，竞品走廊参数由人工计划修订。读取[V6.1 分时段规则](../../docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md#分时段目标利润率阶段-5)及实际修订和决策证明。

两段分别为低于 1000K 和 1000K 及以上。按实际生效的报价合同复盘。采用[普通购买档合同](../../docs/planning/fc27-market-quotes-20261124/CONTRACT.md)后，Lootbar、U7Buy 分档按普通购买价定位并参与保险，U4GM 仅用于监控价差。旧回执按原实交口径解释。两段保留自动调价能力。临时成本保护沿原财务条件处理，成本回落时按当轮数据释放。旧 A/B/C 策略的临时保护沿原经营基准 A。

各平台按北京时间 D-3 至 D-1 三个完整自然日的同单 ES 实际优惠美元总额除以 Admin 优惠前商品美元总额计算平均优惠。按金额加权，缺项如实标记，写前复核同一窗口与实际归档修订。候选按真实购买量、赠送、采购、汇率和舍入逐档核保本，平台主篮与近期篮的组合采购毛利率各以 18% 为底线。未启用 `margin_band` 的 V6.1 计划仍用 25% 作经营比较。以实际毛利额、整体利润率与订单量验收经营效果。

改价前读取商品模型的 ALL 完整价表，原 writer 每平台单次保存，保留数量和赠送。收到本次 Admin 成功回执并重读 MMOEXP 主站（site 266）完整价表一致后确认生效。北京时间午夜后，V6 自动轮等共享 ES 昨日主站 FC27 订单发布，再接续同一任务。每 60 分钟的 P0 调度、计划身份、原 ID、CAS 和 UNKNOWN 对账沿原链路执行。历史 V6 证明按原记录的优惠窗解读。旧标量计划和历史原操作按[三平台旧协议](../../docs/planning/fc-three-platform-20261110/CONTRACT.md)及[原财务合同](../../docs/planning/fc-pricing-v3-20261026/DUAL20-NO-BUDGET-CHANGE.md)处理。

2026-11-28 用户确认（北京时间）：

- Admin 商品单价取本平台 1000K 售价／1000。[单价合同](../planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md#two-band-unit)
- 外部改价触发平台告警，已确认的越界段每轮向参考区间回调最多 15%。[回调规则](../planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md#external-recovery)
- revision 10 已将 PS、PC 大额段 u 调到 +3%，三平台目标均为 31%。[计划参数](../planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md#revision-10)
- Admin 改模型或档位后通知值班 Agent，按最近确认价补写并读回。[标准 15 档与核验](../planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md#admin-model)
- 四张原无封顶的 15% 券现封顶 $80，原 $50 券保持原封顶。[券号与适用范围](../planning/carnival-landing-20261117/COUPONS.md#coupon-caps)

<a name="historical-pricing"></a>

<!-- fc-v3-historical-rules-archived-20261029 -->
早期 FC 定价规则见[历史记录](../../docs/planning/fc-pricing-v3-20261026/history/AGENTS-FC-RULES-BEFORE-100K-20261029.md)。当前执行按本文件顶部的协议入口选择合同，历史操作沿其原协议追溯。

<a name="legacy-pricing"></a>

<!-- fc-v3-current-20261026 -->
FC 当前执行以实际计划协议和已发布版本为准。`fc27_curve_v6` 走本文件顶部的 V6.1 合同。旧标量 `smart`、`daily` 和 `revenue_sprint` 的原版本见[旧标量基线](../../docs/planning/fc-pricing-v3-20261026/CURRENT-BASELINE.md)。
