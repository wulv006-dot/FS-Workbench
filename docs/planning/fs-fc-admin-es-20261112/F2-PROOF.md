# F2 离线财务证明

## 2026-11-13 最新经营口径

用户已确认改用本平台 D-8 至 D-2 七个闭合北京自然日的金额加权平均优惠。报价净收入按候选商品金额乘同范围留存比例计算；平均优惠分子是已核 ES 实扣，分母是同单优惠前商品金额，不混入支付附加金额。原订单结构窗口与优惠窗口分别记录，不能仅因都称“七日”混用日期。

零线、主／近期组合 18% 和软目标 25% 沿用计算器，但结论以该平均优惠假设为条件，不代表所有单笔优惠组合均保本。逐券、VIP、积分、混单分摊的完整精确证明不再是本次激活前置；已有逐单证据和诊断保留。普通采购、实际购买与赠送数量、币种及数据覆盖仍需可追溯，缺失不补零。

曲线按 Admin 对应产品模型 ALL 编辑器的真实档位联动编译：必要控制档按从低到高生效，后续档位继承该控制档单价，直到另一个显式控制档覆盖。保留原生舍入及赠币，写后核完整目标价表。下文全优惠路径输入为原实现合同和诊断能力，不得据其旧“全域缺口”重新阻塞已被本条覆盖的平均优惠方案。新代码、部署、激活状态另见实际回执。

`pricing_proof_v6.validate_curve(curve, baskets, evidence, validation_domain)` 对单个平台的一张目标价表核算 [MASTER 第二部分 §3、§4、§5.6 和 §11.1](MASTER.md)。每个已核可达路径计算净实收减压力采购成本和已知必要费用。主站按两个篮子各自汇总同一组成员的净实收和保守采购成本，以较低毛利率核 18%。活跃卫星站各自核零线。25% 的三个差额取主站主篮子，供经营比较。

## 输入

| 参数 | 约定 |
| --- | --- |
| `curve` | F0 `read_curve` 的结果，商品来自 ALL/site0 或 MMOEXP/site266。平台按原生 `aid` 绑定。 |
| `validation_domain` | `curve_key`、`platform`、证明域 `version`、`coverage_status`、`coverage_gaps`，以及 `source_revisions` 下的 `quantity`、`offers`、`fulfilment`、`propagation`。`site_paths` 以字符串站点 ID 列出已核范围的路径 ID。包含 `266` 及实际活跃接收站，路径 ID 在本平台域中唯一。 `complete` 和空缺口列表表示来源已核定该域完整。 |
| `evidence` | `curve_key` 与 `paths`。每条路径也携带原报价所绑定的 `curve_key` 和确切 `site_id`。 |
| `baskets` | `main` 和 `recent` 分别保留 `evidence_ref`、`coverage_status`、`coverage_gaps`、`selection` 及 `members`。每个成员以 `path_id` 引用主站路径，`weight` 是原成员结构的正权重。同一篮子每个路径 ID 一行，聚合同路径权重由构造方完成。主篮子 `selection=closed_bjt_7d`。近期用 `latest_24h`、`latest_3d` 或 `main_fallback`。回退使用已核的主篮子成员及权重。 |

路径需带 `proof_status=verified`、`cost_status=verified`、`quote_ref`、`cost_ref`、`native_tier_or_rule`、`rounding_contract`、`offer_version`、`fulfilment_contract` 和采购 `quantity_basis`。传入购买、承诺赠送和承诺交付 K，以及统一换算后的总额 `regular_usd`、`net_receipt_usd`、`expected_cost_usd`、`safe_cost_usd`、`stress_cost_usd`，并标明 `currency=USD` 和 `amount_kind=TOTAL`。以合并履约为路径时，输入须已按真实关联汇总净实收、承诺交付和必要费用，并去重采购批次。

费用用 `known_fee_usd`、`fee_status` 和 `fee_ref` 表达。`verified` 用可核金额，包括已确认的零费用。`contract_upper_bound` 用有据的金额上界。未知费用在路径结果中保持空值，仍可核算输入齐全的采购毛利。

## 结果与证据范围

- `PROVEN` 表示提供的完整域通过两条硬约束。`HARD_CONSTRAINT_FAILED` 表示输入完整且有硬约束失守。`PROOF_INCOMPLETE` 保留缺口以及独立查明的 `hard_failures`。空篮子、无有效权重或零收入的篮子标记 `NOT_EVALUABLE`。
- 结果保留分站路径、两个篮子成员权重、证据引用和目标差。`proof_hash` 随曲线、版本、引用、范围和金额变化，等价十进制写法、输入列表顺序和价表捕获时间得到同一指纹。它标识本次计算记录。
- 调用方负责核实原生数量、舍入、优惠资格、必要费用、合并履约、站点传播、篮子窗口、成本成熟度与 FX，随后提供该曲线对应的冻结证据。此函数只校验上述证据输入及其财务计算。F0 的价表读取结果仅提供曲线身份，原生报价需独立取证。当前验证用合成样例，生产报价全域、同批旧新真实回放和断点求解待完成。

## 规划篮子适配

`planning_baskets_v6.build_planning_baskets` 输出可传入 `validate_curve` 的 `main` 和 `recent`。`paid_cutoff` 是本轮支付查询截止点，`as_of` 是完成本轮读证据并冻结的时间。主篮沿 `business_source.historical_period('7d')` 取七个闭合北京付款日。近期源至少覆盖 24 小时。付款人口完整且同平台少于 30 笔时检查 3 日，3 日证据完整且仍不足时沿用主篮并标 `weak_structure`。两次窗口的证据与缺口保留在 `previous_attempt`。

闭合输入直接接 `business_source.collect_historical_attachment` 的私有订单附件。适配器读取 `order_key`、`paid_at`、`available_at`、`platform`、`base_k`、`cost_cny` 和 `source_sha256`。原附件提供合格实付群体和现有支付区间，退款修订缺口保留为 `paid_source_refund_revisions_unverified`。待接入的完整付款源可用同形私有附件提供已核 `population_scope=site266_fc27_coins_paid`、`population_status=complete`、`window_complete=true`、`refund_revision_coverage=complete`，连同版本、可用时间及精确区间。缺成本订单仍贡献权重，历史成本金额不进入当前报价计算。

当前报价映射按匿名 `order_key` 提供 `order_revision`、`curve_key`、`purchase_k`、`path_id`、`quote_ref`、`eligibility_ref`、`fulfilment_ref` 和 `available_at`。映射与订单修订、目标曲线、购买数量一致时才进入聚合。同一路径有不同报价引用时报告冲突。`validate_curve` 核适配器输出成员的 `quote_ref`，回退复制主篮成员及权重。生产近窗读源、完整退款修订、资格与履约报价映射以及当前分层成本适配待接入。
