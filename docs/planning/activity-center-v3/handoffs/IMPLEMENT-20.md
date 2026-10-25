# IMPLEMENT20：已证付款状态接线与未激活规则交接

## 本次代码

复用业务基准的Admin order/index付款枚举：整数/字符串1为paid、2为refunded（含部分退款观察）。实际分析链原先把2默认标unknown，本次更正；仍不从状态、return_money或订单金额推算退款额、净额或活动行实收。旧持久快照不迁移；只有后续明确窗口重读才产生新事实版本。一般写入、活动销售、生产配置和正式生效窗均不改变。

依据：docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md“逐笔订单查询一个月上限”；rea_admin_contract_20261021/patch_paid.py；releases/fs-dashboard/user-analytics-20261022/source/user_config.json的refund_policy。相关合成测试涵盖1/2类型、未知/bool/float、重复拉取、历史保留、金额/分摊保持未知。没有访问真实订单或执行退款。

## Seasonal准确原型规则与两个用户问题

出处：app/seasonal/campaign-data.js、vault-core.js、event.js，均来自原限定页交付。

- 六游戏固定区均为演示5%优惠；随机区每轮最多8张、不重复、已锁卡保留，10/15/20/25四档等概率。featuredGames为FC/Diablo/PoE的运营演示槽位，不是实测人气排行。
- 初始刷新钥匙0；每次刷新消耗1，全部锁定不能刷新。DEMO-1/2/3各最多计一次，每个增加1钥匙；最多3个示例回执，没有真实注册验证或发奖。
- 主题日期均为CONCEPT：Halloween OCT24–NOV02、Thanksgiving NOV20–NOV30、Christmas DEC15–DEC28、BlackFriday NOV27–NOV30。不是批准的年份/时区/生产生效窗。
- FC原ACTIVITY-PRICING-CONTRACT明确当前实售价额外10%、按既有互斥叠券码积分、对应品类利润规则；promotion-policy/catalog无正式start/end。无需活动券ID，服务端活动价格层引用即可。

可由老D合并提交用户的两项问题：

1. Seasonal当前先保留原演示并交接正式权益依赖（推荐，不激活），还是要把固定5%及随机四档方案转为正式经营规则？选择后者还需确认概率/适用商品/资格/成本边界与真实邀请要求，不能把一个“继续”解释为这些值全部批准。
2. FC九折活动的正式开始、结束时间和时区是什么？未确定前保持未激活，代码与G1交接仍可继续。

## 技术外部依赖（不是用户猜字段）

- FC固定行历史合同已知：new_items、id/group/num/attr/aid；主站核兼容性及活动报价/实际优惠回执。原始合同建议的activityQuote不是已存在路由，不调用。
- 币类显示K/M到实际请求数量、Aion goods/model数量表优先级：由现有购买消费者源码或字段合同证明。9个403公开路径不重试。
- paytime按北京时间已有同源消费者依据；不能自动推广到券日志use_time、退款时间或折扣应用时间。当前analysis的source_utc_offset用于优惠应用时间，本次不填默认值。
- 金额业务口径已知：订单/优惠USD、实付原币；仍缺实付字段精度及退款字段累计/事件、币种、稳定标识、更新/撤销语义。状态2只证退款观察，不证金额。已拒退款样本不换路。
- 核心BenefitRef支持campaign，但实际analysis仅投影coupon/discount；主站提供实际活动层字段后本方仍须接线，不强迫FC改用券来迎合现有代码。

UI17已通过，不再写1307。专用benefit_restore未验单列，不作为新增G1门槛。未设置正式生效窗不阻止安全代码交付，但不能据此声称已运营或G1全部完成；G2真实交易未启动。
