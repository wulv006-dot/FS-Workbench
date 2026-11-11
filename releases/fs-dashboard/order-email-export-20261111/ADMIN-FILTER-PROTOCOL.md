# Admin order email export protocol — 2026-11-11

Read-only shipped-code evidence, not a claim of completed implementation or live acceptance.

Router https://admin.p2pah.cn/assets/router-752569ae.js maps `/src/views/backend/order/order/index.vue` to https://admin.p2pah.cn/assets/index-cac49fc8.js (12,861 decoded characters observed). The latter defines `new baTable(new baTableApi('/admin/order.Order/'),...)` and the following common-search columns:

| Label | field | operator | directory path | key / label |
|---|---|---|---|---|
| 订单进度 | progress | = | /admin/order.Order/getOrderProgress | id / id,title |
| 订单状态 | status | = | /admin/order.Order/getOrderStatus | status / status,title |
| 订单站点 | site_id | = | /admin/site.Site/siteList | id / id,full_title |
| 产品类型 | cid | = | /admin/order.Order/getProType | id / id,title |
| 游戏/服务器/产品 | content | LIKE | none | text |
| 游戏 | gid | = | /admin/site.Game/gameList | id / id,title |
| 服务区 | aid | = | /admin/goods.GameServer/getServerByGid | id / title |
| 推广人ID | recommend_uid | = | none | text |
| 折扣码 | discount_code | = | none | complete code |
| 促销活动ID | promotion_id | = | none | text |
| 商品ID | pid | = | none | text |
| 操作人 | admin_id | = | /admin/auth.Admin/getGroupAdminList?gid=8,11 | id / nickname |
| 下单时间 | paytime | RANGE | none | datetime |
| 国家 | country | LIKE | /admin/order.Order/getCountryList | country / code,country |

Status directory receives `id=progress`; server directory receives `gid=selected game`. Multi-game export traverses each selected gid serially instead of inventing an upstream IN operator. The Admin label 下单时间 actually uses `paytime`; retain the real Admin behavior, not a guessed creation-time field. Its frontend rejects ranges over 31 days. Existing FS 28-day request windows can safely compose a longer requested period.

Directory transport evidence: https://admin.p2pah.cn/assets/remoteTreeSelect-6030a9dc.js initializes page=1/pageSize=10 and requests page, initKey=pk, initValue. It accepts `response.data.options` or `response.data.list`, with optional total. https://admin.p2pah.cn/assets/index-e643222d.js defines `function getSelectData(e,r,t){return createAxios({url:e,method:"get",params:Object.assign(t,{select:!0,quick_search:r})})}`. Directory coverage and pagination must be verified; a partial list must not silently represent the full directory.

## Internal integration contract (local implementation; live acceptance pending)

Keep page `site_id`, `game_id`, `start`, `end_exclusive`; traversal uses `game_ids`. Optional `filters` contains only progress,status,cid,content,aid,recommend_uid,discount_code,promotion_id,pid,admin_id,country. Every page/cursor binds the whole selected filter set; response echoes `filters` when nonempty.

Metadata uses authenticated existing POST endpoint with `kind: order_email_export_options`, optional progress and game_ids. Frontend expects `options` containing sites,games,progress,status,cid,aid,admin_id,country arrays of `{value:string,label:string}`. No fabricated options, broader privileges, customer emails in URLs, or automatic mail sending.

## 17:02 live read-only direct-API evidence

Using the existing pinned shared Admin HMAC proxy (8912), with GET/select=true/page=1/quick_search/initKey/initValue:
- siteList: code=1, data.list=266 rows, no total; gameList: code=1, data.list=583 rows, no total; getCountryList: code=1, data.list=245 rows, no total. This matches the shipped remote select's list response and optional-total behavior; do not require a fabricated total for these fixed full-list directories.
- getOrderProgress, getOrderStatus(id=10), getProType, getServerByGid(gid=1327), getGroupAdminList(gid=8,11): application code=401, not usable metadata. No alternate credentials, browser-cookie fallback or authorization bypass attempted. This is an unresolved direct-API support/authentication boundary, not proof these controls work live. No partial options returned as a complete form. A subsequent read-only `/admin/index/index` returned HTTP200/code1 for the same existing API identity; its advertised routes include order/order/index, order/order/getCountryList, site/site/siteList and site/game/gamelist, but none of the five rejected methods. This narrows the blocker to missing direct-API method support/original route grants, not a general login outage; no alternate identity or route was used to fetch denied data.
- Existing user_runtime.authorize(private=True) checks the real caller's RBAC admin permission, not user_config sites/projects. The export-only source uses that existing private authorization; the generic live feature's old site/project configuration and worker are unchanged. Directory results are actual upstream data, not expanded role grants.
