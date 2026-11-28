# 2026-10-28 生产热修登记（8 个文件）

> **这些改动直接落在生产机，私库维护源尚未同步。**
> 每条都附 SHA256、备份名、验证证据与**当前是否有效**的判断。
> 发布前必须逐个处理：同步入库 or 明确保留现场 or 回滚。

## 一、已验证有效

| # | 文件 | 改动 | 现 SHA256(前12) | 备份 | 验证 |
|---|---|---|---|---|---|
| 1 | `/opt/fs-hermes-fc/channel_source.py` | `pages()` 增加两处容错：total 增长接受、行位移重复跳过。**`search()` 已回滚为原始 search 语法**（等值走 search，不用简单参数） | `ce01980e1115` | `.bak-20261028T1025` | 今日 FC27 194 单、昨日 386 单，返回行 gid 纯净 |
| 2 | `/opt/fs-hermes-fc/channel_cost_source.py` | `collect()` 的 `from lxml import html` 改为 `_lxml_html()` 单例 + 模块加载预加载，修复常驻服务多线程首次 import 报 `cannot import name getfullargspec` | `416aa286ca50` | `.bak-20261028T1115` | 昨日 FC27 成本覆盖 324/324（100%），毛利 ¥56,552.91 |
| 3 | `/opt/fs-hermes-fc/channel_effects.py` | 缓存 TTL 分流：`cache_ttl = 604800 if closed_day else 600`（已封账 7 天 / 当日 600 秒） | `746bea4099c6` | `.bak-20261028T1040` | 昨日 `200/0.014s/refreshing False`；今日 `refreshing True/stale True`（实时性未受影响） |
| 4 | `/opt/fs-exact-range-20261001/actual_profit.py` | 新增 `_closed_complete()`：已封账且 `sources.orders/cost.status == complete` 时永久复用，`refresh=1` 仍可强制 | `08ca85f9336a` | `.bak-20261028T1055` | 昨日毛利 0.014 秒返回且不重算 |
| 5 | `/opt/fs-exact-range-20261001/range_api.py` | 入口预加载 `lxml.etree` / `lxml.html` | `22bc75b8b479` | `.bak-20261028T1145` | 服务 `active`，六卡正常 |
| 6 | `/opt/fs-exact-range-20261001/archive_jobs.py` | history 模式两处时间限制加 `ARCHIVE_FORCE` 环境变量豁免（`run_once` + `main`），允许 1–6 点以外补跑 | `de24cb028101` | `.bak-20261028T1200` | `ARCHIVE_FORCE=1 --scheduled` 可执行，`completed 63`（仍受 8931 busy 限制） |

## 二、未验证 / 可能无效（**建议回滚或待审查**）

| # | 文件 | 改动 | 现 SHA256(前12) | 备份 | 状态 |
|---|---|---|---|---|---|
| 7 | `/opt/fc27-cloud-browser/execute_price.sh` | 给改价容器注入 dc 版 `p2pah_session_service.py`（`/usr/local/bin`），意图让 ALL 登录走 dc 短路 | `44731afb663c` | `.bak-20261028T1345` | **未验证**：改价仍停在 `original_operation_reconciliation_pending`，未走到执行阶段 |
| 8 | `/opt/fc27-cloud-browser/fc_pricing_v3/business_source.py` | `selective_history_signature` 在 ES manifest 缺失时降级为空签名 | `a0c038bb068d` | `.bak-20261028T1208` | **判定无效**：降级后下游 `build_shared_history_cache` 仍需 ES 数据，报 `history_source_incomplete`。**建议回滚** |

## 三、数据/状态类改动（已回滚）

| 项目 | 处理 |
|---|---|
| `control.sqlite3` 手工改账本（operation status / recovery_status / 删租约） | **已全部回滚**至 `.bak-20261028T1340` |
| `executions/3678aed7….json` 账本改写 | **已回滚**至 `.bak-20261028T1338` |
| Admin `goods.Goods` 18 条 `unit_price` 误改（其他 6 站点） | **已恢复** 0.0799；`price` 无法回 0（后端拒绝），保持 0.0799 |

## 四、教训（写给审核的人）

1. **不要用 curl 直接改 Admin 商品表**。改价唯一合法路径是 `price_writer.py`（Order 后台 + 账本 + 读回校验）。
2. **不要手工改 `control.sqlite3`**。状态机有严格终态白名单（`ledger.py:184`），手工改一个字段会引出 `pricing_resource_unresolved` → `process_output_invalid` 连锁错误。
3. **判断筛选是否生效，必须看返回行字段纯净度**，不能只看 total。
4. 查价格要用 `goods.Goods/edit?id=` 精确读，**不要用 `top_cid` / `site_id` 组合筛选**——那会混入地区覆盖记录（`price=0`、`unit_price` 为子站价格）。
