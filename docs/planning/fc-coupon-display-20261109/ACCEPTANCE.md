# FC27 优惠展示适配验收

## 配置与现役链路

2026-11-09生产Admin已登录页面及实际GET返回：`/admin/site.GameCouponDisplay/index?site_id=266`的FC规则为game1327/category9623/coupon1343；券原始详情为注册、保留85%、0门槛、封顶$50、不叠码、领取后7天。截图UAT的1242/20%不用于生产。

匿名USD前台及实际`/ajax/goods`核验：PS100K原8.49/展示7.22/赠5K；PC100K原6.12/展示5.20/赠5K。`price_discount`是原数值，`price_discount_format`是券后显示串；不以本记录历史数值建议当前新售价。

现役mode=server/revision3，187 monitor整对象进入snapshot/evidence，额外展示字段无投影丢失；183仅竞品，不在MMOEXP源链。旧local备用模式的白名单不支持新展示字段，本轮不改变其原功能，也不宣称已适配新展示。

原monitor现役8435B含既有sports_outbound，与根目录历史7870B不同；本轮先保留现役完整源再适配，fetch的AST与现役一致。pricing_sources与Git相同且raw原价合同仍成立，不需要改变；其源码、Arab采集、角色manifest及local模块作为保护项。

## 代码与直接检查

基价/加赠/实际优惠金额结构不变；新增独立展示证据和稳定规则指纹，按已确认百分比与封顶核展示金额。展示异常只影响展示证据，不把原价采集伪报失败。smart按观测规则隔离同钟点配对、平台政策及纠偏缓存，首次观测前明确未观测；不改原计划、物理价格窗、财务与固定小时节拍。

183隔离Python3.9.18统一190/190通过、0跳过；冻结LF输入204文本文件，包SHA256为6b168882b07816ecc5844cc46a1d6792eae0b5940e958270311e2a040c993fac。含collector16、发布46、业务128；另两个Node用例沿既有Windows真实Node检查单列，不算入Linux190。Windows原runtime两个CRLF pin失败在LF Linux原断言通过，未放宽断言。

原知识收尾104项：97通过、7项Linux-only未在Windows执行；首次缺tzdata已用任务隔离既有依赖解决。工具pr-fast自检通过；已把storefront直接回归纳入原fc-control组，无新workflow。正式CI、合并、发布、实际新展示回执和自然轮待补。

## 已发布与真实匿名验收

PR951 head a73f1d5057f6f87262d49ac8cdbda69892a3b92b，正式CI42604571122成功，合并9fb7b594716402d2a85ff992febdea3315a10795。固定102源归档SHA e59c2cc13658f7dad51b73b7ba5e8ecaf2c74193379b4c7ab10213b015e9f57a，专用范围仅5目标，其余原范围不扩展。

原publisher发布nav-20261109T105800Z，manifest afb844d25d1596593e012cecaa216f34bb6fbf280d9aff750942c964cecd334b；5目标、166保护项及FC/Hermes/range五服务active读回通过。原备份同名保留，发布未发价格POST、未改计划/账本/队列或策略起点。

18:59真实匿名验收：以现役fc27api uid994及原出站配置，实际collector向临时STATE_FILE采集，页面1次+三平台goods共4次公开读取。PS/Xbox基价8.49/展示7.22，PC6.12/5.20，三平台100K+赠5K、15%及$50封顶均verified。原API数值、商品ID/aid、15档/K单位核实；生产monitor前后SHA相同。规则指纹5fc94b…跨价格不变的证明包含一次实采及同输入离线回放，不冒称两次实采。证据.agent_runtime/t1-collection/coupon-live-anonymous.jsonl；未注册、领券、下单或核销。

知识发布nav-20261109T105900Z：manifest982eca603566c20d167749a9fbcc0bbc42974856001a4e1812d85b505799848d，归档90a2b026f44099eebbacdc4f092ada6422bc9ddd4d2f15820d07b01508935bea；33目标/83保护读回通过、原8选择器available。只更新v3为20261109-coupon-display及共享合同hash，财务版本fc27_dual20_d9_d2_v2保持。今日7个合法保护漂移均按原3个written journal闭环，其余源/路线/权限保留，无服务或模型动作。

统一知识变更KL-5f7ffd5801144f85cf44a40c的Git/生产发布/加载读回/两原Notion页独立摘要均完成，无工具警告；早期未执行候选KL-427ac2f016318fd4c795cb6c被最终冻结计划取代。

18:59只读预检：原smart计划rev2/v2全资源仍归属、无UNKNOWN，43个原自然确认无网格违规；下一轮19:36:56.5895，未手动触发验收轮。展示元数据尚未出现，须由下一自然轮首次观测；不回填上线时间。实际支付/核销、自然轮及长期经营效果仍待分别核验。
