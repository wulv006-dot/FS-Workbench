# FC27 捆绑包定价工具 · 一期交付（2026-10-13）

> ★ 二期（同日追加）见文末「二期」节。

## 一句话
FS 工作台球类专区新增「FC27 捆绑包定价」工具：按 Futbin ID 匹配球员金币价 × 后台金币单价，
按腾讯文档《捆绑包》prices 表公式自动算出 PS/Xbox 与 PC 的**页面显示原价**与**折扣售价**，
采集间隔可配（小时），捆绑包标题/球员/ID 可在线编辑，手动+定时刷新。
**一期只读定价，不写后台**；二期（Admin 后台改价）待另批授权。

## 线上落点（47.85.224.112）
| 项 | 值 |
|---|---|
| 服务 | `fc27-pack-bundles.service`（enabled/active），`/opt/python39/bin/python3 /opt/fc27-pack-bundles/pack_bundles_server.py --port 8904` |
| 数据目录 | `/opt/fc27-pack-bundles/data/`（config.json / futbin_players.json.gz / last_refresh.json / history.json） |
| API 入口 | `https://47.85.224.112/dashboard/fc27-bundles-api/`（nginx auth_request 门禁，未登录 302） |
| 页面 | `https://47.85.224.112/dashboard/modules/sports/bundles/`（fs-home 壳，球类工作区卡片「FC27 捆绑包定价」） |
| 导航注册 | `/var/www/dashboard/fs-home/navigation.json`（sports.ids + tools 追加 `fc27-bundles`，备份 `.bak-bundles-20261013`） |
| nginx | `iggm-web.conf` 注入 `fc27-bundles-api` 块（备份 `.bak-bundles-20261013`，注入锚点 `# <<< unified-dashboard (auto) <<<`） |
| 回滚 | 还原两个 `.bak-bundles-20261013` + `systemctl disable --now fc27-pack-bundles` |

## 数据链路（全部实测）
1. **Futbin 库**（老大自建 `http://139.28.18.234:8001`）：`GET /api/export/players.json`
   gzip 全量（下载 2.2MB / 23086 球员 / 线上实测 2.1s）。按 `futbin_id` 建映射；
   字段 `ps_price / pc_price / xbox_price`（金币原值）。
   ⚠️ 库内 xbox_price 大多为 null → **PS/Xbox 共用 ps_price**（与腾讯文档口径一致，已实测腾讯文档 22 个 ID 全覆盖）。
   采集节奏：库自身每 60 分钟刷新。
2. **金币单价**：`/var/lib/fc27-cloud/monitor/storefront.json` →
   **⚠️ 口径纠正（2026-10-13 17:41 老大指出）**：单价 = `package_usd ÷ base_k`
   （页面标价 ÷ 标称金币量），**赠送 bonus 金币绝不能摊入**。
   storefront 自带 `usd_per_k` 字段是 `package_usd ÷ (base_k+bonus_k)`（如 12.57÷105=0.1197），
   会把单价压低——**不要直接用**；工具改为自算 `package/base_k`（12.57÷100=**0.1257** ✓），
   字段缺失才回退自带值并标注 `includes_bonus`。
   （实测当时 PS/XBOX 0.1257 / PC 0.0994=9.94÷100 $/K；PC 老大前台看到 0.094，
   与采集值 9.94 存在时间差或档位差，待核对。）
3. **计价公式**（腾讯文档 prices 表逆向，单元测试逐分对齐 ManCity11 行）：
   - 球员页实际售价 = 金币K × 单价 × **1.1**
   - 球员页划线价 = 实际 ÷ **0.9**
   - 捆绑包页面售价（商品页红价）= Σ球员划线价 × **0.8**
   - 捆绑包页面原价（灰划线）= 页面售价 ÷ **0.7**（角标 30% OFF）
   - 对比实际让利 = (售价 − Σ实际) ÷ Σ实际（恒 ≈ −11.11%）
   - 中间链路 Decimal 不舍入，仅展示 2 位小数；系数可在 settings 调整。

## 接口（应用层，前置 nginx 门禁）
- `GET /health` / `GET /api/state`（整状态+实时算价）/ `GET /api/search?q=`（球员搜索选人）
- `POST /api/config`（`{expected_revision, settings?, bundles?}`，revision 乐观锁）
- `POST /api/refresh`（后台线程刷新，进行中返回 409）
- ⚠️ 应用层对 POST 额外要求 `X-Forwarded-Proto: https`（与 MLB 同款约定）

## 刷新机制
- 服务内置调度线程：每分钟检查距上次刷新是否 ≥ `interval_hours`（默认 1 小时，可 0.1~168）；
  服务启动 60 秒内自动跑首轮。
- Futbin 拉取失败不致命：沿用旧缓存继续算价，errors 记入 last_refresh。

## 本地任务目录 `fc27_pack_bundles_20261013/`
- `src/pack_bundles_server.py`（28,492 B / sha256 前 16 位 `69c5102171285b1e`）
- `web/index.html`（16,413 B / `a5b04bd369f3335d`）
- `tests/test_pack_bundles_offline.py` —— **14/14 通过**（公式对齐腾讯文档 ManCity11：
  PS 20.77/29.67、PC 13.74/19.62；校验器/revision/缺价兜底）
- `deploy/inject_nginx.py`、`deploy/update_nav.py`（部署注入脚本，幂等）
- `evidence/`（fb_players_sample.json.gz 样本、上传计划、冒烟日志）

## 已验证
| 项 | 结果 |
|---|---|
| 离线单测 | 14/14 OK（公式与腾讯文档数字逐分一致） |
| 本地端到端 | 真实 Futbin 数据 + 模拟单价：ManCity PS 20.16/28.80，让利 −11.11% |
| 线上首轮采集 | auto 触发，2.1s，23086 球员，0 errors |
| 线上算价 | ManCity PS 20.16/28.80、PC 13.07/18.68；Paris PS 259.37/370.53，11/11 匹配 |
| 门禁 | 未登录访问 API/页面均 302 → 登录页；服务只绑 127.0.0.1 |
| nginx | `nginx -t` 退出码通过后 reload；备份留存 |

## 待办 / 边界
- ⏳ **老大登录浏览器验收**（页面 UI、编辑器、改间隔、立即刷新）——本次无法替登录验证。
- 二期（**需单独授权**）：自动采集后进 Admin 后台 FC27-Packs 列表改「站点-ALL」产品价。
  参考：admin_api_client.py（`admin-api.p2pah.cn`，Bearer token + ddddocr 过码），
  截图中的两条产品 ID：185327265(PS)/185327726(Xbox)/185327193(PC)。
- Futbin 库 xbox_price 覆盖率低（多为 null）→ 已按「PS/Xbox 共用 ps_price」处理；
  若未来库内 Xbox 价齐了，可在 settings 加开关分开取价。
- `shared server_187/manifest.json` 不含本工具与 navigation.json（已核实，无需 refresh_local）。

---

# 二期（2026-10-13 当日追加）：订单后台取价 + Admin 自动改价

## 数据源升级：订单后台 b2c（老大 17:53 提供 Order 后台截图）
- `order.p2pah.cn` → 金币价格管理 → 所属游戏 **1322（FC 27）**（⚠️ ≠商品后台 1327）→ **b2c = USD/1K**
- 行：21942 PS / 21944 XBOX / 21946 PC；实测 b2c 0.1257 / 0.1257 / **0.0994**
- 实现：vendor/p2pah_price.py（自 MLB §11.3 已验证字节复制），`fetch_rows(gid=1322)`，
  登录过验证码（ddddocr）→ **只在 refresh 时拉取**（/api/state 读缓存，防锁号）；
  失败自动回退 storefront 自算并记 errors。
- 单价口径铁律不变：**赠送 bonus 不摊入**（b2c 本身就是标价口径，与自算 package/base_k 一致）。

## Admin 写价（goods.Goods，站点-ALL）
- 侦察结论（只读，/tmp/pb_probe*.py，零写入）：
  - 捆绑包产品 gid=1327 / cid=10255(Packs) / site_id=0(ALL) / mid：ManCity 44656527、Paris 44656303
  - **aid：21587=PS / 21585=Xbox / 21589=PC**
  - 产品 ID：ManCity PS 185327193 / Xbox 185327229 / PC 185327265；
    Paris PS 185327085 / Xbox 185327121 / PC 185327157
  - 后台价格结构：**unit_price=页面原价（划线），price=unit_price×discount/100（售价，3 位小数），discount=70（=30% OFF）**
  - 老大给的截图 ID 185327726 不存在（Record not found）；Paris PC 当前还是旧手填价 271.474
- 写入：`POST /admin/goods.Goods/edit` **最小字段** `{id, unit_price, price}`
  （球员工具 edit_product 生产验证过的模式）；discount 不动。
- **四道闸门**（settings，页面开关）：`write_enabled`（总闸，默认 false）→
  `write_dry_run`（默认 true，只出 planned 不写）→ `write_auto`（采集后自动写，默认 false）→
  **delta 幂等**（变化 <0.005 跳过）。
- 红线（沿 MLB §10.4）：POST 不自动重试（异常→needs_review 留痕）；
  写前完整 row 快照 `data/before/<pid>.json`（**首次基线绝不覆盖**）；
  写后 sleep 2s 回读验证（mismatch 留痕）；审计 `data/write_log.json`（cap 200）。

## 部署（在 v1 基础上）
| 文件 | sha256 前 16 |
|---|---|
| /opt/fc27-pack-bundles/pack_bundles_server.py | 2dd7c2d7fcbeed97 |
| /opt/fc27-pack-bundles/vendor/p2pah_price.py | 39fb0becb9713521 |
| /opt/fc27-pack-bundles/vendor/admin_api_client.py | 14b7ed16dd0bd5b8 |
| /var/www/dashboard/modules/sports/bundles/index.html | 1f51f10898d854db |
- 旧版备份 `.bak-v1` / `.bak-v2`；config 轻迁移：缺 products 绑定的 bundle 自动补默认表（只补缺）。
- 回滚：还原 .bak-v2 + restart。

## 已验证
- 离线：23/23（一期 16 + 二期 7：闸门/dry_run/Xbox 共用 PS 目标/needs_review/日志上限/校验器）
- 线上 refresh：status ok / 0 errors / 23090 球员 / **order_b2c 实时取价成功**（PS/XBOX 0.1257、PC 0.0994）
- 线上 dry_run 演练（18:33，**零写入**）：6 产品全部 planned，目标价与前台结构一致，
  如 ManCity PS 29.67→30.18（金币价微涨）、Paris PC 271.474→275.499（旧手填价被修正）。
- 途中修了两个部署 bug：手动 refresh 端点 `self.refresh_lock` 属性错误（一期就带病，无人触发过）、
  vendor 路径 parent.parent 错层。

## 待办
- ⏳ **老大批准后**：关 dry_run 实际写一次（6 产品）→ 前台回读验收 → 再评估开 write_auto。
- 当前线上开关状态：write_enabled=true / write_dry_run=true / write_auto=false（安全：只出计划）。
