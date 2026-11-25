# Order 真实页面回归夹具

2026-11-25 从 187 通过共享 Order 会话获取。每份夹具来自对应路由的一页 GET。原响应只在 187 内存中处理。夹具保留解析器使用的表格、筛选控件、节点布局、分页链接及详情所需的内嵌 JavaScript 变量。每种平台最多保留前三条明细，保留非明细行及原列合并。页面外壳与无关脚本被移除。

- `real_delivery_v6.html`、`real_delivery_scalar.html` 来自 FC27 Coins 近 3 小时与默认历史窗口。两页各有 19 列明细，表尾一行 8 个单元格，首尾的单元格各有 `colspan="6"`。
- `real_delivery_v6_page2.html` 来自随后定位的 V6 第 2 页，其中一条明细的交货类型单元格含独立操作下拉菜单。
- `real_delivery_order_links.html` 来自已知旧采集成功窗口的首屏。商户订单链接保留 JavaScript 包裹形态，包装内容换为无操作表达式。
- `real_channel_delivery.html`、`real_sales_delivery.html` 分别使用渠道成本的主站全游戏筛选和销售采集的 Aion 2 订单发货筛选。两页具有相同的表尾结构。
- `real_shipping_stats.html`、`real_shipping_stats_rs.html` 来自经营看板的 FC27 主站与 RS 全站发货统计，保留各自的六列表头和筛选读回。
- `real_order_detail.html`、`real_attribution_list.html` 来自同一笔去标识化订单的详情页和活动归因精确查询列表，用于核对商品属性、订单链接和发货脚本结构。

脚本在 187 重建白名单节点与属性。订单、发货和商品标识替换为一致的测试值，人员、联系方式、备注和无关文本替换为占位值。日期整体平移，金额改为同格式示例数值。金额用于解析回归。原始 HTML、会话与凭据均未带出服务器。
