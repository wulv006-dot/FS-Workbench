# P1 实际合同与尚未接通能力

工作要求 FS-V3-G1-CONTINUE-02。证据均由 PC-20260909OJLI 原 SSH 通道读取，未改变网络、凭据或后台权限。

## 已核商品引用

| 原成果 | goods_id | site_id | gid | mid | aid | sid | cid | unit | sku_switch / attr_switch |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| FC 原球员 | 170014917 | 266 | 1327 | 43167385 | 21587 | 7645 | 9627 | 空 | 0 / 1 |
| Seasonal FC Coins | 163329311 | 266 | 1327 | 41217957 | 21587 | 7645 | 9623 | K | 1 / 1 |

两次 GET `/admin/goods.Goods/edit?id=…` 均 HTTP200/code1；模型、在售商品、平台、服务器和类别不可混用。球员 more 含 baseprop/extend/saleprop/skuTableSet；金币 more 含 delivery_time/discount/extend/give/gold/hot/price。开关不单独证明规格可直接购买，空单位不推断为原生下单单位。原页面快照用于保留设计，公开种子商品一律 unavailable，待验证购买映射后再开放相应能力。

## 原生券动作

`GET /admin/index/index` 实际返回现有权限节点：market/coupon/add、edit、goods、previewJumpUrl；market/couponGrant/import、jobStatus、downloadReport、couponSelect、suggestBatchNo；market/discount/add、edit。只取相关节点，不输出账号或全权限列表。

现役公开前端组件及共用 API 封装证明：

| 动作 | 精确合同 | 验证层级 |
|---|---|---|
| 列表 | GET /admin/market.Coupon/index | 实际200/code1；完整分页由既有消费者校验 |
| 创建 | POST /admin/market.Coupon/add，JSON form.items 去掉 null | 当前源码+权限已核；本记录时未写入 |
| 编辑/启停 | POST /admin/market.Coupon/edit；switch 发 `{id,status}` | 当前源码+权限已核；不因此开启公开售卖 |
| 详情 | GET /admin/market.Coupon/edit?id=… | 共用 API 封装定义；实际本项目详情读回待测 |
| 定向发放 | POST /admin/market.CouponGrant/import，JSON `{site_id,coupon_id,grant_batch_no,emails}` 或 multipart文件 | 当前源码+权限已核；未发券 |
| 发放结果 | GET /admin/market.CouponGrant/jobStatus?job_id=… | 当前源码已核；未拿到job_id的未知提交不能靠换ID重发 |
| 建议批次 | GET /admin/market.CouponGrant/suggestBatchNo，coupon_id/site_id | 不等价于按批次查询实际发放结果 |

GET Coupon/add HTTP200/code0，并未返回初始表单；保留该结果，不宣称已验证创建。API封装对add的POST定义与这个GET结果是不同证据。

券枚举由当前列表和表单读取：type=1优惠券；fetch_scene=1注册/2赠送/3活动页面/4后台定向；mode_type=1固定值、2百分比（reduce=80表示八折）、3领取时转固定额且创建后不能随意改；time_effect=1绝对时间（后台输入北京时间）、2领取后N天；is_open=1允许按主站规则叠加折扣码。0或通用范围表示不限，不能误当站点266。GET列表 productTypes 实测1货币、2物品、3账号、4代练、5代练包、6CDK、7礼品卡、8充值、9陪玩、0通用。

普通券叠加开关不证明“独立活动10%层＋主站所有合法优惠”已实现。未确认的组合保持不支持。没有把原站价格改低实现活动优惠。

已实现验证专用 disabled draft adapter：仅site266的两个已核商品，status0、fetch_scene4、不发放、不启用，标题含原operation UUID；一次POST、关闭重定向、原标题精确完整分页读回。它复用共享会话，不调用有重试风险的sales_auth.post_admin。真正调用前还需独立Q与现场单次验证。此窄适配不冒充完整运营券生命周期。

## 订单与归因

当前订单详情组件明确 `pay_status==1` 显示已支付；退款、部分退款和活动行金额仍需真实字段合同。纯逻辑使用显式规范化字段，未把旧渠道“已完成履约”当付款判据。实际优惠引用+有效付款才可归因；共享优惠只到组、混单无分摊保持未知、全局去重、退款稳定引用、原币种分别统计。没有真实活动支付订单，尚无G2归因证据。

## 公共合同

见模块 runtime-contract.md 与 backend-contract.md。公开端只读白名单发布快照，独立服务与管理权限隔离；默认preview，live_checkout=false。意图保存真实引用结构，报价/购物车需主站适配；integration_test结果固定test_only且authoritative=false。配置变化拒绝旧版本意图；未知操作查询原ID，不盲重放。

FS 中心草稿/预览发布通过原鉴权、管理员角色、Origin和CSRF；版本CAS、持久原操作回执。发布的文件只含公共投影，管理配置和凭据不进入公开目录。原FC商品编排、原Seasonal主题及原页面设计保留。

## 当前前端源码证据 SHA256

来源 `https://admin.p2pah.cn/assets/`，只读源码副本在独立任务 inputs；不将整份第三方前端纳入项目。

| 文件 | SHA256 |
|---|---|
| index-c327c9a6.js | c599043e11383f27d4e60f5602d7c81a4d7d2344102f4b82313289a632052f3a |
| popupForm-ed30603f.js | bbadafc16205d7a533cfec7519e8bdad4959dd2a87d3a00308a862605705c966 |
| index-410fa6ea.js | 4b154b7d7bb78e572780b4323a6d6fb6b6501d453ea91a9fb543ef80d08729df |
| coupon-ddcc5cb4.js | 15f60b5d9b6843e9ba6e9e15d813772a716c161a6e68ad5341a96cdf740921f2 |
| orderStatus-9f89c2eb.js | ec4770f3ff28db51566f66f32a0b760e2d0a38c196c7514b28e32854dad3c488 |
| index-6af19510.js | be4b84a03bc44bf6886259c6412ceea33cce1ee40155bd8d3df757ce398c492e |
| baTable-2f2e7c29.js | 36a008812ce897617688a073b5933a9d7f52c20f99ae236f7c0f9ab06f3be76c |

一次泛取HTML所有JS引用时遇403，失败未打印具体资源URL；后检查发现包含多个无关第三方CDN。没有对那些资源重试或绕过；后续限定已成功的Admin同源/assets及其真实依赖，取得上述源码。该失败不被改写为后台写入被拒。
