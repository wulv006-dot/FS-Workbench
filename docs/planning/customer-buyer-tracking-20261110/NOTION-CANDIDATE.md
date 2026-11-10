# Notion 摘要候选（待正式读回后同步）

目标：既有「构建 FS 运营决策中枢」项目页、既有「MMOEXP / FS 业务基准与取数手册」页。只在各页新增一段本次变更摘要和版本链接，保留原人工正文、历史链接与已完成收尾标记；以同一 `change_id` 去重。

## 待追加正文

### FC27 客户追踪 Buyer ID 候选优化｜2026-11-10

用户确认候选单笔金额以 ES 原导出的美元订单额决定，门槛仍严格大于当前配置；商品、折扣、新老客、主站与已付款条件不变。ES `buyer_id` 是稳定的私密分组标识，不能据此反推出邮箱。每个 Buyer ID 先取一笔合格代表订单，用原 Admin 只读链路核对订单和邮箱；未核实成功再试同组下一笔。无 Buyer ID 仍按订单处理，异常邮箱不自动合并或加入。日期范围名单按 Buyer ID、网站和已核邮箱去重，旧候选、追踪历史与原任务回执不回写。

现有私有 ES 归档复用，不新增整单副本或 Buyer ID 映射表。实际 XLSX 列名为 `buyer_id`，最近检查的一份归档 33,284 行均有值；Admin 只读核验订单号 IN 条件 20/20 精确返回。代码和知识版本见 [PR #976](https://github.com/wulv006-dot/FS-Workbench/pull/976) 及 [改造记录](https://github.com/wulv006-dot/FS-Workbench/blob/codex/customer-buyer-tracking-20261110/docs/planning/customer-buyer-tracking-20261110/IMPLEMENTATION.md)。

本次正式发布状态、版本、真实入口候选与 Admin 页数、磁盘读回和自然周期结果，以后续实际回执补入；暂存检查或 CI 通过不代表线上已生效。

## 同步时检查

- 先读回两页现有正文，确认没有本次 `change_id`，避免重复新增。
- PR 合并、发布与真实读回各有独立证据后，更新最后一段为实际结果；未验项照实保留。
- 不新增页面，不扩大共享范围，不复制邮箱、Buyer ID、订单号或原始表。
