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


## G. 万圣节活动页 UI 与价格呈现（2026-10-27 晚，`nav-20261027T173601Z` / PR #570）

### G.1 静态资源与运行时

- `/opt/fs-campaign-dashboard/seasonal/event.js` SHA256 `f98f31f40f6f7a9a0928f479cdfec0db95066922e0836298844562cd0d0717b3`；`event.css` `8bf8aebfad5aeb13422959efcc6688d05d66f410fc07bbf1123cf88b79836bd4`。
- `runtime/static-manifest.json` 97 键不变，两个 seasonal 键已同步；旧件备份 `runtime/static-manifest.before-nav86.json`。
- `fs-campaign-dashboard` / `fs-campaign-runtime` / `nginx` / `auth-portal` 均 `active`；`fs-campaign-runtime` 重启后日志无 `STATIC_HASH_MISMATCH`（近 3 分钟计数 0）。

### G.2 浏览器实际读回（1600×1000，`https://47.85.224.112/events/seasonal/`）

- 四张游戏卡 `.game-art` 计算样式 `filter: saturate(1.04) brightness(1.12) contrast(1.02)`；`.game-shade` 顶部 `rgba(31,18,50,.10)`、中部 `rgba(27,16,44,.06)`、底部 `rgba(11,7,23,.9)`。
- 第一张游戏卡原图平均亮度 118/255（未取改动前同口径样本，不作前后对比声明）。
- 卡正面 innerText 为 `10% OFF ✦ coins 1000K Coins`——**不含游戏名**；三槽标签仍 `MYSTERY PICK 01/02/03`（固定池身份不对外区分）。
- 价格区：`$71.91` / `$79.90` 原价 / `Limited-Time Price`；`.unavailable-price` 计数 0。
- `/events/seasonal/` HTTP 200。

### G.3 未执行

- 未做付款、下单、退款验收；未等待自然跨日（America/New_York）验证重置；未做移动端实机读回。
- 商品图与折扣 Icon 仍为占位（`✦` 与 CSS 徽章），等素材替换后需重新走一次本流程。

---

## H. 本次会话的测试面（2026-10-27 晚）

- `pr_fast.py` 受影响组 `campaign-analytics` 离线通过（含 `halloween52-browser` / `halloween61-browser` / `catalog.test.cjs`）。
- 三处断言按新行为更新，不是回退产品：`catalog.test.cjs` 的失败文案、`ops-presentation-browser.mjs` 与 `halloween52-browser.cjs` 的 `/1000K Coins/`（固定池数量不再公开）与「价格缺失即 unavailable」。
- CI 有一次 `ops-presentation-browser.mjs` 报 `Cannot read properties of null`，本地连跑两次 PASS、CI 重跑 PASS，判为时序 flaky。
