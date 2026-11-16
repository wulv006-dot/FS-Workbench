# 接口与字段

以下都在 2026-11-16 用正式站读回验证过。拿不准的字段先去 Admin 页面逆向（见末尾"查字段的办法"），不要靠探测硬撞。

## 主站 carnival 接口（活动页同源调用，带登录 Cookie）

信封统一是 `{code:1,data:{…}}`，`code!==1` 视为失败。请求都带 `X-Requested-With: XMLHttpRequest`、`credentials:'same-origin'`、`cache:'no-store'`、`redirect:'error'`。

| 接口 | 用途 | 关键字段 |
|---|---|---|
| `GET /ajax/carnival/user` | 当前登录态 | `logged_in`、`uid` |
| `GET /ajax/carnival/coupon?slot=<slot>` | 该槽位可领的券 | `enabled`、`logged_in`、`slot`、`error`、`list[]`（`coupon_id`、`can_claim`） |
| `POST /ajax/carnival/claim`（`slot=…&coupon_id=…`，表单编码） | 领券 | `claim_status:'claimed'`、`coupon_id`、`member_coupon_id` |

槽位命名：`fc_weekly`、`fc_sbc`、`fc_trio`（`native-code-handoff.js` 的 `COUPON_SLOTS`，`page_id → slot`）。

语义（`claimActivityCoupon` 已实现，别改成别的）：

- 读 `coupon` 失败、`enabled!==true`、`slot` 不匹配、没有可领券 → 返回 `unavailable`，页面**静默回退优惠码**，页面仍可销售。
- 未登录 → `login_required`，弹登录框，**此时不加购**。
- `claim` 的 POST **只发一次、不重试**；结果无法确认 → 抛 `COUPON_CLAIM_UNCONFIRMED`，页面停下提示"稍后再试"，不加购。
- 领券成功后把 `member_coupon_id` 写入 `sessionStorage.pending_member_coupon_id`；购物车页的 `applyPendingMemberCoupon()` 按 `li[data-id]===member_coupon_id` 选中该券。券与优惠码互斥，领券成功时不暂存 `pending_discount_code`。
- 24 小时限领：`localStorage['fs-fc27-coupon-claims-v1']` 按 uid 记最近一次领取；窗口内再次确认沿用同一张会员券，不再发 `claim`。仅浏览器本地，换设备或清存储可绕过。

## 主站登录接口

- 邮箱：`POST /user/login.html`，表单字段只有 `usname`、`passwd`、`remPwd`、`site_id`（**不带** `loginbindkey`），`Accept: application/json, text/javascript, */*; q=0.01`，`Content-Type: application/x-www-form-urlencoded; charset=UTF-8`。失败返回的提示原样展示（红框、保留输入、按钮恢复），超时 15 秒。
- 第三方：`POST /user/login.html?act=loginapp&selfurl=<当前页>&site_id=266&type=google|facebook` → 返回 `redirect_url`；授权后跳回 `selfurl?ba-user-token=…&member_welcome=1`。
- 主站页面会在服务端把这个令牌换成 `ba-user-token` Cookie 再去掉参数；活动页没有这一步，所以：模块加载时**立即从地址栏去掉令牌**（早于统计脚本和浏览历史），令牌只放内存，只交给 `GET /ajax/html?ba-user-token=…&member_welcome=1` 一次，之后再刷新顶栏、恢复之前的选择。
- 顶栏登录态来自 `/ajax/html` 片段：未登录是 `jq-user-area`；已登录取 `img.user-avatar-img`（头像）、`img.member-level-avatar__frame`（等级框）、`.cart-total`（购物车数量）。未登录只显示 Log In，已登录只显示头像，无下拉。
- 登录前的选择用 `sessionStorage['fs-fc27-login-resume']` 保存 20 分钟，登录后恢复并继续领券。

## Admin 配置（写操作需授权）

- **TempActivity**（站点 266，code `carnival`）：`carnival_enabled`、起止时间、`carnival_slot_coupons`（JSON：槽位 → 券 ID 数组）。统一券时三个槽位都指向同一个券 ID。当前活动窗口到 2026-12-02，之后需要开发把接口改成常驻。
- **券模板**（`market.Coupon`）：入口券必须 `fetch_scene=3`；`mode_type=2` 为百分比，`reduce=90.00` 表示九折（10% off）；`time_effect=2` 为领取后相对有效期，`days=7`；带 `param_code`（例 `carnival_202611`）；`site_id=266`、`game_id=1327`。券自带累计计数 `fetch_qty`（已领取）、`used_qty`（已使用）。
- 券不叠加、不与积分混用，沿主站规则；页面文案写"券与积分不能合并"。

## Admin 只读接口

- **在 187 上读**：共享 Admin 代理 `http://127.0.0.1:8912`，请求头 `server: true`、`think-lang: zh-cn`，路径形如 `/admin/<模块>.<控制器>/<动作>`。只读核对示例：
  - `/admin/market.TempActivity/index?code=carnival&site_id=266`
  - `/admin/market.Coupon/edit?id=<券ID>`
  - `/admin/user.MemberCouponLog/index?limit=…&page=…&order=id,desc&search[0][field]=…&search[0][val]=…&search[0][operator]=…`
- 过滤参数：`search[i][field|val|operator]`，运算符 `=`、`IN`、`LIKE`、`RANGE`（范围另加 `search[i][render]=datetime`，值为 `起,止`）。订单列表支持 `order_no IN a,b,c`。
- 这个代理账号**没有** `user.MemberCoupon`（发放记录）权限，会返回 `code:401 You have no permission`；有 `market.Coupon`、`market.TempActivity`、`user.MemberCouponLog`、`order.Order`。后端读取层 `backend/campaign_backend/adapters.py` 的 `LIST_ROUTES` 已登记 `coupons`、`coupon_logs`、`orders`、`discounts` 等只读路由。
- 用户本人的 Admin 令牌（`admin.p2pah.cn` 页面 `localStorage.adminInfo`）可在用户授权下做**只读**请求（接口域 `admin-api.p2pah.cn`，请求头 `batoken`）；永远不要把令牌打印或写进任何文件。

## `user/memberCouponLog` 字段（用券记录，按订单一行）

列表字段：`id`、`site_id`、`order_no`、`title`、`status`、`member_id`、`coupon_id`（券模板）、`member_coupon_id`（会员券）、`use_time`、`discount_amount`（优惠金额）、`ip`、`remark`、`member{uid,usname 打码}`、`memberCoupon{grant_batch_no}`、`order{before_discount（订单价格）,amount（实付金额）}`、`repurchase_count`、`repurchase_amount`。

语义（来自 Admin 页面标签文件和线上数据）：

- `status` 在页面上标为"订单支付状态"：1 已付款，0 未付款（券已用到订单但没付款）；未付款的日志对应订单常不在 Admin 订单列表里。
- 金额都是美元，即使订单币种是 GBP/MXN 等；订单价格 − 优惠金额 ≈ 用券后商品小计，实付金额可能还含手续费、积分抵扣，两者不必相等。
- 复购次数/金额：用券后 90 天内、同站点已支付订单（不含本单），随时间增长，读取时截止。
- 过滤支持：`site_id`、`coupon_id`、`use_time` 范围；个别已付款日志的订单在订单列表里查不到，按日志状态和金额处理，不要整体失败。

`user/memberCoupon`（发放记录）：`status` 0 未使用 / 1 已使用 / 2 已过期，含 `start_time`（发放时间）、`end_time`、`grant_batch_no`。需要该权限才能读；**不是必须**——`memberCouponLog` 已足够做使用与转化。

## 查字段的办法（拿不准时）

Admin 前端是 BuildAdmin（Vite）。入口 `https://admin.p2pah.cn/` 引用 `assets/index-*.js`；其中 `./backend/zh-cn/user/<页面>.ts` 对应的懒加载块（如 `memberCouponLog-*.js`）是该页面的字段中文标签和枚举（例如 `"status 0":"未使用"`）。直接下载这些公开的静态文件读标签，比反复调接口猜字段含义快得多。视图组件本身不在主包静态引用里，不用花时间找。
