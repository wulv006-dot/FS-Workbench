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

Corrected transport evidence (18:24 re-read): the order common-search uses remoteSelect in https://admin.p2pah.cn/assets/index-f6e8338f.js, not remoteTreeSelect. Its request construction is `i.params={...n.params||{},page:z?1:i.currentPage,initKey:n.pk,initValue:z?I:""},n.remote?i.params.limit=i.pageSize:delete i.params.limit,g$(n.remoteUrl,i.keyword,i.params)`. These order columns do not set remote=true, so their native full-list requests omit limit. Labels split field by commas and join values using ` | `. The previously read https://admin.p2pah.cn/assets/index-e643222d.js defines `function getSelectData(e,r,t){return createAxios({url:e,method:"get",params:Object.assign(t,{select:!0,quick_search:r})})}`. Directory coverage and pagination must be verified; a partial list must not silently represent the full directory.

## Internal integration contract (local implementation; live acceptance pending)

Keep page `site_id`, `game_id`, `start`, `end_exclusive`; traversal uses `game_ids`. Optional `filters` contains only progress,status,cid,content,aid,recommend_uid,discount_code,promotion_id,pid,admin_id,country. Every page/cursor binds the whole selected filter set; response echoes `filters` when nonempty.

Metadata uses authenticated existing POST endpoint with `kind: order_email_export_options`, optional progress and game_ids. Frontend expects `options` containing sites,games,progress,status,cid,aid,admin_id,country arrays of `{value:string,label:string}`. No fabricated options, broader privileges, customer emails in URLs, or automatic mail sending.

## 17:02 live read-only direct-API evidence

Using the existing pinned shared Admin HMAC proxy (8912), with GET/select=true/page=1/quick_search/initKey/initValue:
- siteList: code=1, data.list=266 rows, no total; gameList: code=1, data.list=583 rows, no total; getCountryList: code=1, data.list=245 rows, no total. This matches the shipped remote select's list response and optional-total behavior; do not require a fabricated total for these fixed full-list directories.
- getOrderProgress, getOrderStatus(id=10), getProType, getServerByGid(gid=1327), getGroupAdminList(gid=8,11): application code=401, not usable metadata. No alternate credentials, browser-cookie fallback or authorization bypass attempted. This is an unresolved direct-API support/authentication boundary, not proof these controls work live. No partial options returned as a complete form. A subsequent read-only `/admin/index/index` returned HTTP200/code1 for the same existing API identity; its advertised routes include order/order/index, order/order/getCountryList, site/site/siteList and site/game/gamelist, but none of the five rejected methods. This narrows the blocker to missing direct-API method support/original route grants, not a general login outage; no alternate identity or route was used to fetch denied data.
- Existing user_runtime.authorize(private=True) checks the real caller's RBAC admin permission, not user_config sites/projects. The export-only source uses that existing private authorization; the generic live feature's old site/project configuration and worker are unchanged. Directory results are actual upstream data, not expanded role grants.

## 18:30 native-directory candidate (not deployed)

The user now requests all retained dropdowns to use native Admin mapping and dependencies; the previously removed operator control stays removed. The candidate reads progress, status(id=progress), global product types, sites, games, countries, and per-game servers without fixed paid/type arrays. The UI sends default progress=1 explicitly, selects status11 only from the real initial response, reloads/clears status after progress changes, and sends progress="" explicitly for an unlimited selection. No selected progress means no status read. Required-directory refusal fails closed, not a synthesized enum. Only a refused optional server directory retains its existing explicit unavailable state.

The four required additional methods were confirmed at18:27 as HTTP200/application401/`You have no permission`. Existing signed proxy routing forwards upstream and does not itself filter these metadata routes. No permission change or alternate identity has been made; one scoped request for the four readonly grants awaits human authorization. This source candidate must not replace the working paid-only production version while the metadata methods are still denied. Offline regressions do not establish actual directory availability.

## Historical 17:34 user-confirmed paid defaults and reduced controls (superseded for the candidate; still deployed)

The user supplied fresh Admin screenshots showing progress `1 | 已支付` and status `11 | 已支付` (the other status visible is `12 | Pending`). They explicitly request the paid+paid default and no operator filter. These observed paid options can be used without calling the rejected progress/status/operator methods; this does not grant access to those methods. Other progress/status values are not inferred.

The product-type screenshot supplies the actual complete visible enum: `1 | 货币(Gold)`, `0 | 物品(Items)`, `3 | 账号(Account)`, `2 | 代练(Powerleveling)`, `5 | 代练包(Package)`, `7 | 礼品卡(Gift Cards)`, `8 | 充值(Top Up)`, `9 | 陪玩(Coach)`. Show these observed values after game selection; the shipped getProType configuration itself has no gid parameter, so do not claim the enum is game-specific. Servers genuinely depend on selected gid and must only be requested after selection.

Keep mandatory sites/games/country reads fail-closed. A refused optional server directory must be explicitly reported as unavailable, disabled and omitted from the chosen filters; it must not block a query using the remaining selected conditions, return a partial cross-game server union, or fabricate servers. The response may include `unavailable.aid = metadata_source_unavailable` alongside the existing options shape. Local private-role revocation remains a request denial, not a recoverable optional-directory warning.

Current acceptance (18:24): PR995/996 merged; live main `812309725a9e601e8f2e9542ec8520809cfcdc54`, main CI43000160068 passed, release nav-20261111T100500Z. Real FS site266 / games833+1327 / dates2026-01-01 through2026-11-10 / progress1+status11 traversed 44 pages and all24 windows, downloaded true XLSX; independent readback399 nonempty, trim/casefold-unique text addresses and0 formulas. This is not all-status data, a snapshot, marketing consent or completed server filtering. Native server URL/parameters were independently re-read and match METADATA/worker; application401 remains a direct-API support/grant boundary, not proof the native directory is absent. Progress/status currently offer only the user-confirmed paid values, not full native dynamic directories. No production source changed during this read-only acceptance.

Historical: PR993 merged as `d30bc4023b6bf19040381256dfd64eb1ce6606fb`, exact main CI run42996231742 passed. That intermediate version was not deployed before the user's follow-up. The deployment target is the follow-up verified-main candidate through the same 11-target publisher; current live baseline is still nav-20261111T083330Z. No new accounts, privileges or email sending.
