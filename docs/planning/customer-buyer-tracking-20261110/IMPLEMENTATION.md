# FC27 客户追踪 Buyer ID 候选优化

日期：2026-11-10（Asia/Shanghai）；范围：原客户追踪池，不修改用户分析主键、ES 导出器、权限、定时器、历史订单或 FC 定价。

## 决定与实现

吴律确认候选单笔订单金额改按 ES 导出的美元订单金额判定；折扣仍严格小于当前配置上限。原追踪在 ES 按商品、折扣、新老客初筛后，按 20 条一页完整读取当日 Admin 订单，最终再按 Admin 金额核 `$500` 门槛。2026-11-10 只读的已存扫描显示：11-09 的 839 行 ES、241 笔初筛订单需 13 页 Admin，最终候选 0；11-08 的 1142 行、362 笔需 19 页，最终候选 0。这证明了提速机会，不能外推每一天候选都是零。

新链路：完整 ES 原归档与 SHA 核验 → 原标签、商品、折扣、新老客及 ES 金额初筛 → 每个 Buyer ID 选一笔代表订单，按最多 20 个单号一组发 `order_no IN` 的 Admin 只读查询；未查到时尝试同 Buyer ID 下一笔 → 逐行核订单号、游戏、主站、已付款及付款日 → 同 Buyer ID、同 Admin 邮箱合并候选。Buyer ID 缺失时保留逐订单核验；查到同 Buyer ID 不同邮箱时不合并且禁止加入。候选保留 `ES_candidate_export` 金额来源和 Admin/ES 差异，历史已存候选不改写。所选日期范围的页面再按 Buyer ID、网站、已核邮箱去重，仅显示代表订单。

真实接口小范围对照：2026-11-09 已存在订单的单号筛选返回 1/1，无匹配单号返回 0/0；`order_no IN` 两笔返回 2/2，20 笔返回 20/20，均无其他订单。只输出汇总计数，原订单号、Buyer ID、邮箱及请求凭据未进 Git。本结论限本次原 HMAC Admin 读取身份与接口；代码对返回不在目标组内的行立即拒绝并回原完整日读取，不把 HTTP 200 当精确筛选成功。

## 来源与发布范围

| 维护源码 | 当前原目标 |
| --- | --- |
| `releases/fs-dashboard/hermes-customer-tracking-20261018/source/tracking_source.py` | `/opt/fc27-cloud/marketing-session-20261009/tracking_source.py` 及原会话镜像 |
| 同目录 `customer_tracking.py` | 原会话镜像的同名文件 |
| `releases/fs-dashboard/hermes-customer-lifecycle-20261019/source/customer_tracking.py` | `/opt/fs-hermes-fc/customer_tracking.py` |
| 同目录 `frontend/page.js`、`frontend/index.html` | 原 FS 工作台客户追踪页面 |

原 SOURCE-MAP/CURRENT-SOURCE-MAP 与 2026-10-19 读回是历史证据，不以本文件宣布新版本已部署。现役目标须在发布前重新读取 hash、publisher 保护范围及空闲状态，按原备份与回滚路径发布。不能以重启或改请求 ID 消除在途/UNKNOWN 任务。

## 存储与验证

本改动不生成第二份 ES 原文件或客户映射表。2026-11-10 只读观察原 ES 归档 59,101,486 字节、148 文件；所在文件系统剩余 118,857,134,080 字节。现有归档源码限制 512 MiB、512 文件并保留至少 64 MiB 空闲空间；现有成功发布后的冗余件清理照旧。代码限制和这次磁盘读数不证明未来所有自然周期都不会积压。

相关 Python 两组单测、页面 JavaScript 语法、项目 pr-fast 和正式 CI 以各自执行结果补记。真实入口候选数、Admin 调用页数、磁盘前后量、自然周期须在发布后独立读回；未执行前不得称上线验收。
