# 活动模块验收记录（ACCEPTANCE）

只记录**真实入口读回**，不把 CI 绿、合并、HTTP 200 当成业务闭环。
每条含：时间、版本/发布 ID、入口、方法与结果、缺口。

---

## A. FC 三页正式可售（2026-10-27，`nav-20261027T044415Z` / PR #551）

入口：`https://www.mmoexp.com/events/{Weekly-Scout,Sbc-Companions,Player-Trio}.html`
方法：独立浏览器上下文（无既有会话），逐页选平台 → 读价 → 核对 → 原生加购 → 购物车自动 Apply；不付款、不建单。

### A1. 页面价 = 主站现价 × 90%

| 页面 | 平台 | 商品 | 页面价 | 同商品实时目录价（`/ajax/goods`） | 应得 |
|---|---|---|---:|---:|---|
| Weekly | PS | Mikel Oyarzabal Ugarte | $1.19 | `1.32` | 132×0.9→119 ✓ |
| Weekly | PC | Mikel Oyarzabal Ugarte | $1.06 | `1.18` | 118×0.9→106 ✓ |
| SBC | PS | Alphadjo Cissè | $6.27 | `6.97` | 697×0.9→627 ✓ |
| Trio | PS | Bradley Barcola | $48.03 | `53.37` | 5337×0.9→4803 ✓ |

平台切换确实换价：Weekly PS $1.19 / PC $1.06；Trio PS $68.12 / PC $78.22。
页面价用 `Number.toFixed` 同口径四舍五入，原价以划线显示。

### A2. 原生链路与应付金额

| 页面 | 件数 | `native_plan` | 页面价合计 | 购物车小计 | 折扣 | 支付费 | 应付 |
|---|---:|---|---:|---:|---:|---:|---:|
| Weekly PS | 1 | 200 · `FCSCOUT10` 10% | $1.19 | $1.32 | −$0.13 | +$0.33 | **$1.52** |
| Weekly PC | 1 | 200 · `FCSCOUT10` 10% | $1.06 | $1.18 | −$0.12 | +$0.33 | **$1.39** |
| SBC PS | 2 | 200 · `FCSBC10` 10% | $25.24 | $28.05 | −$2.80 | +$1.03 | **$26.28** |
| Trio PS | 3 | 200 · `FCTRIO10` 10% | $68.12 | $75.69 | −$7.57 | +$2.28 | **$70.40** |

`POST /Cart/add.html` 均 200；`/ajax/discount` 均 `status=1`，回执含
`code=FCSCOUT10/FCSBC10/FCTRIO10`、`discount="90.00"`、`uid=0`、`site_id=266`、`gid=1327`、`status=1`。
购物车显示对应码、`Discount Amount` 负数、`Total Amount` 与上表一致（SBC/Trio 存在 ≤$0.01 逐行舍入差，以购物车为准）。

### A3. 未完成

- 未付款、未创建订单。
- 未验证退款/售后链路。
- 未做自然周期观察（价格随时间波动下的长期一致性）。

---

## B. 万圣节四游戏固定档（2026-10-27，`nav-20261027T030717Z` / PR #546）

入口：`https://www.mmoexp.com/events/seasonal/`；方法同上（隔离空车，未付款）。

| 商品 | 码 / Discount ID | 商品价 | 折扣 | 支付费 | 应付 |
|---|---|---:|---:|---:|---:|
| FC 1000K coins | `HWFC10` / 6029 | $80.20 | −$8.02 | +$2.39 | **$74.57** |
| FC Items 43167385 | `HWFC15` / 6027 | $5.16 | −$0.77 | +$0.43 | **$4.82** |
| Aion2 100M Kinah | `HWAION10` / 6035 | $74.71 | −$7.47 | +$2.92 | **$70.16** |
| WoW 20G | `HWWOW10` / 6041 | $37.56 | −$3.76 | +$1.28 | **$35.08** |
| MapleStory 300K | `HWMAPLE10` / 6047 | $20.74 | −$2.07 | +$0.84 | **$19.51** |

均产生 `native_plan 200` → `Cart/add.html 200` → `/ajax/discount status=1`，购物车出现对应商品行并显示 Apply 成功。

---

## C. 派生价格有效期（2026-10-27 13:28，配置变更）

- policy：12 条 `max_age_ms` `300000 → 900000`，`refresh_interval_ms` 仍 `60000`；新 SHA `3f53fd1c…26f4`，旧件备份 `nav-20261027T044415Z/policy-before-ttl.json`。
- 未重启服务；下一刷新周期生效。
- 缓存回执：`generated_at=2026-10-27T05:28:21.129Z`，价格 `expires_at` 落 `05:43:18–05:43:21Z`（= 观测时间 +15 分钟），124 products / 8 models 不变。
- 四游戏翻牌均 200 且带随机档：FC/Aion/WoW `fixed:10 / random-1:10 / random-2:8`；MapleStory `fixed:10 / random-1:15 / random-2:15`。
- 依据：实测同一轮 12 个模型 3 秒内取完、60 秒一轮，故 TTL 是"连续刷新失败容忍窗口"，不是日常价格年龄；硬上限 1 小时。

---

## D. 资源版本与页面缓存（2026-10-27）

- 四个入口 HTML 一律 `Cache-Control: no-store`。
- 活动脚本均带 manifest 哈希版本：`activity.js?v=587d5099…`、`activity-core.js?v=7016c5f8…`、`host-adapter.js?v=0c37f560…`、`catalog.js?v=b592da5b…`（绑 `config_hash`）。
- 换版即换 URL，不依赖用户清缓存。

---

## E. 现场服务（2026-10-27 13:28 读回）

`fs-campaign-dashboard`、`fs-campaign-runtime`、`nginx`、`auth-portal` 均 `active`；
`/var/lib/fs-campaign-dashboard` 无 `pending.json`；公开配置 `campaign-preview-9` / `b592da5b…`；policy `3f53fd1c…`（TTL 变更后）。

---

## F. 已知缺口（未完成项）

1. 缓存年龄（`now - generated_at`）>5 分钟没有告警；刷新真故障会被最长 15 分钟的"看起来正常"掩盖。
2. 万圣节随机档在 TTL 上限仍会 409（`HALLOWEEN_FIXED_MAPPING_REQUIRED` / `CURRENT_PRICE_UNAVAILABLE`），只是窗口从 5 分钟拉长到 15 分钟，根因（刷新失败时整层拒绝）未消除。
3. FC 三页无"区服"维度（球员卡只有 PS/Xbox/PC），属商品结构，不是缺口。
4. 未做付款、订单、退款与长期自然周期验收。

### 2026-10-27 `nav-20261027T190500Z`（PR #573）读回

- 范围：`app/seasonal/event.js` + `app/seasonal/event.css`，共 2 个文件。
- 游戏卡：四张 `.game-art` 计算样式均为 `saturate(0.95) brightness(1.14) contrast(1.02)`；卡片高度 267px 未变。
- 翻牌卡：三张正面 `card-front small` 计数 0（游戏小字已移除）；卡高 320px 未变；正面文案与价格正常。
- 翻牌与状态：三张翻完后 `is-revealed` 全 true；`reload()` 后重新进入游戏页，三张仍为 true（固定卡持久化在 PR #572 修复后保持）。
- 控制台：无 pageerror、无 console error。
- 未执行：未改 policy / 公开配置 / 优惠码 / 派生价格缓存；未重启服务（清单先更新、文件后落盘，顺序保证无 `STATIC_HASH_MISMATCH`）。

### 2026-10-28 `nav-20261028T020826Z`（PR #577）读回：可见文案可配置

- 服务：`fs-campaign-runtime` / `fs-campaign-dashboard` / `nginx` 全 active；`/events/`、Weekly、Trio、SBC 均 200。
- 落盘核对：`activity.js` 含 `hero(state.view)`（1 处）、`runtime/snapshot.mjs` 含 `pageCopyFields`（2 处）、`analytics/products.js` 含 `copyControls`（2 处）；`CAMPAIGN_SOURCE_REVISION=fb70be54105c20a4cd1d9c8727bcfa8f1f91597c`。
- 渲染链路（只读验证，未改线上配置）：在浏览器拦截 `/events/api/campaign/config` 响应、仅给 `fc27-weekly` 注入 `copy:{heading,body}`，线上页面 `#view-heading` / `#hero-body` 即显示注入文案，无 JS 报错 —— 证明"发布配置里的 copy 会被公开页消费"。
- 编辑器：`products-page-flow-browser.cjs` 在真实页面里填写英文 heading/intro，拦截 `api/center/preview` 断言提交体 `page.copy` 与输入一致；清空后 `copy` 键被整体移除（不写空串）。
- 合同：`pageCopyFields()` 只接受 FC 三页的 `heading/intro/body`（120/320/400），拒绝尖括号、控制字符与中文；草稿保存与发布两处都校验（`INVALID_PAGE_COPY`）。
- 未执行：未改任何线上 `copy`（当前仍沿用代码默认文案），未改商品、价格、绑定与 policy；未做付款/订单验收。

