# FC27 客户追踪 Buyer ID 候选优化

日期：2026-11-10（Asia/Shanghai）；范围：原客户追踪池，不修改用户分析主键、ES 导出器、权限、定时器、历史订单或 FC 定价。

## 决定与实现

吴律确认候选单笔订单金额改按 ES 导出的美元订单金额判定；折扣仍严格小于当前配置上限。原追踪在 ES 按商品、折扣、新老客初筛后，按 20 条一页完整读取当日 Admin 订单，最终再按 Admin 金额核 `$500` 门槛。2026-11-10 只读的已存扫描显示：11-09 的 839 行 ES、241 笔初筛订单需 13 页 Admin，最终候选 0；11-08 的 1142 行、362 笔需 19 页，最终候选 0。这证明了提速机会，不能外推每一天候选都是零。

新链路：完整 ES 原归档与 SHA 核验 → 原标签、商品、折扣、新老客及 ES 金额初筛 → 每个 Buyer ID 选一笔代表订单，按最多 20 个单号一组发 `order_no IN` 的 Admin 只读查询；未查到时尝试同 Buyer ID 下一笔 → 逐行核订单号、游戏、主站、已付款及付款日 → 同 Buyer ID、同 Admin 邮箱合并候选。Buyer ID 缺失时保留逐订单核验；查到同 Buyer ID 不同邮箱时不合并且禁止加入。候选保留 `ES_candidate_export` 金额来源和 Admin/ES 差异，历史已存候选不改写。所选日期范围的页面再按 Buyer ID、网站、已核邮箱去重，仅显示代表订单。

真实接口小范围对照：2026-11-09 已存在订单的单号筛选返回 1/1，无匹配单号返回 0/0；`order_no IN` 两笔返回 2/2，20 笔返回 20/20，均无其他订单。只输出汇总计数，原订单号、Buyer ID、邮箱及请求凭据未进 Git。本结论限本次原 HMAC Admin 读取身份与接口；代码对返回不在目标组内的行立即拒绝并回原完整日读取，不把 HTTP 200 当精确筛选成功。

2026-11-10 只读检查最新一份原 XLSX 归档：解析 33,284 行，无解析失败；实际列名为 `buyer_id`，该列 33,284 行非空。代码同时接受界面所称 `Buyer ID` 列名；两者均只作不透明分组值，不尝试反推邮箱。

## 来源与发布范围

| 维护源码 | 当前原目标 |
| --- | --- |
| `releases/fs-dashboard/hermes-customer-tracking-20261018/source/tracking_source.py` | **现役** `/opt/fs-hermes-fc/tracking_source.py` |
| 同目录 `customer_tracking.py` | 历史会话源码的兼容更新；当前入口不发布它 |
| `releases/fs-dashboard/hermes-customer-lifecycle-20261019/source/customer_tracking.py` | **现役** `/opt/fs-hermes-fc/customer_tracking.py` |
| 同目录 `frontend/page.js`、`frontend/index.html` | 原 FS 工作台客户追踪页面 |

原 SOURCE-MAP/CURRENT-SOURCE-MAP 与 2026-10-19 读回是历史证据。2026-11-10 只读核对：`fc27-p2pah-session.service` 为 failed，容器不存在；`fs-hermes-fc.service` 与 `fs-business-range.service` 均 active。Hermes `tracking_controller.PrivateClient` 导入同目录 `tracking_private_session.direct_reads`，该适配器再导入同目录 `tracking_source.scan_day`，通过现役 HMAC Admin API 读取。现役 `/opt/fs-hermes-fc/tracking_source.py` 的 SHA256 为 `4544704459ab3681b0dd9ff2df692bfeb255ca66f4b15b4b71522c72ebc181db`，与本次仓库改动前基线一致；不重启已退役 8767 会话容器。现役目标仍须在发布前复核 hash、publisher 保护范围及任务空闲，按原备份与回滚路径发布。不能以重启或改请求 ID 消除在途/UNKNOWN 任务。

本次只读读回的其余现役目标 SHA256：Hermes `customer_tracking.py` 为 `a9ec5f24eae2e369aa6d0c05567e0db76cf349bfed7a44fabba87f8b27864094`，页面 `page.js`/`index.html` 为 `ba7cc477f63aa096685c8e85adc9f6721d9eac373e49ab96cccff2f96525a93a`/`bcf5a1c906d1ab2075c96b5c09e158a2831858b64bf60727564637ce68cc4e8f`。Hermes `customer_tracking.py` 的仓库基线包含尚未部署的 Buyer 身份证据；本次精确发布会一并带入。旧会话目录的源码与现役服务不同步，不以它们作为发布基线，也不触碰其邮箱报告提示词限制。

计划的四个现役载荷（发布前仍须 CAS 复核）：

| 目标 | 现役前值 SHA256 | 本 PR 候选值 SHA256 |
| --- | --- | --- |
| `/opt/fs-hermes-fc/tracking_source.py` | `4544704459ab3681b0dd9ff2df692bfeb255ca66f4b15b4b71522c72ebc181db` | `a811cb4a059eb5ca1cdf309925c2c9323b47f1cf24e1c86f4997e36bc2e79033` |
| `/opt/fs-hermes-fc/customer_tracking.py` | `a9ec5f24eae2e369aa6d0c05567e0db76cf349bfed7a44fabba87f8b27864094` | `9cd1feffda0bfcb85eb39adb2ff6783f3fa1d81fedc738cc0d0360612f764006` |
| `/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/page.js` | `ba7cc477f63aa096685c8e85adc9f6721d9eac373e49ab96cccff2f96525a93a` | `dd2763ee5c34bb9e3349eaeb90718bed2e6e4458c33db04705ad6ef3c2ef38df` |
| 同目录 `index.html` | `bcf5a1c906d1ab2075c96b5c09e158a2831858b64bf60727564637ce68cc4e8f` | `7c92e176c1ee8f7946bda98c510f72590db52854c52baefdf4e0f205ca1a9ce4` |

已准备 `releases/fs-dashboard/hermes-customer-lifecycle-20261019/deploy/buyer_release.py`：绑定原固定哈希 navigation publisher，仅允许这四个现役载荷，原共享发布锁、CAS、空闲检查、备份/回滚与读回保持；额外检查追踪扫描和阶段任务无在途。旧 lifecycle bridge 的 8767 健康检查已经失效，不能原样执行。本桥本地清单静态校验通过。四文件已暂存到独立目录 `/opt/fs-release-stage/customer-buyer-tracking-20261110-pr976-998bd06`，刷新 370 个保护项后，原 publisher 的 `inspect` 只读返回 `sourceCAS=passed`、`protectedCAS=passed`、`mutations=false`；没有执行 `apply`。暂存清单绑定当时提交 `998bd064`，正式发布前须重新绑定最终 Git 版本并复核。原 publisher 的 Hermes/FS Range 重启仍在该范围内；不恢复旧会话容器、不改调度。发布前再次核原服务与 P0 任务空闲；失败保留原发布 ID 和回执核对。

## 存储与验证

本改动不生成第二份 ES 原文件或客户映射表。2026-11-10 只读观察原 ES 归档 59,101,486 字节、148 文件；所在文件系统剩余 118,857,134,080 字节。现有归档源码限制 512 MiB、512 文件并保留至少 64 MiB 空闲空间；现有成功发布后的冗余件清理照旧。代码限制和这次磁盘读数不证明未来所有自然周期都不会积压。

相关 Python 两组单测分别通过 51/33 项；页面 JavaScript 语法通过；知识收尾测试通过 104 项（当前 Windows 环境跳过 7 项 Linux 专属）。本地 pr-fast 在 Windows 共享 UI 文件 CRLF 字节哈希和缺少 Playwright/tzdata 环境处不能完成；PR #976 的 Linux 正式 CI 独立验收。真实入口候选数、Admin 调用页数、磁盘前后量、自然周期须在发布后独立读回；未执行前不得称上线验收。
