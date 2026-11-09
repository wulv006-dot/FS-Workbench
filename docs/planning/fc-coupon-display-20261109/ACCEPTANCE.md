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
