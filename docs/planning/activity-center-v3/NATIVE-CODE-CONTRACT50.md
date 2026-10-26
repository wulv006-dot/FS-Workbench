# 原生折扣码交接与有效期：有界证据结论

2026-10-26，仅检查现有获准源码/已存REA和只读合同。没有网络请求、后台写入、加购、用码或部署。

## 支付前码校验：已存在；活动页自动交接：未证实

`inputs/G2-CART-LOCAL27-RECEIPT.md`记录2026-10-25已打开Cart DOM内联脚本（SHA256 fb38b620dc642813d2b16dc1108e255e72d8ea1c527d312606076c8b6d39ae25）：

- 原生函数 `coupon(rate, skipSwitchConfirm)` 调用 POST `/ajax/discount`，已有字段 `cheaced='discountCode'`、`code`、`coupon`。
- 读取 `res.data.discount.index.status/msg/info.type/info.discount`；原建单前分支使用 `discount_code`，与coupon_id/积分存在互斥选择。
- 以上是原生页面内部调用结构，不是活动页可直接调用的公开API合同。rate、coupon具体枚举/空值、CSRF/会话上下文及最终提交行为不可凭名称猜测。HTTP200或前端计算金额均不能代替业务确认。
- 原始内联全文当时未保存，不能现在补称完成自动带码全代码审计。

复核历史5份shipped-js及既有REA记录：ev_7864e1c3c13e59a9f682f48800c570a311fd58817ddf27235a545173be90b3d6、ev_dc81caf93a894a4d2536e87aa95b81f3031a1edeafdca426aa2e75b571397686。该5文件未命中discountCode/discount_code或/ajax/discount；start.min.js唯一URLSearchParams用于统计sendBeacon，不是优惠参数入口。该有界缺证不能推断主站完全不支持自动填码。

## 有效期：字段存在；源时区与端点语义未证实

LIVE-BASELINE.md记录原生折扣列表HTTP200/code1并存在timestart/timeend；backend/campaign_backend/benefits.py、bridge.py保留原始字段。通用Admin打包脚本index-6af19510.js包含日期选择器valueFormat及Date/getTimezoneOffset通用代码，但没有证明折扣表单选用哪个序列化配置，更没有服务端解析与比较证据。不能从服务器/浏览器时区、中文UI、订单paytime北京时间，推定折扣生效窗也相同。

父端截图已证实repeat使用次数0为无限次；用户已确认discount为支付百分比，100原价、90九折、80八折。这两项不再待问。0折、小数输入范围及正式折扣值不从示例推断。

## 本地未配置边界

FORMAL49候选保留native_discount_code未配置、discountPercent=null、enabled=false；真实提交禁用，旧native adapter明确拒绝未验证的折扣码交接。不会拼造Cart.html?code=、写localStorage/Cookie、自动点击主站输入框，或直接调用上述POST。参数确定本身也不会解除技术验证门禁。码有效期不做无时区默认转换；现有归因source_time仍要求明确offset和verification_ref，无证不得填480。

## 只需主站技术确认两项

1. **支付前自动带码的正式入口**：现有Cart是否消费某个参数/受控会话引用或已有函数？提供对应代码片段或精确入口/字段、业务成功回执和码与券积分切换语义。若确无入口，最小开发是在现有Cart初始化中接收经校验的活动码意图并走原校验；不要求新建购物车。该入口必须最终由主站显示支付前金额，不能仅填输入框。未确认前不擅自降级为手动复制码。
2. **折扣生效窗合同**：timestart/timeend提交格式、服务端解释时区，以及开始/结束相等时的生效判定（含是否包含截止时刻）。提供该表单提交与后端校验片段或维护方明确字段说明即可，无需完整源码、凭据或真实订单。

拿到上述任一合同后只补对应接线与隔离用例；真正应用码/建单/付款仍另行批准。现有字段证据不等于现场联调通过，旧失败和权限边界保留。
