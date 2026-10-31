# B2独立观察消费者首片

沿唯一长期主方案阶段2，不新增路线。Personal B独占模块及测试；A文件、controller、公共schema、迁移、发布清单未改。

## 已合并基线

PR705已于2026-10-31合并，merge `db8879010dc9b51146fd5ebbff465a0130646c7e`。Codex Review对head `4e4faca711bab7f86db4864bbb2a91238b687141`完成，报告未发现重大问题，summary显示无发现/无未解决项；同head PR fast通过。原先未完成的机器人审查已被这次明确核心范围的成功回执替代。不是生产上线证明。

原worktree和`t3/550049c1`保留；只快进到上述主线再开发本片。

## 本片范围与合同

`releases/fs-dashboard/hermes-v2-core-20261020/source/b2_customer_followup.py`为纯函数消费者；对应`test_b2_customer_followup.py`由原`test_core.py`加载。无客户库、采集器、调度器、模型调用、写业务或A接点。

`Observation`是B内部最小观察摘要，不是公共schema变更。A以后负责服务端身份/站点/游戏/目标范围过滤，给出可授权解析的evidence_ref、source/version/as_of、complete/missing、身份可靠性、必要首付/最近付款时点、退款复核标记。暂不接A2 HTTP协议，也不根据客户端传入owner取数。

`assess`消费受信目标提供的observation_anchor、recheck_at及可选expected_next_purchase_at，不自行发明统一7天流失线、高价值门槛、净利润或干预收益。窗口7/14/30按来源截止的北京自然日判断成熟度；来源不足时不报告成熟结果。

结果区分needs_evidence、refresh_required、review_due、investigate、waiting、purchase_observed和stopped。必要证据不足或退款更正先补证，旧截止不能证明到期仍未复购；无新订单也可在到期时复查，相同证据ID不能抑制到期/购买节奏触发。观察后新付款只表示观察事实，不证明营销增量。所有结果均包含不干预选项和business_write_performed=false，不自动触达、发券、改价或退出原账本。

## 验证及后续

冻结模拟案例11项，合并原B1/Core/DeepSeek离线回归后共69项，通过原test_core入口运行；没有真实API或客户数据。覆盖身份歧义、部分覆盖、缺成本字段、退款复核、旧截止、无新订单到期、相同证据重查、个人节奏、停止、复购观察及未成熟窗口。

这是B2独立消费者首片，不是高价值用户全闭环。尚缺真实群体聚合/候选筛选、A2工具接线、最小必要下钻、价值/风险方法、干预与不干预比较、目标持久化及真实变化复查/费用负载计量。B1的OpenAI仍为文本离线子集。

PR704仍为A独占后端首片，原失败日志明确缺openpyxl；本次PR705已使安装条件进入main。A分支须按其交接流程更新主线并取得新CI，不能把旧失败或新条件已合入main当作PR704已通过。未接管或修改A分支，未通知另一端已完成未发生的操作。

回退仅移除本片独立模块/测试加载，不动原账本、人工停止、会话及自动化。原知识收尾plan的Windows字节合同错误保留，未改相关发布器，未宣称同步或发布完成。

## PR706核心审查修正

Codex对fcc621c提出两项P2，均接受并修正：缺项/退款待更正时成熟窗口保持未知；观察锚点之后的较早付款不再遮住后续到期或购买节奏检查。新增purchase_since_anchor仅保存已核历史事实，先走到期/节奏及来源新鲜度判断，再处理尚未到期的付款观察。

补充3项回归（含缺项/退款两个子案例）在原实现复现4处断言失败，修正后B2共14项、原入口合计72项通过。覆盖同一证据ID、锚点后付款、过期截止、到期/节奏及更新截止后的再次评估。未改A或共享文件；新head仍须CI及核心复核，旧head完成审查不等于本片通过。
