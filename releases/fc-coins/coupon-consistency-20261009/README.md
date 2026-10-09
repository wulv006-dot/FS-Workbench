# FC27-20261009-coupon-consistency

已部署一份 `snapshot_layer.py` 源码，把 LootBar 快照门禁从「**每个平台都必须有券前价**」改为「**三个平台必须在券状态上一致**」。北京时间 2026-10-09 19:47:49 以单文件受控发布器上线，12 份保护文件保持，服务健康与队列空闲均在发布时复核。

本文是证据入口，实际收据见 `evidence/`，不以文档代替上线验收。

## 目标与范围

修复「竞品撤券即触发数据语义失败、且链路不自愈」的问题：门禁原本硬要求每个平台都存在券前价，LootBar 撤掉 FC27 新客券后三平台全部变成无券，门禁仍按旧判据拦下，周期 latch 成 `paused_after_failure`。

改法是把判据从**「结构上有券」**换成**「口径一致」**——保留真正的不变量（跨平台可比性），去掉对站点券策略的硬编码假设。不放松任何比对强度、不伪造通过、不改业务参数、不新增依赖或 workflow。

仅修改 `fc27_cloud_browser/snapshot_layer.py` 一个文件。

## 基线与来源

先核对真实工作源与宿主目标。工作源为原工程 `fc27_cloud_browser/snapshot_layer.py`，宿主目标 `/opt/fc27-cloud-browser/snapshot_layer.py`，运行根 `/var/lib/fc27-cloud`（由 `snapshot_layer.ROOT` 解析，非环境变量）。

GitHub 根 FC 仍 legacy-unreconciled；本 PR 回补专用 release 与精确 source→runtime 映射，不用本地旧副本覆盖根目录。

⚠️ **基线取值说明**：main 上 `fc27_cloud_browser/snapshot_layer.py`（sha256 `b91dbbbf…`，14408 B）与线上**不一致**，缺了 noncore 紧急修复引入的 `source_coverage` / `source_warnings` 逻辑。真正的线上字节与 `releases/fc-coins/noncore-emergency-20261009/source/snapshot_layer.py`（sha256 `280cc936…`，15000 B）逐字节一致，因此**基线取后者**。若误用根目录那份做基线，会回滚他人改动。

| 文件 | 发布前 SHA-256 | 发布后 SHA-256 |
| --- | --- | --- |
| snapshot_layer.py | 280cc936ceaa68da0895533a8d03e7a551b00b492d254656d4b083a0a9cc8a60 | 1d8a40c2bd0489f36444e74abc6e8ff3bc8543522cb5c58dfe305e052b36f4fd |

## 根因

当日证据链：

1. 08:44 – 16:58 共 8 个周期，三平台全部 `coupon_excluded=true`，正常出价
2. **19:01** 变成 PS=`true` / XBOX=`false` / PC=`false` —— LootBar 开始撤券
3. **19:38** 手工只读复采，三平台全部 `false`
4. 快照门禁 `snapshot_layer.py:54-57` 逐平台检查 `offers[p].get("coupon_excluded") is not True` → 抛 `platform_or_coupon_mismatch`
5. 该错误属**数据语义类**，不在 `automation_tick.proven_prewrite_timeout()` 的 `TRANSIENT_TIMEOUTS` 白名单内 → 无自动重试 → latch 成 `paused_after_failure`

关键判定：采集器**如实记录**了 `couponState='none'`。分类器 `background.js:118-160` 的判据是「负金额文本 ∨ 券提示文案 ∨ 划线价节点」，全无才落到 `none`；解析失败会落到 `discount_format` / `original_missing` 等「…未唯一核实」分支。既然落到 `none`，说明**页面上真的没有券**——是站点侧真实变化，不是采集故障。

原判据的问题在于：它拦的不是「口径不一致」，而是「**没有券**」这个本身完全合法的事实。

## 实现

原实现（逐平台）：

```python
for p in PLATFORMS:
    if offers[p].get("coupon_excluded") is not True:
        raise ValueError("platform_or_coupon_mismatch")
```

改为（先取集合，再判一致性）：

```python
coupon_states = {offers[platform].get("coupon_excluded") for platform in PLATFORMS}
if len(coupon_states) != 1:
    raise ValueError("platform_or_coupon_mismatch")
coupon_excluded = coupon_states.pop()
if type(coupon_excluded) is not bool:
    raise ValueError("platform_or_coupon_mismatch")
```

同时把行内硬编码的 `"coupon_excluded": True` 改为携带观测值：

```python
"coupon_excluded": coupon_excluded, "auth_state": "logged_in",
```

要点：

- **保留真正的不变量**：平台间券状态**必须一致**。混用券前价与券后/无券价会让跨平台不可比、进而算出错误报价 —— 这条仍然硬拦。
- **去掉对站点策略的假设**：三平台**一致地**有券、或**一致地**无券，都是合法口径，怎么一致是站点自己的事。
- **类型守卫**：`type(...) is not bool` 排除字符串 `"true"`、整数 `1`、`None` 等伪装值（注意不用 `isinstance`，`bool` 是 `int` 子类）。
- 未触碰新鲜度门禁（3600 s）、`collector_incomplete`、`platform_coverage_incomplete`、`invalid_capture_time`、`unexpected_package_size`、`invalid_bonus` 等其余判据。

## 影响

现有 EN/USD、平台、100K 规格、赠送/折扣、成本/毛利与定价合同**全部保持**。未扩大任何自动重试白名单；未触碰写价路径、队列、锁、门禁或机器人。

行为差异仅在：三平台一致地无券时，由「拒绝」变为「接受并如实记录 `coupon_excluded=false`」。三平台券状态不一致时，仍拒绝。

## 验证

隔离测试 `test_coupon_consistency.py` 共 15 项，本地 CPython 3.13.12 与服务器 CPython 3.9.18 各 **15/15 通过**：

| 用例 | 断言 |
| --- | --- |
| 三平台全有券 | 通过 |
| 三平台全无券 | 通过 |
| 券状态如实透传 | 行内值 == 观测值，非硬编码 |
| 2 有 1 无 | 拒绝 |
| 1 有 2 无 | 拒绝 |
| 非布尔标志（`"true"`/`"True"`/`1`/`0`/`None`） | 拒绝 |
| 缺 `coupon_excluded` 键 | 拒绝 |
| 平台标签漂移 | 拒绝 |
| 规格 ≠ 100K（`base_k`） | 拒绝 |
| 缺平台 | 拒绝 |
| 采集过期（>3600 s） | 拒绝 |
| `collector_incomplete` | 拒绝 |
| 赠送无效 | 拒绝 |
| 每 K 单价换算 | 正确 |
| 每行盖 `run_id` | 正确 |

**真实线上证据回归**（非合成夹具）：

| 时刻 | 观测 | 期望 | 实测 |
| --- | --- | --- | --- |
| 16:58 全有券 | `true/true/true` | ACCEPTED | ✅ ACCEPTED |
| 19:01 混合口径 | `true/false/false` | REJECTED | ✅ REJECTED |
| 19:38 全无券 | `false/false/false` | ACCEPTED | ✅ ACCEPTED |

（16:58 初次报 `stale_capture` 是新鲜度门禁 3600 s 的正确拦截 —— 该采集已约 3 小时旧；刷新时间戳后 ACCEPTED，非误判。）

发布侧：`stage/deploy.py` 在服务器端以 root 运行，先 dry-run（`status: checked`，`protected: 12`），再 `--apply`。纪律与 `publish_worker.py` 一致：`flock` 排他锁 + 队列/任务/执行 idle 核对 + 12 份基线哈希逐一复核 + 备份到 `rollback/coupon-consistency-20261009T114749Z/` + 停 API/worker + `os.replace` 原子替换（保留 mode/owner）+ fsync 文件与目录 + 重启 + 健康等待 + 安装哈希与保护哈希复验；任一步失败即还原备份并重新抛出。

## 发布与运行

2026-10-09 11:47:49 UTC / 19:47:49 北京，以单文件受控发布器上线。

上线后半小时内即得到**端到端实证**（详见 `evidence/regression-real-evidence.json`）：

- 门禁放行，被拦周期 `5919057b` 的自动重试 `9d2476dd`（`attempt=1`）完整跑通
- 三平台全部 `status: confirmed`，`blocked_platforms: {}`，`unchanged_platforms: []`
- `public_page_readback: verified`，三平台，**`attempts: 1`**（CDN 一次即过，上一版补的有界重试未触发）
- 独立只读监控 `fc-ops-readonly-monitor` 三平台 `phase: RECOVERED`，`reasons: []`

## 遗留

1. `read_only_status.py:186-210` 的 `prewrite_failure_recovery` 标记要求 `collection.created_at > job.completed_at`。当采集与失败写价属**同一 job** 时该条件永不成立，链路无法自愈，须人工推一把（本次即以一次只读 `collect` 作业破解）。建议提修复案，允许同周期采集满足标记。
2. 门禁的「口径」语义仍是**结构判据**而非**数值判据**。若 LootBar 撤券后净价恰等于原券前价，口径其实变可比，但门禁仍会按结构差异拦下。业务侧「无券价能否当我方对标基准」需老大确认。
