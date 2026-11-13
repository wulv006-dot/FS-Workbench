# 原生数量报价脚本：定向增量核对

2026-11-13 只读 GET `https://www.mmoexp.com/mmoexp-v250528/js/goods/mlb26-landing.min.js`，HTTP 200，25016 字节，SHA256 `77a707f72b3debdf880529fe76d85276f1902a8e0ede4ed0beff37ddb141e618`。本机原始文件 `.agent_runtime/native-quantity-20261113.js`，没有执行页面初始化、登录、加购、结账或后台写入。

现有 `source/pricing_sources.py` 的 CUSTOM_SHA 是 `ad92c2d1c36bfd4d0de8fe4c6cb566be3957209aec86cb3f64fcd9299074c10d`，验证日为 2026-10-22。字节版本已不同；没有取得旧脚本逐函数差分，因此不声称全部报价语义改变，也没有更新现役 pin。

## 当前脚本可以证明的前端行为

- `numRegular` 接受正整数字符串；FC 页面无效输入回退 DOM `data-min`。blur 还按最低档限制下界，以 `goods_list` 枚举的最后一档乘 100 作为输入上界。该行为仅是前端输入规则，不能视为后端拒绝非法数量的证明。
- 固定档 blur 使用响应行的 `price_discount_format` 展示最终金额，原价展示 `full_price_format`。不能仅以 Admin 的 `more.price` 证明客户优惠后结账金额。
- 自定义档循环先计算当前枚举档的 `100 * price / (quantity * discount)` 并 `toFixed(8)`，再判断是否大于购买量并 break；因此边界前的派生单价可能来自下一档。折扣取已选的前一档，派生单价与商品 `unit_price` 按 JavaScript 的原始类型及 `>` 比较结果选择。不能把自定义数量简单按100K价格线性外推。
- `getGoldGift` 选不大于购买量且赠币为正的最高数量键；后续档赠币为零时，不会覆盖此前正赠币。这一点与直接读取当前档 give 不等价，原生响应映射需要独立核对。
- `fc27PresentmentFromUsd` 先按六位小数约束后美元分币舍入，再乘展示汇率并重复分币舍入。`fc27WriteTierBuyPrice` 在已领取状态下还应用 `fc27ApplyPctOff`，以整数分计算百分比优惠。
- `fc27UpdateDiscountRows`、静态促销 DOM、`display_discount_code` 等共同影响展示；自定义档会清除部分行优惠输入，但可回到静态已领取促销。仅看一个百分比字段不足以证明资格、封顶、互斥和购物车路径。

## 下一步与未验边界

继续沿同一脚本版本提取数量和展示纯函数，与实际 `/ajax/goods` 响应字段逐项对齐，再核结账端处理器；不执行整个不受信任页面脚本。只在有原生证据时扩展 `quote_native` 的可证明域。当前 saved-tier 目录金额仍只是目录金额，优惠后实收、手续费、多件分摊和后端数量上界未知，不能由本记录提升 PricingProof 为 PROVEN。

原下载默认网络环境出现 WinError 10013，获工具审批后同一只读 GET 成功；没有安装依赖或更改网络设置。网页工具未取得正文；本记录依据本机保存字节及静态源码核对，不把失败请求当证据。

## 输入与展示的边界复核

- 只考虑失焦后的展示。即时 `input` 预览即使命中固定档，也用派生计算。失焦时先比较 `Number(raw)` 与 `data-min`，再验证正整数字符串，最后按最后一个原生枚举键乘 100 限制最大输入。初始 HTML 的 `data-min` 与 AJAX 刷新后用最小正 `num` 重算的值分别留证。页面价格循环使用 `tableData` 的最后一项，购买按钮 id 取首项，单条响应和确切身份需同时确认。
- 自定义档的八位 `toFixed` 结果是字符串。若响应 `unit_price` 也是字符串，`>` 按字典序比较。保留 JSON 原始类型与 `goods_list` 的键，不能先做统一数值转换或改成无键的数组。固定档价来自格式化字段，赠币展示仍选截至购买量的最高正赠币档。
- 已领取状态直接按分对当前展示价应用百分比，`max_reduce` 在这段脚本仅影响上限提示。若已领取但百分比无效，`fc27WriteTierBuyPrice` 不重写购买价文本。首轮复算限定可核实的未领取 USD 展示，优惠、领取及结账资格留作独立证据。

### 可复跑的离线断言

从任务工作树运行以下命令。需 Node 24 与上文相同的本机 JS 字节，也可将已保存同版本文件的路径作为脚本参数。

```powershell
node --expose-internals docs/planning/fs-fc-admin-es-20261112/evidence/check-native-quantity.cjs
```

当前 Node 24.22.1 通过 13 条合成断言与 8 条历史样例断言。脚本核验完整文件 SHA256，再在隔离环境执行白名单算术函数及自定义档循环片段。合成 101K 样例在 `unit_price` 为数值 8 时取派生单价 25，为字符串 `"8"` 时取字符串 8。两次分币舍入的合成结果为 1.52，再按已领取 7.5% 显示 1.41。

2026-10-28 的匿名 AR/USD PS 响应归档用于复核固定档来源。80K 的 `full_price_format` 为 5.73，`price_discount_format` 为 5.72，`discount` 为 100。200K 行原赠币为 0，用 11 月 13 日脚本重算展示继承 5K。该归档未保存原始 `unit_price` 类型，重算只证明脚本读字段的差异。运行过程无网络、页面初始化或后端操作。 [历史响应归档](../../../releases/fc-coins/fc-pricing-v3-20261026/tests/fixtures/d8-lowest-anchor.json)

### 只读采集入口

`fc_pricing_v3.regional_public.collect` 已有同一匿名 CookieJar 的页面 GET 和商品读取请求，区域仅支持 UK/USD、AR/USD。保留它已有的单条响应、币种、商品身份和区域因子核验。现有结果将 `goods_list` 转成档位列表并丢弃商品行 `unit_price` 与 DOM 上下文。普通 US/USD 的现有入口是 `fc27_cloud_browser/storefront_monitor.py` 的 `page_mapping`、`fetch`、`offer_from_response`，只保存 100K 投影。其 `collect` 会更新状态文件。

11 月 9 日匿名 US/USD PS 的测试切片保留字符串 `unit_price="0.08490000"`，仅有 100K 档。11 月 13 日另沿普通页面 `https://www.mmoexp.com/Fc-27/Coins.html?cy=USD` GET 页面和该页面引用的同源脚本，再沿页面的 PS aid 向既有 `/ajax/goods` 发一条商品读取请求。三份原始字节与请求回执保存在任务本机证据目录。 [11 月 9 日 US/USD 切片](../../../fc27_cloud_browser/test_storefront_monitor.py)

## 2026-11-13 同批次 US/USD PS 证据

04:15 UTC 的页面、脚本和商品响应均 HTTP 200，三份 SHA256 与落盘回执一致。页面根 URL 选中 `US | USD`，静态解析 `plConfig.common.currency.current` 得到 USD、汇率 1、符号 `$`。页面调用 `getMount(plConfig)`，脚本从这个对象设定 `listRate`。后续 `getAxios` 更新商品列表并沿用已设定的 `listRate`。 [原始哈希、身份和结果摘要](evidence/f0-native-quantity-ps-usd-20261113.json)

独立商品响应的 `common` 只有 `thememode`。`goods.index.coupon_display[0].currency` 为 USD，字段作用域是券。原采集的独立商品币种校验仍为 `verification_failed`，错误 `goods_response_usd_currency_structure_unverified`。页面初始化与 AJAX 均只有 PS 商品 `163329311`（`mid=41217957`、`aid=21587`、`site_id=266`、`_region_factor=1`），原始 `unit_price` 同为字符串 `"0.08040000"`，15 个键控档位逐字段完全相同。页面 `data-min="10"`，商品 `min_qty=1`，静态促销为 1%，初始未领取。

将同页初始化币种和目录交给固定 SHA 的原生失焦回调，在隔离的 DOM 替身上通过 16 组输入断言。固定档 100K 原价展示 8.04、购买价展示 6.83，1000K 展示 80.40 和 68.34、赠 30K，5000K 展示 402.00 和 352.00、赠 150K。自定义 101K 两个金额均显示 8.12，1001K 均显示 80.48 并继承 30K。固定档促销提示为 15%，自定义回到静态 1% 提示，样例均为未领取状态。500001K 输入被页面钳到 500000K，后端最大可售数量仍未知。

在可读取原始证据目录的环境复跑。命令核对源哈希、页面初始化、目录严格相等及失焦样例，只执行抽取的回调和必要函数，无页面初始化、网络或结账。

```powershell
node --expose-internals docs/planning/fs-fc-admin-es-20261112/evidence/check-native-quantity.cjs .agent_runtime/native-quantity-ps-usd-evidence-20261113/quantity-script.js .agent_runtime/native-quantity-ps-usd-evidence-20261113
```

下一步由 `storefront_monitor.py` 的公开页面读取保留同批次初始化证据，挂到现有只读预览中的 CURRENT 商品对照。输入需要捕获时刻、页面和脚本 SHA、商品身份、原始类型与键、页面 USD 汇率和输入 DOM 状态。消费者仅追加独立的展示金额、赠币和归一化数量字段，`quote_native` 的 Admin 目录投影沿用既有字段。新曲线、结账权益、后端赠币、手续费和多件分摊仍缺真实证据。 [普通商品读取](../../../fc27_cloud_browser/storefront_monitor.py) · [现有目录报价](../../../releases/fc-coins/fc-pricing-v3-20261026/source/fc_pricing_v3/price_curve.py)
