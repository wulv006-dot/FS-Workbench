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

### 5. 万圣节奖池扩容与价格并发（PR #560 / #561，policy + 代码）

- 来源：分支 `codex/seasonal-countdown-widget80`；#560 合并后 `MAX_PRICE_ENTRIES` 20 → 80；#561 把 `admin-price-provider.mjs` 的逐个 `await` 改成先缓存 Promise 再 `Promise.allSettled`。
- 池子写入（policy，非代码发布）：42 个模型 / 126 个商品 / 378 条 binding 增量，`valid_until` 一年；`set_end_only.py` 结构化只改 `halloween.ends_at = 2026-11-08T23:59:59-05:00`（文本替换会导致 `RUNTIME_UNAVAILABLE`）。
- 结果：公开配置 `campaign-preview-10`，池 44 个模型、价格覆盖 49 个合约 / 247 个商品、43 个可抽；连抽 5 轮得到 5 个不同球员。
- 排除项：模型 `43042209` 的 PC 行数量与已发布 contract 不一致（`admin-266-1327-169757277-21589`），已在价格清单 SKIP——它仍在池内但无价，因此抽不到。
- 已知坑：`PUBLIC_OPTIONS_CONFLICT` 是**整份缓存**失效（provider 拿 Admin 实时行与 contract 的 `quantity`/`attributes`/`product_ref` 逐项比对，任一条不一致即全灭）；policy 落盘后必须 `chmod 600`，`os.replace` 会改成 644 触发 `PRIVATE_PRICE_POLICY_REQUIRED`。

### 6. `nav-20261027T101723Z`（PR #562：倒计时移到右上角）

- 目标：`seasonal/index.html` + `event.js` + `event.css`。
- hero 的 `ENDS IN` 从角色脚下 `.story-bottom .event-meta` 移到 `.game-picker .picker-actions`（右上角，与 `04 STORES` 同排）。
- 进游戏后 `#event-countdown.hidden = !!activeGame`，专区页只保留每日刷新倒计时；移动端 `.picker-actions` 改 `flex-wrap` 让倒计时独占一行。

### 7. `nav-20261027T103401Z`（PR #563：4K 视口空白）

- 目标：`event.css`。
- 原因：`.hero` / `.hero-inner` 固定 `min-height:608px`，4K 下内容只到 608，下方全空。
- 修法：`@media(min-height:780px)` 下 `body{min-height:100vh;display:flex;flex-direction:column}` + `main/.hero{flex:1}` + `.hero-inner{align-content:center}`；超宽屏 `@media(min-width:2000px){--content:1760px}`。
- 实测 3840×2160：`document.scrollHeight=2160` 与视口等高；1600×1000 仍 1380px。

### 8. `nav-20261027T111052Z`（PR #564：卡片化与版式适配）

- 目标：`event.css` + `event.js` + `index.html`。
- 三列 offer 改为完整商品卡（价格与 Buy Now 进卡内）；卡高 `clamp(300px,32vh,540px)`；球员标题拆主标题 + 副属性行；新增 About/FAQ 区块（4 条）填充高视口。
- 口径依据：内容列限宽 1200–1440px（宽屏可适度放大但有上限），`clamp()` 流式排版，超宽屏靠"限宽 + 放大主体 + 真实内容区"而不是无限拉宽。

### 9. `nav-20261027T135337Z`（PR #567：价格不消失 + 三卡统一 + 翻转可恢复）

- 目标 97 键静态清单内的 3 个 seasonal 文件（`event.js` / `event.css` / `index.html`）。
- 价格保留：`lastPrices` Map 按 `game:model:off:qty` 缓存，`referenceFor` 取价失败时回退到最后一次成功值；文案 `Limited-Time Price`；删除 `Choose your server to continue` 与 native binding 提示。**结算仍按实时价**（用户明确接受的折中）。
- 三卡统一：`faceContent()` 统一正面（商品图 + 名称 + 右上角折扣徽章），固定卡背面也改为 `? Reveal your surprise`，标签统一 `MYSTERY PICK 01/02/03`——固定池身份不再对外暴露。商品图当时为占位 `✦`。
- 翻转卡死：`standalone-adapter` 的 fetch 原本无超时，挂起时卡片永久禁用；已加 `AbortSignal.timeout(15000)` + reveal 重试一次（复用同一 request_id，不会重抽）。
- 跨天重置：`nyDay()`（America/New_York）变化时清 `revealed`/`receipts`/`lastPrices`，卡片合上重新翻。

### 10. `nav-20261027T143508Z`（PR #568：过期价格不再空转刷新）

- 目标：`event.js`。
- 风险属实：`lastPrices` 保留了过期的 `expires_at` → `nextExpiry` 是过去时间 → 定时器延迟被钳成 1ms → 每 1ms 重建卡片并调 `refresh()`。
- 修法：定时器加 5 秒下限；`#offer-slots` 的 innerHTML 只在内容变化时写。实测 12 秒内 DOM 变更 0 次（修复前每 1ms 一次），价格仍保持显示、过期后仍能及时刷新。

### 11. `nav-20261027T173601Z`（PR #570：去掉卡片游戏小字 + 游戏卡提亮）

- 来源：分支 `codex/seasonal-card-polish86`，合并 `a4761cf664379498c4de0adb4e13d939768199b1`；CI run `40550894894` success。
- 目标 6 个 / 实际变化 2 个（`seasonal/event.js` + `seasonal/event.css`）；manifest `b9c7d7ceb71b396a40cf21fee89ae1c4e4f4e1af04f8a5aad8b52a2980529e50`。
- ① 用户要求去掉商品卡正面的游戏小字（FC27 / Aion2）：`faceContent()` 不再输出 `<small>` 游戏名，正面只剩徽章 + 商品图 + 标题 + 属性行。
- ② 四张游戏卡偏暗的根因是同日 15:18 的提交 `fb533e7`（PR #554 "seasonal page polish and reachable live checkout"），给 `.game-art` 加了 `filter: saturate(.78) brightness(.8)`，`.game-shade` 又叠了一层压到纯黑 `#0b0717` 的紫色遮罩。本次改为 `saturate(1.04) brightness(1.12) contrast(1.02)`，遮罩顶部 .42→.10、中部 .26→.06、底部保持 .9（标题仍压在近不透明区）。
- `runtime/static-manifest.json` 两个键同步：`seasonal/event.js` `f98f31f4…`、`seasonal/event.css` `8bf8aebf…`；旧清单备份 `runtime/static-manifest.before-nav86.json`。
- 上线读回：四个服务 `active`、`STATIC_HASH_MISMATCH` 0 次、`/events/seasonal/` 200；卡正面 innerText 为 `10% OFF ✦ coins 1000K Coins`（无游戏名）、槽位仍 `MYSTERY PICK 01/02/03`、价格 `$71.91` / `Limited-Time Price` / `unavailable-price` 0 个；第一张游戏卡原图平均亮度实测 118/255（改动前的数值未在同一会话取样，不作对比声明）。
- 回退点：`/var/backups/fs-navigation-20261006/nav-20261027T173601Z`。

---

## 回退与边界

- 代码回滚不放回 policy、公开配置、优惠码或派生价格缓存；数据与账本保留在原位置。
- 不恢复退役 publisher，不整包覆盖线上目录，不改认证、经营看板或采集计划。
- 每次发布的目标清单、基线哈希、备份路径与读回见原发布回执（`/var/tmp/fs-campaign-release*-candidate/apply-receipt.json`）。
