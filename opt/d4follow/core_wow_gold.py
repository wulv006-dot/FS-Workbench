# -*- coding: utf-8 -*-
"""WoW Forever (gid1364) cost collection and backend integration.

2026-11-08: DD373 and Bijiaqi SELL offers collected in the same round.
All valid offers contribute inventory; 150G/50G bands use 25%/30%/35%.
IGGM remains removed. Unknown freezes; zero supply keeps the prior fallback.
Hardcore follows DD373 when the zone exists. Backend cost is synthetic: target price times
FX times (1-backend row margin); true procurement costs live in the ledger.
See core_wow_sources.py for availability, unit, stock and pricing rules.
"""
import gzip
import json
import os
import re
import ssl
import time
import urllib.request
import core_wow_sources as WS

DD_BASE = "https://www.dd373.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "wow_gold_config.json")

DEFAULTS = {
    "目标金": 21.0, "跳过最低条数": 0,
    "常规利润率": 0.25, "薄区利润率": 0.30, "稀缺利润率": 0.35, "兜底价USD": 7.99,
    "低价最小库存金": 20.0, "成本采样金": 150.0, "报价最长时效秒": 1200,
    "后台利润率": 0.20, "写入口径": "cost",
}

TYPE_MAP = {
    "PVE": "NORMAL", "Normal": "NORMAL",
    "PVP": "PVP",
    "角色扮演": "RP", "RP": "RP", "Roleplay": "RP",
    "角色扮演PVP": "RP_PVP", "Roleplay PVP": "RP_PVP", "Roleplay-PVP": "RP_PVP",
    "硬核": "HC", "Hardcore": "HC",
}
FACTION_MAP = {"联盟": "A", "部落": "H", "Alliance": "A", "Horde": "H"}
REGIONS = {"亚服", "美服", "欧服", "韩服"}


def load_cfg(path=CFG_PATH):
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    p = dict(DEFAULTS)
    p.update(c.get("参数") or {})
    c["参数"] = p
    return c


# ---------------------------------------------------------------- DD373
def dd_fetch(path, retry=3, timeout=25):
    url = path if path.startswith("http") else DD_BASE + path
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": DD_BASE + "/s-vvenrt-c-4sbptc.html",
            })
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", "ignore")
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError("DD373 抓取失败 %s: %r" % (url, last))


# ---------------------------------------------------------------- DD373 官方接口
# 【2026-11-07 老板定案：「能改接口就都改接口」】魔兽专区从「抓 HTML 页面」改为
#   ① 区服树：GameOther/List?parentId=<父Id> 三层（区 → 类型 → 阵营），
#      5 次请求拿全 40 个叶子，每个叶子自带 GUID；HTML 抓法退为回落。
#   ② 订单簿：ApiGetShopList?GameId&GameOtherId=<类型Id_阵营Id>&GameShopTypeId，
#      单区最多 **30 条**（HTML 一页只有 20 条 ⇒ 接口能多看见 10 条挂单）。
#   收益（实测）：单请求 ~2KB vs HTML ~130KB；不会返回滑块页（会明确报错码）。
# ⚠ 接口层异常（网络 / 非 JSON / StatusCode≠0）一律抛 RuntimeError ⇒ 调用方回落 HTML。
#   **绝不能把「接口挂了」当成「该区没货」** —— 那会把整批区打成 $7.99 兜底。
API_LIST = "https://game.dd373.com/Api/GameOther/List"
API_SHOP = "https://goods.dd373.com/Api/Goods/UserCenter/ApiGetShopList"
WOW_GAME_GUID = "e2daade609d9443aa1da2c91901d1ed7"   # 魔兽世界：无限
WOW_GOLD_GUID = "38d72051a90e4d8daa029ecd7f7312da"   # 商品类型 = 游戏币
WOW_ENTRY = "/s-vvenrt-c-4sbptc.html"
API_ROWS = 30          # 硬上限：分页参数被忽略，30 条就是能拿到的最多量


def _api_get(url, retry=2, timeout=25):
    """取 JSON 接口。非 JSON（ESA 滑块页）一律抛错，由调用方判「接口不可用」。"""
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": DD_BASE + WOW_ENTRY,
            })
            with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
                raw = r.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            txt = raw.decode("utf-8", "ignore")
            try:
                return json.loads(txt)
            except Exception:                       # noqa: BLE001
                raise RuntimeError("接口返回非 JSON（疑似风控滑块页）：%r" % txt[:80])
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1.0 * (i + 1))
    raise RuntimeError("DD373 接口失败 %s: %r" % (url, last))


def _api_list(parent_id):
    """区服树一层。返回 list[dict]，每项含 Name / Identify / Id。"""
    j = _api_get("%s?parentId=%s" % (API_LIST, parent_id))
    if str(j.get("StatusCode")) != "0":
        raise RuntimeError("区服树 StatusCode=%s %s" % (j.get("StatusCode"),
                                                       j.get("StatusMsg")))
    rd = (j.get("StatusData") or {}).get("ResultData")
    if isinstance(rd, dict):
        for _k, v in rd.items():
            if isinstance(v, list):
                return v
        return []
    return rd if isinstance(rd, list) else []


def dd_api_tree(log=print):
    """走接口建区服树：{(区, 类型, 阵营): {'href','label','type_id','zone_id','api'}}。

    只收 亚/美/欧/韩（国服后台没有对应行，抓了也没用）。
    href 用 Identify 段名拼，仅供回落 HTML 时使用。
    """
    tree = {}
    areas = _api_list(WOW_GAME_GUID)
    for a in areas:
        aname = a.get("Name")
        if aname not in REGIONS:
            continue
        for tp in _api_list(a["Id"]):
            tkey = TYPE_MAP.get(tp.get("Name"))
            if not tkey:
                continue
            for fac in _api_list(tp["Id"]):
                fkey = FACTION_MAP.get(fac.get("Name"))
                if not fkey:
                    continue
                tree[(aname, tkey, fkey)] = {
                    "href": "/s-vvenrt-c-4sbptc-%s-%s-%s.html"
                            % (a.get("Identify"), tp.get("Identify"),
                               fac.get("Identify")),
                    "label": "%s/%s/%s" % (aname, tp.get("Name"), fac.get("Name")),
                    "type_id": tp["Id"], "zone_id": fac["Id"], "api": True}
    log("  [DD373·接口] 区服树 %d 个叶子（1+%d+%d 次请求，落盘缓存 7 天）"
        % (len(tree), len(REGIONS), len(tree) // 2))
    return tree


def dd_api_items(type_id, zone_id, target_gold=150):
    """取一个叶子区的订单簿（最多 30 条），转成与 HTML 解析一致的 items。

    ⚠ 字段口径（与 AION2 同一个坑，已踩过）：
      **可买量 = amount × number**（number = 发布件数，amount 只是单件数量）。
      `singleprice` 就是**元/金**，与 HTML 的「1 金 = X 元」同口径，不用换算。
    """
    import urllib.parse as _up
    url = "%s?%s" % (API_SHOP, _up.urlencode({
        "GameId": WOW_GAME_GUID,
        "GameOtherId": "%s_%s" % (type_id, zone_id),
        "GameShopTypeId": WOW_GOLD_GUID}))
    j = _api_get(url)
    st = j.get("StatusData") or {}
    if str(j.get("StatusCode")) != "0" or str(st.get("ResultCode")) != "0":
        raise RuntimeError("订单簿 Status=%s/%s %s"
                           % (j.get("StatusCode"), st.get("ResultCode"),
                              st.get("ResultMsg") or j.get("StatusMsg")))
    rows = st.get("ResultData")
    if not isinstance(rows, list):
        rows = []
    out = []
    for r in rows:
        try:
            amount = float(r.get("amount") or 0)
            number = float(r.get("number") or 1)
            price = float(r.get("singleprice") or 0)
        except Exception:                           # noqa: BLE001
            continue
        if amount <= 0 or price <= 0:
            continue
        # 「万金」单位的商家要折回「金」，否则一条就能把均价拉低 1 万倍
        if "万" in str(r.get("unit") or ""):
            amount *= 10000.0
        out.append({"region": "", "type_raw": "", "faction_raw": "",
                    "unit_rmb": price,
                    "stock": amount * number,
                    "min_qty": amount, "step_qty": amount,
                    "offer_id": str(r.get("shopno") or (r.get("id") if str(r.get("id")) not in ("0", "None") else "") or ""),
                    "title": r.get("title") or ""})
    if rows and not out:
        raise RuntimeError('DD373 invalid offers; incomplete order book')
    if len(rows) >= 30:
        if sum(o['stock'] for o in out) < target_gold:
            raise RuntimeError("DD373 endpoint cap reached; incomplete order book")
        if any(a['unit_rmb'] > b['unit_rmb'] for a,b in zip(out,out[1:])):
            raise RuntimeError("DD373 capped order book is not price-sorted; incomplete order book")
    for o in out: o['book_truncated'] = len(rows) >= 30
    return out


def _anchors(html, marker, span=900):
    i = html.find(marker)
    if i < 0:
        return []
    out = []
    for m in re.finditer(r'<a([^>]*)href="([^"]*)"[^>]*>([^<]*)</a>', html[i:i + span]):
        attrs, href, txt = m.group(1), m.group(2), m.group(3).strip()
        cm = re.search(r'class="([^"]*)"', attrs)
        out.append((cm.group(1) if cm else "", href, txt))
    return out


def dd_discover(log=print):
    """{(区, 类型, 阵营): {'href','label'}}（HC 也会返回，由调用方跳过）"""
    home = dd_fetch("/s-vvenrt-c-4sbptc.html")
    tree = {}
    for _c, rhref, rname in _anchors(home, "游戏区："):
        if rname not in REGIONS:
            continue
        page = dd_fetch(rhref)
        for _c2, thref, tname in _anchors(page, "游戏服："):
            tkey = TYPE_MAP.get(tname)
            if not tkey:
                continue
            tpage = dd_fetch(thref)
            for _c3, fhref, fname in _anchors(tpage, "阵营：", span=700):
                if fname not in FACTION_MAP:
                    continue
                tree[(rname, tkey, FACTION_MAP[fname])] = {
                    "href": fhref, "label": "%s/%s/%s" % (rname, tname, fname)}
            time.sleep(0.5)
        time.sleep(0.4)
    return tree


def dd_parse_items(html):
    out = []
    for b in html.split("goods-list-item")[1:]:
        b = re.sub(r"<script[\s\S]*?</script>", " ", b)
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", b))
        qf = re.search(r"区服：\s*([^型]{1,60}?)\s*类型：", txt)
        up = re.search(r"1\s*金\s*=\s*([\d.]+)\s*元", txt)
        if not (qf and up):
            continue
        segs = [x.strip() for x in qf.group(1).split("/") if x.strip()]
        st = re.search(r"库存：\s*([\d.]+)\s*金", txt)
        mn = re.search(r"起售：\s*([\d.]+)\s*金", txt)
        out.append({"region": segs[0] if segs else "",
                    "type_raw": segs[1] if len(segs) > 1 else "",
                    "faction_raw": segs[2] if len(segs) > 2 else "",
                    "unit_rmb": float(up.group(1)),
                    "stock": float(st.group(1)) if st else 0.0,
                    "min_qty": float(mn.group(1)) if mn else None,
                    "offer_id": (re.search(r"shopNumber=([A-Za-z0-9-]+)", b).group(1) if re.search(r"shopNumber=([A-Za-z0-9-]+)", b) else None)})
    return out


def dd_html_items_all(href):
    """Read every public result page when the API hits its 30-offer cap."""
    import html as html_lib
    out, seen_urls, seen_ids = [], set(), set()
    expected_pages = None
    current = href
    for page_no in range(1, 101):
        if current in seen_urls: raise RuntimeError('DD373 repeated pagination URL')
        seen_urls.add(current)
        html = dd_fetch(current)
        m = re.search(r'class="[^"]*max-number[^"]*">\s*(\d+)',html)
        count = int(m.group(1)) if m else 1
        if expected_pages is None: expected_pages=count
        if count != expected_pages: raise RuntimeError('DD373 pagination total changed')
        offers = dd_parse_items(html)
        if not offers: raise RuntimeError('DD373 HTML contains no verified offers')
        for offer in offers:
            ident=offer.get('offer_id')
            if not ident: raise RuntimeError('DD373 HTML missing offer identity')
            if ident in seen_ids: raise RuntimeError('DD373 offers shifted across pages')
            seen_ids.add(ident);out.append(offer)
        links=[html_lib.unescape(url) for url,body in re.findall(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>',html,re.S) if '下一页' in re.sub(r'<[^>]+>','',body)]
        if page_no==expected_pages:
            if links: raise RuntimeError('DD373 unexpected extra page')
            return out
        if len(links)!=1: raise RuntimeError('DD373 incomplete pagination')
        current=links[0]
        if not current.startswith('/s-'): raise RuntimeError('DD373 unexpected page destination')
        time.sleep(.35)
    raise RuntimeError('DD373 pagination safety limit exceeded')


TREE_CACHE = os.path.join(HERE, "data", "wow_dd_tree.json")


def _load_tree_cache(max_age_d=7, log=print):
    import datetime as _dt
    try:
        doc = json.load(open(TREE_CACHE, encoding="utf-8"))
        age = (_dt.datetime.now()
               - _dt.datetime.fromisoformat(doc.get("ts"))).total_seconds() / 86400.0
        if age > max_age_d:
            return None
        tree = {(k[0], k[1], k[2]): v for k, v in
                ((tuple(x.split("|")), v) for x, v in doc["tree"].items())}
        log("  [DD373] 用区服树缓存（%d 个叶子页，%.1f 天前）" % (len(tree), age))
        return tree
    except Exception:                               # noqa: BLE001
        return None


def _save_tree_cache(tree):
    try:
        os.makedirs(os.path.dirname(TREE_CACHE), exist_ok=True)
        import datetime as _dt
        json.dump({"ts": _dt.datetime.now().isoformat(timespec="seconds"),
                   "tree": {"%s|%s|%s" % k: v for k, v in tree.items()}},
                  open(TREE_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception:                               # noqa: BLE001
        pass


def dd_crawl(log=print, skip_hc=True, refresh_tree=False, source="auto", parameters=None):
    """抓全部叶子区。source: auto（接口优先、失败回落 HTML）/ api / html。

    返回 {(区,类型,阵营): {'href','label','items',...,'source','error'}}
    """
    tree = (None if refresh_tree else _load_tree_cache(log=log))
    # 旧缓存（HTML 抓的）没有 type_id ⇒ 走不了接口，重建一次
    if tree and not any(v.get("type_id") for v in tree.values()):
        log("  [DD373] 旧版区服树缓存（无 GUID）⇒ 重建")
        tree = None
    if not tree:
        tree = None
        if source in ("auto", "api"):
            try:
                tree = dd_api_tree(log=log)
            except Exception as e:                  # noqa: BLE001
                log("  [DD373·接口] 区服树失败 %r ⇒ 回落 HTML 建树" % e)
        if not tree:
            tree = dd_discover(log=log)
        _save_tree_cache(tree)

    pages = {}
    api_ok = api_fail = 0
    api_broken = False          # 连续失败熔断：别拿 40 个叶子逐个撞墙
    for key, meta in tree.items():
        if skip_hc and key[1] == "HC":
            continue
        items, src, err = None, None, None
        if meta.get("type_id") and source in ("auto", "api") and not api_broken:
            try:
                items = dd_api_items(meta["type_id"], meta["zone_id"],
                                     float((parameters or {}).get('成本采样金',150)))
                src = "api"
                api_ok += 1
            except Exception as e:                  # noqa: BLE001
                if 'incomplete order book' in str(e):
                    # Public pagination is currently gated by a human verification page.
                    # Do not retry that challenge or treat truncated inventory as complete.
                    items, src, err = [], 'api_incomplete', str(e)
                api_fail += 1
                log("  [DD373·接口] %-22s ✗ %r" % (meta["label"], e))
                if api_ok == 0 and api_fail >= 5:
                    api_broken = True
                    log("  [DD373·接口] 连续 %d 次失败且无一次成功 ⇒ 本轮整体回落 HTML"
                        % api_fail)
        if items is None and source in ("auto", "html"):
            try:
                items = dd_html_items_all(meta["href"])
                src = "html"
            except Exception as e:                  # noqa: BLE001
                items, err = [], repr(e)
                log("  [DD373] %-22s ✗ %r" % (meta["label"], e))
        if items is None:
            items, src = [], (src or "none")
        items.sort(key=lambda x: x["unit_rmb"])
        pages[key] = dict(meta, items=items, source=src, captured_at=time.time(),
                          inventory_complete=not any(o.get("book_truncated", False) for o in items),
                          error=(err if not items else None))
        log("  [DD373·%s] %-22s %2d 条 最低 %.4f 元/金 可买 %.0f 金"
            % (src, meta["label"], len(items),
               items[0]["unit_rmb"] if items else 0,
               sum(i["stock"] for i in items)))
        time.sleep(0.35 if src == "api" else 0.9)
    log("  [DD373] 本轮来源：接口 %d 区 / HTML 回落 %d 区%s"
        % (api_ok, sum(1 for p in pages.values() if p.get("source") == "html"),
           "（接口已熔断）" if api_broken else ""))
    return pages


# 2026-11-10 老板定案：IGGM 抓取 / 锚定 / Decodo 兜底整段移除（168 行）。


# ---------------------------------------------------------------- 定价
def price_zone(items, p, fx):
    """Compatibility single-source calculator using the current margin contract."""
    return WS.price_pair({'items': items, 'captured_at': time.time()}, None, p, fx)


def write_cost_for(b2c, p, fx):
    """把目标 b2c 反推成「写进后台的采购成本」"""
    if p.get("写入口径") == "margin":
        return None
    return round(b2c * fx * (1 - float(p["后台利润率"])), 6)


def build_plan(backend_rows, pages, cfg, fx, log=print, bjq_pages=None):
    p = cfg["参数"]
    zone_meta = {(z["区"], z["类型"], z["阵营"]): z for z in cfg.get("区服", [])}
    hold_band = float(p.get("变动闸百分比", 0.5)) / 100.0
    plan = []
    for r in backend_rows:
        key = (r["region"], r["type"], r["faction"])
        zmeta = zone_meta.get(key) or {}
        pg = pages.get(key)
        # 2026-11-10 WB：内测期「HC 一律跳过」的老逻辑作废。公测后韩服已开硬核，
        #   DD373 有该叶子就正常跟价；DD373 没有该区（美/欧/亚 HC）才跳过。
        if r["type"] == "HC" and not pg:
            res = {"mode": "Hardcore未开放(跳过)", "margin": None, "avg_rmb": None,
                   "cost_usd": None, "iggm": None, "b2c": r.get("b2c"),
                   "gold_used": 0.0, "n_items": 0, "n_used": 0, "avail_gold": 0.0,
                   "note": "", "base_price": None, "rule": ""}
        else:
            res = WS.price_pair(pg, (bjq_pages or {}).get(key), p, fx)
        price_cap = float(p.get('最高售价USD每G', 1.60))
        res = WS.cap_price_result(res, r.get('b2c'), price_cap)
        cap_required = (r.get('b2c') or 0) > price_cap and not res.get('cap_exempt')
        row_p = dict(p, 后台利润率=r.get("margin"))
        writable = ((zmeta.get("启用") is True or cap_required) and str(zmeta.get("后台行ID")) == str(r["id"])
                    and WS.number(r.get("margin")) is not None and 0 <= r["margin"] < 1)
        # 2026-11-10 WB：去掉「HC 永不出单」限制（DD373 有货才走到这里，无货 b2c 为空）。
        new_cost = (write_cost_for(res["b2c"], row_p, fx)
                    if res["b2c"] and writable else None)
        old_b2c = r.get("b2c")
        action = "hold"
        if res["mode"] not in ("Hardcore未开放(跳过)",) and new_cost is not None:
            current_margin = (1 - res["cost_usd"] / old_b2c
                              if old_b2c and res.get("cost_usd") else None)
            # 2026-11-10：毛利统一 30%，不再有区间闸；要不要改只看变动闸 hold_band。
            outside_margin = cap_required
            if old_b2c and abs(res["b2c"] / old_b2c - 1) < hold_band and not outside_margin:
                action = "hold"
            elif old_b2c and res["b2c"] > old_b2c:
                action = "follow_up"
            elif old_b2c:
                action = "follow_down"
            else:
                action = "follow_up"
        plan.append({
            "key": zmeta.get("key") or "WOWF_%s" % r["id"],
            "后台行ID": r["id"], "后台名": r["name"],
            "区": r["region"], "类型": r["type"], "阵营": r["faction"],
            "DD373": pg["label"] if pg else "",
            "DD373_url": (DD_BASE + pg["href"]) if pg else "",
            "现采购成本": r.get("cost"), "现b2c": old_b2c,
            "均价元每金": res["avg_rmb"], "可买金": res["avail_gold"],
            "用金": res["gold_used"], "挂单数": res["n_items"],
            "用单数": res["n_used"], "规则": res["mode"], "规则0": res.get("rule"),
            "成本价USD": res.get("cost_usd"), "IGGM": None, "IGGM倍数": None,
            "备注": res.get("note") or "",
            "双源价差": res.get("source_gap"), "双源差异告警": res.get("source_gap_alert", False),
            "成本来源": res.get("selected_source"), "双源报价": res.get("source_quotes", []),
            "毛利底价USD": res.get("floor_usd"), "毛利封顶价USD": res.get("ceiling_usd"),
            "后台计算利润率": r.get("margin"), "策略版本": WS.VERSION,
            "利润率": res["margin"], "目标b2c": res["b2c"],
            "双源无货": res.get("both_empty", False), "上限例外": res.get("cap_exempt", False),
            "售价上限": price_cap, "触发封顶": res.get("cap_applied", False), "封顶前目标": res.get("uncapped_b2c"), "原目标毛利": res.get("target_margin"),
            "建议采购成本": new_cost,
            "变动pct": (round((res["b2c"] / old_b2c - 1) * 100, 2)
                        if old_b2c and res["b2c"] else None),
            "动作": action,
        })
    return plan


# ---------------------------------------------------------------- 后台读行
def parse_backend_name(name):
    """'美服-Normal - Horde' / '亚服- Alliance-Hardcore' / '韩服-Roleplay-PVP - Alliance'"""
    s = (name or "").replace("－", "-").strip()
    region = None
    for rn in REGIONS:
        if s.startswith(rn):
            region = rn
            s = s[len(rn):]
            break
    region = region or "?"
    if re.search(r"Alliance", s, re.I):
        fac = "A"
    elif re.search(r"Horde", s, re.I):
        fac = "H"
    else:
        fac = "?"
    low = s.lower()
    if re.search(r"roleplay\s*[- ]?\s*pvp|rp\s*[- ]?pvp", low):
        t = "RP_PVP"
    elif re.search(r"roleplay|(?<![a-z])rp(?![a-z])", low):
        t = "RP"
    elif "hardcore" in low:
        t = "HC"
    elif "normal" in low or "pve" in low:
        t = "NORMAL"
    elif "pvp" in low:
        t = "PVP"
    else:
        t = "?"
    return region, t, fac


def read_backend_rows(client, cfg, log=print):
    """读「金币价格管理」页（gid=1364）的全部行：id / 区服名 / 采购成本 / 利润率 / b2c"""
    gid = str(cfg.get("gid") or "1364")
    html = client.request("/game/admin_game_price/index.html?gid=%s" % gid,
                          headers={"Accept": "text/html"})
    rows = []
    for t in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html)[1:]:
        m = re.search(r"<td>(\d+)</td>", t)
        if not m:
            continue
        rid = m.group(1)
        nm = re.search(r'<span><i class="fa fa-edit text-info"></i>\s*([^<]*)</span>', t)
        cost = re.search(r'jq_showprice_costprice_%s"><i[^>]*></i>\s*([\d.]+)' % rid, t)
        lr = re.search(r'jq_showprice_lirunlv_%s"><i[^>]*></i>\s*([\d.]+)' % rid, t)
        b2c = re.search(r'jq_showprice_b2c_%s"><i[^>]*></i>\s*([\d.]+)' % rid, t)
        region, tkey, fac = parse_backend_name(nm.group(1) if nm else "")
        rows.append({"id": rid, "name": (nm.group(1).strip() if nm else ""),
                     "region": region, "type": tkey, "faction": fac,
                     "cost": float(cost.group(1)) if cost else None,
                     "margin": float(lr.group(1)) if lr else None,
                     "b2c": float(b2c.group(1)) if b2c else None})
    log("  [后台] gid=%s 共 %d 行" % (gid, len(rows)))
    return rows










