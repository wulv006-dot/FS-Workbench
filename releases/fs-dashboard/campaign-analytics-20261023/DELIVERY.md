# 活动模块投放记录（DELIVERY）

模块：`releases/fs-dashboard/campaign-analytics-20261023/`，负责人：吴律。
线上：187 `/opt/fs-campaign-dashboard/`（代码/静态资源）+ `/var/lib/fs-campaign-public/`（公开配置与价格缓存）+ `/var/lib/campaign-dashboard`→`/var/lib/fs-campaign-dashboard/`（后台状态与 policy）。
发布器：模块内 `publish.py`（复用冻结 publisher），`inspect` → `apply --approved-manifest-sha`。
本文件按时间追加，只记实际发生的发布与回执；未执行的动作写"未执行"。

---

## 2026-10-27

### 1. `nav-20261027T013850Z`（前任主控执行，此处仅登记既有回执）

- 来源：PR #539，合并 `0536230414fa77ee40d772d9b6c150a8e6cc33b0`。
- 目标 36 个，实际变化 32 个；manifest `74df59354cda5c46738c9948937f8fe1ea9b89804126baf02770e45d4951dfb0`。
- policy 安装 1107 bindings，SHA256 `76ade73f20850d66d4fec6d3d3f049a86bd1192f8fb59c7ab915d7aa45276463`。
- 公开配置 `campaign-preview-9`（revision 9），config_hash `b592da5b48be130b2f33c4b3ef48f9ea6bf625faf393c77bba7f22eb733fe983`。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261027T013850Z`。
- 本次接手未重放该发布。

### 2. `nav-20261027T030717Z`（PR #546：Items 原生价格 + 资源版本）

- 来源：分支 `codex/fs-activity-price-cache66`，合并 `aa2efadc6743713442f52a8f32c767d6d2c62563`；CI run `40440980474` success。
- 目标 10 个 / 实际变化 7 个；manifest `104724fdcc199e9dfd6bd6a57e65b5fd00ddac25351471fb6c94075d8cd9f4f4`。
- 内容：4 个 Items 模型支持 `unit_price` + `native_item_display_total` + `Number.toFixed(2)`；活动页 JS/CSS 按 static-manifest SHA 加 `?v=`，`catalog.js` 绑 `config_hash`。
- policy 精确修改 4 条（43167385 / 43168455 / 45059385 / 45059383），新 SHA256 `0cae43fa4d206043b1c48b8f5b14424e522b353018b040c72acae8296271b272`，其余 1103 bindings 未动；备份同 release 目录 `policy-before.json`。
- 派生价格缓存由 `unavailable / 0` 变为 `ready / 124 products / 8 models`。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261027T030717Z`。

### 3. `nav-20261027T044415Z`（PR #551：FC 三页正式可售）

- 来源：分支 `codex/fs-campaign-fc-live67`，合并 `cc567574c2b3d7b3850575a11d0d8ca4875abe96`；CI run `40450837292` success。
- 目标 16 个 / 实际变化 13 个；manifest `35b085f8adf9921c1054cb0623112a96669387de2479b5bb6aa410008727b602`；回执 `targets_all_match=true`、`preserved_all_match=true`。
- 内容（仅活动模块）：
  - `activityPricing`：`enabled=true`、`status=configured`、`promoterUid="0"`、`backendStatus=native_code_live`；折扣仍 10%，与券/积分互斥。
  - `activity.js`：按所选平台展示活动价；平台切换清空旧价并重读；核对/提交走已有原生链路；去掉"预览未接入"旧文案。
  - `host-adapter.js`：新增 `createLivePrice`（仅 `https://www.mmoexp.com` + 同源 `/ajax/goods`；钉住 id/aid/cid/gid/status/auto_off/无 SKU/无规格）。
  - `activity-core.js`：允许标题正常改版，但玩家名段、商品 id、平台属性必须一致，否则失败关闭。
  - `activity-content.js` / `build-seo.mjs` + 静态产物：横幅与静态价同步为活动价。
- 公开配置与 policy 未变（仍 `campaign-preview-9` / `0cae43fa…`）。
- 事故与修正：首次 apply 后 `fs-campaign-runtime` 因 `STATIC_HASH_MISMATCH` 反复失败、`/events/` 502 约 90 秒——手工增量包漏发 `runtime/static-manifest.json`。已将 9 个已部署文件真实哈希写回清单（旧清单备份 `nav-20261027T044415Z/static-manifest.before.json`），新清单 SHA256 `0fd424b9247541c8b11312521d8f0139fc26ea82c62e0946645a961c3ced4f81`。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261027T044415Z`（含上述清单备份）。

### 4. 派生价格有效期放宽（配置，非代码发布）

- 时间：2026-10-27 13:28（北京时间）。
- 变更：`/var/lib/fs-campaign-dashboard/backend/policy.json` 中 `admin_reference_prices.entries[*].max_age_ms` 12 条由 `300000` 改为 `900000`；`refresh_interval_ms` 保持 `60000`；其余字节不变（脚本断言 `NON_TARGET_POLICY_MUTATED`）。
- 生效方式：provider 每轮 `readPolicy()`，下一刷新周期（≤60 秒）自动生效，**未重启服务**。
- 新 policy SHA256 `3f53fd1cf7c64521f849fa8b6dcf058139f32b3d12ed8769eb2b4e23f59926f4`；旧件备份 `nav-20261027T044415Z/policy-before-ttl.json`（`0cae43fa…`）。
- 依据与边界：TTL 是"刷新连续失败时的容忍窗口"，不是日常价格年龄（实测 12 个模型同一轮 3 秒内取完、60 秒一轮）；硬上限 1 小时（`max_age_ms<=3600000` 且缓存校验 `expires_at-generated_at<=3600000`），超出会被 policy 校验拒绝、缓存不可用。
- 回退：把 12 条改回 `300000` 并恢复备份文件即可，无需重启。

### 5. `nav-20261027T190500Z`（PR #573：游戏卡提亮 + 翻牌卡面去掉游戏小字）

- 来源：分支 `codex/seasonal-bright-label89`，提交 `a0295230abe09a035bc89c828ae4481f764f2fbc`，合并 `16c330c6fdc534cd8482b5495bed5e2184ca080f`；CI run `40565155327` success。
- 目标 6 个 / 实际变化 2 个（`app/seasonal/event.js`、`app/seasonal/event.css`）；manifest `dff9dd2a27de38da497959f90a0cbd7770da71bdb5848197e33c126374e42ede`。
- 内容（只这两项，翻牌逻辑、布局、文案均未动）：
  1. `faceContent()` 去掉 `label` 参数与卡面 `<small>`，翻牌卡正面不再打印 `FC27` / `Aion2` 这类游戏名；两处调用点同步不再传参。卡面高 320px 不变。
  2. `.game-art` 由 `saturate(.78) brightness(.8) contrast(1.04)` 改为 `saturate(.95) brightness(1.14) contrast(1.02)`；`.game-shade` 紫色压层减薄，只在标题所在底条接近不透明，标题对比度不变。四张游戏卡实测滤镜一致、高 267px 不变。
- 静态清单：`seasonal/event.js` → `cb4909581417…`、`seasonal/event.css` → `d754645594f5…`；备份 `runtime/static-manifest.before-nav89.json`。
- 读回（正式域名 `www.mmoexp.com`）：页面 / js / css 均 200；四卡滤镜为新区间；三张翻牌正面为 `10% OFF / coins / 1000K Coins`、`10% OFF / Marcos Llorente Moreno`、`10% OFF / Pedri`，`card-front small` 计数 0；翻完刷新后三张全部保持翻开；无 JS 报错。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261027T190500Z`。


### 2026-10-28 `nav-20261028T020826Z`（PR #577）可见文案可配置

- 代码：PR #577（head `ccad71a7f2`，CI success）合并 `fb70be54105c20a4cd1d9c8727bcfa8f1f91597c`。
- 目标：12 个（5 个代码/模块 + 6 个边界文件 + `runtime/static-manifest.json`），变更 9 个；`inspect` 报 `sourceCAS/protectedCAS passed`、`mutations:false`；apply 回执 `all_match=true`、`failed:[]`。
- 变更文件：`app/activity.js`、`app/activity-content.js`、`app/runtime/snapshot.mjs`、`app/analytics/products.js`、`app/analytics/center-store.mjs`。
- 边界：`CAMPAIGN_SOURCE_REVISION=fb70be5…`（runtime.env + 两个 unit）；`current.json` 与 `policy.json` 由 `preservedBusinessState` 保护且未变。
- 静态清单：97 键不变，其中 `activity.js`、`activity-content.js` 两条哈希更新；`runtime/snapshot.mjs` 与 `analytics/*.mjs` 属模块代码，不进静态清单（塞进去会 `INVALID_PUBLIC_PATH`）。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261028T020826Z`。


### 2026-10-28 `nav-20261028T024922Z`（PR #581）活动卡素材换成游戏通用图 + 金色折扣徽章

- 来源：分支 `buddy/seasonal-card-art-20261028`，提交 `ebe88dd9450f7bbad2cd150e1babb77bb6eaeccb`，CI `pr-fast` success；合并 `c3ff16c05c6124923824a5fdfc732368882ab487`。
- 目标 15 个（10 个 seasonal 资源 + `app/runtime/static-manifest.json` + 4 个边界文件：`navigation.conf` / `navigation.json` / `module-registry.json` / `fs-campaign-dashboard.service`）；`inspect` 报 `sourceCAS/protectedCAS passed`、`mutations:false`；apply 回执 `applied-awaiting-actual-http-role-acceptance`、`staticFiles:15`。
- 内容：
  1. `event.js` 新增 `CATEGORY_ART` / `artCategory()` / `categoryArt()`：卡面插图改为按「游戏 + 品类」取一张通用图 —— FC 金币 `product-fc-coins.webp`、FC 球员与 Pack/Bundle/POTM/EVO 一律 `product-fc-set.webp`；Aion2 / WoW / MapleStory 金币各用一张。MapleStory 物品图仍在制作，暂由金币图兜底。
  2. 角标折扣由 CSS 文字 pill 改为金色徽章图 `assets/badge-<档位>.webp`（56px，≤640px 时 46px）。
  3. 顺带消除旧缺陷：商品记录里的 `image` 是相对路径 `assets/product-*.webp`，页面在 `/events/seasonal/` 下会请求 `/events/seasonal/assets/...` → 404，其余三游戏 `image` 本来就是空，所以此前卡面全是 `✦` 占位。
  4. `seasonal-source/tests/halloween52-browser.cjs` 原断言「未知导入商品在卡面不产生 img」改为「卡面 img 的 src 必须来自 `assets/`」，防注入语义不变且更严。
- 新增素材：`seasonal/assets/` 下 8 个 webp（`badge-8/10/15`、`product-fc-coins`、`product-fc-set`、`product-aion-coins`、`product-wow-coins`、`product-maplestory-coins`），合计约 460KB。
- 静态清单：97 → 105 键（新增 8 条）；`seasonal/event.js` → `aecb4fc34d79…`、`seasonal/event.css` → `c9ebca709a50…`；清单本体 `bf1da57b6693…`。
- 边界：`current.json`、`policy.json` 由 `preservedBusinessState` 保护且未变；runtime 模式、公开配置、共享配置均未改。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261028T024922Z`。
- 未做：`-10%` 徽章素材本身没有百分号（另两张有），按原样上线待换图；MapleStory 物品通用图待补；首页四张游戏卡图（`game-1..4.png`）本次未动。

---

## 回退与边界

- 代码回滚不放回 policy、公开配置、优惠码或派生价格缓存；数据与账本保留在原位置。
- 不恢复退役 publisher，不整包覆盖线上目录，不改认证、经营看板或采集计划。
- 每次发布的目标清单、基线哈希、备份路径与读回见原发布回执（`/var/tmp/fs-campaign-release*-candidate/apply-receipt.json`）。
