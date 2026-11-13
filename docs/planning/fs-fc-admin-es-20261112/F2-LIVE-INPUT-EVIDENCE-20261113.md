# FC27 V6.1 报价证明的真实输入核对

2026-11-13 13:09–13:28（北京时间）。使用现有 FS 只读目录、187 Admin 8912、Order 8768 共享读取及已有发货缓存。查询范围为 MMOEXP/site266、Admin gid1327、Order gid1322。原始订单号、券号、客户及供应商字段仅用于原处匹配。以下 SHA256 标识当次响应或缓存。

## 已核实的入口和字段

| 来源 | 实际读到 | 可证明范围 |
| --- | --- | --- |
| FS `orders.live` / `/dashboard/users/live-orders.json` | 11月11日首20条，partial，有后续游标。响应含付款时间和状态，没有商品实收、数量及费用字段。 | 实时付款成员分页。沿 FS 私有权限保留原字段限制。 |
| Admin `GET /admin/order.Order/index` | 同日 site266/gid1327、原生 pay_status=1 筛选总293条。首20条均有 `amount_usd_format`、`amount_rmb_format`、`before_discount`、`discount`、`points`、`paytime`、状态和商品内容。 `pay_money_format2` 20条可读，其中4条USD与 `amount_usd_format` 相等。 | 历史订单金额及商品承诺快照。`pay_money_format2` 按数组自带币种读，保留 `currency_code`。源返回付款显示金额和订单金额，均未取得商家结算费分解。 |
| Admin `GET /admin/user.MemberCouponLog/index`；`GET /admin/market.Coupon/index` | 同单及对应模板各一条。日志有 `coupon_id`、`discount_amount`、`use_time`、`status`；模板有 `mode_type/reduce/attain/max_reduce`、`is_open`、有效期、`fetch_scene/product_type/site_id/game_id`，本条无 `stacking/is_stackable`。 | 实际核销与关联模板可复用。当前全部已发权益、VIP/积分、新客登录资格、活动码互斥及购物车分摊仍需原结账端证据。 |
| Order `GET /order/admin_delivery/index.html`，`sn` 精确查询、默认交付类型 | 普通单1行、已有拆单2行，均有原发货ID、交易时间、数量、赠送、采购单价/总价。两条拆单行的数量×采购单价均在¥0.01内匹配总额；另一普通行超出该误差，样本数量列均未附单位。 | 按站点＋商户订单号关联，以原发货ID逐条去重。优先留原采购总额；实际发货分母不能由单价相乘反推全量。交易时间和采购完成/成熟时点分开。 |
| Order 同入口交付类型筛选 | 1订单发货、2采购打款、3销售补发、4销售赠送。选3且不传单号时，200响应的明细表确实不含「订单来源」「商户订单号」，仍有交易时间、数量及采购总价等列。所见汇总行不是可关联采购明细。 | 现有 `channel_cost_source.collect` 固定 genre=1。可见补发入口不能直接套普通发货列位或按邻近时间配单。需找到同单补发/追回账或明确的关联字段。未结算/已结算是页面筛选枚举，不能当采购完成日期。 |
| Order 现有 `/var/lib/fs-channel-effects/order-deliveries.json` | 截取11月11日00:00–11月13日09:00，主站FC 719条发货、710个商户订单，其中9个有多条发货。719条均保留 `qty/gift/cost_unit/cost_total/trade_at`；均无 `quantity_unit/settle_status/completed_at/batch_id/component/recovery_amount`。 | 核定范围内的普通发货记录。缓存完整标志指发货采集窗口。FS `channels.profit` 同日可用，仍沿同单普通发货成本/可关联覆盖口径。 |
| 主站 `/Cart.html` 与历史验收 | 11月9日 Coins 100K+赠5K，原生商品额$8.31，Items码逐条被拒，买方附加费$0.54，总额$8.85。现有 `host-adapter.readCart` 读取商品及数量。11月13日公开匿名商品响应已有原生展示证据。 | 已有访客单路径核验可说明客户总付额如何展示。仍需当前V6各真实价格、资格与多件分摊路径的原生确认，以及商家承担费用或明确合同上界。 |

Admin 首20条的 `peace_contract_fee`、`return_money`、`payback` 皆可解析且当页值为0。显式 `payment_fee`、`gateway_fee`、`refund_amount`、`order_completed_at` 均未出现。这些字段现象不能证明全部必要费用、退款修订已覆盖。现有用户事实读取已保存 `return_money` 原字段，但仍需对到有金额的已知退款单才能证明币种、净扣减、发生时点和修订语义。 [既有付款显示币种合同](../halloween-code-revenue-20261030/PLAN.md) · [主站 Coins 原生购物车证据](../fc27-weekly-console-20261109/deploy/commerce/ACCEPTANCE.md) · [11月13日匿名数量与展示](NATIVE-QUANTITY-20261113.md)

## 同单采购分母复核

- 真实 Coins 样本的 Admin 原商品承诺买2500K、另赠60K。Order 同单发货行的原「数量」为2560、「赠送」为0、「¥采购单价」为0.390000、「¥采购总价」为998.40。`2560 × ¥0.390000 = ¥998.40`，数量与历史承诺交付量相等，原数量列没有独立单位文本。
- 原先发现差额的一笔为同游戏 PS 道具。Order 详情显示 `category_id=2`、数量1、单位空。发货原「数量」为1、「赠送」为2309、「¥采购单价」为0.430000、「¥采购总价」为993.30。此行 `(1 + 2309) × ¥0.430000 = ¥993.30`，原因在原始数量／赠送结构，不能套到 Coins 行或当 K 成本。详情可见生成时间，未取得采购完成时间。
- 普通采集继续用原始交易时间、原采购总额及原身份。候选附加交易改时、原结算字段，D2 私有记录保留采购单价。F2 用同一订单的 Coins 原承诺量及同单有效发货总额识别上面的可核对形状，仅返回汇总覆盖。非零赠送、金额不符或缺字段的记录保留观察成本金额与分母未核状态。对应交易改时和结算原值不作采购完成时间。
- 补发专用解析读出17列结构。11月1日00:00至11月13日09:00不传订单号时首页面无明细，使用同一 PS 道具原单号时返回1条销售补发。精确查询结果仍无来源和原订单号，备注无关联号，因此保留关联未核。现役普通发货缓存仍按原交货类型1读取。

## 当前购物车与配置权限

当前匿名 US/USD 空购物车 GET HTTP200。原生内联代码从 `goods.payFee[method]` 取得 `feetype` 与 `feeval`，按结账商品USD金额和现币汇率对齐买方显示费用。`peace_contract_fee` 独立显示。`computeCouponPrice` 读取购物车限制、订单金额和优惠数据，`/ajax/discount` 与 `/ajax/coupon/register-popup` 的操作未执行。空购物车不包含已登录资格和生效券全域。

当前8912 `GET /admin/index/index` 业务code1，包含 `site.ConfigPay`。在主站范围读取 `GET /admin/site.ConfigPay/index` 得到 HTTP200／业务401，未取得支付配置。`market.DeliverySetting` 未出现在当前菜单，未调用。`market.Coupon` 和 `market.Discount` 可见，优惠模板与实际用券证据见上表。

## 响应指纹

| 只读来源 | SHA256 |
| --- | --- |
| Admin 20条订单响应 | `89fc86c84f542d3227004805250a1f8c639dea8c1a40a7d4ccc4c40d2d04844d` |
| 同单券日志 | `96be0a6a5329355b7c4c5590a4486560cb2060b0bfa54c6823040340e19812d1` |
| 对应券模板 | `adce26ec579e73f1ce6d546a687db6211c814bf77f879b4b8ae2a3a824773172` |
| Order 普通单 / 拆单 | `db7ed980276115e63fb8ecb46a4a63a77d5146e6516f0a8f60357ed042341717` / `009ee939aa9fe5ae89582b2b1cdce33006060bc6d091bbfb84b85e9c011079b8` |
| Order 补发筛选表结构 | `ea436b4d3557a12f12dfa0500c834105c9738f5b2c34611dc2bb073e3a8dff43` |
| Order 补发专用解析的无单号／同单响应 | `ba7725c544ca1e04628c40dd1e3cfd863dfb6ee15f02893256bc7240bdaab0b1` / `f57a7757776ce9a780a80e57b26957b26b08d211bab473184a167199aa1a9c46` |
| Order 普通发货缓存 | `6355aac420981f1bfa51c95d6c07f2b787765f8b4446e0823ce612421782d3ae` |
| 同单Coins Admin响应／Order发货页 | `d050fa1f4645f17a70e05e2847f8a7c31d8830bed97e1357d460df91ccbf71ad` / `ee5177bbd2833d66fc0972d755ab3769b5d4df92c67f4804e84476157d675bda` |
| PS道具 Order详情 | `e33365a2dab5b7f1aa4769e38e58ac8fdcfe2be44ebc9d7c427cbe519c566fb6` |
| Admin ConfigPay 业务401 | `a5330c0734992322a339e2fbbee88e501fe7a5a4a66f634dcdeb54e22242e1e0` |
| 原生匿名空购物车（内联函数） | `40663c74fcb6e908d7e2d117529d831b5bf1b7264772db2fe189a9d48782f861` |

## 候选验证

活动采集器 `/opt/fs-hermes-fc/channel_cost_source.py` 指纹 `416aa286ca50fd2fdcccc490ae616a75d7736f49dcf0bfb3da7064b7793c7393`，候选保留现役 `lxml` 启动时预加载。187 现有 Python 在内存运行候选采集器的原读取函数，用同一原单号只读精确核对 Coins 发货。候选源码工作副本 SHA256 `e71a92eb141bca6d8b019232b100d42ece72d1b8c61659a1f475c534ff01ac98`，现场响应 SHA256 `888c21af4c449ade5fd5d920ff67e6a62c40cc34c35c3963265558882f14bcba`。读取一行，原数量、赠送、单价、总价均一致，结算和交易改时在该行为空。未启动缓存写入入口。

Windows F2 11项、D2 10项、现有渠道39项通过。183隔离 F2 11项、D2 10项通过。实际毛利组34项通过，1项需要测试环境的 `lxml`；187原生只读核对覆盖了候选解析器的真实输入。候选文件独立于已冻结的 ES 发布包。

## 生产证明仍缺的来源

- 商城／财务提供 V6 当前可售数量及资格路径的结账净商品收入和订单级折扣分摊，以及同路径商家承担的支付及必要履约费用或合同上界。可从已有结账确认记录和收单结算费率取证。购物车显示的买方附加费无法确定商家承担金额。
- Order 提供与原订单或履约批次相连的采购完成事件、失败重发／补发、追回采购款及相应修订。优先找原同单账和真实批次关联，已有发货缓存继续提供已观察的成本证据。
- Admin 提供同单退款原金额、币种、发生时点及修订。按原单对账后再构造退款后实收。缺口落到对应平台、数量和资格层，后续由已核原生输入驱动 V6 证明。

现场只执行读取，代码改动在本地。实际生产证明仍为 `PROOF_INCOMPLETE`。
