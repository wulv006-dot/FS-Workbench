# -*- coding: utf-8 -*-
"""ELDorado（ELD）竞品价抓取（Aion 2 Kinah）—— 纯 HTTP，服务器可无人值守运行。

为什么要单独一个模块
--------------------
2026-10-01 接入 AION2 时确定的三源跟价口径：

    基准价 = min(G2G 最低价, ELD 最低价)
    若 IGGM 价 < 基准价 → 基准价 = IGGM 价          （IGGM 只做参考，低了才跟）
    我方目标前端每 M 价 = 基准价 × (1 − 让价百分比)   （默认低 5%）

ELD 页面上选好区服就展示价，下方 `Cheapest first` 能定位最低价（用户原话）。
本模块直接打**前端自己用的那个接口**，等价于「选好区服 + Cheapest first」：
接口返回的 `results[]` 就是按单价升序的卖家列表，取第一个 = 最低价。

## 关键接口（2026-10-01 嗅探 + 服务器实测通过）

    GET https://www.eldorado.gg/api/predefinedOffers/augmentedGame/offers
        ?gameId=360&category=Currency
        &tradeEnvironmentValue0=<大区>&tradeEnvironmentValue1=<服务区>
        &pageIndex=1&pageSize=150

    返回 results[].offer：
      · pricePerUnit.amount           = 单价（$/K）
      · pricePerUnitInUSD.amount      = 同值（USD 口径）
      · unitSystem                    = "Unit1000"  ⇒ $/K × 1000 = $/M
      · minQuantity / quantity        = 起售量 / 库存
      · deliveryMethod / expireDate   = 交货方式 / 报价失效时间

## 区服树（动态拉，不硬编码）

    GET https://www.eldorado.gg/api/library/360/Currency?locale=en-US
    → tradeEnvironments[] = 大区；每区 childTradeEnvironments[] = 服务区

    2026-10-01 实测共 7 个大区 / 20 个服务区：
      NA West 2 · Europe 8 · Asia 2 · NA East 4 · Latin America 4 · KR 0 · TW 0
    ⇒ **AION2 新加的 14 个服务区在 ELD 全无报价**（空区不编数，由上层同大区均价兜底）。

## 换算口径

    ELD 页面写 "$X / K"（unitSystem=Unit1000）
    ⇒ 每 M 价 = X × 1000，与 G2G / IGGM / 我方前端**同为 $/M**，可直接比大小。
"""
import json
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

GAME_ID = "360"
CATEGORY = "Currency"
BASE = "https://www.eldorado.gg"
OFFERS_URL = BASE + "/api/predefinedOffers/augmentedGame/offers"
LIB_URL = BASE + "/api/library/%s/%s?locale=en-US" % (GAME_ID, CATEGORY)
PAGE_URL = BASE + "/aion-2-kinah/g/360"

# unitSystem 字符串 → 每 M 价的乘数（页面单位是「每 K」）
_UNIT_MULT = {
    "Unit1": 1_000_000.0,      # $/1 → ×1e6 得 $/M
    "Unit100": 10_000.0,
    "Unit1000": 1_000.0,       # $/K → ×1000 得 $/M     ← Aion2 Kinah 就是这个
    "Unit10000": 100.0,
    "Unit100000": 10.0,
    "Unit1000000": 1.0,
}


def _f(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _get_json(url, timeout=30, retry=3, log=None):
    last = None
    for i in range(max(1, retry)):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": PAGE_URL,
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                    # noqa: BLE001
            last = e
            if log:
                log("  [ELD] 第 %d 次请求失败：%r" % (i + 1, e))
            time.sleep(1.5 * (i + 1))
    raise last


def server_tree(timeout=30, retry=3, log=None):
    """拉 ELD 区服树 → [(大区, 服务区), ...]（只保留有子服务区的大区）。"""
    d = _get_json(LIB_URL, timeout=timeout, retry=retry, log=log)
    unit = d.get("unitSystem") or "Unit1000"
    pairs = []
    for reg in (d.get("tradeEnvironments") or []):
        rn = (reg.get("value") or "").strip()
        for ch in (reg.get("childTradeEnvironments") or []):
            sn = (ch.get("value") or "").strip()
            if rn and sn:
                pairs.append((rn, sn))
    return pairs, unit


def fetch_offers(region, server, page_size=150, timeout=30, retry=3, log=None):
    """打一个区服的报价列表，返回原始 results[]。"""
    q = urllib.parse.urlencode({
        "gameId": GAME_ID, "category": CATEGORY,
        "tradeEnvironmentValue0": region,
        "tradeEnvironmentValue1": server,
        "pageIndex": 1, "pageSize": page_size,
    })
    d = _get_json("%s?%s" % (OFFERS_URL, q), timeout=timeout, retry=retry, log=log)
    return (d.get("results")) or []


# 离群保护：低于「同区多数派中位数」这个比例的报价，判为脏数据剔除。
# 2026-10-01 实测依据：Europe Vaizel - Elyos 有卖家 HQStoregg 挂 $0.0017/K
# （= $1.7/M），其余 18 家全在 $14.8~20/M ⇒ 差 10 倍，是挂错单位/占位低价。
# 若照单全收，min() 会取到 1.7，让整个大区的目标价被带偏（同大区均价兜底也会被污染）。
# 0.5 = 只有便宜到「不到多数派一半」才剔；正常的低价竞争（便宜 5%~20%）不受影响。
_OUTLIER_RATIO = 0.5

# 库存有效性闸门：报价必须真的买得到。`quantity`（库存）× `minQuantity`（起售量）。
# 与 core_g2g._MIN_QTY_FLOOR 同口径，见那边注释的实测依据。
_MIN_QTY_FLOOR = 1000


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def scrape_one(region, server, timeout=30, retry=3, log=None):
    """抓一个 ELD 区服的最低 $/M 价。

    返回 {大区, 服务区, 最低价, 卖家数, 单价集合, unit, 起售量, 交货方式, 剔除离群}；
    无报价时 `最低价=None`（**不编数**，由上层兜底）。
    """
    rows = fetch_offers(region, server, timeout=timeout, retry=retry, log=log)
    per_m, unit, min_qty, dmethod = [], None, None, None
    skipped = []
    for it in rows:
        o = it.get("offer") or {}
        unit = unit or o.get("unitSystem")
        mult = _UNIT_MULT.get(o.get("unitSystem") or "", 1000.0)
        pu = _f((o.get("pricePerUnitInUSD") or {}).get("amount"))
        if pu is None:
            pu = _f((o.get("pricePerUnit") or {}).get("amount"))
        if pu is None:
            continue
        mq = o.get("minQuantity") or 1
        qty = o.get("quantity") or 0
        # 库存有效才算候选（见模块顶部 _MIN_QTY_FLOOR 注释）
        if qty >= max(mq, _MIN_QTY_FLOOR):
            per_m.append(round(pu * mult, 6))
        else:
            skipped.append({"价": round(pu * mult, 6), "库存": qty, "起售": mq,
                            "卖家": (it.get("user") or {}).get("username")})
        if isinstance(mq, int) and (min_qty is None or mq < min_qty):
            min_qty = mq
        dmethod = dmethod or o.get("deliveryMethod")
    per_m = sorted(set(per_m))
    med = _median(per_m)
    keep, drop = per_m, []
    if med and len(per_m) >= 3:
        keep = [v for v in per_m if v >= med * _OUTLIER_RATIO]
        drop = [v for v in per_m if v < med * _OUTLIER_RATIO]
        if drop and log:
            log("  [ELD] %s / %s 剔除离群低价 %s（多数派中位 %s）"
                % (region, server, drop, round(med, 6)))
    return {
        "大区": region, "服务区": server,
        "最低价": keep[0] if keep else None,       # $/M（已剔库存不足 + 离群）
        "卖家数": len(rows),
        "可用卖家数": len(per_m),
        "单价集合": keep[:10],
        "剔除离群": drop,
        "剔除库存不足": skipped,
        "中位价": round(med, 6) if med else None,
        "unit": unit or "Unit1000",
        "起售量": min_qty,
        "交货方式": dmethod,
    }


def scrape_all(pairs=None, log=None, sleep=0.5, **kw):
    """抓全部（或指定）区服 → {“大区|服务区”: rec}。"""
    if pairs is None:
        pairs, _u = server_tree(log=log)
        if log:
            log("  [ELD] 区服树：%d 个大区 / %d 个服务区" % (
                len({p[0] for p in pairs}), len(pairs)))
    flat = {}
    for rn, sn in pairs:
        try:
            rec = scrape_one(rn, sn, log=log, **kw)
            flat["%s|%s" % (rn, sn)] = rec
            if log:
                log("  [ELD] %-16s %-22s 最低 %s ($/M, %d 卖家)"
                    % (rn, sn, rec["最低价"], rec["卖家数"]))
        except Exception as e:                    # noqa: BLE001
            if log:
                log("  [ELD] %s / %s 抓取失败：%r" % (rn, sn, e))
            flat["%s|%s" % (rn, sn)] = {
                "大区": rn, "服务区": sn, "最低价": None, "卖家数": 0,
                "单价集合": [], "错误": "%r" % e}
        time.sleep(sleep)
    return flat


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="ELDorado Aion2 Kinah 竞品价抓取（只读）")
    ap.add_argument("--out")
    a = ap.parse_args()
    _flat = scrape_all(log=print)
    print("=" * 110)
    ok = [v for v in _flat.values() if v.get("最低价") is not None]
    print("抓到 %d 区有价 / 共 %d 区" % (len(ok), len(_flat)))
    for k in sorted(_flat, key=lambda s: (_flat[s]["大区"], _flat[s]["最低价"] or 9e9)):
        r = _flat[k]
        print("%-16s %-24s 最低 %8s $/M  卖家 %2d  集合 %s"
              % (r["大区"], r["服务区"], r["最低价"], r["卖家数"], r["单价集合"][:6]))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(_flat, f, ensure_ascii=False, indent=1)
        print("\n已存：%s" % a.out)
