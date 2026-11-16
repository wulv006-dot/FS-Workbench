# 追踪与消费归因

## 页面追踪

- **用哪个文件**：线上活动页加载的是 `app/seasonal/activity-analytics.js`（`Weekly-Scout.html` 等页面里 `src="seasonal/activity-analytics.js"`）。顶层 `app/activity-analytics.js` 是旧版，改它线上不会有任何变化——这是踩过的坑。改之前先 `grep -o 'src="[^"]*analytics[^"]*"' app/<Name>.html` 确认。
- **同意与环境**：只有 `FC_ANALYTICS_CONFIG.enabled`、访客在页面里点了 "Allow analytics"、域名在 `allowedHosts`、非预览时才真正上报。验收时**不替访客点同意**。
- **事件白名单**：`permitted` 集合之外的属性一律丢弃；新增属性必须先加进白名单。事件名以 `activity_` 开头（SDK 的 `before_send` 只放行这个前缀）。
- **页面向追踪器交事件**：`activity.js` 的 `signal(name, detail)` 在根元素上发 `fcactivity:<name>`，追踪器监听后 `emit`。现有：`view`、`render`、`selection`、`review`、`cart-result`、`coupon-claim`。
- **券步骤事件** `activity_coupon_claim`：只带 `coupon_state`（`claimed`/`unavailable`）、`coupon_reused`（是否沿用 24 小时内已领的券）、`coupon_id`（券模板 ID）。**不带** uid、邮箱、会员券 ID；有测试断言事件序列化后不含这些字符串。
- 不要用 `uid` 做正则断言：事件自带 `uuid`，会误匹配；改匹配 `"uid"`。

## 从事件到看板

1. PostHog 查询在 `app/analytics/server.mjs`：事件名列表（`names`）和属性列表（`fields`）要同时加新事件、新属性；字符串型布尔要加进 `JSON.parse` 的键列表（例如 `coupon_reused`）。
2. 漏斗在 `app/analytics/funnel-core.cjs`：事件按 `activity_visit_id` 分组，同一访问内重复事件按 `event_id` 去重；新增计数写在同一处，并在返回值里带出。注意测试里不同访问的 `event_id` 不能相同，否则被当成重复事件。
3. 计划汇总在 `app/analytics/statistics-refresh.mjs` 的 `compactSource`：对报告字段严格校验，新增字段用 `count(r.x??0)`，让旧快照读成 0 而不是报错。
4. 看板在 `app/analytics/dashboard.js`：新增计数没定义时（旧快照）不显示，不要显示成 0。
5. 统计日期口径是 UTC，运行时间显示北京时间；这在页面上有说明，别改。

## 消费归因

**优惠码（保留）**：`backend/campaign_backend/discount_revenue.py` 的 `read_revenue`，按 Admin 订单的 `discount_code` 和付款时间汇总；FC 目前只登记 `FCSCOUT10`，三页合计，不归给单页。这部分数据和口径不动。

**优惠券（新增）**：`coupon_usage` 动作，链路是 `bridge.py` → `read_coupon_usage` → Node `app/analytics/coupon-usage.mjs` → `production-server.mjs` 的 `analytics/api/coupon-usage`（需登录）→ 看板面板。

读取顺序：

1. `market.Coupon` 详情，校验是批准的那张券（`id`、`site_id`、`game_id`、`param_code`），取 `fetch_qty`（累计发放）、`used_qty`（累计使用）。
2. `user.MemberCouponLog` 按 `site_id`、`coupon_id`、`use_time` 范围取窗口内使用记录（窗口最长 31 天，内部按 28 天拆）。
3. `order.Order` 按 `order_no IN`（每批 40 个）取订单，**只用来识别退款**和核对金额；订单缺失按日志的状态和金额，计入 `coverage.orders_unmatched`。

输出口径：

- `used_orders` = 日志条数；`paid_orders` = 已付款（订单优先，缺订单时看日志 `status==1`）；`unpaid_orders`；`refunded_orders`（订单 `pay_status==2`）。
- `paid_usd_minor`：订单的美元金额；`discount_usd_minor`：日志优惠金额，仅当日志实付金额与订单美元金额一致时累加。
- `unique_buyers`、`repurchase_orders`/`repurchase_usd_minor`（Admin 的 90 天口径，截至读取时，随时间增长）。
- 转化：`claim_to_use = used_qty / fetch_qty`（累计，分母 0 给空）；`paid_per_use = paid_orders / used_orders`。窗口内逐日发放不读（`issued_in_window: 'not_available'`）。
- 读取失败、字段对不上、状态未知一律失败（看板显示"读取未完成，不记为零"），不返回部分数据。

看板面板在"活动码付款收入"之后，含"优惠码（保留）+ 优惠券 = 合计"对照行。两者互斥，不会同时用在一张订单上。

## 券数据的两个现实限制

- 券真实用起来之前，付款金额、抵扣、复购都是 0，不是 bug。
- 三页共用一张券，归因是三页合计；页面领券步骤只能在行为统计里看（`couponClaims`、`couponReused`）。
