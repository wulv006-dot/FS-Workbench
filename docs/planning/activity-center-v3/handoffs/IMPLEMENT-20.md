# IMPLEMENT20：已证付款状态接线与未激活规则交接

## 本次代码

复用业务基准的Admin order/index付款枚举：整数/字符串1为paid、2为refunded（含部分退款观察）。实际分析链原先把2默认标unknown，本次更正；仍不从状态、return_money或订单金额推算退款额、净额或活动行实收。旧持久快照不迁移；只有后续明确窗口重读才产生新事实版本。一般写入、活动销售、生产配置和正式生效窗均不改变。

依据：docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md“逐笔订单查询一个月上限”；rea_admin_contract_20261021/patch_paid.py；releases/fs-dashboard/user-analytics-20261022/source/user_config.json的refund_policy。相关合成测试涵盖1/2类型、未知/bool/float、重复拉取、历史保留、金额/分摊保持未知。没有访问真实订单或执行退款。

## Seasonal原型参数与原任务决策复核

出处：app/seasonal/campaign-data.js、vault-core.js、event.js，均来自原限定页交付。

- 六游戏固定区均为演示5%优惠；随机区每轮最多8张、不重复、已锁卡保留，10/15/20/25四档等概率。featuredGames为FC/Diablo/PoE的运营演示槽位，不是实测人气排行。
- 初始刷新钥匙0；每次刷新消耗1，全部锁定不能刷新。DEMO-1/2/3各最多计一次，每个增加1钥匙；最多3个示例回执，没有真实注册验证或发奖。
- 主题日期均为CONCEPT：Halloween OCT24–NOV02、Thanksgiving NOV20–NOV30、Christmas DEC15–DEC28、BlackFriday NOV27–NOV30。不是批准的年份/时区/生产生效窗。
- FC原ACTIVITY-PRICING-CONTRACT明确当前实售价额外10%、按既有互斥叠券码积分、对应品类利润规则；promotion-policy/catalog无正式start/end。无需活动券ID，服务端活动价格层引用即可。

### 更正此前两个问题

撤回“是否需要正式随机/邀请玩法”的提问。原任务用户消息 01a169b4-6dc4-76f1-bd8b-a467e99ac6e3 已要求邀请好友有效注册刷新；01a169b6-e49b-7011-87ca-981189aa93d9 要求随机商品池；01a169b9-c32c-7b11-b04c-a26fab32cd90 要求热门游戏及默认较低固定优惠区。这些是已定功能，必须保留，不能降为可选增强或误归 Matchday 排除项。

原规划目录 docs/planning/mmoexp-seasonal-events-20261024/V2-DELIVERY.md 第7/12/15行明确5%纯演示、有效注册换刷新钥匙、3次为演示上限，金额/概率/次数/日期均设计参数；第37行明确FS四主题草稿起止日期留空；第51–58行已有 get_vault/create_invitation/confirm_referral 后端合同，有效注册条件和归因窗仍待确认。V3-DELIVERY.md“商品映射”明确固定5%与随机10/15/20/25%未获正式活动授权。README的V1固定玩法已被V2替代，不再用旧段落否定随机功能。

G1须保留完整原页面与上述后端接口交接，客户端演示不能代表真实身份/注册/奖励/权威抽取已接通。尚未发现正式数值或窗口的批准记录；先由监工对照既有原始决策，不要求用户重复解释已定功能。最早源任务单轮超出支持的历史读取大小，未绕过限制读取原始会话文件。

FC ACTIVITY-PRICING-CONTRACT.md 第5/8/9/84行已确定额外10%、对应品类利润规则及按行币种精度，撤回任何关于折扣幅度的疑问。已查该合同、catalog/promotion-policy、MMOEXP-FS-AUTO-PUBLISH-HANDOFF.md，未见正式起止时间/时区；后者第159–166行明确优惠叠加与权威活动报价回执。仅能说明已查材料缺窗口，不能说用户从未决定。未激活配置不阻止G1安全工程与交接；生产激活前需将已有批准窗口落入配置，确无记录才由监工统一询问。

## 技术外部依赖（不是用户猜字段）

- FC固定行历史合同已知：new_items、id/group/num/attr/aid；主站核兼容性及活动报价/实际优惠回执。原始合同建议的activityQuote不是已存在路由，不调用。
- 币类显示K/M到实际请求数量、Aion goods/model数量表优先级：由现有购买消费者源码或字段合同证明。9个403公开路径不重试。
- paytime按北京时间已有同源消费者依据；不能自动推广到券日志use_time、退款时间或折扣应用时间。当前analysis的source_utc_offset用于优惠应用时间，本次不填默认值。
- 金额业务口径已知：订单/优惠USD、实付原币；仍缺实付字段精度及退款字段累计/事件、币种、稳定标识、更新/撤销语义。状态2只证退款观察，不证金额。已拒退款样本不换路。
- 核心BenefitRef支持campaign，但实际analysis仅投影coupon/discount；主站提供实际活动层字段后本方仍须接线，不强迫FC改用券来迎合现有代码。

UI17已通过，不再写1307。专用benefit_restore未验单列，不作为新增G1门槛。未设置正式生效窗不阻止安全代码交付，但不能据此声称已运营或G1全部完成；G2真实交易未启动。
