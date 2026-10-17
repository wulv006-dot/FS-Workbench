# -*- coding: utf-8 -*-
"""定价引擎：把「DD373 进货成本」+「本店 G2G 现价」算成一张改价建议表。

口径（老板 2026-10-12 定案 · 与 d4follow 的 AION2 口径统一）
-----------------------------------------------------------
    成本够量（DD373 买满 1.5 亿基纳）→  目标价 $/M = 成本 $/M ÷ (1 − 利润率)
                                        利润率取 config.定价.利润率；2026-10-12 起 = 0.50 ⇒ 成本 ÷ 0.50
    成本不足闸门量 / 无有效报价        →  目标价 = 闸门价 $19.9/M
                                          （买满量与够量闸门见 config 定价.*_万基纳）
    现价恰好等于「保护占位价」        →  **不动**（占位价保护，见下；默认为空 = 关闭）

为什么是 ÷(1−利润率) 而不是 ×1.30
-------------------------------
「利润率」指毛利占**售价**的比例。成本 1.00、要 30% 毛利 ⇒ 售价 × 0.7 = 成本
⇒ 售价 = 成本 ÷ 0.7 ≈ 1.4286（毛利 0.4286 / 售价 1.4286 = 30%）。
若写成 ×1.30，毛利只有 0.30/1.30 ≈ 23%，口径会偏。d4follow 已于同日统一为此式。

为什么要有「占位价保护」
--------------------
店里若干区常年挂着 $9.99，远高于成本价——那是「不想卖」的占位（既不缺货也不指望出单）。
若无脑按 成本×1.30 下调，会把这些区一把压到 $1~4，等于主动放量甩货。
故：现价 ∈ 保护占位价 时，出「占位保护·不动」，要改得先把这个值从 config 的
`定价.保护占位价` 里去掉。**清空数组即关闭保护。**

映射键
------
成本侧 config 的键是 (大区, "服务区 - 阵营")，例如 ("NA West", "Siel - Elyos")；
货架侧从标题解析出 (区服组, 服务区, 阵营)，拼成同构键。
同名服务区在 NA West / NA East / EU / Asia 多处都挂，**必须带大区做键**，否则互相串价。
"""
import collections

NO_COST = "无成本数据"
HOLD = "占位保护·不动"
KEEP = "不动"

# 占位价匹配容差：店里实测有个区现价是 9.9999（录入/换算误差），
# 用精确相等会把它漏出保护，故用 ±0.011 的容差。
HOLD_TOL = 0.011


def _is_hold(cur, holds):
    if cur is None or not holds:
        return False
    c = float(cur)
    return any(abs(c - float(h)) < HOLD_TOL for h in holds)


def _fmt(v, nd=2):
    return "" if v is None else round(float(v), nd)


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
            "ok": bool(c.get("ok")),
            "依据": (c.get("依据") or c.get("备注") or ""),
        }
    return idx


def target_price(cost_rec, cfg):
    """按口径算一个区的目标价 → (目标价, 定价方式)。

    目标价 = 成本 ÷ (1 − 利润率)；利润率取 config.定价.利润率（当前 0.50 ⇒ ÷0.50）。
    """
    if cost_rec and cost_rec.get("ok") and cost_rec.get("够量") and cost_rec.get("成本"):
        m = float(cfg["定价"]["利润率"])
        div = 1.0 - m
        if div <= 0:
            raise ValueError("定价.利润率 必须 < 1（当前 %r）" % (m,))
        return (round(cost_rec["成本"] / div, 2), "成本÷%.2f" % div)
    return (float(cfg["定价"]["闸门价_usd_per_m"]), "闸门价")


def build_plan(offers, cost_idx, cfg):
    """货架 + 成本索引 → 逐行建议。offers 为 core_self.parse_offer 的输出列表。"""
    keep_price = list(cfg["定价"].get("保护占位价") or [])
    nd = int(cfg["定价"].get("小数位", 2))
    rows = []
    for o in offers:
        key = (o["区服组"], "%s - %s" % (o["服务区"], o["阵营"]))
        c = cost_idx.get(key)
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
        }
        if c is None:
            r.update({"目标价": None, "差额": None, "动作": NO_COST,
                      "定价方式": "", "说明": "DD373 成本表里没有这个 (大区, 服务区 - 阵营)"})
            rows.append(r)
            continue
        tgt, mode = target_price(c, cfg)
        r["目标价"] = tgt
        r["定价方式"] = mode
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
    """汇总：动作计数 / 闸门价区数 / 未匹配成本的区。"""
    cnt = collections.Counter(r["动作"] for r in rows)
    return {
        "总数": len(rows),
        "动作分布": dict(cnt),
        "闸门价区数": sum(1 for r in rows if r["定价方式"] == "闸门价"),
        "上调": cnt.get("上调", 0),
        "下调": cnt.get("下调", 0),
        "可执行": cnt.get("上调", 0) + cnt.get("下调", 0),
        "占位保护": cnt.get(HOLD, 0),
        "无成本数据": cnt.get(NO_COST, 0),
    }
