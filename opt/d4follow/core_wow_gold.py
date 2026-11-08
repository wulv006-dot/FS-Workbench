# -*- coding: utf-8 -*-
"""WoW Forever (gid1364) cost collection and backend integration.

2026-11-08: DD373 and Bijiaqi SELL offers collected in the same round.
Only confirmed available cost batches >20G qualify. IGGM x1.03 is clamped
to 15%-30% procurement gross margin. Unknown/no supply freezes the row.
Hardcore remains untouched. Backend cost is synthetic: target price times
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
    "常规利润率": 0.30, "薄区利润率": 0.30, "兜底价USD": 7.99,
    "毛利率下限": 0.15, "毛利率上限": 0.30,
    "低价最小库存金": 20.0, "成本采样金": 21.0, "报价最长时效秒": 1200,
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


def dd_api_items(type_id, zone_id):
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
                    "offer_id": str(r.get("id") or r.get("Id") or ""),
                    "title": r.get("title") or ""})
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
                    "min_qty": float(mn.group(1)) if mn else None})
    return out


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


def dd_crawl(log=print, skip_hc=True, refresh_tree=False, source="auto"):
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
                items = dd_api_items(meta["type_id"], meta["zone_id"])
                src = "api"
                api_ok += 1
            except Exception as e:                  # noqa: BLE001
                api_fail += 1
                log("  [DD373·接口] %-22s ✗ %r" % (meta["label"], e))
                if api_ok == 0 and api_fail >= 5:
                    api_broken = True
                    log("  [DD373·接口] 连续 %d 次失败且无一次成功 ⇒ 本轮整体回落 HTML"
                        % api_fail)
        if items is None and source in ("auto", "html"):
            try:
                items = dd_parse_items(dd_fetch(meta["href"]))
                src = "html"
            except Exception as e:                  # noqa: BLE001
                items, err = [], repr(e)
                log("  [DD373] %-22s ✗ %r" % (meta["label"], e))
        if items is None:
            items, src = [], (src or "none")
        items.sort(key=lambda x: x["unit_rmb"])
        pages[key] = dict(meta, items=items, source=src, captured_at=time.time(),
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


# ---------------------------------------------------------------- IGGM 锚定
IGGM_FILE = os.path.join(HERE, "data", "wow_iggm.json")
IGGM_MAP = {("美服", "NORMAL", "A"): "US|Normal-Alliance",
            ("美服", "NORMAL", "H"): "US|Normal-Horde",
            ("美服", "PVP", "A"): "US|PVP-Alliance",
            ("美服", "PVP", "H"): "US|PVP-Horde",
            ("美服", "RP", "A"): "US|Roleplay-Alliance",
            ("美服", "RP", "H"): "US|Roleplay-Horde",
            ("美服", "RP_PVP", "A"): "US|RoleplayPvP-Alliance",
            ("美服", "RP_PVP", "H"): "US|RoleplayPvP-Horde",
            ("欧服", "NORMAL", "A"): "EU|Normal-Alliance",
            ("欧服", "NORMAL", "H"): "EU|Normal-Horde",
            ("欧服", "PVP", "A"): "EU|PVP-Alliance",
            ("欧服", "PVP", "H"): "EU|PVP-Horde",
            ("欧服", "RP", "A"): "EU|Roleplay-Alliance",
            ("欧服", "RP", "H"): "EU|Roleplay-Horde",
            ("欧服", "RP_PVP", "A"): "EU|RoleplayPvP-Alliance",
            ("欧服", "RP_PVP", "H"): "EU|RoleplayPvP-Horde"}

# ── IGGM 兜底通道：Decodo（原 Smartproxy）Web Data API（2026-11-07 接通）──────
# 背景：IGGM / U4GM 在 183 出口被 Cloudflare managed challenge 拦（机房 IP 被拉黑，
#   换 TLS 指纹无效，自建 CF Worker 反代也被 403）。实测 Decodo 免费档 /scrape
#   对 IGGM 金币页与 goods_ajax 均返回 200，16 区单价与本机住宅 IP 采集**逐项一致**。
# 触发：仅当 wow_iggm.json 缺失或超过 max_age_h 时才补采（每区 1 次请求），
#   失败后 30 分钟内不再重试，避免白烧额度、也不拖慢 10 分钟主循环。
IGGM_SID = {"US|Normal-Alliance": 29411, "US|Normal-Horde": 29413,
            "US|PVP-Alliance": 29415, "US|PVP-Horde": 29417,
            "US|Roleplay-Alliance": 29419, "US|Roleplay-Horde": 29421,
            "US|RoleplayPvP-Alliance": 29423, "US|RoleplayPvP-Horde": 29425,
            "EU|Normal-Alliance": 29427, "EU|Normal-Horde": 29429,
            "EU|PVP-Alliance": 29431, "EU|PVP-Horde": 29433,
            "EU|Roleplay-Alliance": 29435, "EU|Roleplay-Horde": 29437,
            "EU|RoleplayPvP-Alliance": 29439, "EU|RoleplayPvP-Horde": 29441}
DECODO_CONF = os.path.join(HERE, "data", "decodo.json")
_DECODO_FAIL = os.path.join(HERE, "data", "_iggm_decodo_fail.json")
IGGM_AJAX = ("https://www.iggm.com/goods/goods_ajax?template_type=golds"
             "&server_id=%s&cate_id=0&game_sku=wowforever74")


def _decodo_scrape(url, key, timeout=120):
    """经 Decodo Web Data API 取一个 URL 的正文（HTML 或 JSON 文本）。"""
    req = urllib.request.Request(
        "https://data.decodo.com/v1/scrape",
        data=json.dumps({"url": url, "headless": "html"}).encode("utf-8"),
        headers={"Authorization": "Bearer " + key,
                 "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        j = json.loads(r.read().decode("utf-8", "ignore"))
    return ((j.get("results") or [{}])[0].get("content") or "")


def fetch_iggm_decodo(path=None, log=print, sleep_s=0.4):
    """用 Decodo 直采 IGGM 16 区金币单价并写回 wow_iggm.json。返回成功区数。

    ⚠ 只在 load_iggm 判定「无数据 / 已过期」时调用；正常情况下本机每小时推送，
      这条通道不消耗额度。账单口径：每区 1 次请求，16 区 ≈ 16 次。
    """
    import datetime as _dt
    path = path or IGGM_FILE
    try:
        key = (json.load(open(DECODO_CONF, encoding="utf-8")) or {}).get("key")
    except Exception:                               # noqa: BLE001
        log("  [IGGM·Decodo] 未配置 data/decodo.json，跳过兜底")
        return 0
    if not key:
        return 0
    doc = {"_说明": "Decodo 直采（服务器侧兜底），单价 USD/G", "sku": "wowforever74",
           "src": "decodo", "ts": _dt.datetime.now().isoformat(timespec="seconds")}
    ok = 0
    for label, sid in IGGM_SID.items():
        try:
            j = json.loads(_decodo_scrape(IGGM_AJAX % sid, key))
            one = ((j.get("data") or {}).get("one_goods") or {})
            p = float(one.get("price") or 0)
            if p <= 0:
                raise RuntimeError("无报价")
            doc[label] = {"price_usd_per_g": p, "title": one.get("title"),
                          "sid": sid, "src": "decodo"}
            ok += 1
        except Exception as e:                      # noqa: BLE001
            log("  [IGGM·Decodo] %-26s ✗ %r" % (label, e))
        time.sleep(sleep_s)
    log("  [IGGM·Decodo] 补采成功 %d / %d 区" % (ok, len(IGGM_SID)))
    if ok >= 8:                                     # 半数以上成功才落盘，避免残缺表覆盖好数据
        os.makedirs(os.path.dirname(path), exist_ok=True)
        json.dump(doc, open(path, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        try:
            os.remove(_DECODO_FAIL)
        except OSError:
            pass
    else:
        try:
            json.dump({"ts": _dt.datetime.now().isoformat(timespec="seconds")},
                      open(_DECODO_FAIL, "w", encoding="utf-8"))
        except OSError:
            pass
    return ok


def _decodo_cooldown(minutes=30):
    """上次兜底失败且未过冷却期 ⇒ True（别每轮都去撞）。"""
    import datetime as _dt
    try:
        ts = json.load(open(_DECODO_FAIL, encoding="utf-8")).get("ts")
        age = (_dt.datetime.now() - _dt.datetime.fromisoformat(ts)).total_seconds()
        return age < minutes * 60
    except Exception:                               # noqa: BLE001
        return False


def load_iggm(path=None, max_age_h=12, log=print):
    """读 IGGM 单价表；缺失或过期且开了兜底时，用 Decodo 补采一次再读。

    为什么会过期：本机每小时推一次，本机长期关机/自动化停摆后文件就不动了。
    过期数据不用（避免拿隔夜竞品价定今天的价），改由 Decodo 服务器侧直采。
    """
    import datetime as _dt
    path = path or IGGM_FILE

    def _age_of(doc):
        try:
            return (_dt.datetime.now()
                    - _dt.datetime.fromisoformat(doc.get("ts"))).total_seconds() / 3600.0
        except Exception:                           # noqa: BLE001
            return None

    doc, stale = None, False
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except Exception as e:                          # noqa: BLE001
        log("  [IGGM] 无数据文件（%s）" % e.__class__.__name__)
        stale = True
    if doc is not None:
        age = _age_of(doc)
        if age is not None and age > max_age_h:
            log("  [IGGM] 数据已 %.1f 小时（阈值 %.0f），先试兜底" % (age, max_age_h))
            stale = True

    if stale:
        mode = str((load_cfg().get("参数") or {}).get("IGGM兜底", "auto") or "auto")
        if mode == "off":
            log("  [IGGM] 兜底已关闭（参数.IGGM兜底=off），本轮不锚定")
            return {}, (doc or {}).get("ts")
        if _decodo_cooldown():
            log("  [IGGM] 兜底刚失败过，冷却中，本轮不锚定")
            return {}, (doc or {}).get("ts")
        n = fetch_iggm_decodo(path=path, log=log)
        if n:
            doc = json.load(open(path, encoding="utf-8"))
            stale = False

    if not doc or stale:
        return {}, (doc or {}).get("ts")

    out = {k: v["price_usd_per_g"] for k, v in doc.items()
           if isinstance(v, dict) and v.get("price_usd_per_g")}
    src = doc.get("src") or "local-push"
    log("  [IGGM] %d 个区可用（%s，采集于 %s，%.1f 小时前）"
        % (len(out), src, doc.get("ts"), _age_of(doc) or 0))
    return out, doc.get("ts")


# ---------------------------------------------------------------- 定价
def price_zone(items, p, fx, iggm_usd=None):
    """Compatibility single-source calculator using the current margin contract."""
    return WS.price_pair({'items': items, 'captured_at': time.time()}, None,
                         p, fx, iggm_usd=iggm_usd)


def write_cost_for(b2c, p, fx):
    """把目标 b2c 反推成「写进后台的采购成本」"""
    if p.get("写入口径") == "margin":
        return None
    return round(b2c * fx * (1 - float(p["后台利润率"])), 6)


def build_plan(backend_rows, pages, cfg, fx, iggm=None, log=print, bjq_pages=None):
    p = cfg["参数"]
    iggm = iggm or {}
    zone_meta = {(z["区"], z["类型"], z["阵营"]): z for z in cfg.get("区服", [])}
    hold_band = float(p.get("变动闸百分比", 0.5)) / 100.0
    plan = []
    for r in backend_rows:
        key = (r["region"], r["type"], r["faction"])
        zmeta = zone_meta.get(key) or {}
        pg = pages.get(key)
        ig_key = IGGM_MAP.get(key)
        iggm_usd = iggm.get(ig_key) if ig_key else None
        if r["type"] == "HC":
            res = {"mode": "Hardcore未开放(跳过)", "margin": None, "avg_rmb": None,
                   "cost_usd": None, "iggm": iggm_usd, "b2c": r.get("b2c"),
                   "gold_used": 0.0, "n_items": 0, "n_used": 0, "avail_gold": 0.0,
                   "note": "", "base_price": None, "rule": ""}
        else:
            res = WS.price_pair(pg, (bjq_pages or {}).get(key), p, fx, iggm_usd=iggm_usd)
        row_p = dict(p, 后台利润率=r.get("margin"))
        writable = (zmeta.get("启用") is True and str(zmeta.get("后台行ID")) == str(r["id"])
                    and WS.number(r.get("margin")) is not None and 0 <= r["margin"] < 1)
        new_cost = (write_cost_for(res["b2c"], row_p, fx)
                    if res["b2c"] and r["type"] != "HC" and writable else None)
        old_b2c = r.get("b2c")
        action = "hold"
        if res["mode"] not in ("Hardcore未开放(跳过)",) and new_cost is not None:
            current_margin = (1 - res["cost_usd"] / old_b2c
                              if old_b2c and res.get("cost_usd") else None)
            outside_margin = (current_margin is not None and
                              (current_margin < float(p["毛利率下限"]) - 1e-8 or
                               current_margin > float(p["毛利率上限"]) + 1e-8))
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
            "成本价USD": res.get("cost_usd"), "IGGM": res.get("iggm"),
            "IGGM倍数": (round(res["b2c"] / res["iggm"], 4)
                         if res.get("iggm") and res.get("b2c") else None),
            "备注": res.get("note") or "",
            "成本来源": res.get("selected_source"), "双源报价": res.get("source_quotes", []),
            "毛利底价USD": res.get("floor_usd"), "毛利封顶价USD": res.get("ceiling_usd"),
            "后台计算利润率": r.get("margin"), "策略版本": WS.VERSION,
            "利润率": res["margin"], "目标b2c": res["b2c"],
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
