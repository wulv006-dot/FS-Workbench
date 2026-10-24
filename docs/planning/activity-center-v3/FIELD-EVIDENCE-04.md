# G1补缺：真实字段读取证据

工作要求 FS-V3-G1-COMPLETE-GAPS-04。全部187读取由主控在PC-20260909OJLI通过原 Invoke-Server187.ps1、现有共享Admin会话执行，Python3.9源码由stdin内存运行。没有安装候选、写券、发放、付款或修改生产文件。原始订单/客户行只在远端内存，回传schema、枚举、计数及摘要。

|读取|本地UTC区间|exit|证据与边界|
|---|---|---|---|
|站点266优惠列表/详情、2026-10-23原始paytime窗口订单+券日志|10:27:53.086–10:28:02.668|0|优惠券82、折扣码760；各取一详情实际GET成功且精确ID/站点通过；订单1128、券日志99关联99订单。未声称这些通用优惠为本活动专属|
|全部商品/模型|10:30:00.424–10:30:56.285|0|96引用/86商品全读取、34模型；9个公开购买页未成功取得，脚本0。公页结果unknown，不能将此写成主站无购买接口|
|100条订单金额形状样本|10:32:38.546–10:32:41.750|0|currency_code共8币种；pay_money和pay_money_format纯decimal解析0/100；pay_money_format2[1]100可解析且[0]100匹配currency_code；只证格式，不自动证明金额口径|
|五项SKU开关商品补充结构|10:34:00.212–10:34:07.464|0|首次证据中5货币商品不含选定saleprop容器，针对5商品/模型补读more嵌套结构，不重复86商品及公开页|
|候选订单管线真实内存验收|10:50:10.663–10:50:18.069|0|使用候选AdminRead→reconcile→SQLite :memory:→summary，真实行仅远端内存；readback_consistent=true，无远端DB或安装|

初次订单pay_status枚举：1共1101、2共27；券日志status1共99。支付状态1含义有既有orderStatus前端支持；本次现役MemberCouponLog前端 `index-56cf6d42.js` 明确 status 0未支付、1已支付，SHA256 `3331e54d6542c4a1cc182b1693006d9563ce20ec0634a1b16ab6e79ba51139c7`。不能仅凭use_time或券记录存在计成交。

候选真实管线实际结果：1128订单/1101有效付款观察/99券日志，按有效付款交集仅94笔用券关联。无本活动专属binding时bound_paid_orders=0、unbound_paid_orders=1101，totals/activities为空而不是冒领通用券成交；refunded_observations=null、history_complete=false。缺口提示保留ACTIVITY_BINDINGS_REQUIRED、PAID_MONEY_MAPPING_REQUIRED、PAYMENT_STATE_UNKNOWN、SOURCE_TIME_MAPPING_REQUIRED。capture_sha256为`50a3c95ad418f1fc047a4511f2f74816da888010105d053f14793191147bfe96`。代码当时以stdin内存执行，最终提交与该执行源的关系另核；不是生产持久化已部署证明。

金额字段关系：amount与pay_money_format2[1]仅43/100样本相等，跨币种不能直接互减。既有业务基准明确订单金额USD、实际支付保留原币。现役退款显示与输入来源语义仍有冲突，refund/活动行分摊保持unknown；不能推断没有退款或主站缺少字段。

currency公开组件 `index-4acdada8.js` SHA256 `67b616f391af83601a08bdf08f1c691414e52850168cd4dc4b96915300c687d3`，未提供精度字段。MemberCouponLog文件首次TLS读取失败；同域另一精确资源成功后，原URL保持证书校验再读一次成功。未改TLS、网络或权限，失败记录保留。

完整脱敏产物保留于任务 inputs/gap-schema-evidence-04.json、gap-catalog-evidence-04.json、gap-catalog-sku-evidence-04.json、gap-money-evidence-04.json；公开源码单独输入缓存，不整份提交第三方代码。商品可消费映射由C生成，必须保留引用级已证/待证边界。

## 仍需明确的业务对象

原生优惠真实写验证需要本项目独占、未发放、可安全停用且无其他活动共享的精确ID；目前没有把任何读到的现役券指定为测试对象。优先现有独占停用券，仅验证标题/说明受限编辑及原ID回读。若需新建，必须先证实停用语义与精确ID补偿，另交老D统一决策；本轮不盲建。

公开购买页没有读成功，不改变原有live保护。字段不足先继续核既有消费者/实际输入，只有证实原后台不存在所需能力才转主站T04；当前未据unknown出具“主站缺字段”结论。
