# -*- coding: utf-8 -*-
"""定价引擎：把「G2G 竞品（cheapold）价」+「DD373 进货成本」+「本店 G2G 现价」算成改价建议表。

口径（老板 2026-10-13 定案 · 与 d4follow 的 AION2 口径**完全同一套**）
--------------------------------------------------------------------
    ① 有 cheapold 卖家            →  目标价 $/M = cheapold价 × (1 − 下浮比例)
    ② 无 cheapold 卖家            →  目标价 = 本区 DD373 成本 ÷ (1 − 无cheapold利润率)
    ③ 成本兜底：基准价 < 我方成本  →  不再跟降，直接按**成本价**定价（不下浮）
    ④ 利润率地板 30%：跟价后 (P−C)/P < 30% ⇒ 强制抬到  成本 ÷ 0.70
    ⑤ 利润率天花板 45%：跟价后 (P−C)/P > 45% ⇒ 强制压到  成本 ÷ 0.55
    ⑥ 无有效报价 / 挂单不足       →  闸门价 $19.9/M；挂单 1~9 条 ⇒ $12.99/M
    ⑦ 现价恰好等于「保护占位价」   →  **不动**（占位价保护，默认为空 = 关闭）

老板原话（2026-10-13；同日 02:15 把带子由 20%/40% 上调到 30%/45%）
------------------------------------------------------------------
    「两个站都运用一套改价思路，跟踪 cheapold 的价格，若他的价格低于利润 20%，
      则我们锁死在 20%，这个是兜底；其次他的价格很高，我们也不必跟太高，
      利润是上限为 40%。」

为什么利润率写成 ÷(1−p) 而不是 ×(1+p)
-----------------------------------
「利润率」指毛利占**售价**的比例（平台口径毛率）。成本 1.00、要 30% 毛利 ⇒ 售价 × 0.7 = 成本
⇒ 售价 = 成本 ÷ 0.7 ≈ 1.4286（毛利 0.4286 / 售价 1.4286 = 30%）。
若写成 ×1.30，毛利只有 0.30/1.30 ≈ 23%，口径会偏。d4follow 与本站已统一为此式。

为什么要有「占位价保护」
--------------------
店里若干区常年挂着 $9.99，远高于成本价——那是「不想卖」的占位（既不缺货也不指望出单）。
若无脑按 成本 ÷ 0.55 下调，会把这些区一把压到 $1~4，等于主动放量甩货。
故：现价 ∈ 保护占位价 时，出「占位保护·不动」，要改得先把这个值从 config 的
`定价.保护占位价` 里去掉。**清空数组即关闭保护。**

映射键
------
成本侧 config 的键是 (大区, "服务区 - 阵营")，例如 ("NA West", "Siel - Elyos")；
竞品侧（vendor.core_g2g.cheapold_base）与货架侧（core_self.parse_offer）同构。
同名服务区在 NA West / NA East / EU / Asia 多处都挂，**必须带大区做键**，否则互相串价。
"""
import collections

NO_COST = "无成本数据"
HOLD = "占位保护·不动"
KEEP = "不动"

# 占位价匹配容差：店里实测有个区现价是 9.9999（录入/换算误差），
# 用精确相等会把它漏出保护，故用 ±0.011 的容差。
HOLD_TOL = 0.011

# 竞品来源标签（与 d4follow 看板同一套字样，便于两个站对照）
SRC_CHEAPOLD = "G2G·cheapold"
SRC_TOP2 = "G2G·推荐前二"


def _is_hold(cur, holds):
    if cur is None or not holds:
        return False
    c = float(cur)
    return any(abs(c - float(h)) < HOLD_TOL for h in holds)


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _clamp_p(p, dflt):
    """利润率必须落在 (−2, 0.99]：≥1 ⇒ 除零；≤−2 ⇒ 售价会低于成本 1/3，都没意义。"""
    v = _f(p)
    if v is None:
        return dflt
    if v >= 1.0:
        return 0.99
    if v <= -2.0:
        return -2.0
    return v


def build_cost_index(costs, servers):
    """把 vendor.fetch_costs 的结果 + config 服务区表，编成 {(大区, "服务区 - 阵营"): 成本记录}。"""
    idx = {}
    for sv in servers:
        k = sv.get("key")
        g2g = (sv.get("g2g_服务区") or "").strip()
        if not g2g:
            continue
        c = costs.get(k) or {}
        idx[(sv.get("大区"), g2g)] = {
            "key": k,
            "中文名": sv.get("中文名"),
            "大区": sv.get("大区"),
            "g2g_服务区": g2g,
            "够量": bool(c.get("够量")),
            "成本": (float(c["成本_USD每M"]) if c.get("成本_USD每M") else None),
            "可买量万": c.get("可供量_万基纳"),
            "条数": c.get("商品条数"),
            "ok": bool(c.get("ok")),
            "依据": (c.get("依据") or c.get("备注") or ""),
        }
    return idx


def build_cheapold_index(cb_map, servers):
    """把 {服务区 key: vendor.core_g2g.cheapold_base() 的返回} 编成同构索引。

    返回 {(大区, "服务区 - 阵营"): {cheapold, base, src, who, t1, t2, n, err}}
    —— base = None 表示该区本轮**没取到可跟的竞品价**（既无 cheapold 也无推荐前二），
    上层会退回「成本 ÷ (1−无cheapold利润率)」。
    """
    idx = {}
    for sv in servers:
        k = sv.get("key")
        g2g = (sv.get("g2g_服务区") or "").strip()
        if not g2g:
            continue
        c = cb_map.get(k) or {}
        idx[(sv.get("大区"), g2g)] = {
            "key": k,
            "cheapold": _f(c.get("cheapold")),
            "base": _f(c.get("base")),
            "src": c.get("src"),
            "who": c.get("who"),
            "t1": _f(c.get("t1")),
            "t2": _f(c.get("t2")),
            "n": c.get("n"),
            "err": c.get("error") or c.get("err"),
        }
    return idx


def target_price(cost_rec, cb_rec, cfg):
    """按口径算一个区的目标价 → (目标价, 定价方式, 跟价详情 dict)。

    priority（与 d4follow `core_gold.build_plan` 的 g2g_cheapold 段一致）：
        无成本        → 上层记「无成本数据」，不出目标价
        成本 ok 且条数不足 → 条数不足价 $12.99
        有 cheapold   → cheapold×(1−下浮) ⇒ 成本兜底 ⇒ 地板 30% ⇒ 天花板 45%
        无 cheapold   → 成本 ÷ (1−无cheapold利润率)
        成本不 ok      → 闸门价 $19.9
    """
    pol = cfg.get("定价") or {}
    _min_items = int(pol.get("条数下限") or 10)
    _shortp = float(pol.get("条数不足售价_usd_per_m") or 12.99)
    _gate = float(pol.get("闸门价_usd_per_m") or 19.9)
    if not (cost_rec and cost_rec.get("ok") and cost_rec.get("成本")):
        return (round(_gate, 2), "闸门价", {"基准价": None, "基准来源": "闸门价"})
    _n = cost_rec.get("条数")
    try:
        _n = int(_n) if _n is not None else None
    except (TypeError, ValueError):
        _n = None
    if _n is not None and 0 < _n < _min_items:
        return (round(_shortp, 2), "条数不足价",
                {"基准价": None, "基准来源": "条数不足价"})
    cost = float(cost_rec["成本"])

    # ── 旧口径（回滚开关 跟cheapold=false）：成本 ÷ (1 − 利润率) ──
    if not pol.get("跟cheapold", True):
        m = _clamp_p(pol.get("利润率"), 0.5)
        return (round(cost / (1.0 - m), 2), "成本÷%.2f" % (1.0 - m),
                {"基准价": None, "基准来源": "成本÷%.2f" % (1.0 - m)})

    base = _f((cb_rec or {}).get("base"))
    if base and base > 0:
        src0 = SRC_CHEAPOLD if (cb_rec or {}).get("src") == "cheapold" else SRC_TOP2
        disc = _f(pol.get("下浮比例"))
        disc = 0.0 if disc is None else max(0.0, disc)
        if base < cost:
            # ⛔ 成本兜底：竞品比我们的进货成本还低 ⇒ 不跟降，直接按成本价（不下浮）
            tgt = cost
            mode = "%s→成本价" % src0
        else:
            tgt = base * (1.0 - disc)
            mode = "%s×(1−%.1f%%)" % (src0, disc * 100)
        # ⛔ 利润率地板（默认 30%）：抬到 成本 ÷ (1−下限)
        lim = _clamp_p(pol.get("利润率下限"), 0.30)
        if tgt > 0 and (tgt - cost) / tgt < lim - 1e-9:
            tgt = cost / (1.0 - lim)
            mode += "｜利润下限%.0f%%" % (lim * 100)
        # ⛔ 利润率天花板（默认 45%）：压到 成本 ÷ (1−上限)
        cap = _clamp_p(pol.get("利润率上限"), 0.45)
        if tgt > 0 and (tgt - cost) / tgt > cap + 1e-9:
            tgt = cost / (1.0 - cap)
            mode += "｜利润率上限%.0f%%" % (cap * 100)
        return (round(tgt, 2), mode,
                {"基准价": round(base, 2), "基准来源": mode,
                 "cheapold": (cb_rec or {}).get("cheapold"),
                 "取价卖家": (cb_rec or {}).get("who"),
                 "推荐1": (cb_rec or {}).get("t1"),
                 "推荐2": (cb_rec or {}).get("t2"),
                 "卖家数": (cb_rec or {}).get("n")})

    # ── 无 cheapold 卖家 ⇒ 成本 ÷ (1 − 无cheapold利润率)（该区与 G2G 竞品价脱钩）──
    nc = _clamp_p(pol.get("无cheapold利润率"), 0.30)
    _old = _f(pol.get("无cheapold加价系数"))       # 旧「乘数」口径自愈：1.30 ⇒ 0.2308
    if _old and _old > 1.0:
        nc = 1.0 - 1.0 / _old
    mode = "成本÷%.2f" % (1.0 - nc)
    return (round(cost / (1.0 - nc), 2), mode,
            {"基准价": None, "基准来源": mode, "无cheapold": True})


def build_plan(offers, cost_idx, cfg, cheapold_idx=None):
    """货架 + 成本索引 + 竞品索引 → 逐行建议。offers 为 core_self.parse_offer 的输出列表。"""
    keep_price = list(cfg["定价"].get("保护占位价") or [])
    nd = int(cfg["定价"].get("小数位", 2))
    cb_idx = cheapold_idx or {}
    rows = []
    for o in offers:
        key = (o["区服组"], "%s - %s" % (o["服务区"], o["阵营"]))
        c = cost_idx.get(key)
        cb = cb_idx.get(key)
        cur = o.get("现价")
        r = {
            "offer_id": o["offer_id"],
            "区服组": o["区服组"],
            "服务区": o["服务区"],
            "阵营": o["阵营"],
            "标题": o.get("title"),
            "当前价": cur,
            "成本": c["成本"] if c else None,
            "可买量万": c["可买量万"] if c else None,
            "够量": ("Y" if c["够量"] else "N") if c else "",
            "状态": o.get("状态"),
            "可售量": o.get("可售量"),
            "offer_updated_at": o.get("updated_at"),
            # 竞品（cheapold）取价结果 —— 看板「竞品cheapold」列用
            "cheapold价": (cb or {}).get("cheapold"),
            "竞品基准价": (cb or {}).get("base"),
            "竞品来源": (cb or {}).get("src"),
            "竞品取价卖家": (cb or {}).get("who"),
            "竞品卖家数": (cb or {}).get("n"),
            "基准价": None,
            "基准来源": "",
        }
        if c is None:
            r.update({"目标价": None, "差额": None, "动作": NO_COST,
                      "定价方式": "", "说明": "DD373 成本表里没有这个 (大区, 服务区 - 阵营)"})
            rows.append(r)
            continue
        tgt, mode, det = target_price(c, cb, cfg)
        r["目标价"] = tgt
        r["定价方式"] = mode
        r["基准价"] = det.get("基准价")
        r["基准来源"] = det.get("基准来源") or mode
        r["说明"] = (c.get("依据") or "")[:80]
        if _is_hold(cur, keep_price):
            r["差额"] = round(tgt - float(cur), nd)
            r["动作"] = HOLD
            r["说明"] = "现价 %s 属保护占位价，按配置不参与改价；%s" % (cur, r["说明"])
            rows.append(r)
            continue
        if cur is None:
            r["差额"] = None
            r["动作"] = KEEP
            r["说明"] = "读不到现价，跳过"
            rows.append(r)
            continue
        diff = round(tgt - float(cur), nd)
        r["差额"] = diff
        if abs(diff) < 0.005:
            r["动作"] = KEEP
        elif diff > 0:
            r["动作"] = "上调"
        else:
            r["动作"] = "下调"
        rows.append(r)
    rows.sort(key=lambda x: (x["区服组"], x["服务区"], x["阵营"]))
    return rows


def summarize(rows):
    """汇总：动作计数 / 闸门价区数 / 未匹配成本的区 / 跟价来源分布。"""
    cnt = collections.Counter(r["动作"] for r in rows)
    src = collections.Counter()
    for r in rows:
        if r["动作"] in (NO_COST, KEEP, HOLD):
            continue
        s = r.get("基准来源") or ""
        if "利润下限" in s:
            src["利润下限抬价"] += 1
        if "利润率上限" in s:
            src["利润率上限压价"] += 1
        if s.startswith(SRC_CHEAPOLD):
            src["跟 cheapold"] += 1
        elif s.startswith(SRC_TOP2):
            src["跟 推荐前二"] += 1
        elif s.startswith("成本÷"):
            src["无cheapold·成本定价"] += 1
    return {
        "总数": len(rows),
        "动作分布": dict(cnt),
        "闸门价区数": sum(1 for r in rows if r["定价方式"] == "闸门价"),
        "上调": cnt.get("上调", 0),
        "下调": cnt.get("下调", 0),
        "可执行": cnt.get("上调", 0) + cnt.get("下调", 0),
        "占位保护": cnt.get(HOLD, 0),
        "无成本数据": cnt.get(NO_COST, 0),
        "来源分布": dict(src),
    }
