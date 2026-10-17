# -*- coding: utf-8 -*-
"""G2G 竞品价抓取（Aion 2 Kinah）—— 纯 urllib，服务器可无人值守运行。

为什么要单独一个模块
--------------------
2026-10-01 接入 AION2 时确定的三源跟价口径：

    基准价 = min(G2G 最低价, ELD 最低价)
    若 IGGM 价 < 基准价 → 基准价 = IGGM 价          （IGGM 只做参考，低了才跟）
    我方目标前端每 M 价 = 基准价 × (1 − 让价百分比)   （默认低 5%）

G2G 必须**点进每张卡片找最低价**（用户原话：外显卡片 7.77 刀，点进去默认 15 刀）。
本模块用官方 REST 接口一次拿全，等价于「每张卡片都点进去」：
`sort=lowest_price&group=0` 会把**同一服务区所有卖家的真实单价**全返回，
按 `offer_group`（服务区卡片 ID）分组取 min，就是该区最低价。

## 关键接口（2026-10-01 服务器实测通过）

    GET https://sls.g2g.com/v3/offer/search
        ?seo_term=aion-2-kinah
        &region_id=<RID>          # 大区
        &country=US&currency=USD
        &page_size=100&page=1
        &sort=lowest_price        # 全局按单价升序 ⇒ page 1 必含每区最低价
        &group=0                  # 0 = 全部卖家；1 = 每区一个代表（会拿不到最低价）
        &v=v2

    返回 payload.results[]，每条：
      · converted_unit_price = 真实单价（$/Mil Kinah —— 正好是本项目口径）
      · unit_name            = "Mil Kinah"
      · title                = "Siel - Elyos [NA West]"   ← 服务区名（带 [大区] 后缀）
      · offer_group          = "/lgc_37781_dropdown_11_64650"  ← 服务区卡片 ID（分区用）
      · total_offer / min_qty / available_qty 等库存字段

## 覆盖度（2026-10-01 实测）

    US   → 10 区（NA West / NA East 各 5）    全 100 条，每区都拿到最低价
    EU   → 14 区                               全 100 条
    Asia →  3 区（Siel / Israphel / Main）      全 100 条
    SAM  →  4 区（Latin）                       全 100 条
    ⇒ 合计 31 区。AION2 需要 34 区，缺的 3 区（Asia Nezekan/Zikel、EU Ariel/Azphel）
      由上层「同大区均价兜底」处理，本模块只负责「抓到的如实返回，没抓到的不编」。

## 汇率 / 国家

`country=US&currency=USD` 拿到的是**美元**单价，与 IGGM/ELD/我方前台同币种，
不需要再折算。G2G 对同一 offer 会给不同国家不同价（`display_to` / `supported_countries`），
本项目统一用 US（北美受众口径）。
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

SEARCH_URL = "https://sls.g2g.com/v3/offer/search"
SEO_TERM = "aion-2-kinah"
CATEGORY_URL = "https://www.g2g.com/categories/aion-2-kinah"

# G2G 大区 region_id（2026-10-01 实测；KR/TW 未被本项目使用，先不列）
REGIONS = {
    "US":   "dfced32f-2f0a-4df5-a218-1e068cfadffa",   # 显示为 [NA West] / [NA East]
    "EU":   "ac3f85c1-7562-437e-b125-e89576b9a38e",   # [EU]
    "Asia": "7d971a93-e541-4055-8fcd-eb942b65701a",   # [Asia]
    "SAM":  "5b2d2761-128d-4185-9f42-6c502df03516",   # [Latin]
    # 备用（本项目暂不用）：
    # "KR": "34571f6d-f812-45e1-b446-cf753e44f79b",
    # "TW": "9820a142-1bc7-4ebe-9997-4e2dc7385879",
}

# G2G 的 [大区] 后缀 → 本项目大区名（与 config 里的「大区」字段对齐）
TAG_TO_REGION = {
    "NA West": "NA West",
    "NA East": "NA East",
    "EU": "EU",
    "Asia": "Asia",
    "Latin": "South America",
    "South America": "South America",
}


def _f(v):
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _get(url, timeout=30, retry=3, log=None):
    """带重试的 GET，返回解析后的 JSON dict。"""
    last = None
    for i in range(max(1, retry)):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": CATEGORY_URL,
                "Origin": "https://www.g2g.com",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:                    # noqa: BLE001
            last = e
            if log:
                log("  [G2G] 第 %d 次请求失败：%r" % (i + 1, e))
            time.sleep(1.5 * (i + 1))
    raise last


def offer_search(region_id, page=1, page_size=100, sort="lowest_price",
                 group=0, country="US", currency="USD",
                 seo_term=SEO_TERM, timeout=30, retry=3, log=None):
    """打一次 G2G 官方搜索接口，返回 payload.results[]（原样，不加工）。"""
    q = urllib.parse.urlencode({
        "seo_term": seo_term,
        "region_id": region_id,
        "country": country,
        "currency": currency,
        "page_size": page_size,
        "page": page,
        "sort": sort,
        "group": group,
        "v": "v2",
    })
    d = _get("%s?%s" % (SEARCH_URL, q), timeout=timeout, retry=retry, log=log)
    if not isinstance(d, dict) or d.get("code") != 2000:
        raise RuntimeError("G2G 接口返回异常：%s" % json.dumps(d, ensure_ascii=False)[:300])
    return ((d.get("payload") or {}).get("results")) or []


# 库存有效性闸门：报价必须**真的买得到**才算数。
# 2026-10-01 实测依据（Aion2 Kinah 全 4 大区扫一遍，只有 2 个区受影响）：
#   · EU Marchutan - Asmodian：SansGoldenV 挂 $6.99/K 但 available_qty=2、orders=0、rating=0
#     （其余 1 家 cheapold 挂 $7.25、库存 9999999）⇒ 6.99 是「库存 2 Mil 的占位低价」，
#     客户根本买不到量，拿它当基准价会让整个 EU 目标价被压低 3.6%。
#   · Asia Siel - Elyos：$7.1047 那条 available_qty=98，同理。
# ⇒ 规则：`available_qty >= max(min_qty, 1000)` 才参与「最低价」计算。
#   （1000 Mil = 1 Mil Kinah × 1000，Aion2 的正常起售量就是 1000；实测各区正常卖家
#     库存是 8.9 万 ~ 10 亿，门槛 1000 只剔真·占位单，不碰正常低价竞争。）
_MIN_QTY_FLOOR = 1000


def _median(vals):
    s = sorted(vals)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _group_key(x):
    """服务区卡片 ID：offer_group 末段（如 lgc_37781_dropdown_11_64650）。"""
    og = (x.get("offer_group") or "").rstrip("/")
    return og.split("/")[-1] if og else ""


def _server_name(title):
    """'Siel - Elyos [NA West]' → ('Siel - Elyos', 'NA West')。"""
    t = (title or "").strip()
    tag = ""
    if t.endswith("]"):
        i = t.rfind("[")
        if i >= 0:
            tag = t[i + 1:-1].strip()
            t = t[:i].strip()
    return t, tag


def scrape_region(region_name, region_id=None, pages=1, log=None, **kw):
    """抓一个 G2G 大区，返回 {服务区卡片ID: {...}}。

    每项：
      key / 服务区 / 大区 / 最低价 / 卖家数 / 单价集合 / 是否含 Elyos|Asmodian

    ⚠ `sort=lowest_price` 是**全局**升序，所以 page 1（100 条）就含每区最低价；
      本函数默认只抓 1 页（够用且省请求）。要更全可传 pages=2/3，
      但**最低价不会变**（越往后越贵），只是卖家数更完整。
    """
    rid = region_id or REGIONS.get(region_name)
    if not rid:
        raise KeyError("未知 G2G 大区：%s（可选 %s）" % (region_name, list(REGIONS)))
    rows = []
    for p in range(1, max(1, pages) + 1):
        got = offer_search(rid, page=p, log=log, **kw)
        rows.extend(got)
        if len(got) < 100:
            break
        time.sleep(0.6)
    out = {}
    for x in rows:
        k = _group_key(x)
        if not k:
            continue
        title = (x.get("title") or "").strip()
        name, tag = _server_name(title)
        up = _f(x.get("converted_unit_price"))
        rec = out.setdefault(k, {
            "key": k, "服务区": name, "G2G大区": tag,
            "大区": TAG_TO_REGION.get(tag, tag),
            "最低价": None, "卖家数": 0, "单价集合": [],
            "可用卖家数": 0, "剔除库存不足": [],
            "unit_name": x.get("unit_name"), "title原样": title,
        })
        rec["卖家数"] += 1
        if up is not None:
            # 库存有效才算候选（见模块顶部 _MIN_QTY_FLOOR 注释）
            _mq = x.get("min_qty") or 1
            _av = x.get("available_qty") or 0
            if _av >= max(_mq, _MIN_QTY_FLOOR):
                rec["单价集合"].append(round(up, 6))
                rec["可用卖家数"] += 1
                if rec["最低价"] is None or up < rec["最低价"]:
                    rec["最低价"] = round(up, 6)
            else:
                rec["剔除库存不足"].append({
                    "价": round(up, 6), "库存": _av, "起售": _mq,
                    "卖家": x.get("username"), "成交数": x.get("total_completed_orders")})
        if not rec.get("服务区") and name:
            rec["服务区"] = name
    # 离群保护（第二道闸）：低于「该区多数派中位数 × 0.5」的报价判为脏数据。
    # 与 core_eld 同一口径，见那边注释（2026-10-01 ELD Vaizel 实测 $1.7 vs 多数派 $14.9）。
    for rec in out.values():
        vals = sorted(set(rec["单价集合"]))
        med = _median(vals)
        if med and len(vals) >= 3:
            keep = [v for v in vals if v >= med * 0.5]
            drop = [v for v in vals if v < med * 0.5]
            rec["剔除离群"] = drop
            rec["中位价"] = round(med, 6)
            rec["最低价"] = keep[0] if keep else None
            rec["单价集合"] = keep
        else:
            rec["单价集合"] = vals
    return out


def scrape_all(region_names=None, pages=1, log=None, **kw):
    """抓多个大区 → {大区: {卡片ID: {...}}}，并顺带返回一张扁平索引。

    返回 (by_region, flat)：
      by_region = {"US": {卡片ID: rec}, ...}
      flat      = {"NA West|Siel - Elyos": rec, ...}   ← 按「大区|服务区」索引，给上层配表用
    """
    names = region_names or ["US", "EU", "Asia", "SAM"]
    by_region, flat = {}, {}
    for rn in names:
        try:
            got = scrape_region(rn, pages=pages, log=log, **kw)
            by_region[rn] = got
            if log:
                log("  [G2G] %-5s 抓到 %d 个服务区：%s" % (
                    rn, len(got),
                    "、".join("%s %s" % (v["服务区"], v["最低价"]) for v in
                              sorted(got.values(), key=lambda z: (z["最低价"] is None, z["最低价"])))))
            for v in got.values():
                flat["%s|%s" % (v.get("大区") or rn, v["服务区"])] = v
        except Exception as e:                    # noqa: BLE001
            if log:
                log("  [G2G] %s 抓取失败：%r" % (rn, e))
            by_region[rn] = {}
        time.sleep(0.6)
    return by_region, flat


# ═══════════════════════════════════════════════════════════════════════════
# 子服务器级抓取：cheapold 跟价（2026-10-05 新增）
# ───────────────────────────────────────────────────────────────────────────
# 需求（用户 2026-10-05 定案，口径 A：**永远优先 cheapold**）：
#   进 G2G 每个子服务器（金币购买页）→
#     · 若 Other Sellers 里有卖家名叫 cheapold  ⇒ 基准 = cheapold 价
#     · 没有 cheapold                          ⇒ 基准 = min(推荐第1位, 推荐第2位)
#   目标前端每M = 基准 × (1 − 下浮比例)          （默认下浮 3%）
#
# ⚠ 与上面 scrape_region 的区别：
#   · scrape_region 抓「整个大区、按最低价排序」，是旧 multisrc 口径；
#   · 本段抓「单个子服务器、按 G2G 页面默认 == 推荐(Recommended)排序」，
#     才能拿到用户说的「推荐第 1 / 第 2 位」，也能在同一份返回里找到 cheapold。
#     filter_attr = <collection_id>:<dataset_id>（如 lgc_37781_dropdown_12:…_64642）。
#   · collection_id 可由 dataset_id 反推：lgc_37781_dropdown_12_64642 → lgc_37781_dropdown_12。
#
# 字段依据（2026-10-05 服务器/本机实测）：
#   · converted_unit_price = 每 1M 的美元价（就是本项目口径）。
#   · min_qty = 起售份数（cheapold 常见 5，即「5M 起售」，**不是** 5M 总价！）。
#   · username = 卖家名；结果顺序 = 推荐序（默认 sort = recommended_v4）。
#   ⚠ 实测：cheapold 并非总是最便宜（NA East 上 cheapold $8.99 而 CNLTeam $2.96）。
#     用户明确要求「永远优先跟进 cheapold」，故这里**不做「取更低者」的兜底**。
CHEAPOLD_NAME = "cheapold"
ALL_SORT = "recommended_v4"

# config 的「大区」字段 → G2G region_id（[NA West]/[NA East] 同属 US 大区）
AREA_TO_RID = {
    "US": REGIONS["US"], "NA West": REGIONS["US"], "NA East": REGIONS["US"],
    "EU": REGIONS["EU"],
    "Asia": REGIONS["Asia"],
    "SAM": REGIONS["SAM"], "Latin": REGIONS["SAM"], "South America": REGIONS["SAM"],
}


def dataset_collection(ds):
    """从 dataset_id 反推 collection_id（末段数字去掉）。"""
    ds = (ds or "").strip()
    return ds.rsplit("_", 1)[0] if "_" in ds else ""


def scrape_offers(ds, area, page_size=100, sort=ALL_SORT,
                  timeout=30, retry=3, log=None):
    """按**单个子服务器**抓全部卖家报价（推荐序），返回 payload.results[] 原样。

    ds   = dataset_id（如 lgc_37781_dropdown_12_64642）
    area = config 的大区名（EU / NA West / NA East / South America / Asia）
    """
    coll = dataset_collection(ds)
    rid = AREA_TO_RID.get(str(area or "").strip())
    if not coll or not rid:
        raise KeyError("无法解析 G2G 入口：ds=%r area=%r" % (ds, area))
    q = urllib.parse.urlencode({
        "seo_term": SEO_TERM,
        "region_id": rid,
        "country": "US",
        "currency": "USD",
        "page_size": page_size,
        "page": 1,
        "sort": sort,
        "group": 0,
        "v": "v2",
        "filter_attr": "%s:%s" % (coll, ds),
    })
    d = _get("%s?%s" % (SEARCH_URL, q), timeout=timeout, retry=retry, log=log)
    if not isinstance(d, dict) or d.get("code") != 2000:
        raise RuntimeError("G2G 接口返回异常：%s" % json.dumps(d, ensure_ascii=False)[:300])
    return ((d.get("payload") or {}).get("results")) or []


def cheapold_base(ds, area, name=CHEAPOLD_NAME, log=None, **kw):
    """按「cheapold 优先」口径算某子服务器的基准价。

    返回 dict：
      base   基准价（$/M）；无报价/失败 → None
      src    'cheapold' | '推荐前二' | None
      who    取价卖家名
      cheapold / t1 / t1_u / t2 / t2_u / n
    """
    offers = scrape_offers(ds, area, log=log, **kw)
    pair = []                                   # 推荐序前两位（有价才收）
    for o in offers[:2]:
        p = _f(o.get("converted_unit_price"))
        if p is not None:
            pair.append((p, o.get("username")))
    ch = None
    for o in offers:
        if str(o.get("username") or "").strip().lower() == str(name).strip().lower():
            ch = _f(o.get("converted_unit_price"))
            break
    rec = {"n": len(offers), "cheapold": ch,
           "t1": pair[0][0] if len(pair) > 0 else None,
           "t1_u": pair[0][1] if len(pair) > 0 else None,
           "t2": pair[1][0] if len(pair) > 1 else None,
           "t2_u": pair[1][1] if len(pair) > 1 else None,
           "base": None, "src": None, "who": None}
    if ch is not None:
        rec.update({"base": ch, "src": "cheapold", "who": str(name)})
    elif pair:
        b, w = min(pair, key=lambda x: x[0])
        rec.update({"base": b, "src": "推荐前二", "who": w})
    return rec


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="G2G Aion2 Kinah 竞品价抓取（只读）")
    ap.add_argument("--regions", default="US,EU,Asia,SAM")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--out")
    a = ap.parse_args()
    _b, _flat = scrape_all(a.regions.split(","), pages=a.pages, log=print)
    print("=" * 120)
    for k in sorted(_flat, key=lambda s: (s.split("|")[0], _flat[s]["最低价"] or 9e9)):
        r = _flat[k]
        print("%-14s %-24s 最低 %8s  卖家 %3d  单价集合 %s"
              % (r.get("大区"), r["服务区"], r["最低价"], r["卖家数"],
                 r["单价集合"][:6]))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump({"by_region": _b, "flat": _flat}, f, ensure_ascii=False, indent=1)
        print("\n已存：%s（%d 区）" % (a.out, len(_flat)))
