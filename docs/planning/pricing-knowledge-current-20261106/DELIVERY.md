# 定价知识整理与上线核验 · 2026-11-06

本页主体是当日10:16 UTC发布快照，其中“未付费实测”等状态仅适用于该时点。当前方法与纠错入口见[定价实测当前入口](HERMES-ACTUAL-ACCEPTANCE.md)及[效果取数与计算](../../../knowledge/reporting/fc27-monthly/DATA.md#定价效果取数与计算)。旧预算结算表不是smart实际效果表，不能再据其为空称“没有归属样本”。

现行入口：[FC知识库](../../../FC知识库/README.md)。

- 项目文档清除“smart待部署”的过时状态；线上计划为smart/ACTIVE，无结束时间，真实资源归属和当前源码已核。
- 更新Hermes智能定价判断方法：比较有效价格曝光窗、同规格实际价格、每小时实际采购毛利及收入/新客取舍；不能用客单价或让利与单量的简单相关代替价格效果。
- fc.pricing.v3、fc.reporting.business更新至20261106-current；双20财务合同版本不变。
- 旧fc.pricing.decision-v15移入archive/retired；历史正文、回执和已冻结任务不删除、不重写。其他账号及原生旧会话的独立路由未修改，不宣称已完成所有profile的清理。
- PR #870，正式CI 42200752651通过，合并cb0619e15ab2a588b278890f16a5b594ae594ba1。
- 原发布器nav-20261106T101600Z完成，manifest SHA256 1eb52007c3bda4178b2755ab189e1680b7c3185238659351426753d03604ac6e；21目标、72保护项读回通过。0服务/业务worker/timer动作。
- FS wulv新任务沿现有知识选择器能够读到新版三个条目；其他路由原样保留。本次未新增付费模型测试，未把装载读回当作模型实际应用或下一自然定价复盘验收。
- 每小时程序执行、价格阈值和Hermes只读判断边界不改。旧发行包仍为回退及已冻结任务保存，不能作为现行教材。

私有证据：.agent_runtime/pricing-knowledge-current-20261106/readback-result.json；本地被替换资料备份在同目录local-before。没有批量删除日志、数据库、历史报告或备份。
