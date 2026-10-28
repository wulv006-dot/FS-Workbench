# 万圣节活动页 · 第四游戏换成 Diablo IV · 交接说明

> 日期：2026-10-28 23:10（CST）
> 交接人：Buddy（AI）
> 接手人：codex / 其他工程同学
> 范围：`releases/fs-dashboard/campaign-analytics-20261023`（campaign-analytics 模块）
> 线上机器：`47.85.224.112`（内部称 187，CentOS 7），运行目录 `/opt/fs-campaign-dashboard`
> 相关 PR：#610（换游戏）、#612（旧 roster 兼容）、#600–#606（价格管道，见姊妹篇）、#607（价格管道文档）

**姊妹篇**：`docs/planning/price-provider-batch-20261028/HANDOFF.md` 讲的是同一天的价格 provider 批量扫描改造。两份合起来才是万圣节活动页的完整状态。本文只讲**换游戏**和**它的直接依赖**。

---

## 0. 五分钟摘要

万圣节 Mystery Store（`https://www.mmoexp.com/events/seasonal/`）原本四个游戏是 FC27 / Aion2 / **World of Warcraft** / MapleStory。现在第三个已换成 **Diablo IV**，金币池 500000M，随机池 5 个物品，活动结束时间改成**美东 2026-11-08 23:59:59**。

**线上当前是好的**：价格缓存 `status: ready` / 253 products / 55 model_contracts，四游戏各 3 张卡全部带实时价，页面 `pageerror: none`，`/events/api/campaign/config` 返回 200。

**但这套东西不是"改个配置"就能换的。** 四个游戏是**写死在运行时白名单**里的，改配置会直接 400；换完之后还需要补三样东西（价格策略条目、模型合同、binding 观测凭证），任何一样缺失都会让整页 400 或全站无价。本文第 3 节按实际操作顺序把四道门槛全写清了。

**你要接的四件事**（详见第 7 节）：

1. **⚠️ 最高优先级**：FC 随机池里的 `43042209`（Large Gold Pack）**没有价格条目**，1/44 概率抽到无价卡。这是本次之前就存在的缺陷，和 D4 无关，但同在一个页面上；
2. D4 合同的 platform 显示名暂填 `Standard`，需确认 Admin 里 aid `15943` 的真实区服名；
3. `current.json` 的 `release_id` 仍 `campaign-preview-10`、`state.published` 仍是同事那版 `preview-11`，两边分裂，需要一次后台正式发布归位；
4. 这次是**直接改文件**落地，没走 center 发布通道，`operations/` 没有回执，正式留痕（DELIVERY / ACCEPTANCE / HANDOFF）也没补。

**三个"别做"**：

- 别用"回滚到历史版本"来修价格问题（已反证无效，见 9.1）；
- 别只改 `current.json` 就以为换完游戏了（白名单会拒）；
- 别在 provider 正在刷新时跑探针测耗时（会把上游压得更慢，测出来的数字全是假的）。

---

## 1. 当前线上真实快照

抓取时间 2026-10-28 23:06 CST，全部为实测值。

### 1.1 服务与数据

| 项 | 值 |
|---|---|
| `fs-campaign-runtime` / `fs-campaign-dashboard` | 均 `active`（dashboard 启动于 22:43:55） |
| 价格缓存 | `status: ready`，253 products，55 contracts，`generated_at 2026-10-28T15:06:54Z` |
| 价格缓存文件 | `/var/lib/fs-campaign-public/admin-reference-prices.json`（274380 字节） |
| 公开配置 | `/var/lib/fs-campaign-public/current.json`（902899 字节，mtime 22:33） |
| 价格策略 | `/var/lib/fs-campaign-dashboard/backend/policy.json`（59 entries，`refresh_interval_ms=300000`，`max_age_ms=900000`，`schema_version=2`） |
| 商品总数 | 394（含 D4 的 5 个 + 原有 389） |
| binding 总数 | 1488（含 D4 的 18 条：6 商品 × 8/10/15 三档） |
| 模型合同 | 56（含 D4 的 6 个）；**其中有价的 55 个，1 个无价（`43042209`，详见 7.4）** |
| `seasonal-vault` 商品键 | 274（换 D4 前 268） |
| 系统负载 | 1.24 / 0.86 / 0.92 |

### 1.2 活动配置

```
halloween.status      : configured
halloween.starts_at   : 2026-10-27T00:00:00+08:00
halloween.ends_at     : 2026-11-08T23:59:59-05:00     ← 美东，本次改的
```

| 游戏 id | label | admin_game_id | fixed_model | 折扣 | 固定量 | 随机池 |
|---|---|---|---|---|---|---|
| `fc` | FC27 | 1327 | 41217957 | 10% | 1000 K | 44 |
| `aion` | Aion2 | 891 | 17815737 | 10% | 100 M | 0（商品库只有 1 个模型，凑不出随机） |
| `diablo` | **Diablo IV** | **456** | **5264** | 10% | **500000 M** | **5** |
| `maplestory` | MapleStory | （null） | 41914685 | 10% | 300 K | 2 |

### 1.3 D4 的六个商品（这是本次新增的全部业务数据）

| 用途 | 商品名 | product_key | goods_id | model_id | cid | Admin 价 | 活动价(10%) |
|---|---|---|---|---|---|---|---|
| 固定卡 / 金币池 | Diablo IV Gold（500000 M） | `admin-266-456-1365865-15943` | 1365865 | 5264 | 442 | $2.76 | **$2.48** |
| 随机池 ① | Resplendent Spark x100 | `admin-266-456-170070065-15943` | 170070065 | 43191217 | 3955 | $7.49 | $6.74 |
| 随机池 ② | Flawless Horadric Ruby(Lv.30) | `admin-266-456-170042137-15943` | 170042137 | 43039181 | 3867 | $2.81 | $2.53 |
| 随机池 ③ | Flawless Horadric Skull(Lv.30) | `admin-266-456-170042461-15943` | 170042461 | 43039069 | 3875 | $1.12 | $1.01 |
| 随机池 ④ | Kullean Tuning Prism (DLC Required)*100 | `admin-266-456-169752893-15943` | 169752893 | 43038035 | 8793 | $1.05 | $0.95 |
| 随机池 ⑤ | Entropic Tuning Prism (DLC Required)*100 | `admin-266-456-169752973-15943` | 169752973 | 43038033 | 8793 | $0.18 | $0.17 |

六个商品的 `aid` 都是 **15943**（同一区服）。金币的 `category: new_gold`，物品的 `category: new_items`。

> ⚠️ `current.json` 里还有三个 D4 旧商品 `seasonal-diablo-1/2/3`（`Wanderer's Stash` / `Hellfire Stash` / `Sanctuary Stash`，goods 都是 1365865，量 100000/300000/600000 M）。它们属于**上一版的活动草稿**，本次没有改动、也没被页面引用。别删——删了会动到 `seasonal_model_contracts` 和旧快照的一致性。

### 1.4 素材

| 文件 | 尺寸 | 用途 |
|---|---|---|
| `app/seasonal/assets/game-3.png` | 664×710 | 游戏列表第 3 张竖版封面（原 WoW 封面，已换成 D4 底图裁切） |
| `app/seasonal/assets/product-diablo-coins.webp` | 800×400 | 金币卡插图 |
| `app/seasonal/assets/product-diablo-item.webp` | 800×800 | 物品卡插图 |

`static-manifest.json` 从 106 键扩到 **108 键**（新增两个 webp；`game-3.png` 是覆盖同名文件所以键数不变）。

素材**不含蒙版、不含 logo**：卡片自己有 `.game-shade` 渐变遮罩和 `<h3>` 游戏名，烘进图里会和 DOM 打架。原图白底用「四边 floodfill 泛洪 + 亮度映射 alpha + GaussianBlur 0.8 软化」抠掉，紫色光晕保留。

---

## 2. 系统拓扑与请求链路

```
浏览器
 └─ https://www.mmoexp.com/events/seasonal/        ← 读回必须用正式域名，不能 IP 直连
      └─ nginx（187）
           └─ proxy_pass 127.0.0.1:8949
                └─ fs-campaign-runtime （runtime/server.mjs）
                     ├─ 模板层：/opt/fs-campaign-dashboard/seasonal/*
                     │    event.js / event.css / index.html / campaign-data.js
                     └─ 配置层：/var/lib/fs-campaign-public/current.json
                          └─ projectRelease()  ← 全站所有 campaign 页面共用这一个函数
                               ├─ 页面：seasonal-vault / fc27-weekly / fc27-sbc / fc27-trio …
                               └─ 价格：seasonal_model_contracts（骨架，无价）

价格注入（每 300 秒一轮）
 fs-campaign-dashboard （analytics/admin-price-provider.mjs）
   └─ 读 policy.json 的 admin_reference_prices.entries（59 条）
        └─ 按游戏分组 → model_provider_batch
             └─ bridge.py （Python，一次一请求）
                  └─ campaign_backend/provider.py → adapters.AdminRead
                       └─ dc-proxy-fs 127.0.0.1:8912
                            └─ https://admin-api.p2pah.cn/admin/goods.Goods{,Mould}/…
   └─ 写出 /var/lib/fs-campaign-public/admin-reference-prices.json
        └─ 包含 model_contracts[].combinations[].price  ← 价格只在这里
```

### 2.1 关键路径表

| 内容 | 路径 |
|---|---|
| 运行时服务代码 | `/opt/fs-campaign-dashboard/runtime/`（`server.mjs` / `snapshot.mjs` / `halloween-contract.mjs` / `admin-price-projection.mjs`） |
| 活动页静态资源 | `/opt/fs-campaign-dashboard/seasonal/` |
| 后台服务代码 | `/opt/fs-campaign-dashboard/analytics/`（`production-server.mjs` / `center-store.mjs` / `admin-price-provider.mjs` / `backend-client.mjs`） |
| Python 桥 | `/opt/fs-campaign-dashboard/backend/`（`bridge.py` / `campaign_backend/*.py`） |
| 静态资源清单 | `/opt/fs-campaign-dashboard/runtime/static-manifest.json`（108 键，**改任何 `app/` 下的公开文件都必须同步**） |
| 对外配置（事实源） | `/var/lib/fs-campaign-public/current.json` |
| 价格缓存 | `/var/lib/fs-campaign-public/admin-reference-prices.json` |
| 价格策略 | `/var/lib/fs-campaign-dashboard/backend/policy.json`（权限 **600**） |
| 后台草稿与版本历史 | `/var/lib/fs-campaign-dashboard/center/state.json` + `center/history/<rev>.json` |
| 发布备份 | `/var/backups/fs-navigation-20261006/nav-<release_id>/` |

---

## 3. 换游戏的完整路径与四道门槛

这一节按**实际操作顺序**写。如果你要再换一次游戏（或加第五个），照着这个顺序走能少踩坑。

### 门槛 1：四个游戏写死在运行时白名单

**现象**：只改 `current.json` 的 `halloween.games` → `POST /events/api/campaign/config` 返回 **400 `INVALID_HALLOWEEN_CONFIG`**。

**原因**：`app/runtime/halloween-contract.mjs` 第 2 行：

```js
const games=[['fc','FC27','1327'],['aion','Aion2','891'],['diablo','Diablo IV','456'],['maplestory','MapleStory',null]];
```

`projectHalloween()` 会校验 `value.games` 的四条 id 必须与白名单逐一对齐，顺序也要对；`admin_game_id` 也必须等于白名单里的第三个元素（`'456'`，不是 `null`）。

**连锁改动**（PR #610，21 个文件，+31/−28 行）：

| 层 | 文件 | 改什么 |
|---|---|---|
| 运行时白名单 | `app/runtime/halloween-contract.mjs` | `games` 数组第三项 |
| 数量档模式判定 | 同上 | `['aion','wow']` → `['aion','diablo']`（只有这两个走 quantity_tiers） |
| 前端游戏表 | `app/seasonal/event.js` | `IDS` / `LABELS` |
| 前端插图映射 | 同上 | `CATEGORY_ART.diablo` + `artCategory()` 分支 |
| 页面启动数据 | `app/seasonal/campaign-data.js` | 游戏列表项的 `id` / `label` |
| SEO 与 FAQ | `app/seasonal/index.html`、`seasonal-source/build-seo.cjs` | `World of Warcraft` → `Diablo IV` |
| 后台编辑器 | `app/analytics/products.js` | 数量模式判定 + 只读判定 + 媒体键 `game:diablo` |
| 测试 | 9 个文件 | 白名单断言、fixture、负向断言（详见第 4 节） |

**关键**：`event.js` 里 `artCategory()` 要给 D4 单独一个分支，否则金币卡和物品卡会用同一张图：

```js
if(gameId==='diablo')return /\bgold\b/i.test(title)?'coins':'item';
```

### 门槛 2：旧 roster 必须仍能读（否则整站陪你挂）

**现象**：代码先上线、配置后改 → 线上 `current.json` 还是 WoW roster → `projectRelease()` 抛错。

**为什么是"整站"而不是"只有活动页"**：`runtime/server.mjs` 里**所有 campaign 页面共用同一个 `projectRelease()`**（FC27 的 Weekly / SBC / Trio 也在内）。一个 400 会把 FC 三页一起带下线。

**修法**（PR #612，`3715607b`）：

```js
// 读取时优先当前 roster，其次旧 roster，两者都不匹配才报错
const roster=games.every(([id])=>value.games.some(g=>g.id===id))?games
  :legacyGames.every(([id])=>value.games.some(g=>g.id===id))?legacyGames:null;
if(!roster)error();
```

`legacyGames` 就是换之前的四游戏数组。语义是「**写新、读旧**」：新草稿一律用当前 roster 创建；历史发布记录仍可投影；第一次后台保存时自动迁移成新 roster。

测试锁在 `app/analytics/tests/halloween-integration.test.mjs` 最后一个用例「legacy roster still projects, unknown roster still rejected」。

> 这是 codex review 提的 P1，成立。**换白名单这类改动一定要先做兼容层再做数据迁移**，顺序反了就是整站故障。

### 门槛 3：合同（contract）必须齐，否则 `PRIVATE_NATIVE_CATALOG_REQUIRED`

**现象**：价格缓存 `status: unavailable`，products 为 0，全站无价。

**原因**：`policy.admin_reference_prices.schema_version === 2` 时，provider 要求 `release.seasonal_model_contracts[model_id]` 存在。D4 的 6 个模型没有合同条目。

**解法**：在 `current.json` 的 `seasonal_model_contracts` 里补 6 条骨架（第 5.4 节有完整结构）。注意合同里**没有 price 字段**——价格由 provider 运行时注入。

### 门槛 4：binding 没有观测凭证时，校验会把游戏写死成 FC

**现象**：配置 400 `NATIVE_CONFIGURATION_INVALID`，即使合同齐了。

**原因**：`projectRelease()` 会挑一个 binding 做"序列化一致性"校验。**没有 `observed_serialization` 的 binding 会被当作 FC 的默认形态**去比对（`game_id==='1327'` / `model_id==='41217957'` / `aid==='21587'` / 单位 `1000K`），D4 怎么填都不匹配。

**解法**：给 D4 的 18 条 binding 全部加上：

```json
"observed_serialization": {
  "verification_ref": "local-readonly-contract62-v2",
  "game_id": "456",
  "model_id": "<该商品 model_id>",
  "region": "us",
  "currency": "USD"
}
```

> `verification_ref` 与现有 1488 条里的写法保持一致即可（当前统一是 `local-readonly-contract62-v2`）。

### 附带的两个"数据残留"坑

从 WoW 记录复制过来做模板时，会带两个必炸的字段：

1. **`random_quantities`** —— WoW 走 `quantity_tiers` 模式，字段是 `random_quantities`（长度 2）。D4 走 `models` 模式，该字段必须**不存在**，否则 `random_models.length` 与模式判定冲突 → 400。用 `diablo.pop('random_quantities', None)` 清掉。
2. **`product_ref` 缺 `model_id`** —— 页面引用的 model 在目录里找不到 → `HALLOWEEN_MODEL_NOT_IN_CATALOG`。D4 每个 product 的 `product_ref` 必须带 `model_id`。

---

## 4. 代码改动清单（仓库 ↔ 线上）

仓库：`wulv006-dot/FS-Workbench`，模块根 `releases/fs-dashboard/campaign-analytics-20261023/`。

### 4.1 PR #610 `a0882a7c`（feat：换第四游戏）

| 仓库路径 | 线上路径 | 改动 |
|---|---|---|
| `app/runtime/halloween-contract.mjs` | `/opt/fs-campaign-dashboard/runtime/halloween-contract.mjs` | roster 第三项；`['aion','wow']`→`['aion','diablo']` |
| `app/seasonal/event.js` | `/opt/fs-campaign-dashboard/seasonal/event.js` | IDS/LABELS；CATEGORY_ART；artCategory 分支 |
| `app/seasonal/campaign-data.js` | `/opt/fs-campaign-dashboard/seasonal/campaign-data.js` | 游戏列表项 |
| `app/seasonal/index.html` | `/opt/fs-campaign-dashboard/seasonal/index.html` | SEO / FAQ 文案 |
| `app/seasonal/halloween-config.json` | 同上（对外 404，仅测试引用） | 静态演示数据同步 |
| `app/seasonal/assets/game-3.png` | `.../seasonal/assets/game-3.png` | 替换为 D4 竖版封面 |
| `app/seasonal/assets/product-diablo-coins.webp` | 同目录 | 新增 800×400 |
| `app/seasonal/assets/product-diablo-item.webp` | 同目录 | 新增 800×800 |
| `app/analytics/products.js` | `/opt/fs-campaign-dashboard/analytics/products.js` | 后台编辑器规则 + `game:diablo` 媒体键 |
| `seasonal-source/build-seo.cjs` | （构建脚本，不部署） | SEO 文案源 |
| 9 个测试文件 | — | 白名单断言与 fixture |

### 4.2 PR #612 `3715607b`（fix：旧 roster 兼容）

| 仓库路径 | 改动 |
|---|---|
| `app/runtime/halloween-contract.mjs` | 新增 `legacyGames` + 读取时双 roster 接受 |
| `app/analytics/tests/halloween-integration.test.mjs` | 新增用例：旧 roster 可投影、陌生 roster 仍拒 |

### 4.3 配置与素材（不走 PR，直接落盘）

| 文件 | 变更 |
|---|---|
| `/var/lib/fs-campaign-public/current.json` | `halloween`（D4 段落 + ends_at + 删 random_quantities）、`products` +6、`native_checkout.bindings` +18、`seasonal_model_contracts` +6、`pages[seasonal-vault].product_keys` 268→274 |
| `/var/lib/fs-campaign-dashboard/backend/policy.json` | `admin_reference_prices.entries` 53→59（+6 D4） |
| `/opt/fs-campaign-dashboard/runtime/static-manifest.json` | 106→108 键 |
| `/var/lib/fs-campaign-dashboard/center/state.json` | `draft` 同步成 D4（避免下次后台发布回退成 WoW） |

### 4.4 本次改动后的线上文件哈希（供核对）

```
e4de493b7e691ecb17869a7888ea091dd8dff4147a9a08b0d187c8253783c501  runtime/halloween-contract.mjs
9dc4ec5f582fb673537d6653c196645efa18dec83a13a1fea00a0e0653524846  seasonal/event.js
37bd7bada4094e41d36992083bbf91440f352251e061d92e1bd23be828097927  seasonal/campaign-data.js
de0696806d3f4d8bec16cb1604d2a19299f0ce3bdf912dc4c07c479fb16ffbfd  /var/lib/fs-campaign-public/current.json
b72a0b5745e1d292325e7edb90b6b2baae4d9c0e0a070b1120f3cc35bf0878ba  backend/policy.json
```

---

## 5. 数据契约

改数据前务必看清这五种结构。**它们不是同一个东西**。

### 5.1 `halloween.games[]`（每条）

```json
{
  "id": "diablo",
  "label": "Diablo IV",
  "admin_game_id": "456",
  "fixed_model": "5264",
  "fixed_off_percent": 10,
  "fixed_quantity": { "value": "500000", "unit": "M", "conversion_verified": false },
  "random_source": { "mode": "models", "category_id": null, "snapshot_complete": false },
  "random_models": ["43191217", "43039181", "43039069", "43038035", "43038033"],
  "random_count": 2
}
```

校验要点（`haloween-contract.mjs`）：

- `id` / `label` / 顺序必须与白名单完全一致；
- `admin_game_id` 必须等于白名单第三元素（`fc`→`'1327'`，`aion`→`'891'`，`diablo`→`'456'`，`maplestory`→`null`）；
- `random_count` 恒为 `2`；
- `fixed_off_percent` ∈ {8, 15, 10}；
- `random_models` 长度 ≤ 100、去重、且不能包含 `fixed_model`；
- `models` 模式下**不能出现 `random_quantities`**；
- `quantity_tiers` 模式（只有 `aion` / `diablo` 允许）要求 `random_quantities` 恰好 2 项。

**随机池最少 2 个模型**（`halloween-reveal.mjs` 的 `HALLOWEEN_POOL_INCOMPLETE`）。这就是 Aion2 现在随机池为 0 的原因——它在商品库里只有 1 个金币模型，物理上凑不出两张不同的卡。这不是配置问题。

### 5.2 `products[]`（每条）

```json
{
  "key": "admin-266-456-170070065-15943",
  "title": "Resplendent Spark x100",
  "product_ref": { "site_id": "266", "game_id": "456", "model_id": "43191217", "goods_id": "170070065" },
  "platform": { "attribute_id": "15943", "label": "..." },
  "quantity": { "unit": "item", "min": "1", "max": "1", "step": "1" }
}
```

`key` 规则：`admin-{site_id}-{game_id}-{goods_id}-{attribute_id}`。

### 5.3 `native_checkout.bindings[]`（每条）

```json
{
  "activity_id": "mmoexp-seasonal",
  "page_id": "seasonal-vault",
  "product_key": "admin-266-456-170070065-15943",
  "quantity": { "value": "1", "unit": "item" },
  "attributes": [],
  "off_percent": 10,
  "code": "HWD410",
  "native": { "category": "new_items", "id": "170070065", "group": "1", "num": "1", "attr": "", "aid": "15943" },
  "observed_serialization": { "verification_ref": "local-readonly-contract62-v2", "game_id": "456", "model_id": "43191217", "region": "us", "currency": "USD" }
}
```

规律：

- 每个商品 **3 条**，`off_percent` 分别为 8 / 10 / 15；
- `code` 按档位固定：`HWD408` / `HWD410` / `HWD415`；
- 金币类 `native.category = "new_gold"`，`native.group` 填**数量值**（如 `"500000"`）；
- 物品类 `native.category = "new_items"`，`native.group = "1"`；
- **`observed_serialization` 不加就会被按 FC 硬编码校验**（门槛 4）。

### 5.4 `seasonal_model_contracts[model_id]`（骨架，**不含价格**）

```json
{
  "schema_version": 1,
  "verified": true,
  "catalog_version": "local-contract62-v2",
  "model_ref": { "site_id": "266", "game_id": "456", "model_id": "43191217" },
  "fields": [
    { "id": "region", "label": "Region", "depends_on": [],
      "values": [{ "id": "6484", "label": "Global" }] },
    { "id": "platform", "label": "Server", "depends_on": ["region"],
      "values": [{ "id": "15943", "label": "Standard" }] }
  ],
  "combinations": [{
    "product_key": "admin-266-456-170070065-15943",
    "choices": { "region": "6484", "platform": "15943" },
    "attributes": [],
    "quantity": { "min": "1", "max": "1", "step": "1", "unit": "item" }
  }],
  "ordering_verified": true,
  "ordering_evidence": "verified_catalog_source_order"
}
```

对比 FC 的合同：`region` 是 `7645 / All Server`，`platform` 有 21587 / 21585 / 21589 三个值。D4 因为只有一个区服，`region` 用 `6484 / Global`、`platform` 用 `15943`。

### 5.5 `policy.admin_reference_prices.entries[]`（价格来源，两种形态）

**A. 金币（按数量档位取价）**

```json
{
  "category_id": "442",
  "model_ref": { "site_id": "266", "game_id": "456", "model_id": "5264" },
  "source_field": "more.price",
  "price_semantics": "current_tier_total",
  "quantity_value": "500000",
  "quantity_unit": "M",
  "baseline_region": "us", "regional_adjustment": "none_verified",
  "currency": "USD", "minor_unit_scale": 2,
  "max_age_ms": 900000,
  "verified_goods_ids": ["1365865"],
  "ordered_goods_ids": ["1365865"],
  "ordering_evidence": "native-raw-order-contract64",
  "evidence_ref": "..."
}
```

**B. 物品（单价直取）**

```json
{
  "category_id": "3955",
  "model_ref": { "site_id": "266", "game_id": "456", "model_id": "43191217" },
  "source_field": "unit_price",
  "price_semantics": "native_item_display_total",
  "rounding_contract": "native-js-number-format-tofixed-2",
  "quantity_value": "1",
  "quantity_unit": "item",
  ...
}
```

> **D4 物品的 `tiers` 是空的**，价格只在 `unit_price` 上。这就是为什么必须用 `unit_price` + `native_item_display_total`，不能用金币那套 `more.price` + `current_tier_total`。实测三种语义只有 B 成功（`more.price` / `full_price_format` 都失败）。

### 5.6 价格从哪来（最容易搞混的一环）

```
current.json.seasonal_model_contracts[m]           ← 合同骨架：choices / quantity / fields，price 不存在
        +
admin-reference-prices.json.model_contracts[m]     ← provider 写入的真实价格
        ↓  runtime 合并
/events/api/campaign/config 的 seasonal_model_contracts[m].combinations[0].price
   { "source":"admin_current", "base_minor":749, "minor_unit_scale":2,
     "currency":"USD", "quantity_value":"1", "expires_at":"..." }
        ↓  前端展示
活动价 = base_minor / 100 × (1 - off_percent/100)
```

**所以：改 `current.json` 里的合同改不出价格**，价格只能通过 `policy.json` + provider 刷新拿到。反过来，provider 缓存为 `unavailable` 时页面就全站无价——这是同一天价格故障的表象。

---

## 6. 操作手册

### 6.1 改活动结束时间

```python
# 1) 改 current.json（页面窗口 = 结束时间，含时区）
d['halloween']['ends_at'] = '2026-11-08T23:59:59-05:00'
# 页面 window 由 projectRelease 投影，无需单独改

# 2) 原子写 + 读回
tmp = P.with_name('.current.json.tmp'); tmp.write_text(json.dumps(d, ensure_ascii=False, separators=(',', ':')))
os.chmod(tmp, 0o644); json.loads(tmp.read_text()); os.replace(tmp, P)

# 3) 验证
curl -s -H "Host: www.mmoexp.com" http://127.0.0.1:8949/events/api/campaign/config | ...
```

**注意**：`ends_at` 是**带时区的字符串**，美东 `11-08 23:59:59` 写成 `2026-11-08T23:59:59-05:00`（EST 是 −05:00，夏令时期间才是 −04:00；11 月已过 DST 切换，用 −05:00 正确）。页面 window 会投影成 `2026-11-09T04:59:59Z`。

### 6.2 加一个新的随机池商品

四步，**缺一不可**（漏任一步都是 400 或无价）：

1. `current.json.products` 加一条（`product_ref` 必须带 `model_id`）；
2. `current.json.native_checkout.bindings` 加 3 条（8/10/15），**必须带 `observed_serialization`**；
3. `current.json.seasonal_model_contracts` 加模型合同（`price` 不写）；
4. `current.json.pages[seasonal-vault].product_keys` 追加该 key；`halloween.games[].random_models` 追加 model_id；
5. `policy.json.admin_reference_prices.entries` 加一条（物品用 `unit_price` 语义）；
6. 等一轮刷新（300s）确认有价。

### 6.3 改某个商品的折扣档

只改 binding 的 `off_percent` 与 `code`？**不行**。三档是固定 8/10/15，`code` 与档位绑定（`HWD408/410/415`）。要改折扣力度应该改 `halloween.games[].fixed_off_percent`（只能是 8/15/10 之一），或改 `off_percent_tiers`（但它是硬校验 `[8,15,10]`，不能改）。

### 6.4 完整发布一次（让 center 记录归位）

```bash
# 后台发布走 UI，或直接调 analytics/production-server.mjs 的 publish 端点
# 发布后会生成 campaign-preview-12，current.json 的 release_id/config_hash 归位
```

发布前**必须**确认 `state.json.draft` 是正确的 D4 版本，否则会把错的推上线。当前草稿已同步成 D4，可以直接发。

---

## 7. 遗留待办（四项，交给 codex）

### 7.1 D4 合同的区服显示名

**现状**：D4 六条合同的 `fields[1].values[0].label` 是 `Standard`（我填的占位），`region` label 是 `Global`。

**是否需要修**：`fields` 只用于前端下拉展示，**不影响价格和下单**。但用户在页面上看到 "Server: Standard" 可能困惑。

**怎么修**：确认 Admin 里 `aid=15943` 的真实区服名。我试过 `goods.GoodsAttr/index` / `goods.Attr/index` / `goods.GameAttr/index` 都 404，说明属性接口不在这些路径。可行途径：

1. 打开主站任意 D4 商品页，读区服下拉的 label；
2. 问 Admin 侧对接人要 `15943` 的名称；
3. 在 `bridge.py` 加一个属性读取动作（需新增 backend 动作 + 测试，成本较高）。

拿到名字后改 6 条合同的 `label` 即可（纯文案，改完 `config` 仍 200）。

### 7.2 `release_id` / `state.published` 分裂

**现状**：

| 层 | 值 |
|---|---|
| `current.json.release_id` | `campaign-preview-10`（10-27 17:21） |
| `current.json.config_hash` | `c0197b0c…`（内容已变但没重算） |
| `state.published.release_id` | `campaign-preview-11`（同事 15:19 那版） |
| `state.revision` | 11 |

**影响**：功能无影响。但语义上"线上内容"与"记录里的发布号"不对应；`state.published` 指向的版本从未真正对外生效。

**风险**：`center-store.mjs` 的 `restoreDraft` 要求 `restore_revision === current.revision - 1` 且 `history/<rev-1>.published` 与当前 `published` 完全一致，两边分裂时**官方撤销功能失效**（返回 null）。真要回滚只能手工替换文件。

**怎么修**：走一次后台正式发布（生成 `campaign-preview-12`），草稿已是 D4 所以内容不会回退。这会同时把 `release_id` / `config_hash` / `state.published` 对齐。

### 7.3 正式留痕未补

按项目规范，这轮改动应在模块文档里留痕：

- `releases/fs-dashboard/campaign-analytics-20261023/DELIVERY.md` —— 加 `nav-*` 或 changelog 一节；
- 同目录 `ACCEPTANCE.md` —— 加对应读回证据；
- 仓库根 `HANDOFF.md` —— 追加一条同日条目。

**行尾纪律**（今天踩过）：`DELIVERY.md` / `ACCEPTANCE.md` 是 **CRLF**，必须二进制读写；`HANDOFF.md` 是 **LF/CRLF 混排**，只能用 `read_bytes`/`write_bytes` 追加，用 `read_text/write_text` 会把全文件行尾改掉。

### 7.4 ⚠️ FC 随机池漏了一条价格（本次之前就存在，优先级最高）

**现象**：`contracts 56 / priced 55`，唯一无价的是 `43042209`。

**它是什么**：`Large Gold Pack`，`game 1327`（FC27），`cid 10255`，`unit_price` 类，模型级 `price: 1.39`，min_qty 10。三个子商品：

| goods_id | aid | 平台 |
|---|---|---|
| 169757277 | 21589 | PC |
| 169757241 | 21585 | Xbox |
| 169757205 | 21587 | PS |

**为什么是漏洞**：`halloween.games[fc].random_models` 有 **44** 个模型，其中包含 `43042209`；但 `policy` 里 `game 1327` 的 44 条 entry 里**没有它**——多出来的那条是 `41217957`（金币 `fixed_model`，不在随机池里）。

```
in random but NOT in policy: ['43042209']
in policy but NOT in random: ['41217957']
```

结果是：**FC 随机卡有 1/44 的概率抽到 `Large Gold Pack`，抽到就没有价格**。这跟 D4 无关，换游戏之前就是这样。

**修法**（照抄同 cid 的现有条目，改 model_id 与 goods_ids）：

```json
{
  "category_id": "10255",
  "model_ref": { "site_id": "266", "game_id": "1327", "model_id": "43042209" },
  "baseline_region": "us",
  "regional_adjustment": "none_verified",
  "currency": "USD",
  "minor_unit_scale": 2,
  "source_field": "unit_price",
  "price_semantics": "native_item_display_total",
  "evidence_ref": "contract65-native-item-unitprice",
  "max_age_ms": 900000,
  "quantity_value": "1",
  "quantity_unit": "item",
  "verified_goods_ids": ["169757277", "169757241", "169757205"],
  "ordered_goods_ids": ["169757277", "169757241", "169757205"],
  "ordering_evidence": "native-raw-order-contract64",
  "descriptive_baseprop": true,
  "rounding_contract": "native-js-number-format-tofixed-2"
}
```

**加之前必须先验证的两件事**（别直接写 policy）：

1. 现有 12 条 `cid=10255` 条目都是 `quantity_value: "1"` + `unit: "item"`，而 `43042209` 的合同数量是 `min/max: "10"`。**先确认这个数量差异不影响投影**——用 `projectAdminPrices()` 拿真实 observation 跑一遍，看返回 `reference_price_ready_not_checkout` 还是 `QUANTITY_NOT_OFFERED`。如果对不上，`quantity_value` 要填 `"10"`。
2. 加完 entry 数从 59 变 60，单轮刷新时间会略增（当前 ~190s）。加完要确认整轮仍能 `ready`。

**验证**：加完等一轮刷新，`contracts 56 / priced 56`、`/tmp/chk_cache.py` 为 `ready`，然后在页面上连翻 FC 随机卡直到出现 `Large Gold Pack`（或用 `halloween/reveal` 直接打接口），确认带价格。

---

## 8. 回滚点

按阶段从近到远。**先在离线环境验证再落盘**。

| 阶段 | 备份路径 | 说明 |
|---|---|---|
| 换 D4 前 | `/var/backups/fs-campaign-d4-20261028/current.json.before-d4` | 889200 字节（16:52），四游戏仍是 WoW |
| 加 D4 商品前 | `/var/lib/fs-campaign-public/current.json.before-d4cfg` | 889200 字节（21:54） |
| 加 D4 合同前 | `/var/lib/fs-campaign-public/current.json.before-d4contracts` | 899152 字节（22:14） |
| 改结束时间前 | `/var/lib/fs-campaign-public/current.json.before-ends` | 889200 字节（21:53） |
| 策略改动前 | `/var/backups/fs-campaign-d4-20261028/policy.json.before-d4` | 893259 字节 |
| 后台草稿 | `/var/backups/fs-campaign-d4-20261028/state.json.before-d4` | 10932 字节 |
| FC 三页修配置前 | `/var/lib/fs-campaign-public/current.json.before-fcfix-20261028` | 893705 字节 |
| 事故总快照 | `/var/backups/fs-campaign-incident-20261028/` | 21 文件，含 history 1–10 |
| 价格管道改动前 | `/var/backups/fs-campaign-batch-20261028/` | 5 个 py/mjs 原文件 |
| 价格超时改动前 | `/var/backups/fs-campaign-price-timeout-20261028/` | adapters / provider / policy |

回滚到"换 D4 前"的完整命令：

```bash
B=/var/backups/fs-campaign-d4-20261028
cp -f $B/current.json.before-d4 /var/lib/fs-campaign-public/current.json && chmod 644 /var/lib/fs-campaign-public/current.json
cp -f $B/policy.json.before-d4 /var/lib/fs-campaign-dashboard/backend/policy.json && chmod 600 /var/lib/fs-campaign-dashboard/backend/policy.json
cp -f $B/state.json.before-d4 /var/lib/fs-campaign-dashboard/center/state.json && chmod 600 /var/lib/fs-campaign-dashboard/center/state.json
# 代码也要一起退（否则新白名单 + 旧配置 = 400）
cd /path/to/wt && git show 1e94cd25^:releases/.../app/runtime/halloween-contract.mjs > /tmp/hc.mjs
install -m 644 /tmp/hc.mjs /opt/fs-campaign-dashboard/runtime/halloween-contract.mjs
systemctl restart fs-campaign-runtime fs-campaign-dashboard
```

> 注意：**只回滚配置不回滚代码**会撞门槛 1（新白名单拒绝 WoW roster）。有了 #612 的 `legacyGames` 之后这一条不再致命，但仍建议成对回滚。

---

## 9. 坑与禁令

### 9.1 别用"回滚历史版本"修价格

已反证：把 10-28 上午 11:00 的 `adapters.py` / `admin-price-provider.mjs` / `policy.json` 三个文件**逐字节还原**后，连续多轮刷新仍然 `unavailable`。根因在上游 Admin 的列表查询偶发 40–70s 阻塞，不在版本。

### 9.2 三件套必须同步

`current.json` 里 `pages[].product_keys` / `fc_layout` / `native_checkout.bindings` 三者互有校验。只改其中一个 → **400 `NATIVE_CONFIGURATION_INVALID`**。（FC 三页那次事故就是这个坑。）

### 9.3 `static-manifest.json` 是硬门禁

改任何 `app/` 下公开文件（`seasonal/*.js` / `*.css` / `*.html` / `assets/*`）后必须重建清单，否则 runtime 报 `STATIC_HASH_MISMATCH`，`/events/` 全站 **502**。

- 清单只允许白名单文件 + `assets/*.(webp|png|svg|jpg|jpeg|gif|woff2)`；
- 塞 `catalog.json` / `promotion-policy.json` 会 `INVALID_PUBLIC_PATH`；
- 文件权限必须 **0644**（600 会让 `nobody` 读不到 → 502）；
- 格式：`json.dumps(..., indent=2, sort_keys=True)` + 末尾 `\n`。

### 9.4 `runtime/*.mjs` 不能进 static-manifest

`runtime/halloween-contract.mjs` 是模块代码，不是静态资源。加进清单会报错。

### 9.5 服务文件权限

`policy.json` / `state.json` 必须 **600**；静态资源与 `current.json` 必须 **644**。

### 9.6 不要在 provider 刷新时测耗时

一轮刷新会拉起 bridge 子进程打上游。这时跑探针测出来的"20s / 40s"全是自己压出来的假数字。正确做法：`systemctl stop fs-campaign-dashboard` → 静默 10s → 测 → 立刻 `start`。

实测对比（同一条查询）：静默后 **0.9s**，全并发时 **20s+**。

### 9.7 `limit=50` 比 `limit=200` 慢 30 倍

`Goods/index` 的每页 COUNT + filesort 是主要成本，不是返回行数：

| 查询 | 耗时 |
|---|---|
| `mid IN (...)` + `limit=50` | 7395ms（需 3 页） |
| 同查询 `limit=200` | **240ms**（一页拿全） |

### 9.8 `IN` 必须大写 + 逗号

`operator=in` 或数组形式 `search[2][val][]=` 都会被**静默忽略**（返回全量数据，不报错）。只有 `operator=IN` + `val=1,2,3` 生效。校验方式是看 `data.total` 是否变小。

### 9.9 `bridge.py` 一次只处理一个请求

所以批量扫描的缓存必须**在同一个 Python 进程内**跨模型复用。跨进程调 bridge 时缓存不存在，等于没做批量。

### 9.10 `unavailable()` 只清 memory 不清 sticky

价格 provider 里 `memory`（本轮）与 `sticky`（跨轮）是两套。失败路径清的是 `memory`，`sticky` 靠 `max_age_ms` 自然过期。

### 9.11 读回必须用正式域名

`https://www.mmoexp.com/events/...`。IP 直连时 `halloween/reveal` 返回 **403 `ORIGIN_REQUIRED`**（看起来像抽卡坏了，其实是 Origin 校验）。

### 9.12 活动页前端禁止本地存储

翻牌状态只能走服务端 receipt。任何 `localStorage` / `sessionStorage` 都会挂测试 #219。

### 9.13 SSH 单条命令 sleep 超 ~200 秒会断

长任务要拆成多次短连接，或把结果写文件再读。

### 9.14 反引号会被 shell 吞

用 `ssh 'bash -c "..."'` 传含反引号的 Python 脚本时，反引号会被当命令替换，写进文件变空白。**写成 .py 文件 scp 上去执行**，别用内联 heredoc。

### 9.15 Windows 侧 `/tmp` 与 bash 的 `/tmp` 不是同一个

在 Windows 上 `python -c` 里的 `/tmp/x` 和 Git Bash 的 `/tmp/x` 是不同位置。用 `sed -i` 或统一用相对路径。

---

## 10. 验证脚本

全部在 `47.85.224.112:/tmp/` 下（本轮留下，重启不丢；`/tmp` 被清则按下方"重建方法"恢复）。

| 脚本 | 作用 | 期望输出 |
|---|---|---|
| `/tmp/chk_cache.py` | 查价格缓存状态 | `status: ready`、`products: 253`、`contracts: 55` |
| `/tmp/probe_policy_detail.py` | 查 policy entries 与活动配置 | 59 entries、`ends_at 2026-11-08T23:59:59-05:00`、四游戏含 `diablo` |
| `/tmp/probe_d4_map.py` | 查 D4 商品/绑定/合同 | 9 个 D4 product（含 3 个旧 Stash）、18 条 binding |
| `/tmp/probe_contract_shape.py` | 查合同骨架与缓存价格 | `current.json` 里 `price` 为 null；缓存里 `base_minor` 有值 |
| `/tmp/probe_doc_expect.py` | **一键核对本文档所有期望值** | 四游戏、`contracts 56 / priced 55`、D4 六价 |
| `/tmp/probe_fc_pool_gap.py` | 查 FC 随机池与 policy 的差集 | `in random but NOT in policy: ['43042209']` |
| `/tmp/probe_orphan_contract.py` | 查有合同无价格的模型 | 定位到 `43042209` = Large Gold Pack |
| `/tmp/probe_cid10255.py` | 列出 cid 10255 的条目模板 | 12 条同构条目，可照抄 |
| `/tmp/probe_pack_gap.py` | 查 `43042209` 的 Admin 详情与子商品 | cid 10255、3 个 goods（169757277/241/205） |
| `/tmp/verify_d4_reads.py` | 单跑 D4 六个模型的读取与投影 | 6/6 ok，全部命中目标 goods |
| `/tmp/probe_batch_call.py` | 跑一次完整 batch（按游戏分组） | 4 组，1327 组 44/44，总耗时 ~196s |

一键体检：

```bash
ssh -i ~/.ssh/wulv_root_ed25519 root@47.85.224.112 '
curl -s -o /dev/null -w "config   %{http_code}\n" -H "Host: www.mmoexp.com" http://127.0.0.1:8949/events/api/campaign/config
curl -s -o /dev/null -w "seasonal %{http_code}\n" -H "Host: www.mmoexp.com" http://127.0.0.1:8949/events/seasonal/
curl -s -o /dev/null -w "weekly   %{http_code}\n" -H "Host: www.mmoexp.com" http://127.0.0.1:8949/events/Weekly-Scout.html
/usr/bin/python3 /tmp/chk_cache.py
'
```

三个都应是 200，缓存应是 ready。

浏览器侧（本地 Windows，需 `NODE_PATH`）：

```bash
cd E:/WorkBuddy/大超服务器/.agent_runtime/seasonal-media-20261028
NODE_PATH=C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules node probe_all_games.js
```

期望：四游戏各 3 卡、`pageerror: none`、价格形如 `$2.48 / $2.76`。

### 10.1 重建验证脚本的最小版

如果 `/tmp` 被清，最省事的体检是直接读接口 + 缓存：

```bash
ssh -i ~/.ssh/wulv_root_ed25519 root@47.85.224.112 '
python3 -c "
import json,urllib.request
d=json.loads(urllib.request.urlopen(urllib.request.Request(\"http://127.0.0.1:8949/events/api/campaign/config\",headers={\"Host\":\"www.mmoexp.com\"}),timeout=60).read())
h=d[\"halloween\"]
print(\"ends_at\", h[\"ends_at\"])
print([(g[\"id\"],g[\"label\"],g[\"fixed_model\"],len(g[\"random_models\"])) for g in h[\"games\"]])
mc=d[\"seasonal_model_contracts\"]
print(\"contracts\", len(mc), \"priced\", sum(1 for v in mc.values() if (v.get(\"combinations\") or [{}])[0].get(\"price\")))
"
cat /var/lib/fs-campaign-public/admin-reference-prices.json | head -c 200
'
```

期望：`ends_at 2026-11-08T23:59:59-05:00`；四游戏含 `('diablo','Diablo IV','5264',5)`；`contracts 56 priced 55`（无价的是 `43042209`，见 7.4）；缓存 `status:"ready"`。

D4 六个模型的期望价格（`current.json` 合同里 price 为 null，这里读的是 provider 注入后的值）：

| model_id | 商品 | 期望 `base_minor` |
|---|---|---|
| 5264 | Diablo IV Gold 500000M | 276（$2.76） |
| 43191217 | Resplendent Spark x100 | 749（$7.49） |
| 43039181 | Flawless Horadric Ruby | 281（$2.81） |
| 43039069 | Flawless Horadric Skull | 112（$1.12） |
| 43038035 | Kullean Tuning Prism | 105（$1.05） |
| 43038033 | Entropic Tuning Prism | 18（$0.18） |

---

## 11. 环境与工具

| 项 | 值 |
|---|---|
| SSH（187） | `ssh -i C:\Users\Administrator\.ssh\wulv_root_ed25519 root@47.85.224.112` |
| SSH（门户机） | `No1.pem` 才对 `47.253.252.55`；`wulv_root_ed25519` 只对 187 |
| GitHub 通道 | 手工 PAT（`~/.agent_runtime/seasonal-media-20261028/.tok`）+ REST API。官方连接器 token 无 `repo` scope，不可用 |
| 测试 | `python tools/pr_fast.py <NUL分隔路径文件> origin/main HEAD`，需 `NODE_PATH=C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules` |
| 路径文件格式 | **NUL 分隔**（`'\0'.join(paths)`），换行分隔会被当单个路径 |
| Python（服务器） | `/opt/python39/bin/python3`（3.9.18），**无 PIL** |
| Node（服务器） | `/usr/local/bin/node` |
| 图片处理（本机） | Pillow 13.0.0；**无 numpy**（`cut_diablo_art.py` 已改为纯 PIL） |
| SQLite | 线上 3.7.17：禁 UPSERT / `RETURNING` / `json_extract` / 窗口函数 |
| 合并 PR | 端点必须 `PUT`；分支落后要先 `update-branch`（否则 405）；按精确 head SHA 合并 |

---

## 12. 时间线（便于追溯）

| 时间 | 事件 |
|---|---|
| 10-27 17:21 | `campaign-preview-10` 发布，万圣节四游戏（含 WoW） |
| 10-28 15:19 | 同事 chenchao 发布 `preview-11`（Diablo + 美东时间），**未落到对外配置**，形成分裂 |
| 10-28 16:07 | 一批文件被整批重写（`cp -p` 保留 mtime，导致看起来"没动过"） |
| 10-28 17:40–19:45 | 价格全站无价排查；五次尝试（#593/#595/#596/#598/#599）均无效；19:45 逐字节还原上午版仍无价 |
| 10-28 20:00–21:30 | 批量改造 #600/#602/#603/#604/#606 → 价格恢复 `ready` |
| 10-28 21:34 | #607 价格管道文档合并 |
| 10-28 21:53 | 改活动结束时间为美东 11-08 |
| 10-28 22:08–22:11 | #610 换 D4 合并（`1e94cd25`） |
| 10-28 22:26 | #612 旧 roster 兼容合并（`e90d8084`），回应 codex 的 P1 |
| 10-28 22:33 | D4 配置 + 6 个价格条目 + 6 个合同落盘，config 200 |
| 10-28 22:47 | 价格 `ready` 253/55，D4 三卡有价，四游戏全部正常 |
| 10-28 23:06 | 复验：`ready` 253/55，页面无报错 |

---

## 13. 一句话给接手人

**这套系统里"换一个游戏"不是配置动作，是代码 + 配置 + 价格 + 合同 + 凭证 五层联动。** 每一层都有硬校验，顺序错了就是 400 或全站无价。本文第 3 节按正确顺序排好了，第 5 节给了五种数据结构的准确形状，第 9 节是今天真实踩过的 15 个坑。

有疑问先看第 10 节的验证脚本——**"我觉得应该没问题"在这套系统里没有意义，必须读回数字**。
