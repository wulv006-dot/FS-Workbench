# 旧策略只读回放验收｜2026-10-27

两个退役算法已能通过真实研究入口回放同一原决策快照，保持源码版本与旧财务合同；没有恢复旧策略的生产写权。

## 原问题与修复

原快照cfd497f9-3f43-550f-84df-5182b1ff7d5b于北京时间07:12:56开始采集，07:14:25保存决策。旧入口仅取evidence.checked_at（采集开始），稍后正常取得的汇率被当作“未来来源”，两个算法均误报pricing_source_stale。

PR534改用原保存的created_at作为决策时点，旧格式缺该字段时保持原checked_at。晚于保存时点的来源仍拒绝，不自动向后移动截止、不放宽新鲜度。Hermes研究桥同步改从已有认证API按原pricing_snapshot回放，不再依赖可能不存在的可执行quote，也不丢失原时点或使用裁剪过的公开输入。

测试先复现错报，再验证修复、截止后来源拒绝、无quote快照、接口范围、只读返回及原账本不变。正式CI40420607878/job121913793837共224项通过。merge为d0f588be34ab3bbcb243e1d54888ee6d5ecc280a；沿原publisher发布5目标，nav-20261026T233800Z，manifest SHA为6cb027f11109e6c5cd4455646bd82ff32dbae59db6dcfa1ebdb0663c1c3cde00，实际91/91目标SHA匹配。

## 同一原快照的真实回放

原快照时点2026-10-27 07:14:25.056147北京时间，存档指纹43d4cc49de2555ddb79684a01fd40aa61920fa0322db171e16d9ffc056066870。以下为历史算法输出，单位USD/100K购买档，并非当前推荐或执行价格。

| 算法 | Console | PC | 核验结果 |
| --- | ---: | ---: | --- |
| 退役80/15/5 | 9.12 | 8.67 | 原双10算法可回放，read_only=true |
| 退役ItemD2R钉价 | 8.54 | 8.55 | 原双10算法可回放，read_only=true |
| 当前V3冲额/双20 | 无可执行候选 | 无可执行候选 | 原始自然结果INFEASIBLE，不被旧输出覆盖 |

旧源码哈希分别为91f8d143e21e05544b17442bd8a20d3735f62caa4aa5b182584a4fd4c4ec993a与f68459feb07ff59690a4a6b716e9760a7c556e74b92b7e02dfa4c57d23eb0a42；仅修改共用回放入口，旧算法文件未变。当前真实售价和原执行仍以定价台公开读回为准。

真实链为已部署SimulationBridge→原认证HTTP API→私有原快照→固定旧源码。两个结果均available、execution_authorized=false、training_eligible=false；未新增模型调用或采价。operations与experiment_assignments仍各3条，前后联合指纹dc88bfa553378509260300d38dda3ae48e2a04727732b77627fe0096a67c3825一致。

## 使用入口与限制

Hermes只读研究方法为SimulationBridge.legacy_replay(snapshot_id, name)，name仅支持legacy_80_15_5及legacy_itemd2r_parity。缺原快照、非法名称或超出原截止的来源仍返回缺口或拒绝；GET不创建执行单，不返回私有订单/完整证据。

已登录的维护人员可直接查看该历史例子的[80/15/5回放](https://47.85.224.112/api/fc27/cloud/pricing/v3/legacy-replay/cfd497f9-3f43-550f-84df-5182b1ff7d5b/legacy_80_15_5)和[ItemD2R回放](https://47.85.224.112/api/fc27/cloud/pricing/v3/legacy-replay/cfd497f9-3f43-550f-84df-5182b1ff7d5b/legacy_itemd2r_parity)。前者已从登录后的真实Chrome入口读回相同结果；两个方法均已通过真实研究桥核验。

这是旧/新算法在同一冻结经营输入上的行为对照，不是按旧价真实成交的收入、不等于固定订单金额重算，也不是因果收益。原失败sidecar与新版本成功凭据分开保留；不改写旧历史任务或模拟结果。月度完整价格窗口、原优惠条款、历史汇率及退款链缺口仍按历史覆盖文档处理。
