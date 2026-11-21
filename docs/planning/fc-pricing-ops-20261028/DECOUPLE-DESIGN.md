# FC27 自动改价：三环节解耦与故障隔离（待审查）

> 状态：**设计稿，未实施**。等待 Dot 审查通过后再改代码。
> 作者：Buddy ｜ 2026-10-28 ｜ 触发事件：10-28 自动改价连续 5 轮失败且页面卡死

## 1. 要解决的问题

当前一轮改价是**串行强耦合**：任一环节失败，整轮被标记为失败或 `UNKNOWN`，并**占用资源租约**，导致：

- 页面停在"待核 `original_operation_reconciliation_pending`"，不刷新
- 后续轮次拿不到资源（`ledger.py:184` 要求操作走到 `COMPLETED` 才释放）
- **已经成功的部分也看不到**：竞品采到了、Admin 当前价读到了，但页面只显示"失败"

**实测复现（2026-10-28）**：

```
12:05  报价算出 7.99 → console 7.38 / pc 7.46
       Order 改价实际生效（读回 0.0746 / 0.0738，前台 $7.38）
       但 ALL 站点同步失败（coin_auth_unavailable）
       → 整个操作 status = UNKNOWN
       → 资源不释放 → 之后 5 轮全部 original_operation_reconciliation_pending
       → 页面停在 7.99
```

## 2. 目标行为（用户明确要求）

**把三个环节拆成独立状态，各自成败互不影响展示：**

| 环节 | 独立产出的状态 | 失败时的表现 |
|---|---|---|
| A. 采集竞品价格 | `competitors: ok / partial / failed` + 抓到的各家报价 | 显示上次成功值 + "竞品采集失败" |
| B. 读取 Admin 当前价 | `current_prices: ok / failed` + PS/XBOX/PC 当前价 | 显示上次成功值 + "当前价读取失败" |
| C. 改价执行 | `execution: ok / failed / unknown` + 已写/未写 | 显示"改价运行失败"，**但 A、B 照常显示最新** |

**关键约束**：
- A、B 必须**每轮都刷新**，不因为 C 失败而停止
- C 失败**不能**占用资源导致下一轮 A、B 也跑不了
- 页面必须能同时展示"竞品价 / 我们当前价 / 改价结果"三块，任一块坏了只坏那一块

## 3. 设计

### 3.1 状态模型（每轮产生独立的三个结果）

```json
{
  "run_id": "...",
  "competitors": {
    "status": "ok|partial|failed",
    "captured_at": "...",
    "offers": {"Lootbar": 8.68, "ItemD2R": 8.42, "...": 0},
    "error": null
  },
  "current_prices": {
    "status": "ok|failed",
    "captured_at": "...",
    "rows": {"PC": 0.0746, "PS": 0.0738, "XBOX": 0.0738},
    "error": null
  },
  "execution": {
    "status": "ok|failed|unknown|skipped",
    "targets": {"PC": 0.0746, "PS": 0.0738, "XBOX": 0.0738},
    "written": true,
    "error": null,
    "note": "..."
  }
}
```

### 3.2 执行顺序与失败隔离

```
1) 采竞品   → 失败记 competitors.failed，继续第 2 步
2) 读当前价 → 失败记 current_prices.failed
3) 算价     → **必须 1、2 都 ok**；任一失败 → execution.skipped，不进入写价
4) 写价     → 走原有 operation / 租约 / 请求 ID 保护，失败只记 execution.failed
5) 展示层   → 三块独立渲染；1、2 的旧值可显示并标注时间
```

**约束**：竞品或当前价失败 → 本轮不写价；第 5 步只做展示，不涉及租约（租约规则见 §3.3）。

### 3.3 资源与写入保护（**不引入超时放行**）

**当前价没变 ≠ 请求没发出去。** 因此：

**禁止**：写价结果 `UNKNOWN` 时按超时自动释放锁 / 自动放行下一轮。
理由：30 分钟后放行，新请求可能与仍在路上的旧请求相撞，产生**双写**。

**正确行为**：

| 操作状态 | 租约 | 采集/计算/展示 | 处置 |
|---|---|---|---|
| `COMPLETED` / `NO_CHANGE` | 释放（现有 `finish()`） | 正常 | — |
| `CANCELLED_NOT_SENT`（确定未发出） | 释放（现有 `cancel_not_sent()`） | 正常 | — |
| `KNOWN_PARTIAL_*`（部分已确认） | 释放（现有 `finish_known_partial()`） | 正常 | — |
| **`UNKNOWN`（已发出但结果未知）** | **保留，不释放** | **照常跑（不占租约）** | **按原请求 ID 持续核对，直到结果明确** |

**超时的用途只有一个：告警**。超时阈值（建议 30 分钟）触发的是**通知人来看**，不是自动解锁。

**写入侧必须保持**：原 operation ID、原 step 的 `transport_claimed_at`、原 `dispatch_context`。核对也只能用这个 ID 去读回，不能开新操作。

### 3.4 ALL 同步：必须区分"没发出"和"未知"

按下面两态判定：

| ALL 侧状态 | 判据（严格发送证明） | 处置 |
|---|---|---|
| **确定没有发出** | **必须同时满足**：无 `dispatched_at` **且** `transport_claimed_at` 为空 **且** `receipt.status == 'NOT_SENT'` | 可在**实际售价核验完整**的前提下，按现有规则降级（不回退 Order 已确认结果） |
| **已发出或证明不足 = 未知** | 上述任一条件不满足（含 receipt 缺失、非 `NOT_SENT`、有 `dispatched_at`、有 `transport_claimed_at`） | **继续核对，不得因 Order 成功就结束** |

**关键约束**：`sync_confirmed: true` 只代表 Order 侧确认，**不等于 ALL 侧已定**；ALL 侧一律按 §6.1 的严格发送证明判定。

### 3.4.1 展示旧数据不放宽红线

允许展示上一次成功值（并标注采集时间），但：

- **成本、汇率、优惠、双 20% 红线的计算不得使用过期输入**
- 输入不新鲜 → 本轮**不写价**（`execution.skipped`），只展示
- 展示层要区分"实时值"与"上次值（时间戳）"，不能混用

### 3.4.2 数据刷新频率（业务确认）

| 数据 | 刷新频率 | 用途 |
|---|---|---|
| **汇率、优惠（券/折扣）** | **每日更新即可** | 当日展示与计算使用当日快照 |
| **成本、双 20% 计算** | **每次运行都刷新** | 写价依据，必须为本轮实时值 |

成本或双 20% 输入不新鲜 → 本轮不写价（`execution.skipped`），只展示。汇率/优惠允许用当日快照，但页面须标注快照日期。

### 3.5 页面（FC27 定价工作台）

**现状**：整页读一个 `latest_job`，任一环节失败整块变"待核"。

**改为**：三块独立读取、独立降级。**失败时仍显示上次成功值，并在同区块提示本次失败。**

| 区块 | 数据源 | 成功 | 失败 |
|---|---|---|---|
| 竞品价格追踪 | `competitors` | 各家最新报价 | **显示上次成功报价**，角标"上次采集：<时间>"，同区块红字"**本次采集失败：<原因>**" |
| 我方当前价 | `current_prices` | PS/XBOX/PC 当前价 | **显示上次成功的当前价**，角标时间，红字"**本次读取失败：<原因>**" |
| 改价执行 | `execution` | 目标价 / 已写入 | **不改动上两块**；本区块显示"**本次改价失败：<原因>**"（如有上次成功执行，保留其时间与结果） |

**展示规则（三条）**：

1. **数值优先显示"上次成功值"**，不显示 "—"；每个区块必须带**该值的采集时间**。
2. **本次失败用红字提示**，与上次值同区块并列，写明原因（如 `竞品采集超时` / `当前价读取失败` / `改价资源未释放`）。
3. **不得把上次值伪装成实时值**：样式（灰化/角标）或文案必须能区分，且上次值不参与成本、汇率、优惠、双 20% 计算（见 §3.4.1）。

## 4. 要改的文件（**待审查通过后才动**）

| 文件 | 改动 | 风险 |
|---|---|---|
| `fc_pricing_v3/business_source.py` | 拆出 `collect_competitors()` / `read_current_prices()`，各自 try 包裹；两者不入账本、不占租约 | 中 |
| `fc_pricing_v3/scheduler.py` | 按 §3.2 顺序执行；收尾**只调用现有** `cancel_not_sent()` / `finish()` / `finish_known_partial()`，不新增释放路径 | 中 |
| `fc_pricing_v3/ledger.py` | **不改释放条件、不改终态白名单**；仅在 `reconcile` 入口补"读回核对后调用现有收尾函数" | 低 |
| `price_writer.py` | ALL 侧按 §3.4 两态处理：严格证明未发送→可降级；已发出/证明不足→保持未知继续核对 | 中 |
| 前端 `fc27-coins` | 三块独立展示 | 低 |

**测试要求**（CI 必过，逐条对应现有流程）：

1. **竞品失败** → `execution.skipped`，**本轮不写价**；当前价照常展示
2. **当前价失败** → `execution.skipped`，**本轮不写价**；竞品照常展示
3. **改价失败且每个未确认 step 均满足严格发送证明** → 调 `cancel_not_sent()`（释放租约），下一轮可跑
4. **改价失败但证据不足**（如 base 有 `dispatched_at`）→ **保持 `UNKNOWN`、租约保留、下一轮不写价**，只告警
5. **`coin_auth_unavailable`（ALL 已发出后失败）** → 保持 `UNKNOWN` 继续核对；**不得**标 `COMPLETED`，不得只记 note 就放行
6. **迟到响应**：写价请求超时后才返回成功 → 不重复下发，用原 operation ID 读回确认
7. **部分地区生效**：base 成功、region 部分失败 → 走 `finish_known_partial()`，页面标注"部分地区已改"

## 5. 已定约束（Dot 审查 2026-10-28）

1. **未知结果不超时放行**：`UNKNOWN` 超时只告警；租约、请求 ID、`dispatch_context` 保持；写入侧继续用原 operation ID 核对。
2. **ALL 两态**：仅当严格发送证明成立才可按现有规则降级；已发出或证明不足，一律视为未知、继续核对。
3. **展示旧值不放宽红线**：成本、汇率、优惠、双 20% 计算不得使用过期输入；输入不新鲜 → 本轮不写价。
4. **失败即不写价**：竞品或当前价失败 → `execution.skipped`。
5. **保写入保护，只拆三层**：采集 / 计算展示 / 写入调度。
6. **页面失败态**：显示**上次成功值 + 该值采集时间**，同区块红字提示**本次失败及原因**；上次值不参与红线计算（见 §3.5）。

**无待确认项。**

## 6. 实施依据（复用现有流程）

### 6.1 严格发送证明（唯一判据）

一个未确认 step 只有**同时满足**下列三条，才算「确定未发出」：

- 无 `dispatched_at`
- `transport_claimed_at` 为空
- `receipt.status == 'NOT_SENT'`

任一不满足 → 视为「已发出 / 未知」，保持核对。**不得用价格是否变化来推断发送状态。**

### 6.2 现有收尾函数（直接复用，不新增释放路径）

| 函数 | 位置 | 触发条件 | 结果 |
|---|---|---|---|
| `cancel_not_sent()` | `ledger.py:451` | 全部 step 满足 §6.1 | `CANCELLED_NOT_SENT` + 释放租约 |
| `finish()` | `ledger.py:466` | 所有 step `CONFIRMED` | `COMPLETED` / `NO_CHANGE` + 释放租约 |
| `finish_known_partial()` | `ledger.py:507` | 部分已确认、其余满足 §6.1 | `KNOWN_PARTIAL_EXIT_PENDING` + 释放租约 |
| `stop_unissued_and_exit()` | `runtime.py:526` | 上述三条的调度入口 | 按上表分流；证据不足则返回原操作 |

`ledger.py:184 / 218 / 368` 的终态白名单**保持不变**。

### 6.3 改价成功的判定（用户 2026-10-28 确认）

> **本次 Order 修改明确成功 + 随后 Admin 单位价格核对正确，即记录改价成功。**

两个条件**必须同时成立**，缺一不可：

| # | 条件 | 判定依据（字段映射） |
|---|---|---|
| 1 | **本次 Order 操作保存的成功反馈** | 审计记录中 `sync_message` 非空（`clickSync` 返回 `success` 且 `message` 非空）。**`sync_recipient_readback` 不算条件 1**：它是两次 Admin 读价稳定一致的推断，判据与条件 2 完全重合，同步超时也会生成，接受它等于把「价格碰巧正确」当成 Order 成功。**不读 `record['stage']`**（每次 `stage()` 都会覆盖它，后续 `readback_confirmed` 会冲掉 `sync_feedback`）；**不读 `record['status']`**（要等 ALL 收尾才 `CONFIRMED`，中途是 `PARTIAL`） |
| 2 | **随后 Admin 单位价格核对正确** | 从 Admin 重新查询对应商品的 `unit_price`（`goods.Goods/edit?id=` 逐条精确读），换算后**等于本次目标价** |

**满足即记录改价成功，不再补回公开页强制门槛**；公开页核对仅作事后补充，不阻塞收尾。

**字段来源（`price_writer.py` 现有实现，两条成功反馈路径）**：

```python
# 正常路径：点击同步后拿到明确反馈
feedback = page.evaluate("async () => FC27RepricingDOM.clickSync('mmoexp.com')")
stage(record, "sync_feedback", sync_confirmed=True, sync_message=str(feedback["message"])[:120])
# 兜底路径：反馈异常时用接收方回执确认
stage(record, 'sync_recipient_confirmed', sync_confirmed=True, sync_recipient_readback=receipt)
```

`stage()` 的实现是 `record.update(fields)` + `record["stage"] = name`（`price_writer.py:76`），
所以**只有 `fields` 里的 `sync_message` `sync_recipient_readback` 会长期保留**，`record["stage"]` 会被后续阶段覆盖。
但两者**证据等级不同**：`sync_message` 是 Order 返回的成功反馈，`sync_recipient_readback` 只是读价推断 ——
⇒ 条件 1 取 `sync_message`；`sync_recipient_readback` 只作为 `price_inference` 留痕（`usable_as_proof: false`）。
**不读 `record['status']` 也不读 `record['stage']`**，因此不会被 ALL 的阻塞带回来。

> 单位换算：Admin `unit_price` 是**每 K**，目标价是**每 100K** ⇒ `unit_price × 100 == 目标价`（实测 0.0738→$7.38 / 0.0746→$7.46）。
> 读回只校验 `unit_price`；`price` 字段必须保持 0（有数值会影响折扣计算）。
> 不用 `top_cid`/`site_id` 组合筛选——那会混入地区覆盖记录。

### 6.4 要补的入口

现有流程缺少「已发出且已核对成功 → 推进收尾」的入口。补在 `reconcile`：

1. **确认本次 Order 操作保存的成功反馈**（§6.3 条件 1）：**只认 `sync_message`**（`clickSync` 返回 `success` 且 `message` 非空）。`sync_recipient_readback` 是两次读价一致的推断，判据与条件 2 重合，**不得**当作条件 1。不读全局 `status`，也不读会被覆盖的 `stage`
2. **随后从 Admin 核对单位价格**（§6.3 条件 2）：逐平台读 `unit_price`，换算后等于本次目标价
3. **两个条件同时成立** → 记录改价成功：对应 step 标 `CONFIRMED`；其余满足 §6.1 则标 `CANCELLED_NOT_SENT`；调 `finish_known_partial()`
4. **先收尾，再退出**：`reconcile` 中所有提前退出（授权过期 `pricing_authorization_expired`、复算/授权校验失败、公开页异常、`KNOWN_PARTIAL_PUBLIC_PENDING` 重入）必须先尝试第 1、2 条；能收尾就不走取消路径。收尾只记录既成事实，**不授权任何新写入**
5. **两侧写同一终态**：账本收尾后同步把 `executions/<operation_id>.json` 写成终态；`price_writer` 的 `unresolved_execution_exists` 扫描交叉核对账本状态。只释放一侧 = 下一轮仍被拦
6. **任一条件不成立** → 保持 `UNKNOWN`，继续核对；不改锁、不新建操作

### 6.5 三环节解耦

- A（采竞品）/ B（读当前价）：**不入账本、不占租约**，各自独立 try，结果写 run 快照
- C（写价）：走 operation / 租约 / 请求 ID
- 页面三块分别读 `competitors` / `current_prices` / `execution`，互不阻塞

### 6.6 施工与测试硬条件

保留现有写入保护，只拆三层。测试见 §4「测试要求」7 条，全部通过才进入实施。
