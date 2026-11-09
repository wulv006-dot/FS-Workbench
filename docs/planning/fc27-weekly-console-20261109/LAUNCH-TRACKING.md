# FC 三页追踪与用码付款接入

日期：2026-11-09。此文区分源码、隔离测试与生产状态；以下生产配置差异由总控沿原入口执行，本文不代表已执行。

## 当前真实观察

187 只读核验：正式 `campaign-preview-27` 三个 FC 页面均 active；`/opt/fs-campaign-dashboard/analytics-config.js` 的总开关仍为 `enabled:false`，允许域名为 `www.mmoexp.com`，原 PostHog 项目已配置。现役脚本 SHA256：`04bfcb6e2cb9c787ba59d0dbfa653ced169c99c4a6efc517b0a425267b0d0d2d`。不得把历史哈希用于未经重读的覆盖。

FS 登记 state revision 8：三页仍为 `/Fc-27/...`、`testing`；万圣节为 active。共享源码不等于 FC 已开始正式采集。未发送真实验证事件，本次浏览器测试全部拦截网络。

用户随后明确授权打开追踪总开关，并使用优惠码付款订单追踪成交。无需新增商城 payment writer 才能使用现有真实用码订单统计。

## 最小配置差异

| 对象 | 现值 | 授权目标 |
| --- | --- | --- |
| 正式 `analytics-config.js` | `enabled: false` | `enabled: true`，其余字节不变 |
| fc27-weekly | testing，`/Fc-27/Weekly-Scout.html` | active，`/events/Weekly-Scout.html` |
| fc27-sbc | testing，`/Fc-27/Sbc-Companions.html` | active，`/events/Sbc-Companions.html` |
| fc27-trio | testing，`/Fc-27/Player-Trio.html` | active，`/events/Player-Trio.html` |

总开关位于公开静态脚本，正式 runtime 从既有 static manifest 装载。沿原 publisher 对现场唯一 `enabled:false` 字段替换，并更新该静态文件 manifest 哈希；不复制现场凭据、不改变项目或 host。管理 `production-server.mjs` 的 `analytics-config.js` 响应故意强制 `enabled:false`，私有预览保持不采集。

登记沿 `/dashboard/analytics/campaigns/analytics/` 原管理区逐项编辑并“保存服务器配置”，或已登录同源的 `CampaignServer.read()` / `CampaignServer.save({registry})`。传完整原 registry，仅修改上述三条；原 client 保留 layout、revision、CSRF 和稳定 operationId，实际 POST 为 `analytics/api/config`。不得直接编辑 state.json。未知保存先查原回执，不换 ID 重写。读回三条新路径/status及其余 registry/layout 未变。

## 原能力复用与本轮变更

- `app/seasonal/activity-analytics.js`：三页复用万圣节同意、Google 和 PostHog transport。只有正式域名、有效发布、开关开启、同意满足才发送。撤回停止后续发送；preview 与标记测试不混入生产。修复同值重复同意会重新建立 visit 的缺陷，原 1 次访问曾在隔离测试变 3 次，现保持 1 次。
- `app/activity.js` 的 native `onCartConfirmed` 只在真实 Cart/add 确认后发加购观察；`native-code-handoff.js` 保留原 operation journal，不把导航、优惠码准备或 Apply 当付款。追踪失败不能阻断结账。
- `backend/campaign_backend/discount_revenue.py`：沿原 Admin 只读 paid-order 查询，新增固定活动组 `fc27-season2` → 原 discount 6049 / FCSCOUT10 / FC27 1327。原万圣节十二码保持；原 6051/6053 配置与历史未删除。
- `app/analytics/discount-revenue.mjs`：任一 FC 页选择映射至同一活动组查询与缓存。只允许原 MMOEXP 范围、UTC 日期窗、all/1327 游戏，无任意 code 输入。
- `app/analytics/dashboard.js`：任一 FC 页显示“FC三页合计用码付款”，按真实已付款用码订单去重，单独显示整单 USD 与含退款订单数。单页行为和确认加购仍可读；单页支付、转化率留空，不与合计付款相除。

金额沿 Admin `amount_usd_format` 原美元整单口径；原付款显示币种单独保留。未付款不算核销付款，退款保留付款事实并另列订单数；未知退款金额不补零，结果不是净收入。混合购物车不分摊商品，也不能凭共同码分配三页收入；未用码成交不在此口径。query 失败或覆盖不完整不显示为 0。

## 验证与证据状态

已通过隔离验证：三页同意前无发送、同意后曝光/选择、部分加购只含 confirmed 行、撤回无发送、同值同意幂等、暂停生效；原 Google/行为聚合回归 16 项。Python 用码查询 9 项，Node 收入接口 5 项；管理页浏览器覆盖三页共享标题/码/不分单页、原万圣节、异常、日期游戏筛选与四种视口主题。

尚未验收：生产开关实际读回、三页真实标记事件的接收与同 event_id 查询读回、部署后正式 API 的 FCSCOUT10 汇总读回。总控可在授权范围沿原 GET `analytics/api/discount-revenue?activity=fc27-weekly&mode=live&from=YYYY-MM-DD&to=YYYY-MM-DD&game=1327` 读取；返回 `activity_id=fc27-season2`、`attribution_level=shared_activity_group`、`page_allocation=not_available`。实际订单不得用隔离 fixture 数字替代。

原商城 `activity_begin_checkout` / `activity_purchase` 逐访客 writer 未接入，原文档 `app/ANALYTICS-INTEGRATION.md` 的上下文/支付 outbox 是未来接入合同，不是已上线事实。当前用码付款独立可用，不需要虚构或浏览器代发 purchase。

## 部署闭包

代码：`app/seasonal/activity-analytics.js`、`app/analytics/dashboard.js`、`app/analytics/discount-revenue.mjs`、`backend/campaign_backend/discount_revenue.py`。共享活动追踪脚本属于 static manifest，按原工具派生哈希。另含上述已授权正式 `analytics-config.js` 字段差异及对应 manifest；registry 走原管理保存，不作为文件覆盖。

未新增 collector、分析平台、业务权限或定时任务；未改优惠资格、原订单 writer、主站结账和正式版本27的商品配置。

## 当前日真实只读查询（候选代码，未部署）

2026-11-09 13:07:34 UTC，187 使用现有 `AdminRead.from_shared_session()` 和上述候选 `discount_revenue.py` 在进程内只读执行。候选工作树原字节 SHA256：`c910bc59df78ffbe3561ef797957c7b920e07efe2cfdc51be581ebaab738c08a`（提交/部署采用 Git 字节时应另核换行归一后的 SHA，不混称现场已安装）。脚本 `.agent_runtime/weekly-console/read-fc-code-revenue.py`；没有订单写入、分析事件或生产文件修改，也没有输出客户/订单标识。

查询窗口 `[2026-11-09 00:00:00Z, 2026-11-10 00:00:00Z)`，按 Admin 北京时间付款字段转为 `[11-09 08:00, 11-10 08:00)`。截至读取时已完成分页，`coverage.complete=true`、source_rows=0、unique_orders=0；FCSCOUT10 / discount6049 原码身份核验通过。返回用码付款订单 **0**、整单 USD **$0.00**、含退款付款订单 **0**。当天尚未结束，此数仅为该次读取观察，不是全天最终数。

这证明查询合同、真实码身份和当次完整空结果可读；尚无非零付款样本，不能据此声称正例付款事件或三页成交已验证。原真实购物车 Apply 成功也不替代付款。无逐页、逐访客、商品行分摊或退款净额证据。
