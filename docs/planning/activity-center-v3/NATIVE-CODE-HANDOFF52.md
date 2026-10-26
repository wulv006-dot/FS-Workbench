# 原生带码核查52（2026-10-26，本机Chrome只读）

## 已证实的当前页面源码

用户指定 `https://www.mmoexp.com/uk/Fc-27/Coins.html` 本轮在用户Chrome正常打开，未遭挑战。当前Claim & Apply按钮是`.jq-x-copy`，`data-discount`为公开促销码FCCOINS。点击处理器读取该值，执行`sessionStorage.setItem('pending_discount_code', String(textToCopy))`，另执行复制到剪贴板。这里只读代码，没有点击或读取剪贴板。

当前已打开的 `https://www.mmoexp.com/uk/Cart.html` 内联源码存在`applyPendingDiscountCode()`，初始化调用顺序为`syncPaymentMethodPrices()`之后调用。函数读取上述键，非空即removeItem，随后检查`cartNoDiscountRestricted`和`.discount-code`。满足后设`this.discountCode=String(code).trim()`，300ms后点击`.cart-discount-zone .discount .btn`；找不到按钮则直接`that.coupon(that.rate)`。

**因此当前源码不止预填，还尝试自动Apply。** 用户接受“预填+手动Apply”是最低业务要求，不代表我们能把当前消费者描述成仅预填。真实浏览器本轮未触发这条流程，不证明自动Apply成功。

原生`coupon(rate,skipSwitchConfirm)`请求`POST /ajax/discount`，参数`cheaced:'discountCode'`、trim后的`code`及现选coupon或0。存在不可用商品阻断及原券切换确认分支；结果读取`res.data.discount.index.status/msg`。不能把UI“优惠券区域”误认成MemberCoupon发放：这条按钮实际传折扣码。未执行POST。

## 作用域、覆盖与风险

- sessionStorage以origin及标签页隔离，不按/uk路径隔离。可复用需`https://www.mmoexp.com`同标签导航；187 IP、裸域与www不共享，不能宣称跨域复制有效。新标签行为不可依赖。
- 原生写入是单键last-write-wins，没有码过期/活动/商品版本信息。原生读取在检查禁用前删除，失败后不能靠旧键恢复；当前源代码没证明持久重试机制。
- 该传码处理器没有改购物车商品；但Buy Now正常购物车合并行为本轮未实测，不拿代码存取证明不丢已有商品。
- 现有用户Cart非空，本轮完全未更改，不保存购物车/身份明细到工程文件。
- 原生Apply仍负责金额、适用性、互斥。已填、请求中、被拒、实际应用、付款须分别记录，不能直接发成交事件。

## 用户随后更正（同日）

用户明确自动触发Apply符合预期，目标现为自动预填加原生自动Apply，取代先前“手动Apply即可”口径。这是实现方向确认，不是本轮真实应用优惠或加购授权。无需再问自动Apply是否需要；仍需在现场测试前一次批准具体业务范围。

## 本地候选与下一步

`native-code-handoff.js`为未接入运行页的薄合同实现：同源/同标签/已知Cart路径验证，只允许该已观察键；不同旧码冲突不覆盖，Storage异常失败，不造URL参数、不复制Cookie、不主动Apply、不加购。由于下游会自动尝试Apply，调用前必须明确确认消费者行为，默认阻断，不暗中把仅预填接成业务写入。合成测试覆盖作用域、旧码、错误与状态。

后续最小现场验证需要单次批准：指定可用活动测试码、独立空购物车及确定商品/数量，一次正常加购/带码进入原生Cart，允许原生初始化可能触发Apply，读取输入与业务回执，原生移除本次商品并恢复测试状态。当前用户购物车有内容，不作为自动清理对象。无订单或支付；正式码创建和优惠规则仍另批。

本轮证据为浏览器DOM内联源码及当前UI，不是网络成功回执，也未使用HTTP重抓被拒URL。没有读取Cookie/session值、客户信息导出、执行Claim/Buy/Apply或修改后台。截图附件未另材料化；实际本机页面提供对应入口证据。

## 替代旧问题

NATIVE-CODE-CONTRACT50里“带码机制未发现”已由本次证据更新；用户最新明确FC10%OFF、北京时间2026-10-26起一年及截止包含，不再把时区和折扣作为重复问题。精确创建时刻仍在创建前列明。主站原生代码实际自动Apply差异必须随接入说明披露。
