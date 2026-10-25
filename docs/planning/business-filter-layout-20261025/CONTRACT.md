# 经营看板网站与游戏筛选

用户要求：范围在第一项，游戏在第二项，时间随后；移除重复参考范围和RS网站选择。当前为已实现待发布候选，生产状态以ACCEPTANCE为准。

- 范围：全部站点、MMOEXP、RSOrders、RSMalls、RSFast。后三项强制RS并禁用游戏选择；切回前两项解锁。
- 游戏：全部；球类FC27/NBA2K27/NFL27/MLB26/CFB27；RPG为POE2/D4/AION2/DARK_AND_DARKER/WOW_FOREVER；综合为RS/MAPLESTORY_CLASSIC/ARC_RAIDERS/ARENA_BREAKOUT_INFINITE/COD_BO7。FC26旧链接保留历史选项。
- 使用原生分组选项、全局布局和主题；label显式关联控件。RS保留商品类目与更多区服，当前积压与支付时间分开。
- 新状态b_site=all/mmoexp/rsorders/rsmalls/rsfast；旧b_profit_site、b_rs_site与b_profile链接可迁移。不向数据接口传UI字段。
- 非RS显式profit_site=all/main；RS使用原rs_site/rs_category/rs_server。MMOEXP Admin原生统计site=266，全部仍沿原共享接口；毛利币种、同订单群体、覆盖和每日合计不变。
- FC明细随顶部范围选择all/main；MMOEXP时禁用细分网站，全部站点仍允许原卫星细分。细分无同粒度成本时不展示整游戏利润；新旧范围不得串值。
- 未指定profit_site的既有summary调用与旧归档键保持原样，仍返回原全站Admin；新显式网站有独立缓存身份。旧query.site历史文字不代替source.normalisedScope/filters证据。
- 共享会话、池/锁/冷却、授权、定时、v15/80-15-5与UNKNOWN保持。仅需原范围服务重启与Nginx重新载入，不操作模型/定价/采集或业务工作器。

发布范围为SOURCE-MAP列出的11个精确目标（含4个新版本界面文件、4个后端文件、2个规则文件和路由）；沿原publisher、CAS、备份与保护清单。规则和Notion已获本次用户同步授权；本新清单的合并/上线须按HOTFIX第6条完成具体授权。
