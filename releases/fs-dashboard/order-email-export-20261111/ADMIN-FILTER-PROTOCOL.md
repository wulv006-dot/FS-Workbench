# Admin邮箱导出：现行协议

现行口径统一见[知识源](../../../knowledge/order-email-export.md)。PR999/main158ddab93103695ef13917bbd5368bbbe5c7b179已发布nav-20261111T113950Z，默认单日282及跨月725邮箱真实XLSX验收通过。旧paid1/11、截图静态类型、全原生候选与待发布描述从当前入口删除；审计沿Git历史及施工记录，不再作为可执行默认。

## 已核原生协议（不等于全部方法已获授权）

Admin `/admin/order.Order/index` 的search[i][field|operator|val]：progress/status/site_id/cid/gid/aid/recommend_uid/discount_code/promotion_id/pid/admin_id为=，content/country为LIKE，paytime为RANGE、render=datetime。页面标签下单时间实际为paytime。原生31日前端上限；FS专用分页仍28日/20条/滚动365日。

原生目录：site.Site/siteList id→id,full_title；site.Game/gameList id→id,title；order.Order/getCountryList country→code,country。原生进度order.Order/getOrderProgress、状态order.Order/getOrderStatus(id=progress)、类型order.Order/getProType、区服goods.GameServer/getServerByGid(gid=game)虽已定位，既有身份返回You have no permission；当前面板不读这四目录、不提交对应四条件。操作人已移除，不启用auth.Admin/getGroupAdminList。

原生common-search使用remoteSelect，不是remoteTreeSelect。证据：[订单页面](https://admin.p2pah.cn/assets/index-cac49fc8.js)、[远程选择器](https://admin.p2pah.cn/assets/index-f6e8338f.js)、[公共请求](https://admin.p2pah.cn/assets/index-e643222d.js)。select=true、page、quick_search、initKey、initValue；原生这些列未配置remote=true，不发limit。标签字段按逗号拆分并以` | `拼接。实际目录sites266/games583/country245原始记录是当次取证，非固定业务常量；country不同电话代码变体经原始记录覆盖校验后按country去重242选项，不能把重复原始记录或缺页伪作完整目录。

## FS调用

复用鉴权POST `/dashboard/users/live-orders.json`，kind=order_email_export_options返回三类真实目录，四禁用目录为空并给不可用原因；kind=order_email_export_page传site_id/game_id/start/end_exclusive及实际可用filters。UI编排game_ids，逐游戏game_id映射gid串行读页，游标绑定全filter。面板禁止提交progress/status/cid/aid；通用页面调用契约未借此擅自缩减。user_email字段唯一，非支付邮箱，结果实时非快照。私有RBAC、真实actor/session、共享admission和失败清空保持。

这是UI/API已上线协议；连接器/Hermes未注册邮箱export operation，不能伪造工具名或将普通orders.customer当成此接口。默认全年、营销APP导入未验收。
