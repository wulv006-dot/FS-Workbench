# G2 Native Contract 25：历史原生合同的本地适配

用户授权仅本地/隔离代码、必要测试与项目PR；不授权真实加购/订单/付款、优惠启用、发券或部署。未访问此前9个403页面，也不换路径/浏览器绕过。

## 证据与能力分层

历史发布JS已在DISCOVERY24逐份核定SHA：原规划research/SCRIPT-SOURCES.json与shipped-js五文件。REA根ev_7864e1c3c13e59a9f682f48800c570a311fd58817ddf27235a545173be90b3d6；购物车视图ev_dc81caf93a894a4d2536e87aa95b81f3031a1edeafdca426aa2e75b571397686。start.min.js SHA a57e79d13ef0811cd87dc868567f2a8eaddea642f91b818a6066a239e9708a3b，字符48239–49232对应原add-cart调用。此为2026-10-22历史制品，不是今天实联。

- 原Cart/add.html发送category/id/group/num/attr/aid，可选sku；FC原固定商品使用new_items。原返回code1只证明旧加购分支成功，不证明权威活动价。历史cartShow包含cart_key、num及显示金额，但没有已证的活动quote/rule/operation回执合同。
- 五脚本有界检索未发现activityQuote/promotion_id/rule_version/discount_code/points；不是全站不存在证明。原注册的coupon参数是通用注册送券开关，不是购物车券叠加或邀请刷新奖励证据。
- 已有Admin Discount/Coupon列表、用券日志、订单discount_code/coupon_id/order_no/pay_status读取是券/码与付款关联依据；不能据此宣称额外九折价格层、允许叠加矩阵或活动层订单金额已接。

## 实现范围

app/runtime/native-fc-contract.mjs为纯转换边界，供隔离集成消费；不安装到公开HTTP路由、不接网络、不调用fetch、不持有会话、不触发cart或quote。以已核固定FC映射校验商品身份、平台、固定数量/组别与空规格，输出历史原生商品字段。line_key及activity/page/rule/operation上下文留本方信封，不擅传未观察到的原站参数。所有当前兼容/权威报价/活动价/交接能力保持未验证。host-adapter原同源与activityPricing保护、commerce的MAIN_INTEGRATION_REQUIRED不改。

这完成“本方选购意图到历史消费者字段”的局部转换，不是结算适配器上线。现有原payload和持久映射复用，币类/Seasonal不猜参数。

## 下一步最小联调请求（未执行）

首选仍不写购物车，先补当前结账消费者只读证据：在原本机、主站正常允许的访问范围，对 https://www.mmoexp.com/Cart.html 作一次GET获取HTML且不执行JS、不跟随跨域重定向；只记录实际引用的一方购物车/优惠脚本URL、字段与版本摘要。仅针对文档中已存在的Cart路径，不对9个403商品页换路。如果Cart本身拒绝即停止；如果登录必需则报告，不提交凭据、不代登录。读取可能由服务器建立游客会话/访问日志，不能保证服务端完全无状态；不提交加购、不创建订单、不领券。不得输出已有购物车商品/客户明细或Cookie。

若正常页面已有权威活动价模块，再按其实际脚本提供的精确只读合同核版本；没有观察到quote路由就不猜测请求。所引脚本如另需访问，只列具体URL与用途，不扫目录。

下一次真实加购必须另批，而且应在已证明活动价能力及明确可清理测试会话后才提出。预期仅一个指定FC商品/平台/数量，原Cart/add.html POST一次会改变购物车，可能留下会话/埋点；目前没有可证原操作幂等/lookup，故不能承诺超时后安全重试，未知必须止写读回。没有权威九折证据时，不用普通原价加购“验证”活动购买成功；本轮不申请或执行这种降级测试。

不可替代依赖：主站权威结算是否支持额外10%且兼容原普通券、活动上下文如何写入订单、实际会话/幂等结果查询。它们可通过合法网页脚本/脱敏接口回执/明确授权联调获得，不一定要完整源码；若后端确无能力，仍需主站owner开发或批准变更方案，FS不能靠展示折扣替代。
