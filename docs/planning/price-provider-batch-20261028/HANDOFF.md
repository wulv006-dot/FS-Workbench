# 价格 provider 批量扫描改造 · 交接说明

> 日期：2026-10-28
> 范围：`releases/fs-dashboard/campaign-analytics-20261023`（campaign-analytics 模块）
> 线上机器：`47.85.224.112`（内部称 187，CentOS 7），运行目录 `/opt/fs-campaign-dashboard`
> 相关 PR：#600 / #602 / #603 / #604 / #606（均为 `pr-fast` 全套通过后合并）

---

## 0. 一分钟摘要

`/events/seasonal/`（万圣节 Mystery Store）四个游戏的商品卡片曾经全站无价。现在**已恢复并稳定**：价格缓存 `status: ready`、247 products / 49 model_contracts，四游戏每页 3 张卡全部带实时价，`halloween/reveal` 从 409 变 200。

根因不是我们的代码坏了，而是**上游 Admin 的商品列表接口偶发卡 40–70 秒**，而价格 provider 是「任一模型失败 → 整份价格作废」的语义。原来 49 个模型各扫一次、共 120+ 次请求，在 1/3 卡顿率下全成功概率趋近于零。

修法是把「每个模型扫一次」换成「每个游戏扫一次」（`mid IN (...)`），请求量 120+ → 9 次列表查询；再配合每模型独立预算、跨轮兜底和一次重试。

**不要做的事**：不要"恢复历史版本"来修这个问题。已经反证过：把上午 11:00 的三个文件逐字节还原后，连续多轮仍然无价。

---

## 1. 链路拓扑（先读这节再动手）

```
浏览器
  └─ https://www.mmoexp.com/events/seasonal/     ← 正式域名，必须用它读回
       └─ nginx（187）proxy_pass 127.0.0.1:8949
            └─ fs-campaign-runtime.service   runtime/server.mjs
                 ├─ 页面模板：/opt/fs-campaign-dashboard/*.html（文案来源）
                 └─ 配置：/var/lib/fs-campaign-public/current.json（商品 / 布局来源）

价格链路（本次改造的对象）
fs-campaign-dashboard.service（Node，analytics/production-server.mjs）
  └─ analytics/admin-price-provider.mjs      每 300s 一轮
       └─ analytics/backend-client.mjs  backendRead()  execFile 起子进程
            └─ backend/bridge.py  （JSON 走 stdin/stdout，一次一个请求）
                 └─ backend/campaign_backend/provider.py  model_provider_batch()
                      ├─ adapters.py  AdminRead.prefetch_goods()   ← 一次 IN 扫全游戏
                      │    └─ HTTP → http://127.0.0.1:8912（dc-proxy-fs）
                      │         └─ admin-api.p2pah.cn/admin/goods.Goods/index   ← 会卡 40–70s 的那一个
                      └─ adapters.py  AdminRead.catalog_model()  →  GoodsMould/edit（快，135–321ms）
输出：/var/lib/fs-campaign-public/admin-reference-prices.json
      └─ runtime 读它，把 seasonal_model_contracts 注入 /events/api/campaign/config
```

关键路径：

| 用途 | 路径 |
|---|---|
| 运行时根目录 | `/opt/fs-campaign-dashboard` |
| 价格策略（私有，600） | `/var/lib/fs-campaign-dashboard/backend/policy.json` |
| 价格缓存（对外可读） | `/var/lib/fs-campaign-public/admin-reference-prices.json` |
| 公开活动配置 | `/var/lib/fs-campaign-public/current.json` |
| 后台状态 / 草稿 / 历史 | `/var/lib/fs-campaign-dashboard/center/{state.json,history/}` |
| 静态清单 | `/opt/fs-campaign-dashboard/runtime/static-manifest.json` |

**SSH**：`ssh -i C:/Users/Administrator/.ssh/wulv_root_ed25519 root@47.85.224.112`（注意：`No1.pem` 对这台无效）

---

## 2. 这次改了什么（文件级）

全部在仓库 `releases/fs-dashboard/campaign-analytics-20261023/` 下，部署时对应到 `/opt/fs-campaign-dashboard/`：

| 仓库路径 | 线上路径 | 改动 |
|---|---|---|
| `backend/campaign_backend/adapters.py` | `backend/campaign_backend/adapters.py` | 新增 `prefetch_goods()`、`reset_catalog_budget()`；`search_goods_page()` 增加缓存分支；`catalog_timeout` 45s / socket `(5,40)` / base `http://127.0.0.1:8912` |
| `backend/campaign_backend/provider.py` | 同 | 新增 `model_provider_batch()`：按游戏分组、一次扫描、每模型独立预算、失败重试一次 |
| `backend/bridge.py` | `backend/bridge.py` | 新增 `model_provider_batch` 动作分发（字段白名单、固定错误码） |
| `app/analytics/backend-client.mjs` | `analytics/backend-client.mjs` | `readActions` 增加 `model_provider_batch` |
| `app/analytics/admin-price-provider.mjs` | `analytics/admin-price-provider.mjs` | 读取循环按游戏分组批量；子进程预算 300s；rejected promise 逐条降级 |

新增测试：

- `backend/tests/test_model_provider.py`：`test_batch_read_sweeps_the_catalogue_once_for_all_models_of_a_game`、`test_batch_read_reports_a_failed_game_without_dropping_the_other_games`
- `app/analytics/tests/admin-price-provider.test.mjs`、`app/tests/multigame-price-provider.test.mjs`：mock 从单模型改成批量

**单模型动作 `model_provider_read` 保留不动**，其他调用方不受影响。

---

## 3. 五个坎与实测数据（照这个顺序理解改动为什么长这样）

每一步都是先测出数字、再改，不是猜的。

### 坎 1 · 批量本身（PR #600）

Admin 的 `search` 组件**本来就支持 `IN`**（`adapters.search()` 的合法操作符列表里一直有 `IN`，只是商品列表从没用过）。注意写法：

```
search[2][field]=mid & search[2][operator]=IN & search[2][val]=41217957,43167385,...
```

必须是**大写 `IN` + 逗号分隔**。小写 `in` 或数组形式 `search[2][val][]=...` 都会被忽略（返回全游戏商品，`total` 变 3303）。

改完请求数 49 → 4，但 1327 组（44 模型 / 132 商品）扫描阶段就吃满 45s 预算，后面 44 次详情全超时。

### 坎 2 · limit=50 比 limit=200 慢 30 倍（PR #602）

停掉 provider 后单独测同一组 `IN` 查询：

| 查询 | 耗时 | 结果 |
|---|---|---|
| 1327 `limit=50` | 7395 ms | 50 行，需 3 页 |
| 1327 **`limit=200`** | **240 ms** | 132 行，一页拿全 |
| 891 `limit=50` | 211 ms | 50 行，需 4 页 |
| 891 **`limit=200`** | **264 ms** | 189 行，一页拿全 |

每页的 `COUNT` + `filesort` 是主要成本，不是行数。所以扫描用 `limit=200` 单页。

同时加 `reset_catalog_budget()`：扫描和逐模型详情是两个阶段，不能共用同一个 45s 窗口。

> 数据一致性验证（改代码前做的）：44 个 mid 一次 IN 取全 132 行、3 页、503ms，44 个 mid 全部有数据；抽样 3 个 mid 与单查（带 `cid`）逐 `id` 比对完全一致。

### 坎 3 · 44 次详情共用一个 45s 窗口（PR #603）

即使扫描很快，44 次 `GoodsMould/edit` 串行累计也超过 45s（前 15 个用完，后面 29 个无条件超时）。

改两处：

1. 每个模型读详情前 `reset_catalog_budget()`，各用各的窗口。
2. `admin-price-provider.mjs` 里 `await reads.get(readKey)` 原本会直接抛到外层 catch 把**整份**作废，改成逐条降级：

```js
let observation=null;
try{observation=await reads.get(readKey);}catch{observation=null;}
```

这一条是关键 —— **#599 加的 `sticky` 跨轮兜底一直没真正生效**，就是因为 rejected promise 在 await 处就抛出去了，根本走不到 sticky 分支。改完之后，单条失败只影响它自己（用 `max_age_ms` 窗口内的旧值顶替），不再是全站无价。

### 坎 4 · 全成功但 196s，被 180s 上限 kill（PR #604）

受控测试下 1327 组做到 **44/44 全成功**，但耗时 196117ms，而 provider 给子进程的 `execFile` timeout 是 180000 —— 进程在收尾前被 kill，结果又被报成失败。

改：`{timeout: 300000}`。

### 坎 5 · 稳定 42/44，2 条瞬时拒绝（PR #606）

用 Node 通道实测：1367 / 891 / 1333 全成功，1327 是 42/44，失败的 2 条是 `CATALOG_SEARCH_HTTP_REJECTED`（上游瞬时拒绝，不是超时）。

这 2 个模型从未成功过 → 永远进不了 sticky → 每轮都卡在同一处。改：扫描完成后对仍失败的模型**在原扫描缓存上重试一次**（只重跑模型详情，不再打列表接口）。

---

## 4. 现在的运行时状态与指标

```
价格缓存：status=ready，247 products，49 model_contracts，267792 字节
刷新间隔：policy.json → admin_reference_prices.refresh_interval_ms = 300000
新鲜度窗口：每 entry 的 max_age_ms = 900000（15 分钟）
一轮耗时：1327 组约 150–196s，其余三组 1–7s，整轮约 190s
请求量：列表查询约 9 次/轮，bridge 子进程 4 个/轮
```

### 快速自检脚本（服务器上）

```bash
# 价格缓存状态（最有用的一条）
/usr/bin/python3 /tmp/chk_cache.py
# 等价于：
python3 -c "
import json,datetime
from pathlib import Path
f=Path('/var/lib/fs-campaign-public/admin-reference-prices.json')
d=json.loads(f.read_text())
print(datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime('%H:%M:%S'),
      d.get('status'), len(d.get('products') or []), len(d.get('model_contracts') or {}))
"
```

期望：`ready` + `247` + `49`，且 mtime 在最近 5–6 分钟内。

### 公开读回（本机，必须用正式域名）

```bash
python -c "
import urllib.request, json
req=urllib.request.Request('https://www.mmoexp.com/events/api/campaign/config',
    headers={'Cache-Control':'no-cache','User-Agent':'buddy-agent'})
d=json.loads(urllib.request.urlopen(req,timeout=60).read())
mc=d.get('seasonal_model_contracts') or {}
priced=[k for k,v in mc.items() if v.get('combinations') and v['combinations'][0].get('price')]
print('contracts', len(mc), 'priced', len(priced))
"
```

期望：`contracts 50 priced 49`。

> ⛔ **不要用 IP 直连读回** `/events/`：halloween/reveal 在 IP 直连下返回 403 `ORIGIN_REQUIRED`，看起来像坏了，其实是 Origin 校验。

### 页面级验证（本机 Playwright）

工作目录 `E:/WorkBuddy/大超服务器/.agent_runtime/seasonal-media-20261028/`：

```bash
NODE_PATH=C:/Users/Administrator/.workbuddy/binaries/node/workspace/node_modules \
  node probe_all_games.js
```

它会依次进入四个游戏、翻开每张卡，输出 `cards` / `picks` / `money` / `pageerror`。期望每个游戏 `cards=3 picks=3`、`money` 6 个数字、`pageerrors: none`。

---

## 5. 待办一：优化详情读取速度

### 现状

单轮约 190s，其中 1327 组约 150–196s，**几乎全花在 44 次 `GoodsMould/edit` 模型详情**上 —— 平均约 4s/次，而历史实测（10 月 28 日白天）是 135–321ms，10 次里 0 次慢请求。差了约一个量级。

### 可选方向（按风险从低到高）

| 方向 | 做法 | 预期 | 风险 |
|---|---|---|---|
| A. 组内并发读详情 | `model_provider_batch` 里把 44 次串行 detail 改成 4–6 路线程池，每次仍 `reset_catalog_budget()` | 190s → 约 50s | 上游对并发敏感（见下），需实测确认 4 路不会反过来拖慢 |
| B. 减小 detail 依赖 | 检查 `catalog_model()` 拿的字段是否全部必需，能否用扫描行里已有的字段替代 | 去掉部分请求 | 要确认 `project_source(model,args,True)` 的字段需求，动了会影响契约 |
| C. 拉长间隔 | `refresh_interval_ms` 300000 → 600000 | 压力减半，不解决速度 | 价格最多 10 分钟更新一次，需业务确认 |

**A 的注意点**：10 月 28 日测过「49 路全并发打列表接口 → 28 个超时、21 个成功，最慢 21850ms」，说明上游对并发很敏感。但那次并发的是**列表接口**（重查询），不是 `GoodsMould/edit`（按主键查单行，10/10 都 <321ms）。4 路 detail 并发风险较低，但**必须实测**，不能照搬结论。

### 改前必须做的验证

1. 停服务测基线：`systemctl stop fs-campaign-dashboard` → 跑 `probe_batch_call.py` → 记录每组耗时与成功率 → 起服务。
   （不停服务测会和 provider 自己抢上游，数据不可信 —— 这一点踩过。）
2. 改完用同一方法对比，确认 44/44 仍是 100%。

---

## 6. 待办二：D4 替换 WoW 上线

### 现状

`/var/lib/fs-campaign-dashboard/center/state.json` 的 **草稿** 已经是 Diablo + 结束时间 `2026-11-08T23:59:59-05:00`（美东），但对外 `/var/lib/fs-campaign-public/current.json` 仍是 WoW + `11-10 23:59 +08:00`（北京）。

> 用户在 2026-10-28 明确：**Diablo 替换 WoW 本身是对的，结束时间按美东。**

### 两条路

**路 A：走后台发布（推荐，有回执）**

1. 确认价格链路是 `ready`（否则发出去的页面照样没价）。
2. 后台加载当前草稿 → 保存 → 发布。会生成 `campaign-preview-12`，写 `current.json`，同时把 `state.published` 从同事那版 `preview-11` 纠正过来。
3. 读回：`/events/api/campaign/config` 四游戏应是 FC27 / Aion2 / **Diablo** / MapleStory，`halloween.ends_at` = `2026-11-08T23:59:59-05:00`。

**路 B：直接改 `current.json`（无回执，只在后台不可用时用）**

改 `halloween.games` 的第四个游戏 + `ends_at`，**注意三件套同步**（见下节坑 1），否则 `NATIVE_CONFIGURATION_INVALID`。

无论走哪条，**改前先备份**：

```bash
cp -a /var/lib/fs-campaign-public/current.json /var/lib/fs-campaign-public/current.json.before-d4-$(date +%Y%m%dT%H%M)
cp -a /var/lib/fs-campaign-dashboard/center/state.json /var/lib/fs-campaign-dashboard/center/state.json.before-d4-$(date +%Y%m%dT%H%M)
```

---

## 7. 坑与禁令（血泪清单）

1. **配置三件套必须同步**：`fc_layout`、`pages[].product_keys`、`native_checkout.bindings` 任一不同步 → `/events/api/campaign/config` 直接 **400 `NATIVE_CONFIGURATION_INVALID`**。改 FC 三页时踩过：只改 `fc_layout` 或只加 `product_keys` 都是 400。
2. **不要为了"修价格"去还原历史版本**：已反证无效（逐字节还原后仍失败）。真因在上游卡顿 + 全或无语义。
3. **不要在 provider 运行时跑探针测耗时**：会和 provider 抢上游，测出来的 20s/40s 全是自己压出来的。要么停服务测，要么接受数据不可信。
4. **`bridge.py` 走 stdin/stdout，一次一个请求**：所以缓存类优化必须放在**同一个进程内**（这就是为什么要有 `model_provider_batch`，而不是只加 `prefetch_goods`）。
5. **`limit` 越大越快，与直觉相反**：`Goods/index` 的成本在每页的 `COUNT` + `filesort`，不在行数。
6. **provider 是全或无语义**：任一 entry 失败 → 整份 `unavailable`。`sticky` 只能在「曾经成功过」的 entry 上兜底，从未成功过的 entry 永远是硬失败 —— 所以第一次必须全成功，重试机制就是为此。
7. **`unavailable()` 只清 `memory`，不清 `sticky`**（`admin-price-provider.mjs` 第 44 行），这是跨轮兜底能工作的前提，别"顺手"一起清。
8. **`policy.json` 权限必须 600、属主不变**：`readAdminPricePolicy()` 会拒绝公开可读的策略文件（`PRIVATE_PRICE_POLICY_REQUIRED`）。
9. **改静态资源要同步 `runtime/static-manifest.json`**，否则 runtime 报 `STATIC_HASH_MISMATCH`、`/events/` 全站 502。本次没动静态资源。
10. **发布代码 ≠ 走 publisher**：publisher 只发静态资源，不发 `backend/`、`analytics/`。本次是直接 `install -m 644` + 重启，`operations/` 没有回执 —— 这是已知缺口，不是遗漏。
11. **SSH 长连接会被断**：单条命令 `sleep` 超过约 200 秒容易被断，拆成两条。

---

## 8. 回滚点

| 位置 | 内容 |
|---|---|
| `/var/backups/fs-campaign-batch-20261028/` | 本次改造前 5 个文件的原始版本 |
| `/var/backups/fs-campaign-price-timeout-20261028/` | 10-27 的 `adapters.py` / `provider.mjs` / `policy.json` 基线 |
| `/var/backups/fs-campaign-price-current-20261028T1945/` | 10-28 19:45 回滚时的当前版本存档 |
| `/var/backups/fs-campaign-incident-20261028/` | 事故取证快照（center state / history 1–10 / current.json / 5 个 before 快照） |

回滚代码：

```bash
D=/opt/fs-campaign-dashboard; B=/var/backups/fs-campaign-batch-20261028
install -m 644 $B/backend/campaign_backend/adapters.py $D/backend/campaign_backend/adapters.py
install -m 644 $B/backend/campaign_backend/provider.py $D/backend/campaign_backend/provider.py
install -m 644 $B/backend/bridge.py $D/backend/bridge.py
install -m 644 $B/analytics/backend-client.mjs $D/analytics/backend-client.mjs
install -m 644 $B/analytics/admin-price-provider.mjs $D/analytics/admin-price-provider.mjs
find $D/backend -name "__pycache__" -type d -exec rm -rf {} +
systemctl restart fs-campaign-dashboard
```

回滚后价格会重新变 `unavailable`（因为回到全或无语义 + 49 次扫描）。这是已知代价。

---

## 9. 相关文档

- 模块交付：`releases/fs-dashboard/campaign-analytics-20261023/DELIVERY.md`（`2026-10-28 价格 provider 批量扫描改造` 一节）
- 模块验收：同目录 `ACCEPTANCE.md`（同日读回）
- 项目总交接：仓库根 `HANDOFF.md`（同日条目）
- 事故记录：`.agent_runtime/seasonal-media-20261028/out/INCIDENT-fc-config-20261028.md`（FC 三页配置错位，与本议题不同问题）
