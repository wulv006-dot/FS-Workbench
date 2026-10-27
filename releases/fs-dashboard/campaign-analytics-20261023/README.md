# 活动转化分析 · FS 接入

负责人：吴律。范围：三个 FC 活动页漏斗、可维护的活动登记、商品草稿与预览、PostHog Query Read 服务端保存。结账、支付、原站促销与竞猜发奖不在本服务写入范围。

## 使用

- 看板 `/dashboard/analytics/campaigns/analytics/`，商品编辑 `products.html`，连接 `connect.html`。
- 现有 dashboard 权限可查看；当前 FS 管理员可保存。每次请求均经现有 8895 验证，不信任客户端角色。
- 管理员首次在 HTTPS 连接页粘贴项目 682816 / US 的 Query Read 密钥。验证真实查询后原子保存 `/var/lib/fs-campaign-dashboard/posthog-secret.json`，0600；目录0700。密钥不回传浏览器、不纳入Git/开发包、不写日志。重启无需重输；更换失败保留原连接。
- 活动配置与商品草稿同存 `state.json`；保存带版本 CAS 和操作ID。冲突刷新后再编辑；未知结果先读回，不换ID盲重发。历史保存 `history/<revision>.json`，回滚代码不回滚数据。
- 可自选每周推荐、当前 Star Performer 三人组、SBC 核心/两个默认搭档/备选、现有固定包。目录为2026-10-22核验的26件商品快照，不能当实时售价或库存。新商品/新卡种需开发同步 catalog 与素材；不制造 SKU，不直接更改原站商品。
- 商品预览读取服务器已保存草稿；不追踪内部预览、不生成订单。导出给开发的 JSON 无密钥。开发以导出 catalog 生成 catalog.js，再运行 `node build-seo.mjs` 同步正文/SEO/结构化数据，复核后部署原站。
- 新增活动立即进入查询白名单，但仍需网站接入对应 activity_id、view、version 和真实事件；竞猜可维护 match_id、开赛/封盘配置，保存不控制原站开盘/发奖。

## 开发尚需完成

原站埋点需同意管理和正式域名接入。购物车确认后上报真实加购；结账创建成功上报 begin_checkout；支付确认用服务端幂等 order_key 上报 purchase，退款单独处理。保留 activity_visit_id 与活动商品行归因，活动实付统一USD分，不把整单混合商品金额都归因活动。具体事件合同见 app/ANALYTICS-INTEGRATION.md 与 MATCHDAY-ANALYTICS-PLAN.md。

活动9折与券/码/积分叠加由网站服务端校验及结算；本服务不会核销优惠或改价。真实促销利润规则遵循网站当前审批合同，不用前端金额替代结算。

## 运行与验收

Node18+标准库，无新收费服务/定时任务。`fs-campaign-dashboard.service` 仅监听127.0.0.1:8948，Nginx受原登录保护。每次更新分析查询PostHog；正式数据缓存5分钟，联调3秒。超过50,000事件拒绝不完整统计，应缩短日期；后续规模提升再迁移服务端聚合（不伪造完整结果）。

`node --test app/tests/*.test.*` 为离线数据/接口验证（认证与PostHog有fixture）；`python -m unittest test_publish -v` 验证发布边界。`app/tests/production-browser.cjs` 是本地模拟认证浏览器验证，不能替代真实登录验收。

发布适配器按精确SHA复用 menu-cache 冻结publisher，保留全局锁、CAS、原ID日志、备份/回退。仅 app、独立systemd单元、导航两JSON与当前Nginx片段追加路由；不重启认证/经营/采集服务。暂存包须含原publisher精确字节、候选、当前基线manifest，运行 inspect 后以同manifestSHA apply。真实入口、匿名拒绝、管理员保存、只读账号、密钥真实回读及服务重启恢复分别记录；未验项不得称已完成。

上线状态以本次实际回执为准，本说明不是部署证明。投放与验收记录见 `DELIVERY.md` / `ACCEPTANCE.md`；价格新鲜度与失败关闭合同见 `runtime-contract.md`。
