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

发布准备时新增 `releases/fs-dashboard/hermes-customer-lifecycle-20261019/deploy/buyer_release.py`：绑定原固定哈希 navigation publisher，仅允许这四个现役载荷，原共享发布锁、CAS、空闲检查、备份/回滚与读回保持；额外检查追踪扫描和阶段任务无在途。旧 lifecycle bridge 的 8767 健康检查已经失效，不能原样执行。本桥本地清单静态校验通过。四文件暂存于独立目录 `/opt/fs-release-stage/customer-buyer-tracking-20261110-pr976-998bd06`；当时以提交 `1e8cb540` 重绑清单并刷新 370 个保护项，原 publisher 的 `inspect` 只读返回 `sourceCAS=passed`、`protectedCAS=passed`、`mutations=false`。该次准备没有执行 `apply`；随后实际发布及读回见下文。原 publisher 的 Hermes/FS Range 服务操作在本次范围内；不恢复旧会话容器、不改调度。失败保留原发布 ID 和回执核对。

## 存储与验证

本改动不生成第二份 ES 原文件或客户映射表。2026-11-10 只读复查现役 `/opt/fs-hermes-fc/es_order_structure.py`：热归档写入前限制 512 MiB、512 文件，并保留至少 64 MiB 空闲空间；超过限制则返回容量错误，不继续堆积。原归档读回为 107,909,225 字节，所在文件系统剩余 118,843,346,944 字节；此前观察值 59,101,486 字节，仅说明观察间归档增长，未归因于本改造。本次不修改 ES 导出与原有归档维护；现有成功发布后的冗余件清理照旧。热归档限制和这次磁盘读数不证明包括冷归档在内的未来所有自然周期都不会积压。

相关 Python 两组单测分别通过 51/33 项；页面 JavaScript 语法通过；知识收尾测试通过 104 项（当前 Windows 环境跳过 7 项 Linux 专属）。本地 pr-fast 在 Windows 共享 UI 文件 CRLF 字节哈希和缺少 Playwright/tzdata 环境处不能完成；PR #976 最终 HEAD `9f1489e3` 的 Linux 正式 CI 两轮均成功（run 1877、1878）。

## 发布与真实入口读回（2026-11-10）

吴律确认一次性清单 `KL-157678d5b4dcabdb780a9b0d` 后，[PR #976](https://github.com/wulv006-dot/FS-Workbench/pull/976) 合并至 `main`，合并提交 `4286b171664616c8ec5fd332215b0ce6c5309227`。发布清单重绑该版本，SHA256 `12035f876ca5b002f4b52f75ad79e979b5fb2eaa9e063f2f85accfffc8c06644`；原发布器 `inspect` 对四目标及 370 个保护项均通过。原发布器以 `nav-20261110T104121Z` 执行 `apply`，备份在 `/var/backups/fs-navigation-20261006/nav-20261110T104121Z`。发布回执为 `applied-awaiting-actual-http-role-acceptance`，后续四个目标哈希与上表候选值逐一一致，Hermes、FS Range 服务均 active，业务 worker 定时器操作数 0。回滚应沿同一发布 ID 和备份进行，保留客户 DB、原扫描任务和回执。

已登录管理员从真实 FS 页面打开客户追踪，配置版本 2 正常加载，页面显示“候选订单金额以 ES 导出为准”；11-09 已存区间名单返回 1/1 天、0 候选。生产私有读取对原 11-09 归档重新计算：ES 839 行，符合 ES 金额门槛 0 笔，Admin 请求 0 页，结果 `available`。另一份原 10-30 归档用现役 Admin 身份只读扫描：ES 1247 行，符合 1 笔，请求 1 个订单、1 页，后台分页完整并返回 1 位候选。该旧归档没有 Buyer ID；新归档 11-09 虽有 Buyer ID，却无金额合格订单，因此真实 Buyer ID 合并量仍未获得非零样本，不能用本次零结果宣称合并效率已自然验收。两次只读验收不重写旧候选库或原任务编号。

验收后原 ES 归档仍为 107,909,225 字节，暂存发布包 289,938 字节，文件系统剩余 118,838,779,904 字节（使用率 42%）。现有容量限制继续有效；冷归档长期占用和后续自然扫描效果尚未验证。两篇既有 Notion 页均以同一 `change_id` 增量追加摘要并读回，原正文与旧标识保留；见 [Notion 同步记录](NOTION-CANDIDATE.md)。正式 Git 知识版本为 `fs.customer.lifecycle@buyer-candidates-20261110-v1`；未单独发布新的 Hermes 知识加载包，也未声称模型已在自然任务中采用该条目。
