# FS数据与方法发现

2026-11-09：当前AI连接FS后，使用原业务数据和方法自主分析、归因。本轮不接入Hermes会话、代理或历史报告池，不新增报告模板、生成任务或分析模型。已发布目录113项操作、36项范围记录；原服务及客户端真实状态见 [LIVE-ACCEPTANCE.md](LIVE-ACCEPTANCE.md)。

## 现有两工具

1. `fs_list_data_sources`：无参数返回实际用户获准的简短导航；传`module`取得该模块闭合参数schema、来源、分页/资源预算、覆盖缺项和完整`data_methods`。这是实际客户端目录截断后的最小修复，发布状态见验收记录。方法指南引用的操作和来源同步过滤，权限服务故障明确报错，不伪装空目录。
2. `fs_query_data(operation, arguments, data_path?, offset?, limit?)`：只调用目录内的命名业务读取。身份来自OAuth及原FS会话，每次沿原权限校验。原始来源、期间、游标、部分覆盖、错误和实时非快照语义保留。

大响应先返回字段索引，按返回的`data_path`（JSON Pointer）展开；数组用`offset/limit`展示分页，沿`next_offset`继续。这些参数只选择已授权返回值，不改变业务查询范围；`response_view.value_complete`仅说明所选值是否展开，不能替代上游complete/partial/coverage。祖先路径下的来源、日期、币种、实际filters及normalisedScope应与指标一起阅读；跨源网站不一致时不能直接合算。多次读取仍遵循原实时/快照语义，不宣称形成新快照。过大单一字符串或无法展开的大字段索引会明确报response_too_large，不静默截断。

方法导航按本次问题选用，不要求每次全拉或照固定顺序写报告。先查看实际范围目录，选择有效网站、游戏/项目、日期和快照；不能猜ID或使用历史示例数字冒充现值。业务知识读取仅返回真实用户获准的published文本，无匹配路由明确不可用，不创建代理任务。

## 需要区分的口径

| 数据与操作 | 原口径及限制 |
| --- | --- |
| `business.*`、`users.*`、`orders.*` | Admin销售、订单、客户遵循原网站/项目/付款状态和日期范围；USD销售/订单数是客单价，客户平均消费ARPU另算。先核真实coverage，不将范围内最早订单当终生首购。 |
| `business.summary/profit_history/native_range` | 主看板Order发货人民币毛利=同一发货统计响应销售减采购；全局率按同口径总毛利/总销售，分游戏读原行。交易/交货日期轴不同于Admin付款日人群，可能含退款、申诉、欺诈，非净利润。actual与shipping按原来源分别解释。 |
| `management.*` | 已发布全站目标与日报事实，非任意月范围明细。已有USD利润若为Admin销售乘Order同期参考率，应标预估，非逐单实结，不能与发货人民币毛利混写。 |
| `coins.*`、`knowledge.index/read` | 现有 Coins 操作读取已保存状态和证据。阶段 5 按计划修订及原回执解释 `margin_band`，以实际返回字段为准。当前目录未提供逐轮 `strategy_decisions` 的账本专用读取。报表按原交易及成本合同计算实际毛利。 |
| `orders.live/customer` | 每页最多20条，按游标继续；单窗口28个上海自然日、365天边界及原字节/时限。**28天只适用于对应详情，不机械切割全部汇总。**精确邮箱仅受限POST请求体；原权限内邮箱、UID、原订单号可返回。 |
| `marketing.range`、`campaigns.ads/ga4/gsc` | 营销返回的账户、calculation_campaigns、时区和period.sources决定实际范围。活动Google接口固定mmoexp-seasonal，不能代表全部FC27。GA4浏览、落地sessions、purchase事件及GSC点击与Admin付费订单不同。 |
| `channels.*`及流量来源 | 券/码归因并非增量因果；CAC需要同来源花费和可关联新付费客户分母。跨源人群无法关联、归因覆盖不全或群体未成熟时，保留方向判断的证据与限制，不制造精确CAC、漏斗、LTV或因果结论。 |
| `customer_tracking.*`、`sales.snapshot` | 原保存数据/回执仍是业务数据。追踪保留stored_only/refreshed/history/complete；销售快照后页绑定snapshot_sha256，不能跨版本拼接。源码路径或固定传输mode含Hermes不代表调用代理。 |

整单归属、同单成本/优惠、多SKU去重等复用原合同，不在连接器重算业务规则。指南引用的仓库路径及LF规范化SHA仅说明方法版本，不证明该规则已装入每个生产接口或当前数据完整。

## 用户分析和客户维护（2026-11-25）

- 用 `users.catalog` 确定当前范围与发布截止，`users.summary` 或 `analytics.user_section` 请求 `fs-users-v4`。FC 系列用 `game=series:FC`；`cohort_type` 控制首单批次，`customer_type` 控制阶段。返回 202 时汇总只传 `query_id`，分节另传 `section`。完成后按 `snapshot_id` 对数或读取获准名单。
- `customer_tracking.stage_groups` 查单款 FC27 的维护名单，单组须同时传 `tier`、`stage`、`customer_type`。返回 `total`、`offset`、`page_size` 与 `next_offset`，管理员可按原权限读取所在页邮箱。原有候选、观察及发券各按对应业务合同。

取数口径见[用户生命周期](../../../knowledge/customer-tracking/BUYER-ID-CANDIDATES.md)。当前公开目录与原后端需分别验证。

## 订单用户邮箱导出与现有订单操作分开（2026-11-11）

按[现行合同](../../../knowledge/order-email-export.md)，已登录FS数据分析工具可按真实站点、多游戏、日期和其余可用字段导出`user_email`。`progress/status/cid/aid`固定置灰空值，不请求四目录、不提交四条件，使用Admin默认行为；操作人已移除，不继续补权，不能把导出称固定已支付/已完成或已证明的全部状态。旧付费明细投影与旧progress1/status11年度399结果不适用于本次默认口径。

日期沿原生`paytime`，每页20条、最多28日窗口、滚动近365日边界，逐游戏串行遍历全部窗口与游标，实时非快照。只提用户邮箱、不替代支付邮箱，trim/casefold去重保留首次拼写，全部计划完整后才下载真XLSX文本单元格，失败不交部分名单。不发送邮件或证明营销同意；真实actor/private权限、filter/游标绑定及覆盖边界保持，邮箱不进URL/日志。

UI/API已发布源码`158ddab93103695ef13917bbd5368bbbe5c7b179`、生产`nav-20261111T113950Z`（[验收](../order-email-export-20261111.md)），但尚未作为MCP/Hermes导出操作暴露。先看实际目录schema，不猜operation、不给`orders.live/customer`塞专用kind或多游戏参数，也不把普通主站266限制套给专用多站点来源。此方法说明不新增操作、修改计数或证明新连接器已部署。

## 当前明确缺口

- 没有任意SQL或任意GA4维度/过滤工具，也未保证独立ES逐产品折扣全量及完整同单实际采购成本关联。问题需要这些字段时先核实际返回；仍缺则说明对结论的影响，不能从汇总率摊出成本。
- 活动商品业务投影、经营历史bundle、新版FC扩展及若干执行错误详情等剩余面见 [DATA-SOURCES.md](DATA-SOURCES.md)。重复CSV/JSON格式不另算数据缺失。
- Hermes会话和历史生成报告是本轮明确退出的范围，不再标为业务数据待补缺口；原FS功能保持。`campaigns.report`为活动统计读取，保留。

方法源复用 [月报数据教材](../../../knowledge/reporting/fc27-monthly/DATA.md)、[月报索引](../../../knowledge/reporting/fc27-monthly/README.md)、[发货毛利合同](../business-shipping-profit-20261024/CONTRACT.md)、[管理台范围合同](../management-all-sites-20261025/CONTRACT.md)、[整单归属合同](../fc-dashboard-category-20261106/CONTRACT.md)及[实时订单合同](../../../releases/fs-dashboard/tiered-data-access-20261101/LIVE-ORDER-PAGINATION.md)。历史`fc.*`研究工具示例不等于本连接器注册操作，实际调用只以当前目录为准。

## 发布前本地验证（历史阶段）

Windows独立Python环境运行`python -m unittest discover -s fs_mcp_connector/tests -v`：164项，163通过、1项POSIX文件权限测试因平台跳过。新增方法合同覆盖真实来源及LF哈希、注册引用闭合、按原权限过滤、401与503不伪装空目录；原扩展合同核实移除操作在网络前拒绝，并保留客户业务身份和活动统计。该结果不代替Linux、正式CI、本轮发布及真实客户端读取验收；本轮未执行Git或部署。
