# FC27 优惠展示适配验收

## 配置与现役链路

2026-11-09生产Admin已登录页面及实际GET返回：`/admin/site.GameCouponDisplay/index?site_id=266`的FC规则为game1327/category9623/coupon1343；券原始详情为注册、保留85%、0门槛、封顶$50、不叠码、领取后7天。截图UAT的1242/20%不用于生产。

匿名USD前台及实际`/ajax/goods`核验：PS100K原8.49/展示7.22/赠5K；PC100K原6.12/展示5.20/赠5K。`price_discount`是原数值，`price_discount_format`是券后显示串；不以本记录历史数值建议当前新售价。

现役mode=server/revision3，187 monitor整对象进入snapshot/evidence，额外展示字段无投影丢失；183仅竞品，不在MMOEXP源链。旧local备用模式的白名单不支持新展示字段，本轮不改变其原功能，也不宣称已适配新展示。

原monitor现役8435B含既有sports_outbound，与根目录历史7870B不同；本轮先保留现役完整源再适配，fetch的AST与现役一致。pricing_sources与Git相同且raw原价合同仍成立，不需要改变；其源码、Arab采集、角色manifest及local模块作为保护项。

## 代码与直接检查

基价/加赠/实际优惠金额结构不变；新增独立展示证据和稳定规则指纹，按已确认百分比与封顶核展示金额。展示异常只影响展示证据，不把原价采集伪报失败。smart按观测规则隔离同钟点配对、平台政策及纠偏缓存，首次观测前明确未观测；不改原计划、物理价格窗、财务与固定小时节拍。

183隔离Python3.9.18统一190/190通过、0跳过；冻结LF输入204文本文件，包SHA256为6b168882b07816ecc5844cc46a1d6792eae0b5940e958270311e2a040c993fac。含collector16、发布46、业务128；另两个Node用例沿既有Windows真实Node检查单列，不算入Linux190。Windows原runtime两个CRLF pin失败在LF Linux原断言通过，未放宽断言。

原知识收尾104项：97通过、7项Linux-only未在Windows执行；首次缺tzdata已用任务隔离既有依赖解决。工具pr-fast自检通过；已把storefront直接回归纳入原fc-control组，无新workflow。正式CI、合并、发布及真实匿名新展示已通过，见下节；自然轮单独验收。

## 已发布与真实匿名验收

PR951 head a73f1d5057f6f87262d49ac8cdbda69892a3b92b，正式CI42604571122成功，合并9fb7b594716402d2a85ff992febdea3315a10795。固定102源归档SHA e59c2cc13658f7dad51b73b7ba5e8ecaf2c74193379b4c7ab10213b015e9f57a，专用范围仅5目标，其余原范围不扩展。

原publisher发布nav-20261109T105800Z，manifest afb844d25d1596593e012cecaa216f34bb6fbf280d9aff750942c964cecd334b；5目标、166保护项及FC/Hermes/range五服务active读回通过。原备份同名保留，发布未发价格POST、未改计划/账本/队列或策略起点。

18:59真实匿名验收：以现役fc27api uid994及原出站配置，实际collector向临时STATE_FILE采集，页面1次+三平台goods共4次公开读取。PS/Xbox基价8.49/展示7.22，PC6.12/5.20，三平台100K+赠5K、15%及$50封顶均verified。原API数值、商品ID/aid、15档/K单位核实；生产monitor前后SHA相同。规则指纹5fc94b…跨价格不变的证明包含一次实采及同输入离线回放，不冒称两次实采。证据.agent_runtime/t1-collection/coupon-live-anonymous.jsonl；未注册、领券、下单或核销。

知识发布nav-20261109T105900Z：manifest982eca603566c20d167749a9fbcc0bbc42974856001a4e1812d85b505799848d，归档90a2b026f44099eebbacdc4f092ada6422bc9ddd4d2f15820d07b01508935bea；33目标/83保护读回通过、原8选择器available。只更新v3为20261109-coupon-display及共享合同hash，财务版本fc27_dual20_d9_d2_v2保持。今日7个合法保护漂移均按原3个written journal闭环，其余源/路线/权限保留，无服务或模型动作。

统一知识变更KL-5f7ffd5801144f85cf44a40c的Git/生产发布/加载读回/两原Notion页独立摘要均完成，无工具警告；早期未执行候选KL-427ac2f016318fd4c795cb6c被最终冻结计划取代。

18:59只读预检：原smart计划rev2/v2全资源仍归属、无UNKNOWN，43个原自然确认无网格违规；下一轮19:36:56.5895，未手动触发验收轮。展示元数据尚未出现，须由下一自然轮首次观测；不回填上线时间。该段为预检时点，后续自然轮见下节；实际支付/核销及长期经营效果仍待分别核验。

19:00原小时outcomes任务498395于19:02:56完成、attempt0；截至19:00:09覆盖query_complete=true且绑定原计划/revision/策略，263条结果220成本已知、43待成本。既有price_trace_unknown/refund/mismatch保留，不以任务完成认定样本成熟或盈利。证据.agent_runtime/t2/coupon-hourly-20261109T1913.json。

## 同事与副机AI分享资料

按负责人2026-11-09提供的一期需求，已在现有FS资料空间创建并读回[MMOEXP 新模板价格展示一期规则](https://chatgpt.com/space/page_31f376585358819186d561afbb6e5875)。覆盖FC/Aion 2新模板、未登录/有适用券/无适用券三种状态、Buy Now/Claim文案及入口、示例与生产配置边界和自动定价接口注意事项；未改变资料权限。Figma视觉细节、客户登录/购物车/核销及Aion技术适配不据此认定完成。

## 原19:36自然轮

原job `cycle:5cecacfd-19f7-584a-8845-16adbef9b13d:1794224216:r0` 的scheduled_at保持2026-11-09 19:36:56.589500+08:00；attempt0、20:36:56.589500仍为下一固定due。于19:40:11.155798按原op `bddf0d00-6f33-52dd-8bf8-5f3ed5bb099e` COMPLETED / ORDER_ADMIN_CONFIRMED，44自然确认、pending0、无UNKNOWN/待对账、网格违规0，未手动触发、重放或更改周期。

新snapshot `72d1fa6e-6fa2-5ee4-b386-04f088688f69` 三平台display verified，15%/封顶50美元；采价时Console基价8.49/展示7.22，PC6.12/5.20。Console首次known为19:38:09.866012，PC19:38:10.356012，均以实际观测为下界；historical_unobserved保留，按平台隔离的display政策键均落库一致，当前WAITING_MORE_DATA，不宣称效果已成熟。

原rev2 / smart-bidirectional-v2、Console C / PC B，财务pass_all=true、pricing_scope=100k_package_only。Console PS/XBOX基价8.49→8.33，Order明确本次推送成功且sync_confirmed=true，Admin同商品单位价PS/XBOX=0.0833、PC=0.0612；selected仅PS/XBOX，PC保持6.12。Admin all_baseline确认三平台产品163329309/163329275/163329343；这些与页面展示SKU各自独立，不混用身份。

原close_receipt的public_verification未确认：cache_clear_rejected、HTTP200/api_code0，未重清缓存或重写价格。Order+Admin已按现行合同完成，本记录不把它提升为PUBLIC_CONFIRMED。证据：.agent_runtime/t2/coupon-natural-confirmed-20261109T1942.json 与 coupon-original-final-receipt-20261109T1942.json。

19:42:14独立写后公开只读采集已见新价：PS/XBOX基价8.33、展示7.08，PC仍6.12/5.20，三平台100K+赠5K、15%/$50封顶均verified。仅同原fc27api身份的页面1次与三平台goods3次、临时STATE_FILE，生产monitor前后hash相同，没有清缓存、重试、改价/周期/模型或客户登录。本次与18:59真实不同基价观测的规则指纹5fc94b…一致，新增跨真实价格变动的稳定性证据；不修改原operation的公开核验失败记录。证据.agent_runtime/t1-collection/coupon-live-post-natural.jsonl。
