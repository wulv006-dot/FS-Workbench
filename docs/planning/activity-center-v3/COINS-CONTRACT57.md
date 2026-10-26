# Coins 原生只读合同补证（2026-10-26）

## 已观察，而非真实加购验收

原本机 Chrome 现有正常标签 `https://www.mmoexp.com/Fc-27/Coins.html?cy=USD`，2026-10-26 12:24:44 UTC。本轮 CDP 只读可用；读取当前 DOM、jQuery 已绑定事件正文及帮助函数。未重新 HTTP 抓取，未点击 Buy Now、Cart、Claim、Apply，未读写 Cookie、购物车内容或 pending code。

实际购买按钮是 `.jq-add-cart.btn.butNow`，不是顶部只滚动到页首的 `handleBuy()`。按钮数据：`data-type=new_gold`、`data-id=163329311`、`data-tp=1`；无 `data-group`、`data-aid`、`data-attr`。当前 `#inputNum.value=1000`，PS；对应元素没有 `.item-num`，该商品没有已加载 SKU 选择数组。缺省 top category 为2，不触发 top-up 专用结算分支。

已加载事件的核心语义：

```js
group = button.attr('data-group') || $('#inputNum').val();
num = parseInt(isNaN(itemNum) ? 1 : itemNum); // 再执行原生最小/最大校验
payload = {category, id, group, num, attr, aid};
$.post(langPageUrl('/Cart/add.html'), payload, response => {
  if (isCartAddOk(response) && tp === '1') location.href = langPageUrl('/Cart.html');
});
```

当前 US 语言前缀为空。对合成对象只调用原页面 `jQuery.param`，未请求网络，得到：

`category=new_gold&id=163329311&group=1000&num=1&attr=&aid=`

因此已证当前 PS 1000K 的消费者编码：**group=1000、num=1，赠送50K不加入提交数量**；不能编码为 group=1050 或1000000。沿用当前按钮产品163329311，平台由该产品身份体现，不自行补 aid。模型41217957关联来自已核Admin证据，不声称模型ID出现在上述POST。

`isCartAddOk` 会拒绝顶层 code=0/status=false 或购物车载荷 status=false，再接受 code=1 或明确购物车结果结构。前端调用路径是加车成功后转 Cart，不是直接订单创建。但本轮没有 POST 回执，仍不证明服务端实际行为、价格或购物车合并效果。

## 范围和剩余依赖

- 数量编码本身不再需要真实加购来猜测。新增 `FCActivityCore.coinsPayload` 仅提供上述精确 US/USD/PS/模型/商品/档位的纯序列化合同，不启用原生写路径；其他平台/币种不能继承该证据。
- 现有购物车曾显示2件；本轮未进入或改动。Cart 初始化可能消费既有 `pending_discount_code` 并自动 Apply，不能未经授权进入 Cart 验证。
- 既有 US/USD 页面显示 $86.80、1000K+50K，匹配该次Admin档位86.8。该样本仅支持有限参考，不证明Admin全局币种规则或将来区域促销均不变。最终金额仍由主站验证。
- 未验证真实加车、自动 Apply、订单/付款；未创建经营优惠码。当前生产仍 RELEASE42，本文与纯函数为本地候选。

## 当前消费者价格字段补证

同一已加载页面的 `tableData` 仅选中商品163329311，unit=K，`goods_list[1000]` 的实际公开数据：`full_price=86.8`、`full_price_format=86.80`、`price=86.8`、`discount=100`、`discount_off=0`、`price_discount=86.8`、`price_discount_format=86.80`、`give=50`，`listRate=1`。已加载数量 blur 处理器对精确档位直接使用 `price_discount_format`，原价使用 `full_price_format`，赠送单独展示。未执行该处理器。

这进一步证明当前组合的主站当前价字段，不需要拿 `full_price` 再减一次既有档位折扣。仍未证所有Admin `more.price` 与主站上述字段的普遍转换规则；尤其区域特惠或 `more.discount!=100` 时不能从当前单点推导。

## 用户另行批准的清空（与数量只读验证分开）

父转交用户“你清空就好了”，明确仅授权当前购物车移除。通过同一商品页原生迷你购物车完成，未导航Cart页，未读取/删除pending_discount_code。已读迷你购物车 `getCart()` 是 `/Cart/cartShow.html`，原生逐项移除为 `/Cart/del`；无自动Apply调用。

展开后badge=2、唯一商品行。`.clear-all` 是空span，高度0；点击超时未形成可操作点击，未重复该动作。改用当前可见原生`.remove`按钮一次，随后badge=0且侧栏自动关闭。重新展开触发独立原生GET读回，**2026-10-26 12:31:34 UTC：badge=0、rows=0、可见Your cart is empty**。未留存商品/客户明细。未加购、Claim、Apply、Checkout、订单或付款；该结果不构成新加购授权。
