# 数据缓存与日归档规则（2026-10-28）

> 适用：看板（8931 `fs-business-range`）、毛利卡（actual-profit）、归档任务（`fs-data-archive`）、
> Hermes 的数据调取。**核心铁律：当日数据必须实时拉取，只有已封账日才允许冻结复用。**

## 1. 已封账 vs 当日（最重要的一条）

| 类型 | 判定 | 缓存策略 | 理由 |
|---|---|---|---|
| **当日** | `end >= 今天` | **600 秒 TTL，到点必刷** | 当天订单/成本还在变，冻结会给出错误的实时经营判断 |
| **已封账日** | `end < 今天` | 毛利结果**永久复用**；8931 缓存 TTL **7 天** | 历史数据不再变化，重算只会拖慢并抢占采集锁 |

`refresh=1`（页面“更新”按钮）对两种类型都有效，会强制重算。

**任何新代码都不得把当日数据纳入长缓存。** 判定一律用 `period['end'] < datetime.now(TZ).date().isoformat()`。

## 2. 日归档机制（已存在，直接复用，不要另建）

- 目录：`/var/lib/fs-data-archive/`
- 索引：`catalog.sqlite3` → `versions(version,key,family,profile,start,end,saved,path)` + `latest` + `references_index`
- 存储：`<family>/<PROFILE>/<start>_<end>/<sha256>.json.gz`
- 四类 family：`native`（原生统计）、`summary`、`native-statistics`、`marketing`
- 节奏：`fs-data-archive.timer`，**00:30** 起，01–06 点每 15 分钟一次；非 daily 模式 **7 点硬停**
- 内容契约：`native-closed-v2` = **已封账日的统计快照**（profile.dimensions/metrics/period/primary/supplement）
- **不含逐单明细**，所以毛利卡不能靠归档，只能靠 actual-profit 自己的缓存

当前覆盖：17 个 profile × 4 类，最新到 `2026-10-27`（10-28 02:26 写入）。

## 3. 归档为什么会 `busy`（今天凌晨的实际故障）

`archive_jobs.py` 的 `run_once(daily,budget=480)`：
- 总预算 480 秒；单任务最多等 8931 **90 秒**；非 daily 模式 7 点后停止
- 归档请求 8931 `/range` 时**故意不带 refresh**（想读缓存）

问题：8931 原先对**所有日期**都用 600 秒 TTL。已封账日 10 分钟后就被判过期 → 触发重采 → 抢
`collector.lock` → 返回 `archive.refreshDeferred` → 归档判 `busy` 跳过。
实测 06:15 / 06:30 / 06:45 三次全部 `daily.completed=0`，`history deferred(8931 busy)`。

**修复**：`channel_effects.get()` 的 TTL 按日期分流（见 §1）。修完归档能直接读缓存、秒级返回，
不再需要错峰、也不需要靠“提高预算”硬等。

## 4. 毛利卡缓存（actual-profit）

- 缓存位置：`/var/lib/fs-channel-effects/actual-profit/<sha256(参数)>.json`
- 结构：`{data:{period,actualPeriod,generatedAt,sources,orders,costOverrides,testOrders}, query, capturedAt}`
  —— **注意 `data` 里没有 `denominator`**，那是 `profit_view` 运行时生成的视图字段，不要用它做持久化判断
- 判定“已封账且完整”的正确方式：
  `data.sources.orders.status == 'complete'` 且 `data.sources.cost.status == 'complete'` 且 `orders` 非空
- 满足即永久复用；不满足则按 600 秒 TTL 或失败态重试

**已知限制**：近 30 天 × 全部游戏**首次采集仍需 5–8 分钟**（订单 + 成本各上百页）。缓存只保证“第二次起秒开”。
要让首次也快，只能在凌晨归档窗口顺带预生成。

## 5. 改动登记（2026-10-28）

| 生产文件 | 改动 | 备份 |
|---|---|---|
| `/opt/fs-hermes-fc/channel_effects.py` | `get()` 的 `fresh` 判定：`cache_ttl = 604800 if closed_day else 600` | `.bak-20261028T1040` |
| `/opt/fs-exact-range-20261001/actual_profit.py` | 新增 `_closed_complete(old,q)`；`fresh` 判定接入 | `.bak-20261028T1035`、`.bak-20261028T1055` |

**实测证据（2026-10-28 10:5x）**：

| 场景 | 结果 |
|---|---|
| 昨日 FC27 毛利（已封账） | `200 / 0.014s / profitCny 56552.91 / refreshing False / stale False`（不再重算） |
| 今日 FC27 毛利（当日） | `200 / 0.009s / refreshing True / stale True`（后台仍在刷） |
| 今日 FC27 六卡（当日） | 连续两次 `202 pending → 200 available`（实时采集生效） |

## 6. 交接要点

1. **不要再新增一套缓存**。归档在 `/var/lib/fs-data-archive/`，接口缓存在 `/var/lib/fs-channel-effects/`。
2. **改 TTL 前先问：这个区间会变吗？** 当日会变，历史不会。
3. **归档与看板共用 `collector.lock`**。任何让归档“绕开锁”的改动都要保留当日实时路径。
4. Hermes 早上出日报依赖归档 → **归档越早完成越好**，所以修 TTL 的方向是“更快”而不是“等更久”。
5. 发布注意：以上改动是**生产热修**，私库维护源尚未同步，发布前必须保留现场或先同步（见
   `docs/planning/admin-dc-proxy-20261027/WRITE-MIGRATION.md` §10）。
