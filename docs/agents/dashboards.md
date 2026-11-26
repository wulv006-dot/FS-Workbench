# FS 经营看板与管理台

<a name="fc-categories"></a>

## FC 看板分类（2026-11-06 用户确认）

修改 FC 看板、趋势、导出或订单组利润时，读取[商品整单归属合同](../../docs/planning/fc-dashboard-category-20261106/CONTRACT.md)。知识源候选与真实数据验收状态见[本轮施工记录](../../docs/planning/fc-dashboard-20261106/IMPLEMENTATION.md)；代码存在不代表已部署。

<a name="shipping-profit-current"></a>

<!-- dashboard-shipping-profit-current-20261030 -->
### 经营看板毛利：Order发货统计（2026-10-30用户最终确认）

经营看板全局、分游戏及RS筛选的毛利卡、毛利率和每日曲线，改用Order「统计管理→发货统计」：交货类型=订单发货，按所选日期时间、对应Order游戏ID、网站及原类目/区服筛选。毛利（¥）=同一响应的人民币销售总额−采购总额；分游戏毛利率取该行原值，全局按总毛利÷总销售额计算，不平均各游戏/每日比例，不用Admin美元销售额乘率。每日仍按同一发货统计口径取完整北京自然日，缺日留空，今日区间卡按截至读取时间显示。

本条覆盖2026-10-24逐单实际成本作默认主展示、2026-10-25刷新合同中的相关利润表述，以及本次中途提出但未实施的「订单统计利润率×美元订单额」预估方案。页面保留八张主卡和简洁「Order发货统计」来源，不增加冗长警告；Admin销售、订单、客户及客单价口径保持。主视图不再自动请求actual-profit，原逐单核算接口、归档与Hermes按需查询能力保留。

内部口径：发货统计按交易时间和交货记录汇总，不是付款日已完成订单的同一群体，也未证明排除退款、申诉、欺诈。2026-10-30按精确订单号只读核对，当前「问题订单」「欺诈报告」「已退款·部分退款」各一笔仍在发货统计有金额；结算状态仅未结算/已结算。用户知悉后明确选择直接采用此统计。不得声称它是排除上述损失后的净利润。FC 定价与成本按计划协议执行，继续沿用原会话权限、自动计划、原 ID、CAS、回执和 UNKNOWN 对账。

<a name="business-filters"></a>

<!-- business-filter-layout-current-20261025 -->
## 经营面板范围与游戏筛选（2026-10-25）

PR470/474已合并并沿原publisher分11+1目标发布；本次12个目标的源码与生成路由精确清单见SOURCE-MAP，源码沿releases/fs-dashboard/dashboard-refresh-20261025/source/维护，其他文件保持各自活动源。网站范围→分组游戏→时间，RS三站锁RS；旧summary未传网站仍取原全站，毛利独立缓存兼容，FC明细网站联动。当前合同、逐链路影响、活动SHA和实际验收见docs/planning/business-filter-layout-20261025/。原成本/权限/会话/调度及当前FC定价合同保持；不把Git候选目录或文件装配当新模型/自然周期验收。

<a name="dashboard-refresh"></a>

<!-- dashboard-refresh-current-20261025 -->
## 经营看板八主卡与刷新（2026-10-25）

用户已确认同范围旧值先展示、顶部提示刷新并替换；默认销售额、订单数、毛利、毛利率、新客人数、复购率、新客占比、客单价八卡，其他收起。来源、历史更正核验、当前积压与未支付来源缺口，见 `docs/planning/business-dashboard-refresh-20261025/CONTRACT.md`；活动源码与正式发布/验收见同目录SOURCE-MAP和ACCEPTANCE。不改变逐单毛利公式、权限、会话、调度、当前FC定价合同；Git候选知识不冒充生产目录或真实模型应用。

<a name="shipping-profit-history"></a>

<!-- business-shipping-profit-current-20261024 -->
## 经营看板利润计算规则（2026-10-24）

全局/分游戏主利润与每日曲线按Order“统计管理→发货统计”同网站、游戏、原生类目、交易时间取人民币销售减采购；分游戏原生率、全局总利润÷总销售，不再用Admin付款USD乘参考率。零分母率不适用，未知不补零，负利润保留，非净利润；同订单Admin整单人民币收入减Order实际成本及覆盖证明独立展示。规则见[现行业务基准](../../docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md)及[计算合同](../../docs/planning/business-shipping-profit-20261024/CONTRACT.md)。PR435/436已上线，活动源见[交付与版本](../../docs/planning/business-shipping-profit-20261024/DELIVERY.md)。仅看板Shipping字段迁移；旧primary兼容、Hermes其他报告、当前FC定价合同、权限/会话/调度和原UNKNOWN保持。Git文档/候选知识与生产装入、模型实际使用分别验收。

<a name="management-scope"></a>

<!-- management-all-sites-current-20261025 -->
## 经营管理台全站范围（2026-10-25）

用户明确要求经营管理台所有项目按全部网站实际比较原目标，不限定MMOEXP主站。活动源为`management_rs_recovery_20261025/source/`清单内文件；Git、发布、真实入口及逐日完整性分别见`docs/planning/management-all-sites-20261025/{CONTRACT,SOURCE-MAP,ACCEPTANCE}`。Admin全站原生USD销售/订单及客户字段共用范围；管理台既有USD利润仍为全站销售额×Order同期间全站参考率，RS仅接受已核发货统计百分比，明确预估非实结。经营分析看板主毛利采用同范围Order发货统计，同单实际成本毛利按需独立核算。保留原目标/负责人、两线程/日更/模型计划、权限会话及原回执；旧主站缓存隔离，同期间旧值有据保留，拒绝/未知不补零。自然日更和模型应用不据手动发布认定。
