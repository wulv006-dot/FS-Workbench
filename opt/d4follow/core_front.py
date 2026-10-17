# -*- coding: utf-8 -*-
"""我方前端价抓取（MMOEXP 自营站 = order.p2pah.cn 的前端）

为什么抓公开页面而不是直接调后台：
- order.p2pah.cn 里的「产品价格管理 → $ 价格」**就是**前端展示价，两者同源。
- 读公开页面零风险（不登录、不写、不会误改），当基线用最稳。
- 真要改价才需要登录 order.p2pah.cn（由 apply_price.py 负责）。

页面结构（2026-09-22 复核 D4 价格监控系统既有实现）：
    <div class="goods-title">Corrupted Roots</div>
    <span id="s170037765" data-price="$ 0.11">
    <span id="z170037765" data-full-price="$ 0.12">
金币页是 .qa-btn[data-id][data-num][data-price]，单位 M。

⭐ 多游戏（2026-09-25 新增 POE2）：
- 暗黑4 走「整页 HTML + 正则」，POE2 那套模板完全不同（价格由 jsonp/ajax 渲染），
  正则会误匹配到「加购数量」里的数字（实测 Divine 读成 0.16，真值 0.0159）。
- 所以 POE2 改走**前端自己的数据接口** `POST https://www.mmoexp.com/ajax/goods`：
    orderBy / prop_ids / site_id=266 / Game_id=<游戏id> / page / top_cid / aid=<服务区>
    / keyword / tid / cid=<类目> / level / screen_cid / get_about_multi_by_cid=1 / perpage
  返回 `goods.index.list[]`，每条含 id / title / unit_price / discount / min_qty —— 直接可用。
- `aid` 是**前台服务区 ID**（与后台 aid 不是一套号）；POE2 货币 cid=1338、金币 cid=4459。
- POE2 的 discount 实测恒为 100（前端价 = 标价），引擎侧按游戏取折扣，别用 D4 的 90。

⭐ 2026-09-25 晚 两处必要改造（接入 ARC Raiders / Dark and Darker 时暴露）：
- **必须翻页**：`/ajax/goods` 单页上限约 300~500 条，而 ARC 单服有 587 条。
  旧实现只取第 1 页 ⇒ 会静默丢掉 287 条（读不到价 → 那一半商品永远不跟价、也不报警）。
  现在按返回里的 `index.total` 循环翻页。
- **cid / top_cid 必须按游戏配**：ARC/DND 的「全部商品」cid=0（不是 POE2 的 1338）；
  DND 金币 cid=1507 且 **top_cid=1**（物品是 2）。取值改为
  「config 里写了就用写的（写成空串 = 该类目不抓），没写才回退旧默认值」——
  这样 POE2 / 暗黑4 的既有行为一字不变。
"""
import html
import json
import re
import sys   # 2026-10-06 补：_audit_pack_conflicts 的每轮自检用到 sys.modules，
            # 原先漏 import，NameError 被 try 吞掉 ⇒ 自检静默失效（现已在轮次里真正生效）

# ── 装量解耦 2026-10-05 ──
def _audit_pack_conflicts(cfg):
    """数量口径硬校验：key 名后缀 vs 数量字段冲突 + 同族数量重复。
    实现复用 /tmp/match_key_v2.py 的 qty_of / key_qty_suffix（同一套口径，避免两处漂移）。"""
    import re as _re
    _Q = _re.compile(r'_x?(\d+)$', _re.I)
    def _qty(it):
        for f in ('数量', '装量'):
            v = it.get(f)
            if v not in (None, ''):
                try:
                    n = int(v)
                    if n > 0:
                        return n
                except (TypeError, ValueError):
                    pass
        m = _Q.search(str(it.get('key') or ''))
        return int(m.group(1)) if m else 1
    _items = (cfg.get('商品映射') or {}).get('对照项') or []
    bad, dupes = [], {}
    for it in _items:
        m = _Q.search(str(it.get('key') or ''))
        if m and int(m.group(1)) != _qty(it):
            bad.append('  key %-34s key名后缀=X%-8s 数量字段=%s' % (it.get('key'), m.group(1), _qty(it)))
        if not it.get('前台商品名'):
            dupes.setdefault((_Q.sub('', str(it.get('key') or '')), _qty(it)), []).append(it.get('key'))
    dupes = {k: v for k, v in dupes.items() if len(v) > 1}
    if bad:
        print('  ⚠⚠ 数量口径错位 %d 条（key 名后缀 ≠ 数量字段）：' % len(bad))
        for x in bad:
            print(x)
    if dupes:
        print('  ⚠⚠ 同数量重复 %d 组（会互相抢前台行）：' % len(dupes))
        for (base, q), ks in sorted(dupes.items()):
            print('     · %s 装量=%s → %s' % (base, q, '、'.join(ks)))
    if not bad and not dupes:
        print('  ✓ 数量口径自检通过：无后缀错位、无同数量重复')
    return bad, dupes
import time
import urllib.parse
import urllib.request
import net_util  # 2026-10-16 统一出网：收干净连接 + 唯一出口开关

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

ITEM_CARD = re.compile(
    r'<div class="goods-title">\s*(?P<name>.*?)\s*</div>.*?'
    r'id="s(?P<sid>\d+)"\s+data-price="\$\s*(?P<price>[\d.]+)".*?'
    r'(?:id="z(?P<zid>\d+)"\s+data-full-price="\$\s*(?P<full>[\d.]+)")?', re.S)
QA_BTN = re.compile(
    r'<div class="qa-btn[^"]*"[^>]*?data-id="(?P<gid>\d+)"[^>]*?'
    r'data-num="(?P<num>\d+)"[^>]*?data-price="(?P<price>[\d.]+)"', re.S)
PACK_RE = re.compile(r"^\s*\((?P<n>\d+)\)\s*(?P<base>.+)$")
# 2026-09-26 加：MMOEXP 还有 `Name*100` 的后缀式装量（Horadric 类目整页都是），
# 原来只认 `(10) Name` 前缀式 ⇒ 这些商品装量被读成 1，对照项装量=100 永远匹配不上。
PACK_SUF_RE = re.compile(r"^(?P<base>.+?)\s*[*\u2715]\s*(?P<n>\d+)\s*$")

# 2026-09-26 加：MMOEXP 每个商品的「精确价」属性（= 后台「$每个价格」标价）。
#   展示位 : <span id="s<id>" data-price="$ 0.09">                 ← 2 位小数（被取整）
#   精确位 : <span data-id="<id>" data-discount="90" data-price="0.089">  ← 同 id，标价
#   关系   : 展示价 = 精确价 × 折扣%
# 旧实现只读展示位 ⇒ 0.089 被记成 0.09、0.4275 被记成 0.43（我方价永远差一点点）。
# 必须同时带 data-discount 才不会误匹配购物车脚本里别处的 data-price。
EXACT_PRICE_RE = re.compile(
    r'data-id="(?P<id>\d+)"[^>]*?data-discount="(?P<disc>[\d.]+)"'
    r'[^>]*?data-price="(?P<p>[\d.]+)"', re.S)

AJAX_GOODS = "https://www.mmoexp.com/ajax/goods"
DEFAULT_ITEM_CID = "1338"       # POE2 货币（回退值，只有 config 里没写才用）
DEFAULT_GOLD_CID = "4459"       # POE2 Quick Gold（回退值）
DEFAULT_TOP_CID = "2"           # 前台大类目：2 = 物品，1 = 金币/货币
MAX_PAGES = 15                  # 翻页上限（500/页 × 15 = 7500 条，够用且能防死循环）


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    # 2026-09-26 修：原手写替换表只认两位式 `&#39;`，但 MMOEXP 用的是三位式 `&#039;`
    # （Adept's / Protector's / Judicator's 三条标题就是这种）⇒ 撇号没还原、名字对不上
    # 对照项关键词，3 条商品永远读不到我方价。改用标准库 html.unescape 覆盖全部实体
    # （命名实体 + &#NN; + &#xNN; 三种数字写法）。
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def norm_name(s):
    """商品名归一化：只留小写字母数字 + 圈号 ①~⑳（'10,000 Gold' → '10000gold'）

    ⚠ 2026-09-26 修：原来圈号也被剥掉，导致 ARC 的
      `[Expedition ①/②/③/④/⑤ Material] Foundation N` 5 个**不同商品**
      归一化成同一个名字 ⇒ `to_multi_rows` 的 idx 互相覆盖（5 个只出 1 个 key），
      其余 4 个 key 永远匹配不上、只能吃库内快照兜底（我方价永不刷新）。
      圈号是唯一区分它们的字符，必须保留。
    """
    return re.sub(r"[^a-z0-9\u2460-\u2473]", "", str(s or "").lower())


def split_pack(name):
    m = PACK_RE.match(name)
    if m:
        return m.group("base").strip(), int(m.group("n"))
    m = PACK_SUF_RE.match(name)          # `Name*100` / `Name✕100`
    if m:
        return m.group("base").strip(), int(m.group("n"))
    return name.strip(), 1


def _get(url, timeout=45, retry=3):
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
            with net_util.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def post_form(url, body, referer=None, timeout=60, retry=4):
    """POST form-urlencoded（前端 /ajax/* 接口统一用法）"""
    data = urllib.parse.urlencode(body).encode()
    headers = {"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
               "X-Requested-With": "XMLHttpRequest",
               "Accept-Language": "en-US,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(url, data=data, headers=headers)
            with net_util.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def scrape_page(url, log=print):
    """抓一个 MMOEXP 页面（道具页或金币页），返回 [{name, sku_id, price_usd, unit_price_usd}]"""
    html = _get(url)
    rows, seen = [], set()
    if "gold" in url.lower():
        unit = re.search(r'class="quick-amounts"[^>]*data-unit="([^"]*)"', html)
        unit = unit.group(1) if unit else "M"
        for m in QA_BTN.finditer(html):
            gid, num, p = m.group("gid"), int(m.group("num")), float(m.group("price"))
            if (gid, num) in seen:
                continue
            seen.add((gid, num))
            rows.append({"name": "Diablo 4 Gold (%d %s)" % (num, unit),
                         "sku_id": "%s-%d" % (gid, num), "price_usd": p,
                         "unit_price_usd": round(p / max(1, num), 10),
                         "pack_size": num, "url": url})
    else:
        # 精确价表 {sku_id: (标价, 折扣比例)} —— 见 EXACT_PRICE_RE 注释
        exact = {}
        for em in EXACT_PRICE_RE.finditer(html):
            try:
                _p = float(em.group("p"))
                _d = float(em.group("disc"))
            except (TypeError, ValueError):
                continue
            if _p <= 0:
                continue
            if _d <= 0:
                _d = 100.0
            exact.setdefault(em.group("id"), (_p, _d / 100.0))
        _n_exact = 0
        for m in ITEM_CARD.finditer(html):
            name = _clean(m.group("name"))
            sid = m.group("sid")
            if not name or sid in seen:
                continue
            seen.add(sid)
            try:
                p = float(m.group("price"))
            except (TypeError, ValueError):
                continue
            # 优先用精确位还原「精确的展示价」= 标价 × 折扣（口径不变、精度提高）
            # 2026-10-01 修复：加合理性护栏 —— 精确位（data-id 关联的标价×折扣）
            # 偶尔会张冠李戴（如 Corrupted Roots 把整包展示价 $2.83 算成单价 $0.283，
            # 差 10 倍），一旦覆盖会让引擎读到错的价、算出假亏损（margin 会变 −320%）。
            # 故：只有当精确价与页面展示价同量级（比值 ≤ 2 倍）才采信精确价；
            #     否则判定精确位疑似错位，回退展示价，保证读到的价永远不做 10 倍跳跃。
            _p0 = p                       # 页面展示价（data-price 直读，作为量级锚）
            _price_src = "display"
            ex = exact.get(sid)
            if ex:
                p_ex = round(ex[0] * ex[1], 6)
                if p_ex > 0:
                    _ratio = p_ex / _p0 if _p0 > 0 else 0.0
                    if 0.5 <= _ratio <= 2.0:
                        p = p_ex
                        _n_exact += 1
                        _price_src = "exact"
                    else:
                        # 精确位与展示价量级不符 —— 保留展示价，并留痕（便于排查上游标记错位）
                        log("    [前端价护栏] %s 精确价 %.4f 与展示价 %.4f 相差 %.1f×，"
                            "回退展示价" % (name[:40], p_ex, _p0,
                                          (_ratio if _ratio >= 1 else 1.0 / max(_ratio, 1e-9))))
                        _price_src = "display(guard)"
            base, n = split_pack(name)
            rows.append({"name": name, "base_name": base, "sku_id": sid,
                         "price_usd": p, "unit_price_usd": round(p / max(1, n), 10),
                         "pack_size": n, "url": url,
                         # 2026-09-27：把前端**实测折扣**（data-discount，百分数）带出来。
                         # 存进 our_price.front_disc，引擎按它反推标价、也按它换目标标价 ——
                         # 折扣是动态的（用户随时改），不能只信 config 里那个数。
                         "_前台折扣": (ex[1] * 100.0 if ex else None),
                         "_price_src": _price_src})
        if _n_exact:
            log("    （%d/%d 条用了精确价＝标价×折扣，其余回退展示价）"
                % (_n_exact, len(rows)))
    log("  [前端] %s -> %d 条" % (url.rsplit("/", 1)[-1], len(rows)))
    return rows


def fetch_all(cfg, log=print, games=None):
    """抓「前端.pages」里的公开页（当前全是暗黑4 的物品页）。

    games: 到期游戏列表；不含「前端.游戏」(默认 暗黑破坏神4) 时直接跳过 ——
           未到期的游戏不必再去抓一遍页面。
    """
    conf = cfg.get("前端") or {}
    _g = str(conf.get("游戏") or "暗黑破坏神4")
    if games is not None and _g not in games:
        log("  [前端] %s 本轮未到期，跳过 pages 抓取" % _g)
        return []
    pages = conf.get("pages") or ["https://www.mmoexp.com/Diablo-4/Items.html"]
    out = []
    for u in pages:
        try:
            out += scrape_page(u, log=log)
        except Exception as e:
            log("  [前端] 抓取失败 %s: %r" % (u, e))
        time.sleep(0.8)
    out += fetch_ajax_cats(cfg, log=log, games=games)
    return out


def fetch_ajax_cats(cfg, log=print, games=None):
    """抓 `前端.ajax类目`：那些**没有 SEO 静态页、只能走 /ajax/goods** 的类目。

    为什么需要（2026-09-29 用户要求把 GEM 类目加进监控）：
      暗黑4 的「Gems ＆ Horadric Gems」类目没有静态页 ——
      /Diablo-4/Items/Gems-horadric-gems.html 等 6 个候选 URL 全部返回 **HTTP 410**，
      商品只在点类目时由 /ajax/goods 返回。而 D4 这个接口要 `category_id=<cid>`；
      传 `cid`、或 `cid` 与 `category_id` 同时传，都会拿到 total=0（实测）。
    输出结构与 `scrape_page` 完全一致，所以 `to_our_rows`（D4 匹配）无需改动。

    `_前台折扣` 存的是**百分数**（90 = 9 折），与 scrape_page / 多游戏路径同口径。
    """
    conf = cfg.get("前端") or {}
    out = []
    for c in (conf.get("ajax类目") or []):
        if not isinstance(c, dict) or c.get("启用", True) is False:
            continue
        g = str(c.get("游戏") or "暗黑破坏神4")
        if games is not None and g not in games:
            log("  [前端/ajax] %s 本轮未到期，跳过" % g)
            continue
        aid, cid = c.get("aid"), c.get("cid")
        if not aid or not cid:
            log("  [前端/ajax] 跳过 %s（缺 aid/cid）" % c.get("名称"))
            continue
        try:
            lst = ajax_goods(cfg, c.get("Game_id") or "456", aid, cid,
                             top_cid=c.get("top_cid") or "2",
                             referer=c.get("referer"),
                             cat_param=c.get("类目参数") or "cid")
        except Exception as e:
            log("  [前端/ajax] 抓取失败 %s: %r" % (c.get("名称"), e))
            continue
        n = 0
        for x in lst:
            name = _clean(x.get("title"))
            if not name:
                continue
            try:
                up = float(x.get("unit_price"))
            except (TypeError, ValueError):
                continue
            try:
                fp = float(x.get("price"))
            except (TypeError, ValueError):
                fp = None
            try:
                dv = float(x.get("discount"))
            except (TypeError, ValueError):
                dv = None
            if fp is None and dv and dv > 0:
                fp = round(up * dv / 100.0, 6)      # 兜底：标价 × 折扣
            if fp is None:
                fp = up
            base, pk = split_pack(name)
            out.append({"name": name, "base_name": base,
                        "sku_id": str(x.get("id") or ""),
                        "price_usd": fp,                       # 折后前端价（客户实付）
                        "unit_price_usd": round(fp / max(1, pk), 10),
                        "pack_size": pk, "url": c.get("referer") or "",
                        "_前台折扣": dv, "_price_src": "ajax"})
            n += 1
        log("  [前端/ajax] %s aid=%s %s=%s → %d 条"
            % (c.get("名称") or cid, aid, c.get("类目参数") or "cid", cid, n))
    return out

# ------------------------------------------------------------------ 多游戏前端（ajax）
def _ajax_page(cfg, game_id, aid, cid, top_cid, page, perpage=500, referer=None,
               cat_param="cid"):
    """拉 /ajax/goods 的**某一页**，返回 (list, total)

    `cat_param` = 类目 ID 用哪个字段名传。POE2 / ARC / DND 用 `cid`（默认，不动）；
    **暗黑4 必须用 `category_id`** —— 2026-09-29 实测：D4 传 `cid`、或两个一起传，
    都得到 total=0（只有单独传 category_id 才返回宝石 28 条）。
    """
    ref = referer or ((cfg.get("前端") or {}).get("referer")
                      or "https://www.mmoexp.com/Poe-2/Currency.html")
    _body = {
        "orderBy": "", "prop_ids": "", "site_id": "266", "Game_id": str(game_id),
        "page": page, "top_cid": str(top_cid), "aid": str(aid), "keyword": "", "tid": "",
        "level": 0, "screen_cid": str(cid),
        "get_about_multi_by_cid": 1, "perpage": perpage}
    _body[str(cat_param or "cid")] = str(cid)
    d = post_form(AJAX_GOODS, _body, referer=ref)
    idx = ((d.get("goods") or {}).get("index") or {})
    try:
        total = int(idx.get("total") or 0)
    except (TypeError, ValueError):
        total = 0
    return (idx.get("list") or []), total


def ajax_goods(cfg, game_id, aid, cid, top_cid="2", perpage=500, referer=None,
               max_pages=MAX_PAGES, cat_param="cid"):
    """前端商品接口（**自动翻页**）。返回 goods.index.list[] 的汇总。

    ⚠ 2026-09-25 晚修：原来只取 page=1 ⇒ 单页上限 300~500，ARC 单服 587 条会丢掉
    287 条，而且**不报错**（前端价读不到 → 那些商品永远 hold 在「我方标价未知」）。
    现在按返回的 total 一直翻到取满或某页为空为止。
    """
    ref = referer or ((cfg.get("前端") or {}).get("referer")
                      or "https://www.mmoexp.com/Poe-2/Currency.html")
    out, page, total = [], 1, None
    while page <= max(1, int(max_pages)):
        lst, total = _ajax_page(cfg, game_id, aid, cid, top_cid, page,
                                perpage=perpage, referer=ref,
                                cat_param=cat_param)
        if not lst:
            break
        out += lst
        if total and len(out) >= total:
            break
        if len(lst) < perpage:
            break
        page += 1
        time.sleep(0.5)
    return out


def fetch_multi_game(cfg, log=print, games=None):
    """按 `iggm.多游戏.<游戏>.服务区[].前台aid` 抓我方前端价（物品 + 金币）。

    返回 [{zone_key, 游戏, kind, name, unit_price, front_price, discount, sku_id}]。
    ⚠ 价格口径（2026-09-27 实测修正）：
      · `unit_price` = **折前标价**（后台「$每个价格」）
      · `front_price` = **折后前端价**（客户实付 = unit_price × discount/100）
    引擎消费的「我方前端价」必须用 `front_price`；`to_multi_rows` 已按此取值。

    cid / top_cid 取值规则（2026-09-25 晚）：
      游戏级配了 `前台物品cid` / `前台金币cid` / `前台物品top_cid` / `前台金币top_cid`
      就用配的（空串 = 该类目不抓）；没配才回退 POE2 的老默认值 —— 保证 POE2/暗黑4 零回归。
    """
    out = []
    for game, g in ((cfg.get("iggm") or {}).get("多游戏") or {}).items():
        if not isinstance(g, dict) or g.get("启用", True) is False:
            continue
        if games is not None and game not in games:
            continue
        gid = g.get("前台Game_id") or g.get("Game_id") or ""
        if not gid:
            continue
        it_cid = (_cid_of(g, "前台物品cid", DEFAULT_ITEM_CID)
                  or DEFAULT_ITEM_CID)
        gd_cid = _cid_of(g, "前台金币cid", DEFAULT_GOLD_CID)
        it_top = _cid_of(g, "前台物品top_cid", DEFAULT_TOP_CID) or DEFAULT_TOP_CID
        gd_top = _cid_of(g, "前台金币top_cid", DEFAULT_TOP_CID) or DEFAULT_TOP_CID
        cats = [(it_cid, "items", it_top)]
        if gd_cid:
            cats.append((gd_cid, "gold", gd_top))
        delay = float((cfg.get("前端") or {}).get("请求延迟秒", 0.8) or 0.8)
        for z in (g.get("服务区") or []):
            if z.get("启用", True) is False:
                continue
            for cid, kind, top in cats:
                aid = z.get("前台aid")
                if kind == "gold":
                    aid = z.get("前台金币aid") or aid
                    if z.get("前端金币aid") is False:
                        continue
                if not aid:
                    continue
                try:
                    page = z.get("前端页面") or g.get("页面")
                    lst = ajax_goods(cfg, gid, aid, cid, top_cid=top, referer=page)
                    for x in lst:
                        up = x.get("unit_price")
                        try:
                            up = float(up)
                        except (TypeError, ValueError):
                            continue
                        # 🔴 2026-09-27 实测纠正：`/ajax/goods` 每条同时给两个价 ——
                        #      unit_price = **折前标价**（后台「$每个价格」那一栏）
                        #      price      = **折后前端价**（客户实付）
                        #   关系：price = unit_price × discount/100
                        #   实测（ARC 折扣 90）：unit_price=9.34167 → price=8.40750 ✓
                        #   引擎要的是**折后前端价**（它的 `ours_old` 口径就是客户实付）。
                        #   旧实现只取 unit_price 当「前端价」⇒ 引擎又按 `÷折扣` 反推标价
                        #   ⇒ 0.81 双重折扣：ARC 前端价被算成目标的 1.1111 倍（虚高 11.1%），
                        #     583 条被误判成「偏贵」并反复触发「偏差纠偏」。**必须取 price**。
                        fp = x.get("price")
                        try:
                            fp = float(fp)
                        except (TypeError, ValueError):
                            fp = None
                        _d = x.get("discount")
                        try:
                            _dv = float(_d) / 100.0
                        except (TypeError, ValueError):
                            _dv = None
                        if fp is None and _dv and _dv > 0:
                            fp = round(up * _dv, 6)     # 兜底：用 unit_price × 折扣还原
                        out.append({
                            "zone_key": z.get("key"), "游戏": game, "kind": kind,
                            "name": _clean(x.get("title")),
                            "unit_price": up,           # 折前标价（留档，便于复核）
                            "front_price": fp,          # 折后前端价（引擎用这个）
                            "discount": x.get("discount"),
                            "sku_id": str(x.get("id")),
                            "min_qty": x.get("min_qty"),
                            "aid": str(aid), "cid": cid,
                        })
                    log("  [前端/%s] %s aid=%s cid=%s top=%s → %d 条"
                        % (game, z.get("名称") or z.get("key"), aid, cid, top, len(lst)))
                except Exception as e:
                    log("  [前端/%s] 抓取失败 aid=%s cid=%s: %r" % (game, aid, cid, e))
                time.sleep(delay)
    return out


def _cid_of(g, key, default):
    """config 里显式写了这个键就用它（可以是空串）；没写才回退旧默认值。"""
    if key in (g or {}):
        v = g.get(key)
        return "" if v is None else str(v)
    return str(default)


def to_multi_rows(cfg, items, all_items=None):
    """把多游戏前端商品按 **(服务区 + 商品名 + 类目)** 精确匹配到 config 对照项 key。

    D4 那套 `match_key` 靠关键词子串，POE2 的规格名高度相似
    （'Divine Orb' / 'Divine Orb(20+1 Free)' / 'Divine Orb(100+5 Free)' …），
    子串匹配会互相抢 → 这里改用配置里显式写死的「前台服务区 + 前台商品名」精确匹配。

    返回 (rows, unmatched)
    """
    idx = {}
    _clash = {}
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        if not it.get("前台服务区") or not it.get("前台商品名"):
            continue
        kind = it.get("前台类目") or "items"
        # 2026-09-26：
        #  ① `_clean()` 去 HTML 实体 —— ARC/DND 有 14 条对照项的「前台商品名」里
        #     存着 `&#039;`（应为 `'`），norm 后多出 `039` 三个字符 ⇒ 永不命中。
        #     前端接口返回的是干净名字，所以必须两边同口径。
        #  ② 键撞车时告警 —— 两个对照项归一化后同名会**静默互相覆盖**，
        #     表现是「某几条永远匹配不上」，极难查。圈号已在 norm_name 保留，
        #     这里再兜一层。
        slot = (str(it["前台服务区"]), norm_name(_clean(it["前台商品名"])), kind)
        if slot in idx and idx[slot] != it["key"]:
            _clash.setdefault(slot, [idx[slot]]).append(it["key"])
            log("  ⚠ 多游戏对照项归一化撞车：%s %s → %s"
                % (slot[0], slot[1], _clash[slot]))
        idx[slot] = it["key"]
    rows, unmatched, seen = [], [], {}
    for x in items:
        k = idx.get((str(x.get("zone_key")), norm_name(_clean(x.get("name"))),
                     x.get("kind")))
        if not k:
            unmatched.append("%s/%s" % (x.get("zone_key"), x.get("name")))
            continue
        rec = {"key": k, "title": x.get("name"),
               # 🔴 2026-09-27 修：必须用 **折后前端价**（`front_price`），
               #   不能用 `unit_price`（那是折前标价）。用错会让引擎把标价当客户实付、
               #   再按 `÷折扣` 反推标价 ⇒ 0.81 双重折扣（ARC 583 条被算成虚高 11.1%，
               #   并反复误触发「偏差纠偏」）。旧库里 ARC 的 price_usd 就是这个错值。
               "price_usd": (x.get("front_price") if x.get("front_price") is not None
                             else x.get("unit_price")),     # 前端展示价（整包，客户实付）
               "unit_price_usd": (x.get("front_price") if x.get("front_price") is not None
                                  else x.get("unit_price")),
               "_标价_接口": x.get("unit_price"),            # 折前标价（留档复核用）
               "cost_cny": None, "game": x.get("游戏") or "", "server_zone": x.get("zone_key"),
               "cate": x.get("kind"), "source": "mmoexp-front",
               "_sku_id": x.get("sku_id"), "_前台折扣": x.get("discount")}
        prev = seen.get(k)
        # 同一 key 多条（重复上架）时取第一条，并记下重复数，便于排查
        if prev is None:
            seen[k] = rec
        else:
            prev["_dup"] = (prev.get("_dup") or 1) + 1
    rows = list(seen.values())
    # ── 装量解耦 2026-10-05 · 启动即暴露数量口径错位 ──
    # 这类错位在本系统会复发（_前台商品名实体修正 记载已修过 14 条同型故障），
    # 靠全库普查才发现代价太大 ⇒ 改成每轮采集都打一遍。
    try:
        _mk = sys.modules.get(__name__)
        if _mk and hasattr(_mk, '_audit_pack_conflicts'):
            _mk._audit_pack_conflicts(cfg)
    except Exception as _e:
        print('  ⚠️ 数量口径自检异常（本轮跳过，不影响采集）：%r' % (_e,))
    return rows, unmatched


# ── norm 中文保留修复 2026-10-05 ──
def _norm_kw(s):
    """关键词/商品名归一化。**中文必须保留。**

    旧实现写作 `[^a-z0-9]+`，把中文全剥掉，于是
    中文名 "巢穴钥匙 ×10" → "10"，变成一个「只要标题里有 10 就命中」的数字匹配器
    （Resplendent Spark x10 被判成 LAIR_KEY_X10 就是这么来的）；
    同时 39 条纯中文名归一化后为空，那一路候选从未生效过。

    与 gates.py 的 _norm_txt 保持同口径。
    """
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(s or "").lower())


def match_key_legacy_20261005(cfg, item_name, pack_size=1):
    """改前的原实现（保留仅供对照/回滚，生产路径已不再调用）"""
    """把前端商品名 + 装量匹配到 config 对照项的 key（暗黑4 专用）。

    前端名字形如 'Lair Key' / '(10) Lair Key' / '(100) Lair Key'，
    base_name 剥掉前缀后是 'Lair Key'，所以单靠名字区分不了 1 件装和 10 件装 ——
    **必须同时用装量**，否则 (10) Lair Key 会被错配到单价口径上去。

    匹配顺序：装量相同 + 关键词命中 > 装量 1 + 关键词命中（降级并告警）。
    """
    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())
    nm = norm(item_name)
    ps = int(pack_size or 1)
    exact, loose = None, None
    for it in cfg["商品映射"]["对照项"]:
        if it.get("前台商品名"):
            continue                     # 多游戏对照项走 to_multi_rows，不参与 D4 模糊匹配
        for cand in [(it.get("p2pah") or {}).get("商品名关键词"),
                     (it.get("iggm") or {}).get("title"), it.get("中文名")]:
            c = norm(cand)
            if not c or c not in nm:
                continue
            if int(it.get("装量", 1) or 1) == ps:
                if exact is None or len(c) > exact[1]:
                    exact = (it["key"], len(c))
            else:
                if loose is None or len(c) > loose[1]:
                    loose = (it["key"], len(c))
    if exact:
        return exact[0], True
    if loose:
        return loose[0], False
    return None, False


# ── 装量解耦 2026-10-05 ──
_KEY_QTY_RE = re.compile(r"_x?(\d+)$", re.I)


def qty_of(it):
    """🔴 数量的唯一真实来源。

    优先级：`数量` 字段 → `装量` 字段 → key 名后缀（兼容旧配置）。
    **key 名后缀排在最后** —— 这就是「数量从 key 名剥离」的实现点：
    今后 key 名不再决定数量，改名/改字段都不会造成口径打架。
    """
    for f in ("数量", "装量"):
        v = it.get(f)
        if v not in (None, ""):
            try:
                n = int(v)
                if n > 0:
                    return n
            except (TypeError, ValueError):
                pass
    m = _KEY_QTY_RE.search(str(it.get("key") or ""))
    return int(m.group(1)) if m else 1


def key_qty_suffix(it):
    """key 名尾部声明的数量（没有则 None）。仅用于审计告警，不参与匹配。"""
    m = _KEY_QTY_RE.search(str(it.get("key") or ""))
    return int(m.group(1)) if m else None


def match_key(cfg, item_name, pack_size=1, _conflicts=None):
    """把前端商品名 + 装量匹配到 config 对照项的 key（暗黑4 专用）。

    返回 (key, exact) —— **签名与旧版完全一致，调用方无需改动**。
      exact=True  表示按数量精确命中
      exact=False 表示降级命中（数量对不上，仅关键词命中）

    2026-10-05 修正（原缺陷见模块 docstring）：
      装量 + 关键词长度都相同时，不再用「严格大于」静默让先遍历者通吃，
      改为记入 _conflicts 并告警。同名候选仍允许先者胜出（幂等）。
    """
    def norm(s):
        return _norm_kw(s)

    nm = norm(item_name)
    ps = int(pack_size or 1)
    exact = loose = None
    # slot[(装量, 关键词长度)] = 命中该槽的不同 key 集合（用于冲突检测）
    slot = {}

    for it in cfg["商品映射"]["对照项"]:
        if it.get("前台商品名"):
            continue                     # 多游戏对照项走 to_multi_rows，不参与 D4 模糊匹配
        for cand in [(it.get("p2pah") or {}).get("商品名关键词"),
                     (it.get("iggm") or {}).get("title"), it.get("中文名")]:
            c = norm(cand)
            if not c or c not in nm:
                continue
            if qty_of(it) == ps:
                tag = (ps, len(c))
                if _conflicts is not None:
                    prev_keys = slot.setdefault(tag, set())
                    if it["key"] not in prev_keys:
                        if prev_keys:
                            _conflicts.append(
                                "装量=%s 关键词长度=%d 被 %s 同时命中（本条 %s 先占位）"
                                % (ps, len(c), "、".join(sorted(prev_keys)), it["key"]))
                        prev_keys.add(it["key"])
                if exact is None or len(c) > exact[1]:
                    exact = (it["key"], len(c))
            else:
                if loose is None or len(c) > loose[1]:
                    loose = (it["key"], len(c))

    if exact:
        return exact[0], True
    if loose:
        return loose[0], False
    return None, False

def to_our_rows(cfg, items):
    """转成 store.save_our 需要的结构（暗黑4）。

    ⭐ 价格口径 = **整包价（该规格在页面上展示的总价）**，不是拆分后的单价。
    原因：IGGM 也是整包报价（'Lair Key * 10' = $0.18139 是 10 个的总价），
    两边必须同口径才能比。单价另存 unit_price_usd 只用于展示。

    同一 key 可能被多条前端商品命中（我们的 1 / 10 / 100 件装都叫 'Lair Key'）。
    **装量精确匹配的优先**，降级匹配只在没有精确匹配时才用 ——
    否则 (100) Lair Key 会把 1 件装的价覆盖掉，整个利润率全是错的。
    """
    unmatched, best = [], {}
    for x in items:
        base = x.get("base_name") or x.get("name")
        ps = int(x.get("pack_size") or 1)
        k, exact = match_key(cfg, base, ps)
        if not k:
            unmatched.append(x.get("name"))
            continue
        pack_total = x.get("price_usd")
        rec = {"key": k, "title": x.get("name"),
               "price_usd": pack_total,                 # ← 整包价，与 IGGM 同口径
               "unit_price_usd": x.get("unit_price_usd"),  # 仅供展示
               "cost_cny": None, "game": "D4", "server_zone": "",
               "cate": "", "source": "mmoexp-front",
               "_pack_size": ps, "_pack_price_usd": pack_total,
               # 2026-09-27：带上前端**实测折扣**（scrape_page 从 data-discount 取）。
               # D4 物品走这条路 —— 之前漏带，导致引擎只能退回 config 里的折扣值，
               # 用户一改后台折扣就跟不上。存库后由 engine.disc_of_key 以实测为准。
               "_前台折扣": x.get("_前台折扣"),
               "_装量匹配": exact}
        prev = best.get(k)
        if prev is None or (exact and not prev["_装量匹配"]) or \
                (exact == prev["_装量匹配"] and ps < prev["_pack_size"]):
            best[k] = rec
    return list(best.values()), unmatched


if __name__ == "__main__":
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))
    its = fetch_all(cfg)
    print("\n抓回 %d 条" % len(its))
    rows, unmatched = to_our_rows(cfg, its)
    print("匹配上 %d 条，未匹配 %d 条" % (len(rows), len(unmatched)))
    seen = set()
    for x in its:
        k, ok = match_key(cfg, x.get("base_name") or x.get("name"), x.get("pack_size") or 1)
        print("  %-30s 整包 $%-8s x%-4s 单价 $%-11s -> %-22s %s"
              % (x.get("name"), x.get("price_usd"), x.get("pack_size"),
                 x.get("unit_price_usd"), k, "" if ok else "⚠ 装量降级匹配"))
        seen.add(x.get("name"))
    if unmatched:
        print("\n未匹配（需在 config 里补对照项）：")
        for u in unmatched:
            print("   ", u)
