# FC三平台独立定价实施计划

> 执行按已确认的CONTRACT.md连续推进；各步骤审查实际证据，原writer和调度保持。子任务共用一个接口合同、一个分支/PR和一个发布者，不各造契约。

目标：独立平台真实优惠→财务红线→策略选价→写前核验→后台/公开读回→独立试验/复盘→所有FC消费链路与知识一致。

1. [ ] 冻结真实三平台八日身份/金额/覆盖与维护源；审定平台键、契约版本、成本来源与迁移接口。例子数值不硬编码。
2. [ ] collection：先写金额/身份/缺失/缓存迁移测试，再实现business_source、selective_sources、sources的三平台实际mix/scenarios/replay及缓存投影；不给当前live pooled回退。
3. [ ] root：先写独立红线/同市场不同优惠/价格/单平台缺项测试，实现financial、engine与必要API/写前source边界；更新UI/控制项及原写入消费者，核所有调用方。
4. [ ] experiment：先写旧plan在途/ownership原子迁移、固定节拍、27组合、独立停损/同钟点累计与历史语义测试，实现smart/ledger/runtime/observations/simulation/daily/order_close/monitoring等明确分工文件。
5. [ ] ops_context：逐项证明SBC/Players/Packs/bundle/evolution现役来源与独立能力，缺失实现对应调用方与接口/渲染/计算测试，保护已有业务功能。
6. [ ] 根统一审查及交叉review，执行受影响单测与既有必要CI；183隔离Linux集成，金额/原ID/缓存/迁移/零及未知/真实入口合同均核验。
7. [ ] 统一正式基准与知识版本，运行knowledge_closeout plan；冻结最终PR、CI、合并及确切源码/manifest/保护对象/回退清单。
8. [ ] 原publisher精确发布，原计划同事务迁移；核完整依赖P0仍active、原每60min网格、当前实际单价/哈希与Knowledge读取。
9. [ ] 原下一自然轮端到端验收及跨产品真实入口验算；若结果未知沿原ID对账，不能新触发一轮掩盖。
10. [ ] 同步资料页、Notion受管理摘要及原heartbeat版本；交付收益方向和剩余长期样本/外部阻碍，不把短期样本当长期结论。

初始数据证据：.agent_runtime/fc-platform-discount-20261110/native-result.json。窗口2026-11-01..08，PS1762/XBOX436/PC499，2697单全覆盖；平均优惠分别8.1880766404%/7.5541616626%/8.9451344275%。精确金额及来源见同目录REPORT.md。此段是2026-11-10历史取证，不作为未来新报价。
