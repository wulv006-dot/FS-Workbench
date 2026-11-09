# FS数据与方法发现

2026-11-09：当前AI连接FS后，使用原业务数据和方法自主分析、归因。本轮不接入Hermes会话、代理或历史报告池，不新增报告模板、生成任务或分析模型。当前本地目录113项操作、36项范围记录；本轮变更须发布后生效，原服务及客户端真实状态见 [LIVE-ACCEPTANCE.md](LIVE-ACCEPTANCE.md)。

## 现有两工具

1. `fs_list_data_sources`：返回实际用户获准的操作、闭合参数schema、来源、分页/资源预算、覆盖缺项和`data_methods`。方法指南引用的操作和来源同步过滤，权限服务故障明确报错，不伪装空目录。
2. `fs_query_data(operation, arguments)`：只调用目录内的命名业务读取。身份来自OAuth及原FS会话，每次沿原权限校验。原始来源、期间、游标、部分覆盖、错误和实时非快照语义保留。

方法导航按本次问题选用，不要求每次全拉或照固定顺序写报告。先查看实际范围目录，选择有效网站、游戏/项目、日期和快照；不能猜ID或使用历史示例数字冒充现值。业务知识读取仅返回真实用户获准的published文本，无匹配路由明确不可用，不创建代理任务。

## 需要区分的口径

| 数据与操作 | 原口径及限制 |
| --- | --- |
| `business.*`、`users.*`、`orders.*` | Admin销售、订单、客户遵循原网站/项目/付款状态和日期范围；USD销售/订单数是客单价，客户平均消费ARPU另算。先核真实coverage，不将范围内最早订单当终生首购。 |
| `business.summary/profit_history/native_range` | 主看板Order发货人民币毛利=同一发货统计响应销售减采购；全局率按同口径总毛利/总销售，分游戏读原行。交易/交货日期轴不同于Admin付款日人群，可能含退款、申诉、欺诈，非净利润。actual与shipping按原来源分别解释。 |
| `management.*` | 已发布全站目标与日报事实，非任意月范围明细。已有USD利润若为Admin销售乘Order同期参考率，应标预估，非逐单实结，不能与发货人民币毛利混写。 |
| `orders.live/customer` | 每页最多20条，按游标继续；单窗口28个上海自然日、365天边界及原字节/时限。**28天只适用于对应详情，不机械切割全部汇总。**精确邮箱仅受限POST请求体；原权限内邮箱、UID、原订单号可返回。 |
| `marketing.range`、`campaigns.ads/ga4/gsc` | 营销返回的账户、calculation_campaigns、时区和period.sources决定实际范围。活动Google接口固定mmoexp-seasonal，不能代表全部FC27。GA4浏览、落地sessions、purchase事件及GSC点击与Admin付费订单不同。 |
| `channels.*`及流量来源 | 券/码归因并非增量因果；CAC需要同来源花费和可关联新付费客户分母。跨源人群无法关联、归因覆盖不全或群体未成熟时，保留方向判断的证据与限制，不制造精确CAC、漏斗、LTV或因果结论。 |
| `customer_tracking.*`、`sales.snapshot` | 原保存数据/回执仍是业务数据。追踪保留stored_only/refreshed/history/complete；销售快照后页绑定snapshot_sha256，不能跨版本拼接。源码路径或固定传输mode含Hermes不代表调用代理。 |

整单归属、同单成本/优惠、多SKU去重等复用原合同，不在连接器重算业务规则。指南引用的仓库路径及LF规范化SHA仅说明方法版本，不证明该规则已装入每个生产接口或当前数据完整。

## 当前明确缺口

- 没有任意SQL或任意GA4维度/过滤工具，也未保证独立ES逐产品折扣全量及完整同单实际采购成本关联。问题需要这些字段时先核实际返回；仍缺则说明对结论的影响，不能从汇总率摊出成本。
- 活动商品业务投影、经营历史bundle、新版FC扩展及若干执行错误详情等剩余面见 [DATA-SOURCES.md](DATA-SOURCES.md)。重复CSV/JSON格式不另算数据缺失。
- Hermes会话和历史生成报告是本轮明确退出的范围，不再标为业务数据待补缺口；原FS功能保持。`campaigns.report`为活动统计读取，保留。

方法源复用 [月报数据教材](../../../knowledge/reporting/fc27-monthly/DATA.md)、[月报索引](../../../knowledge/reporting/fc27-monthly/README.md)、[发货毛利合同](../business-shipping-profit-20261024/CONTRACT.md)、[管理台范围合同](../management-all-sites-20261025/CONTRACT.md)、[整单归属合同](../fc-dashboard-category-20261106/CONTRACT.md)及[实时订单合同](../../../releases/fs-dashboard/tiered-data-access-20261101/LIVE-ORDER-PAGINATION.md)。历史`fc.*`研究工具示例不等于本连接器注册操作，实际调用只以当前目录为准。

## 本轮本地验证

Windows独立Python环境运行`python -m unittest discover -s fs_mcp_connector/tests -v`：164项，163通过、1项POSIX文件权限测试因平台跳过。新增方法合同覆盖真实来源及LF哈希、注册引用闭合、按原权限过滤、401与503不伪装空目录；原扩展合同核实移除操作在网络前拒绝，并保留客户业务身份和活动统计。该结果不代替Linux、正式CI、本轮发布及真实客户端读取验收；本轮未执行Git或部署。
