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

### 2026-10-28 `nav-20261028T030250Z`（PR #583）MapleStory 物品通用图

- 来源：分支 `buddy/seasonal-item-art-20261028`，提交 `831314b3d3ea6b26723e93ded0522ccb8471f8ee`，CI `pr-fast` success；合并 `a0149159b759fc5e7d065dd02e5565cf054f2367`。
- 目标 7 个（`app/seasonal/event.js`、`app/seasonal/assets/product-maplestory-item.webp`、`app/runtime/static-manifest.json` + 4 个边界文件）；`inspect` 报 `sourceCAS/protectedCAS passed`、`mutations:false`；apply 回执 `staticFiles:7`。
- 内容：`artCategory()` 对 MapleStory 拆成两类 —— 标题含 `Meso(s)` 走 `product-maplestory-coins.webp`，其余（`Wooden Top` / `Tobi Throwing Stars` 这类装备）走新增的 `product-maplestory-item.webp`；`CATEGORY_ART.maplestory.item` 一条映射，其余游戏与 FC 的三类判定不变。
- 素材处理：原图 1857×847 纯白底 JPG（无 alpha）。四边泛洪标记背景连通区（阈值 62）→ 区内按亮度映射 alpha（≥250 全清、≤205 保留、中间线性）→ alpha 0.8px 高斯软化 → 裁 bbox → webp 1445×774/214KB。抠掉 884831/1572879 像素；物品内部白色与银色（钻石、银爪、银镖）与背景不连通，全部保留，紫色光晕自然淡出。
- 静态清单：105 → 106 键；`seasonal/event.js` → `de35383cf064…`、清单本体 `375efb554f07…`。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261028T030250Z`。

### 2026-10-28 `nav-20261028T030905Z`（PR #584）10% 折扣徽章换图

- 来源：用户补来带百分号的 `Polished Gold -10% Discount Badge`（1361×1156 RGBA，圆心 693/581.5、直径 ~1005，与另两枚同一套构图）；分支 `buddy/seasonal-item-docs-20261028`（提交 `d69c2474e2`，CI `pr-fast` success）合并 `c4b3bb3048618a67637669beb0d536f0544fcf26`。
- 目标 6 个（`app/seasonal/assets/badge-10.webp`、`app/runtime/static-manifest.json` + 4 个边界文件）；`inspect` 报 `sourceCAS/protectedCAS passed`、`mutations:false`。
- 处理：沿用与 8%/15% 完全相同的裁框（中心 693/583、边长 1146）归一后缩放 176×176 webp；三档并排核对大小与描边一致。
- 静态清单：106 键不变，`seasonal/assets/badge-10.webp` 哈希更新 `deb0a8ec` → `12351b79`；清单本体 `1b186d0d8693…`。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261028T030905Z`。
- 遗留：`/events/` 静态资源带 `Cache-Control: public, max-age=2678400`（31 天）且文件名无内容指纹，换图后老访客浏览器仍用旧图，需要强刷才更新；根治要给素材 URL 加版本参数或文件名带哈希，已在 `HANDOFF.md` 记为待办。

---

### 2026-10-28 价格 provider 批量扫描改造（PR #600/#602/#603/#604/#606，直接部署，未经 publisher）

> 本节不是 publisher 发布：没有 `nav-*` release-id、没有 manifest、没有 `operations/` 回执。做法是从合并提交取 LF 原文，`install -m 644` 覆盖 `/opt/fs-campaign-dashboard` 下运行时文件后 `systemctl restart fs-campaign-dashboard`。`current.json` 的 `release_id` 仍 `campaign-preview-10`、`config_hash` 未重算，`state.published` 仍 `campaign-preview-11`。

- 触发：`/events/seasonal/` 四游戏商品全站无价，`admin-reference-prices.json` 常驻 `status: unavailable` / `products: []`。
- 定位：Admin 列表接口 `goods.Goods/index` 偶发卡 40–70 秒（同一参数在同一分钟内实测 130ms 与 70s），而 provider 是「任一条失败 → 整份作废」。原实现每模型 1 次 detail + 1–4 次 list + ≤12 次 detail，49 个模型约 120+ 次请求，在 1/3 卡顿率下全成功概率趋近于零。
- 反证：19:45 已把上午 11:00 的基线逐字节还原（`adapters.py` `f77b96c7`、`admin-price-provider.mjs` `08678896`、`policy.json` `6751db1f`），连续多轮仍 `unavailable` — 与代码版本无关。
- 实现：`adapters.search()` 原有 `IN` 操作符首次用于商品列表。`AdminRead.prefetch_goods()` 按游戏一次 `mid IN (...)` 扫描，按 `mid` 分组缓存；`search_goods_page()` 命中缓存时本地切片，页码 / 去重 / scope 校验完全保留；新增 `model_provider_batch`（`provider.py` 实现 + `bridge.py` 动作分发 + `backend-client.mjs` 读白名单），`admin-price-provider.mjs` 从 49 次单模型调用改为按游戏 4 次批量、逐游戏串行。
- 五个坎（均实测确认后才改，每个都走 PR + `pr-fast` 全套）：
  1. #600 批量本身：请求数 49→4，但 1327 组扫描吃满整份 45s 预算。
  2. #602 `limit=50` 分页反而更慢（1327 三次分页累计 7.4s），改 `limit=200` 单页 240ms 取全 132 行；新增 `reset_catalog_budget()`，让扫描与详情各用各的窗口。
  3. #603 44 次模型详情共用一个 45s 窗口仍不够（15 成 / 29 败），改为每模型独立预算；`await reads.get()` 的 rejected promise 改为逐条降级 `observation=null`，使 `sticky` 跨轮兜底首次真正生效。
  4. #604 全部成功但整组 196s，超过子进程 180s 上限被 kill，放宽到 300s。
  5. #606 1327 组稳定 42/44，2 条 `CATALOG_SEARCH_HTTP_REJECTED` 瞬时失败且永远进不了 sticky，改为扫描后对失败模型在原缓存上重试一次。
- 数据一致性（改代码前只读验证）：44 个 FC27 模型一次 `IN` 取全 132 行 / 3 页 / 503ms、无缺失；抽样 3 个 `mid` 与单查（带 `cid`）逐 `id` 比对完全一致（`only_in_IN=0 only_in_single=0`）。
- 请求量：列表查询约 110 次 → 9 次；bridge 子进程 49 个 → 4 个。
- 配置：`policy.json` 的 `admin_reference_prices.refresh_interval_ms` 60000 → 300000（实测单轮约 190s，60s 间隔等于连轴打上游）；`entries` 53 条 / 49 唯一模型、`max_age_ms` 900000 均未动。
- 回退点：`/var/backups/fs-campaign-batch-20261028/`（改造前 5 个文件）、`/var/backups/fs-campaign-price-timeout-20261028/`、`/var/backups/fs-campaign-price-current-20261028T1945/`。
- 遗留：单轮约 190s 主要耗在 44 次模型详情（约 4s/次，历史 0.3s），组内并发可提速，本轮未做；`release_id` / `state.published` 未随本次部署更新；D4 替换 WoW 未上线。

### 2026-11-16 `nav-20261116T095231Z`（PR #1160）FC 三页领账户券 + 活动页登录

- 来源：PR #1160（head `26c4bbc`，`pr-fast` success），合并 `3ed7aa298f9b2d67b9f1efd36af133a29b96f75b`。候选目录 `/var/tmp/fs-campaign-release72-candidate`，manifest `bc69d6d76054…`。
- 目标 8 个：`app/activity.js`、`app/activity.css`、`app/native-code-handoff.js`、`app/runtime/static-manifest.json`，加 4 个必需边界文件（原样，哈希不变）。`inspect` 报 `sourceCAS/protectedCAS passed`、`mutations:false`；apply 返回 `applied-awaiting-actual-http-role-acceptance`。
- 发布前基线：线上 `activity.js`、`activity.css` 与合并前 main 的内容一致，只是换行为 CRLF（转成 CRLF 后哈希完全一致）。本次改为发布合并提交的 LF 原文。
- 静态清单：110 个键不变，只更新这 3 个文件的哈希。
- 内容：结账时先按 slot 调用主站 `/ajax/carnival/coupon` 和 `/claim`。页面对应的 slot 为 `fc27-weekly→fc_weekly`、`fc27-sbc→fc_sbc`、`fc27-trio→fc_trio`。领券成功后不再暂存优惠码。未登录用户会看到登录弹窗，支持邮箱、Google、Facebook 登录，也可以选择以游客身份继续走带码流程。
- 读回时发现问题：领券和加购都成功了，但购物车没有选中任何券（优惠 $0）。由下一次发布修复。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T095231Z`。

### 2026-11-16 `nav-20261116T100745Z`（PR #1161）购物车自动选中刚领取的券

- 来源：PR #1161（`pr-fast` success），合并 `80778ecdfdcc26a479a876b87207fa55006075bd`。候选目录 `/var/tmp/fs-campaign-release73-candidate`，manifest `cfa6e6d50dda…`。
- 目标 8 个，有变化的是 `activity.js`、`native-code-handoff.js` 和静态清单；`activity.css` 和 4 个边界文件哈希不变。`inspect` 报 `sourceCAS/protectedCAS passed`。
- 内容：主站购物车只会在加载时根据 `sessionStorage.pending_member_coupon_id`（`applyPendingMemberCoupon`）选中对应的券，所以领券成功后先把 `member_coupon_id` 写入这个键，再跳转购物车。
- 真实入口读回：测试账号在 `www.mmoexp.com/events/Player-Trio.html` 上选择 Victor Ibarbo → Confirm，领到 `member_coupon_id=1033749` 并完成加购，跳转 `/Cart.html` 后自动选中 1033749，商品价 $153.76 抵扣 -$15.38（10%）；`pending_member_coupon_id` 和 `pending_discount_code` 都已被购物车消费，未付款。三页静态资源 `?v=` 均为新哈希，Weekly 页控制台无报错。
- 相关 Admin 配置（正式站点 266）：券 1395 `FC27 Event 10% Coupon`（9 折、无门槛、领取后 7 天有效、不限领取次数）；carnival 的入口 `fc_weekly`、`fc_sbc`、`fc_trio` 都挂 1395；总开关开启，起止时间 2026-11-15 至 2026-12-02，档位券为空。
- 未验证：真实账号的 Google、Facebook 完整授权流程；邮箱登录的真实提交；登录弹窗在手机宽度下的显示效果。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T100745Z`。

### 2026-11-16 `nav-20261116T104906Z`（PR #1166）登录错误反馈、顶栏登录态、只用券结账

- 来源：PR #1166（`pr-fast` success，含新增浏览器端到端测试 `coupon-login-browser.test.cjs`），合并 `934bc6e391d2415d5f65938eb4dbacbd34965440`。候选目录 `/var/tmp/fs-campaign-release74-candidate`，manifest `c6aa6621bf7e…`；`activity.js`、`activity.css`、`native-code-handoff.js` 和静态清单有变化，4 个边界文件不变，`inspect` 报 `sourceCAS/protectedCAS passed`。
- 起因（用户验收未通过）：输入未注册账号后，主站返回「Invalid email or password」，页面却只显示成灰色小字，还清空了自动填充的密码，用户看起来像卡死；顶栏没有登录态；页面仍保留优惠码文案和「游客用码」入口。
- 内容：
  - 登录请求与在主站 `/Fc-27/Coins.html` 抓到的原生请求逐字段一致：只提交 usname、passwd、remPwd、site_id，不带 loginbindkey，Accept 和 Content-Type 与 jQuery 发出的相同。
  - 登录失败时：显示红色 `role=alert` 提示，两个输入框标红，保留已输入内容，提交按钮显示「Logging in…」，超过 15 秒判定超时。
  - 三页顶栏在运行时注入：未登录显示 Log In 按钮；已登录显示头像和等级相框（取 `/ajax/html` 中的 `user-avatar-img` 和 `member-level-avatar__frame`），并显示购物车数量。
  - 只用券：去掉游客用码入口和所有码相关文案。读取券列表失败时视为券服务关闭，静默回退到已发布的码；只有领取请求结果不明时才停止加购。
- 评估后未采用：整套或只搬主站登录框。实测主站页头 HTML 约 610KB；登录框依赖 jQuery、`start.min.js` 和约 14KB 的 `GV` 内联配置；载入 `public.min.css` 后活动页原有顶栏变成空白。长期方案改由主站开发提供官方登录组件。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T104906Z`。

### 2026-11-16 `nav-20261116T110448Z`（PR #1168）Google/Facebook 登录在活动页生效

- 来源：PR #1168（`pr-fast` success），合并 `e8ca752127a8877165ff8448feeb16a33d8f9489`。候选目录 `/var/tmp/fs-campaign-release75-candidate`，manifest `45d29808b1e7…`；`activity.js`、`native-code-handoff.js` 和静态清单有变化。
- 起因（线上验收发现）：第三方登录跳回 `?ba-user-token=…&member_welcome=1` 后，用户仍是未登录，令牌也一直留在地址栏。主站页面会在服务端把这个参数换成 `ba-user-token` Cookie 再去掉参数；活动页由 FS 提供，这两步都没有做。已在线上验证：把同一令牌交给主站 `/ajax/html` 请求一次，就会下发 Cookie。
- 内容：`native-code-handoff.js` 加载后立即从地址栏去掉令牌，早于统计脚本和浏览历史；格式合法的令牌只保存在内存中，并且只交给 `/ajax/html` 一次。`activity.js` 等这一步完成后，再刷新顶栏、恢复之前选的商品；如果页面缺少该模块，不影响页面渲染。
- 真实入口验收（正式站，用户账号，均未付款）：
  - 未登录：三页顶栏显示 Log In 和购物车数量；点结账会弹出登录框，此时不加购。
  - Google：在 Weekly 页选 Barcelona Player Bundle → 登录 → 跳回后地址栏已无令牌，`logged_in=true`，头像显示，所选商品恢复 → 确认 → 领到 1033789 → 购物车自动选中，$96.13 抵扣 -$9.61。
  - 邮箱：用户本人在 Trio 页选择 Florian Wirtz 和 Jakub Błaszczykowski，点击「Log in and continue」→ 领到 1033803 → 购物车自动选中，$111.27 抵扣 -$11.13。
  - SBC 页（已登录）：Lyon Women Player Bundle → 领到 1033779 → $64.89 抵扣 -$6.49。
  - 错误反馈：替换登录函数模拟失败返回，红框提示、输入框标红、内容保留、按钮恢复均正常；邮箱格式错误时同样显示红框。
- 未验证：Facebook 的完整授权流程（只确认了授权地址和回调 `api.mmoexp.com/auth/callback/facebook`）。线上手机宽度未实测，CI 已在 390px 宽度下断言页面无横向溢出、头像可见。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T110448Z`。

### 2026-11-16 `nav-20261116T115927Z`（PR #1171）同一账号 24 小时只给一张券

- 来源：PR #1171（`pr-fast` success），合并 `20fc246d668909686c0011af2dff8780ecaa9e0e`。候选目录 `/var/tmp/fs-campaign-release76-candidate`，manifest `e601057afaa4…`；`activity.js`、`native-code-handoff.js`、`activity.css` 和静态清单有变化。
- 内容：`claimActivityCoupon` 在浏览器本地按账号记录最近一次领券（`localStorage` 键 `fs-fc27-coupon-claims-v1`），24 小时内再次确认沿用已领到的那张券，不再向 `/ajax/carnival/claim` 发新领取；超过 24 小时才重新领。主站服务端冷却没有做（用户决定先不开任务）。
- 验证：单元测试覆盖冷却命中、过期、账号隔离。线上验证尚未专门做（用户明确先发布、验证晚点）。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T115927Z`。

### 2026-11-16 `nav-20261116T140355Z`（PR #1177、#1178）换阵容不再冲突；FAQ 补充 24 小时限领

- 来源：PR #1177 合并 `207b149d0ded77da33a0089c584bee90eb886170`、PR #1178 合并 `893ac854192f661ab9412d04432c86037f99fcf8`（均 `pr-fast` success）。候选目录 `/var/tmp/fs-campaign-release77-candidate`，manifest `41196b04d9bf…`；发布 `native-code-handoff.js`、`activity-content.js`、`Player-Trio.html`、`Sbc-Companions.html`、`Weekly-Scout.html`、`index.html` 和静态清单。
- 起因：用户验证时，同一标签页里第一次加购成功跳到购物车后，再选另一套阵容确认，报 `OPERATION_CONFLICT`，发生在任何购物车请求之前。根因是 `sessionStorage` 里的页面操作记录（`fs-native-page:*`）在成功交接后不释放，其签名含所选阵容；与购物车里是否有东西无关，所以没有做清空购物车。
- 修复：上一次操作已确认加购并跳转（`fs-native-cart:<id>` 状态为 `navigation_attempted_*`）且这次阵容不同，就开新操作；同一阵容仍按原样重放、不重复加购；UNKNOWN 或未完成的操作仍然阻断。
- FAQ：三页新增 “How often can I receive the 10% coupon?”，说明每个账号 24 小时内只能领取一次，期间重复下单不会再获得优惠券，冷却结束后可重新应用。
- 线上读回：三页 200 且均含新 FAQ；同一标签页连续选两套不同阵容，第二套直接进入购物车，不再冲突。
- 未部署：`activity-fragment-*.html` 和 `page-template.html`。线上这几份与仓库本来就有较多差异（模板 85 行、片段 40 多行），不在静态清单内，本次不覆盖。
- 同一阵容再次确认仍是重放：页面提示正在打开购物车但不会跳转也不会再加购，这是现有测试规定的行为，未改。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T140355Z`。

### 2026-11-16 `nav-20261116T141615Z`（PR #1179）三人组、SBC 整组加购

- 来源：PR #1179（`pr-fast` success），合并 `12d57edf3ba4420815de91829c491e45fef4e6c1`。候选目录 `/var/tmp/fs-campaign-release78-candidate`，manifest `f258f811f67e…`；`activity.js`、`activity.css`、`activity-content.js` 和静态清单有变化。
- 内容：三人组的三张球员卡没有各自的加购按钮，一个按钮整组添加或移除。SBC 的两个搭档下拉移到各自商品卡内，一个按钮把两位搭档一起加入；选“Include SBC completion”时连同 SBC 服务共 3 件。SBC 服务不再能单独被选中。Weekly Scout 不变。
- 测试：新增 `group-add-browser.test.cjs`；逐张点击的旧用例改为点整组按钮。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T141615Z`。

### 2026-11-16 `nav-20261116T143252Z`（PR #1181）整组卡片不再有任何单张按钮

- 来源：PR #1181（`pr-fast` success，第一次因 `ops-presentation-browser.mjs` 的管理中心编辑器重载时序偶发失败，原样重跑通过），合并 `11ba9bd42dd2dd595c4f724457ff3f9bbc001ac9`。候选目录 `/var/tmp/fs-campaign-release79-candidate`，manifest `067cef7a2bba…`；`activity-content.js` 和静态清单有变化。
- 起因：用户发现价格暂时不可用时，整组卡片仍显示灰色的 “Purchasing unavailable” 单张按钮。现在整组卡片任何状态下都不渲染按钮，只显示小标签，整组按钮是唯一操作入口，价格没好时置灰。
- 线上读回（正式站，测试账号，价格同步完成后）：
  - Player-Trio：卡片无按钮；整组按钮一点 3 件进清单，$39.93；确认后购物车新增 Seydou Doumbia、Emmanuel Emenike、Victor Ibarbo 三件，10% 券自动应用（折扣 -$12.51）。
  - Sbc-Companions：卡片无按钮，两个下拉在卡内；整组加入 2 件 $13.63，含 SBC 服务 3 件 $14.91，审核弹窗列出 3 行。SBC 整组的实际加购没有在线上确认，只验证到审核弹窗。
- 价格同步：每次发布后公开配置里 FC 三页的现价会短暂缺失（页面显示 Price unavailable，整组按钮置灰），发布后约 1 分钟恢复；本次 14:32 发布后 14:34 读回三页都有现价。
- 未验证：手机宽度线上实测（本地 390px 截图检查过）；24 小时限领的线上专项验证。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T143252Z`。

### 2026-11-16 `nav-20261116T150739Z`（PR #1184）活动券追踪与消费归因，优惠码统计保留

- 来源：PR #1184（`pr-fast` success），合并 `9b5f58761003e4d6f08927ddd415ec23e67510a2`。候选目录 `/var/tmp/fs-campaign-release80-candidate`，manifest `69797417c7b7…`；发布 `app/activity.js`、`app/seasonal/activity-analytics.js`、`app/analytics/{backend-client,coupon-usage(新),dashboard,funnel-core,production-server,server,statistics-refresh}`、`backend/bridge.py`、`backend/campaign_backend/discount_revenue.py` 和静态清单；`statistics-retry.mjs`、`google-traffic.mjs`、`backend/google_traffic.py` 因发布工具的依赖校验一并放入，内容未变。发布前核对了线上这些文件与上一版仓库内容一致（忽略换行），没有覆盖仓库外的改动。
- 页面追踪：线上三页使用的 `seasonal/activity-analytics.js` 新增 `activity_coupon_claim`，只带领取状态（claimed）、是否沿用（coupon_reused）和券模板 ID；不带账号或会员券 ID。`activity.js` 在领券后把这三项交给追踪器。漏斗新增 `couponClaims`（新领券的访问批次）和 `couponReused`（沿用已领券的访问批次），随 PostHog 查询、计划汇总一起保存。
- FS 归因：后端新增只读动作 `coupon_usage`（`discount_revenue.py`）。累计发放/使用取自券 1395 的记录（先核对 `param_code=carnival_202611`、站点 266、游戏 1327）；窗口内使用取自 `user/memberCouponLog`，按券模板过滤、按使用时间分窗（单窗最多 28 天）；Admin 订单只用来识别退款，个别日志订单在订单列表里查不到时按日志状态与金额，不整体失败。日志 `status` 在 Admin 页面标为“订单支付状态”（1 已付款、0 未付款）。输出已付款/未付款/含退款订单、付款金额、券抵扣、买家数、用券后 90 天复购（Admin 口径，截至读取时），以及领取→使用（累计）和用券订单付款率；分母为 0 时给空值，不记零。
- 看板：`/analytics/api/coupon-usage`（需登录，匿名 302）和 FC 看板「活动券使用与转化」面板，位于「活动码付款收入」之后，含“优惠码（保留）+ 优惠券 = 合计”对照；读取失败显示不可用。优惠码收入、FCSCOUT10 口径及三页合计的说明未改。
- 验证：
  - 测试：后端 `test_coupon_usage.py`；Node `coupon-usage.test.mjs`；漏斗、追踪、看板浏览器用例；页面事件不含账号标识的断言。
  - 预发布干跑：在 187 上用 Python 3.9 对真实 Admin 数据跑完整读取路径（券 1343、11-16 窗口），41 条使用记录与 Admin 原始总数一致，订单全部匹配，券标识只在内存中替换。
  - 线上读回（正式站）：已部署的 `bridge.py` 对券 1395 返回累计发放 16、使用 0、窗口内无使用记录；FS 看板切到 FC27 后面板显示 16 / 0 / 0.0%、码与券对照行；三页 200，线上脚本含新事件监听和领券参数。
- 未验证：线上真实“领券事件”未触发（统计事件需访客同意，不替用户点同意）；券 1395 目前没有真实使用订单，付款金额、抵扣和复购在真实订单出现后才能读到数字；逐日发放未单独读取。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261116T150739Z`。

### 2026-11-17 `nav-20261117T061952Z`（PR #1198）狂欢盛典活动页 /events/Carnival.html

- 来源：PR #1198（`pr-fast` success），合并 `30a8c3bc1a48c953f67969c2f60de4d9023589d9`。候选目录 `/var/tmp/fs-campaign-release81-candidate`，manifest `0e7dc3a629c1…`。新增 `Carnival.html`、`carnival.css`、`carnival-proto.js`、`carnival-live.js`、80 张 `assets/carnival-*.webp`、`runtime/carnival.mjs`、`analytics/carnival-unlocks.mjs`；修改 `runtime/{server,snapshot}.mjs`、`analytics/{backend-client,production-server}.mjs`、`seasonal/activity-analytics.js`、`backend/bridge.py`、`backend/campaign_backend/discount_revenue.py`；`google-traffic.mjs`、`backend/google_traffic.py` 因依赖校验带上，内容未变。静态清单由 110 项增加到 194 项（只增加狂欢盛典文件）。发布前核对被替换的 9 个线上文件与合并前仓库内容一致，新文件线上原本不存在。
- 功能：首页 10% 券、神秘商店（服务端抽奖，首轮保底至少一张 15%，之后 40/40/20）、黑五十场（场次开始才放出商品和券）、扭蛋入口、专属码；领券后留在活动页提示，不自动跳转。神秘商店解锁不做定时刷新：会员付款后点「I'VE PAID · VERIFY & RESET」，运行时排一个请求（同一会员同一券组 30 秒内最多一次，队列上限 500），看板只在有请求时读一次 Admin 券记录，写入 `/var/lib/fs-campaign-public/carnival-unlocks.json`，页面弹窗告知成功、未完成购买或暂时无法核对。请求文件名只用会员 ID 哈希。
- 验证：
  - 测试：运行时抽奖与保底、校验队列、看板校验器、券追踪等 62 项；浏览器脚本 `carnival-mystery-browser.mjs`、`carnival-page-browser.mjs`（含校验按钮流程、领券后不跳转）已加入 `pr-fast`。
  - 服务：apply `EXIT=0`，`fs-campaign-dashboard`、`fs-campaign-runtime`、nginx 均 active。
  - 正式站读回：页面、样式、两个脚本和追踪脚本 200；页面和脚本引用的 80 张图全部 200；`api/carnival/schedule` 返回 upcoming 和 10 场；`api/carnival/mystery` 返回各游戏可抽、`verify:null`；`mystery/verify` 无 Origin 返回 `ORIGIN_REQUIRED`，带主站 Origin 返回 `EVENT_NOT_STARTED`。桌面版渲染正常、无坏图、控制台无报错。
- 未验证：活动 11/19 开始前无法在线上实际抽奖、领券和校验付款；登录后的完整流程、统计事件的真实触发（需访客同意）、手机宽度线上实测（本地浏览器测试覆盖）都待开始后确认。
- 待办：11/19 北京 13:00 前把 Admin 中 carnival 的开始/结束改为 11/19 13:00 – 12/2 13:00（Admin 写操作，需用户执行或授权）；扭蛋档位领券接口和签名 uid 待主站开发确认。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261117T061952Z`。

### 2026-11-17 `nav-20261117T065836Z`（PR #1201）狂欢盛典顶栏、平台选择、内部测试开关

- 来源：PR #1201（`pr-fast` success），合并 `4d0921e2f496fa92286ced9e0cc46091203ae948`。候选目录 `/var/tmp/fs-campaign-release82-candidate`，manifest `6b1655184719…`；发布 `Carnival.html`、`carnival.css`、`carnival-proto.js`、`carnival-live.js`、`runtime/carnival.mjs`、`analytics/carnival-unlocks.mjs`、`backend/campaign_backend/discount_revenue.py` 和静态清单。发布前核对线上这 7 个文件与上一版合并 `30a8c3bc` 内容一致。
- 改动：顶栏与主站一致（logo、栏目链接、购物车、主站登录态，Log In 打开活动登录框），去掉中英文切换；修复 FC27 平台下拉不显示（`livePriceNotes` 覆盖了下拉外层 span）；吉祥物气泡去掉 “The item pool updates, too.”；黑五 “?” 占位卡居中。
- 内部测试开关：运维写入 `/var/lib/fs-campaign-public/carnival-test.json`（`{open_until, coupon_id, slot}`，`open_until` 不晚于正式开始 11/19 00:00 ET）后，全部环节开放、所有领券走测试槽位和测试券，校验器只读该测试券的已付款使用；到 `open_until` 或删除文件即关闭。本次发布时该文件不存在，线上行为不变。
- 验证：
  - 测试：Node 160/160；浏览器 carnival 页面 7/7、神秘商店 3/3；Python `test_carnival_unlocks` 5/5。
  - 服务：apply 成功，`fs-campaign-dashboard`、`fs-campaign-runtime` 于 14:58:44 重启并 active。
  - 正式站读回（Chrome，已登录）：三个资源均为 `?v=20261117b`；顶栏存在、logo 加载、无语言切换、登录后 Log In 隐藏且显示头像；平台下拉可见；气泡不含旧句；`schedule` 为 upcoming 且无 `test` 字段；控制台无报错。
- 未验证：内部测试开关的线上实测（需先建测试券、加测试槽位、开 TempActivity，属 Admin 写操作，待用户授权）；手机宽度线上实测（本地浏览器测试覆盖）。
- 另记：`fs-campaign-statistics-refresh` 11/17 08:00 一次运行以 partial 退出（exit 2），早于本次发布，与本次改动无关。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261117T065836Z`。

### 2026-11-17 `nav-20261117T081421Z`（PR #1203）狂欢盛典内部测试反馈

- 来源：PR #1203（`pr-fast` pass），合并 `7c4dc2366e933a46f330e8919063eda2d71d7b7d`。候选目录 `/var/tmp/fs-campaign-release83-candidate`，manifest `a028796d6844…`；发布 `Carnival.html`、`carnival.css`、`carnival-proto.js`、`carnival-live.js` 和静态清单。发布前核对线上这 4 个文件与上一版合并 `4d0921e2` 内容一致；inspect 的 sourceCAS、protectedCAS 均通过。
- 改动：
  - 神秘商店切换游戏恢复（`renderTabs` 不再访问已移除的演示提示）。
  - 价格：D4、POE、ARC 大类目按标题关键字查找；AION 2 按区域 `sid` 区分同名服务器；POE 小额通货用未四舍五入的单价。
  - 翻牌和黑五商品领券后显示「立即结算」：清空购物车，加入同一商品一次，带会员券打开 `/Cart.html`；商品页链接保留作后备。
  - 首页 10% 券领过后按钮变灰、不可点，显示已领取。
  - 黑五代金券卡片突出 “$X OFF” 和 COUPON，门槛和使用期限缩小。
- Admin（用户 2026-11-17 要求）：神秘商店券 1401–1435 共 18 张，`repeat_qty` 由 3 改为 0（不限领取次数），逐张读回只有该字段变化。
- 验证：
  - 测试：浏览器 carnival 页面 + 神秘商店 13/13，carnival 单元测试 4/4。
  - 服务：apply 成功，dashboard、runtime、nginx 均为 active。
  - 正式站读回（Chrome，已登录，未动购物车）：脚本为 `?v=20261117c`；6 个游戏切换后选中状态跟随，无报错；AION 2、D4、POE1、ARC、WoW 全部有价格；FC27 球员 Achraf Hakimi 仍为 PRICE PENDING（球员类目超过翻页上限），由下一次发布修复。
- 未验证：「立即结算」在线上真实清空并加购（会清掉用户自己的购物车，留给用户实测）；首页按钮变灰在内部测试期间看不到，因为测试券 1517 不限领取（`repeat_qty=0`），会一直显示可领，正式券 1399 限领 1 次。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261117T081421Z`。

---

## 回退与边界

- 代码回滚不放回 policy、公开配置、优惠码或派生价格缓存；数据与账本保留在原位置。
- 不恢复退役 publisher，不整包覆盖线上目录，不改认证、经营看板或采集计划。
- 每次发布的目标清单、基线哈希、备份路径与读回见原发布回执（`/var/tmp/fs-campaign-release*-candidate/apply-receipt.json`）。
