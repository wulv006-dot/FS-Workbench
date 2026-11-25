# Order 后台协议

以下为 2026-11-25 对仓库证据的复核。RPG 实测日期来自原实现注释，未载明的留空。FC 已核指核对当前源码和合同。

| 状态 | 协议和边界 | 来源 |
|---|---|---|
| RPG 实测，2026-09-23 | 先取验证码建立 PHPSESSID。登录表单 POST 到 /admin/public/dologin.html，返回 JSON code。会话使用 PHPSESSID、user、admin_username。 | opt/d4follow/core_p2pah.py:17–30 |
| 待核 | MLB 历史实现仅在验证码错误时重试，其他错误立即停止。未实测 FC 登录。 | mlb_admin_import_20261012/src/p2pah_price.py:248–290 |
| FC 已核 | 发货记录 GET /order/admin_delivery/index.html，按 gid、aid、cid、genre、start、end、page 和其余原筛选取 HTML。表为 table.table-list，现役成本核对 lot-game、lot-type、lot-genre、页号及窄窗读回。 | releases/fc-coins/fc-pricing-v3-20261026/source/collect_p2pah_cost.py:32–76,254–306 |
| FC 已核 | 发货分页沿实际数据到首个空页，页限触达单列。分页控件文本可只显示局部页码，或混入记录总数，不作为完成证明。 | shared_backend_session/sales_collection.py:390–414 |
| FC 已核 | 详情 GET /order/admin_order/look/id/{id}.html。商品取 look-goods-table 的 data 属性，发货取内嵌 orderDeliveryData，完成状态取首条 log-item 的 order-status-3。 | releases/fc-coins/fc-pricing-v3-20261026/source/collect_p2pah_cost.py:79–96 |
| FC 已核 | 发货统计 GET /stats/admin_index/delivery.html，回读原表单选值和含「订单总数」的统计表。 | releases/fs-dashboard/shipping-profit-20261024/source/business_shipping.py:12,58–91 |
| RPG 实测 | goodsEdit 使用 JSON 数组。保持原值的哨兵为 min_qty 和 unit_price 传 0，cprice 传 null。itemEdit 为金币行数据编辑，表单字段为 data_type、data_val。 | opt/d4follow/core_p2pah.py:32–40，opt/d4follow/_p2pah_srv/p2pah_local.py:151–171 |
| RPG 实测，2026-10-01 | saveprice.html 返回 JSON code、msg。getweb=1 刷新网站，getweb=0 写后台改价日志。两次操作都排除 allserver。 | opt/d4follow/_p2pah_srv/p2pah_local.py:405–416,474–490 |
| RPG 实测 | /admin/setting/clearcachepost.html 返回 HTML，按正文判断回执。记录中前端更新延迟 5–15 分钟。 | opt/d4follow/_p2pah_srv/p2pah_local.py:156,557–568 |
| FC 已核 | 当前 V6.1 不同步 Order 售价。旧标量保存后等待成功 Noty。 | docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md:35,96，fc27_cloud_browser/repricing_dom.js:184–304 |
| 待核 | RPG 注释记录 187 自 2026-09-27 在 Order IP 白名单。当前连通性、旧标量 getweb=0 在 FC 站点的效果待实际核对。 | opt/d4follow/srv_exec.py:12–16，fc27_cloud_browser/repricing_dom.js:184–304 |
