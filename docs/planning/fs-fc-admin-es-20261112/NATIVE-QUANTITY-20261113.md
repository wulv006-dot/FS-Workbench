# 原生数量报价脚本：定向增量核对

2026-11-13 只读 GET `https://www.mmoexp.com/mmoexp-v250528/js/goods/mlb26-landing.min.js`，HTTP 200，25016 字节，SHA256 `77a707f72b3debdf880529fe76d85276f1902a8e0ede4ed0beff37ddb141e618`。本机原始文件 `.agent_runtime/native-quantity-20261113.js`，没有执行页面初始化、登录、加购、结账或后台写入。

现有 `source/pricing_sources.py` 的 CUSTOM_SHA 是 `ad92c2d1c36bfd4d0de8fe4c6cb566be3957209aec86cb3f64fcd9299074c10d`，验证日为 2026-10-22。字节版本已不同；没有取得旧脚本逐函数差分，因此不声称全部报价语义改变，也没有更新现役 pin。

## 当前脚本可以证明的前端行为

- `numRegular` 接受正整数字符串；FC 页面无效输入回退 DOM `data-min`。blur 还按最低档限制下界，以 `goods_list` 枚举的最后一档乘 100 作为输入上界。该行为仅是前端输入规则，不能视为后端拒绝非法数量的证明。
- 固定档 blur 使用响应行的 `price_discount_format` 展示最终金额，原价展示 `full_price_format`。不能仅以 Admin 的 `more.price` 证明客户优惠后结账金额。
- 自定义档循环先计算当前枚举档的 `100 * price / (quantity * discount)` 并 `toFixed(8)`，再判断是否大于购买量并 break；因此边界前的派生单价可能来自下一档。折扣则取已选的前一档，派生单价与商品 `unit_price` 取较大值。不能把自定义数量简单按100K价格线性外推。
- `getGoldGift` 选不大于购买量且赠币为正的最高数量键；后续档赠币为零时，不会覆盖此前正赠币。这一点与直接读取当前档 give 不等价，原生响应映射需要独立核对。
- `fc27PresentmentFromUsd` 先按六位小数约束后美元分币舍入，再乘展示汇率并重复分币舍入。`fc27WriteTierBuyPrice` 在已领取状态下还应用 `fc27ApplyPctOff`，以整数分计算百分比优惠。
- `fc27UpdateDiscountRows`、静态促销 DOM、`display_discount_code` 等共同影响展示；自定义档会清除部分行优惠输入，但可回到静态已领取促销。仅看一个百分比字段不足以证明资格、封顶、互斥和购物车路径。

## 下一步与未验边界

继续沿同一脚本版本提取数量和展示纯函数，与实际 `/ajax/goods` 响应字段逐项对齐，再核结账端处理器；不执行整个不受信任页面脚本。只在有原生证据时扩展 `quote_native` 的可证明域。当前 saved-tier 目录金额仍只是目录金额，优惠后实收、手续费、多件分摊和后端数量上界未知，不能由本记录提升 PricingProof 为 PROVEN。

原下载默认网络环境出现 WinError 10013，获工具审批后同一只读 GET 成功；没有安装依赖或更改网络设置。网页工具未取得正文；本记录依据本机保存字节及静态源码核对，不把失败请求当证据。
