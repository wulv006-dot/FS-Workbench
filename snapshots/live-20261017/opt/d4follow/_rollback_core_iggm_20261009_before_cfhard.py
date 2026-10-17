# -*- coding: utf-8 -*-
"""IGGM 竞品价格抓取（暗黑4 items + 多游戏）

原理（2026-09-03 实测逆向，2026-09-22 复核）：
- IGGM 品类页价格由 JS 异步加载，统一走 GET /goods/goods_ajax
- 页面内联变量 template_name='items'、goods_game_sku='diablo4724'
- D4 PC 服 server_id=16847；cate_id 决定看哪个分类（7407 = Lair Boss Keys）
- 返回 data.goods[]，每条里 true_price 就是「前端展示单价」（美元）
- ⚠ goods_ajax 无签名、无需登录态，可直接 urllib 请求，比页面渲染稳定得多

⭐ 竞品价折算系数（2026-09-23 定案，第四轮实测）：
- IGGM 对**机房 / 采集来源 IP** 的报价 = 家用 IP（正常客户）的 **×1.10**
  实测 7/7 精确 1.100000：两侧 `update_time` 同一秒、`discount` 完全相同，
  `item_price` 与 `true_price` 同步 ×1.1 → 加价加在**基准价**上，不是折扣差异。
- 所以我们抓到的 `true_price` 是「机房价 A」，客户看到的是「真价 B = A ÷ 1.1」。
- 配置 `iggm.竞品价折算系数` 默认 1.0；本项目填 1/1.1 = 0.909090909，
  写库前就把 A 换算成 B，让 DB / 引擎 / 页面 / 历史 全部统一在「客户实付折后价」口径。
- ⚠ 系数只做「还原真价」这一件事。**不要**再叠加「标价 ÷ 后台折扣」的反推
  （那会把前端价抬回真价、变成与竞品同价，而不是低 10%）。

⭐ 多游戏（2026-09-25 新增 POE2）：
- 每个游戏一套连接参数，放在 `iggm.多游戏.<游戏名>`：
  `{game_sku, 请求延迟秒, 竞品价折算系数, 服务区[{key,名称,server_id,金币server_id,启用}]}`
- 物品：GET /goods/goods_ajax?template_type=items&server_id=<sid>&cate_id=0&game_sku=<sku>
- 金币：GET /goods/goods_ajax?template_type=golds&server_id=<sid>&cate_id=0&game_sku=<sku>
  → data.one_goods.price = **每 1 个单位金币价**（POE2 实测），乘 10000 得「每万金价」。
  金币行给一个合成 goods_no（`G:<服务区key>`）供 engine 精确匹配。

⭐ Cloudflare 挑战（2026-09-27）：
- IGGM 对「裸打 ajax（无 cookie）」的请求返回 403 + CF 挑战页；
  先 GET 一次品类页拿到 `__cf_bm` 等 cookie 再打 ajax 即可 200。
- 见 `_prime()` / `_get()`；cookie 由进程级 CookieJar 持有，失败时自动补一次。
"""
import http.cookiejar
import json
import time
import urllib.parse
import urllib.request

BASE = "https://www.iggm.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# 金币行情：IGGM 返回「每 1 金币」单价；我们与竞品都按 1 万金币对标
GOLD_UNIT = 10000


def factor_of(cfg, game=None):
    """竞品价折算系数：机房抓取价 → 客户实付折后价（默认 1.0 = 不折算）

    game 不为空时优先读 `iggm.多游戏.<game>.竞品价折算系数`，否则回退全局。
    """
    if game:
        try:
            k = float(((cfg or {}).get("iggm", {}).get("多游戏", {})
                       .get(game, {}) or {}).get("竞品价折算系数", None))
            if k > 0:
                return k
        except (TypeError, ValueError):
            pass
    try:
        k = float(((cfg or {}).get("iggm") or {}).get("竞品价折算系数", 1.0))
    except (TypeError, ValueError):
        k = 1.0
    return k if k > 0 else 1.0


def _mul(v, k):
    return None if v is None else v * k


# ---- Cloudflare 托管挑战应对（2026-09-27 新增）-----------------------------
# IGGM 从 2026-09-27 11:29 起对「不带 cookie 直接打 /goods/goods_ajax」的请求
# 返回 403 + CF 挑战页（`window._cf_chl_opt`，约 1.46MB）。
# 实测：用同一 UA 先 GET 一次品类页（HTTP 200，种下 __cf_bm / SESS_ID / a2ec…），
# 再打 ajax 就回到 HTTP 200。这里用进程级 CookieJar 复用这些 cookie，
# 并在「首次」与「失败重试」时补一次页面请求（幂等、便宜，进程内 10 分钟只做一次）。
_CJ = http.cookiejar.CookieJar()
_OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_CJ))
_PRIMED = {"ok": False, "ts": 0.0}
CF_MARK = "cf_chl_opt"          # 挑战页里必有的标记；正常 JSON 不会出现


def _prime(referer, timeout=30, force=False):
    """请求一次页面拿 Cloudflare cookie。幂等、便宜；进程内 10 分钟只做一次。"""
    now = time.time()
    if not force and _PRIMED["ok"] and (now - _PRIMED["ts"]) < 600:
        return True
    try:
        req = urllib.request.Request(referer or (BASE + "/"),
                                     headers={"User-Agent": UA})
        with _OPENER.open(req, timeout=timeout) as r:
            r.read()
        _PRIMED["ok"] = True
        _PRIMED["ts"] = now
        return True
    except Exception:
        _PRIMED["ok"] = False
        return False


def _get(url, referer=None, timeout=30, retry=3):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
        headers["X-Requested-With"] = "XMLHttpRequest"
    last = None
    for i in range(retry):
        try:
            if referer:             # 先补页面 cookie 再打 ajax（挑战拦截的解法）
                _prime(referer, timeout, force=(i > 0))
            req = urllib.request.Request(url, headers=headers)
            with _OPENER.open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            if CF_MARK in body:     # HTTP 200 也可能是挑战页 → 换 cookie 再试
                _PRIMED["ok"] = False
                raise RuntimeError("撞上 Cloudflare 挑战页（len=%d）" % len(body))
            return body
        except Exception as e:      # 网络抖动 / 挑战 → 重试，不当终止条件
            last = e
            _PRIMED["ok"] = False
            time.sleep(1.5 * (i + 1))
    raise last


def goods_ajax(game_sku, server_id, cate_id, page=1, referer=None):
    qs = urllib.parse.urlencode({
        "template_type": "items", "server_id": str(server_id), "cate_id": str(cate_id),
        "game_sku": game_sku, "sort": 0, "goods_name": "", "tag": "", "page": page,
    })
    body = _get(BASE + "/goods/goods_ajax?" + qs, referer=referer)
    return (json.loads(body) or {}).get("data") or {}


def goods_ajax_gold(game_sku, server_id, referer=None):
    """金币行情（golds 模板）。返回 data 原样（含 one_goods / result_goods）"""
    qs = urllib.parse.urlencode({
        "template_type": "golds", "server_id": str(server_id), "cate_id": 0,
        "game_sku": game_sku,
    })
    body = _get(BASE + "/goods/goods_ajax?" + qs, referer=referer)
    return (json.loads(body) or {}).get("data") or {}


def scrape_target(cfg, target, log=print):
    """抓一个 IGGM 目标分类的全部商品。返回 rows（含单价、原价、折扣、更新时间）

    target 可覆盖连接参数（多游戏用）：
      game_sku / server_id / 折算系数 / 页面
    未给则回退 cfg['iggm'] 顶层值（暗黑4 原样）。
    """
    ig = cfg["iggm"]
    sku = target.get("game_sku") or ig["game_sku"]
    srv = target.get("server_id") or ig["server_id"]
    game = target.get("游戏") or ""
    k = target.get("折算系数")
    k = factor_of(cfg, game) if k is None else float(k)
    ref = target.get("页面") or (BASE + "/diablo-4-items")
    cate = str(target["cate_id"])
    rows, page, total = [], 1, None
    while True:
        d = goods_ajax(sku, srv, cate, page, referer=ref)
        if total is None:
            total = int(d.get("count") or 0)
        goods = d.get("goods") or []
        if not goods:
            break
        for g in goods:
            rows.append({
                "goods_no": str(g.get("goods_no") or ""),
                "title": (g.get("title") or "").strip(),
                "cate_id": str(g.get("cate_id") or cate),
                "cate_name": target.get("cate_name", ""),
                "target_key": target["key"],
                "server_id": str(g.get("server_id") or srv),
                "游戏": game,
                # price_usd 入库前即折算成「客户实付折后价」；
                # 原始机房价另存 raw，方便随时核对倍数有没有漂。
                "unit_price_usd": _mul(_f(g.get("true_price")), k),
                "unit_price_raw_usd": _f(g.get("true_price")),
                "list_price_usd": _mul(_f(g.get("item_price")), k),
                "goods_price_usd": _f(g.get("goods_price")),
                "discount": g.get("discount"),
                "min_num": g.get("min_num"),
                "unit": g.get("unit") or "",
                "stock": g.get("stock"),
                "status": g.get("status"),
                "sales": g.get("sales"),
                "ig_update_time": g.get("update_time") or "",
                "url": target.get("页面", ""),
            })
        log("  [IGGM] %s 第%d页 +%d 条 (累计 %d/%d)"
            % (target.get("cate_name") or cate, page, len(goods), len(rows), total))
        if len(rows) >= total or page > 60:
            break
        page += 1
        time.sleep(float(ig.get("请求延迟秒", 0.8)))
    return rows


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def zone_targets(cfg, games=None):
    """多游戏服务区 → IGGM 目标（物品，cate_id=0 表示该服全量）

    games: 只抓这些游戏（= 本轮按采集周期到期的那批）；None = 全抓（向后兼容）。
    """
    out = []
    for game, g in ((cfg.get("iggm") or {}).get("多游戏") or {}).items():
        if not isinstance(g, dict) or g.get("启用", True) is False:
            continue
        if games is not None and game not in games:
            continue
        page = g.get("页面") or (BASE + "/poe-2-currency")
        for z in (g.get("服务区") or []):
            if not z.get("key") or z.get("启用", True) is False:
                continue
            # 2026-09-26 加：`物品:false` = 该游戏 IGGM 侧没有物品可抓
            # （WarDogs / WoW Forever 只有货币页，items 模板返回 true_price=0 的占位）
            # ⇒ 跳过物品抓取，避免每小时写 0 价噪音行。默认 True ⇒ 老游戏零影响；
            # 金币走 gold_targets（看 金币server_id），不受本开关控制。
            if z.get("物品", True) is False:
                continue
            out.append({
                "key": "IGGM_" + str(z["key"]),
                "名称": "%s · %s" % (game, z.get("名称") or z["key"]),
                "cate_id": "0",
                "cate_name": z.get("名称") or "",
                "页面": page,
                "启用": True,
                "游戏": game,
                "game_sku": g.get("game_sku"),
                "server_id": str(z.get("server_id") or ""),
                "折算系数": g.get("竞品价折算系数"),
            })
    return out


def scrape_zones(cfg, log=print, games=None):
    """多游戏：按服务区抓物品全量（cate_id=0）；games 限定只抓到期的游戏"""
    out = []
    delay = float(((cfg.get("iggm") or {}).get("请求延迟秒", 0.8)) or 0.8)
    for t in zone_targets(cfg, games=games):
        try:
            rows = scrape_target(cfg, t, log=log)
            for r in rows:
                r["zone_key"] = t["key"][5:]        # 去掉 IGGM_ 前缀 → 配置里的服务区 key
            out += rows
        except Exception as e:
            log("  [IGGM] %s 抓取失败: %r" % (t.get("名称"), e))
        time.sleep(delay)
    return out


def gold_targets(cfg, games=None):
    out = []
    for game, g in ((cfg.get("iggm") or {}).get("多游戏") or {}).items():
        if not isinstance(g, dict) or g.get("启用", True) is False:
            continue
        if games is not None and game not in games:
            continue
        for z in (g.get("服务区") or []):
            sid = z.get("金币server_id")
            if not z.get("key") or not sid or z.get("启用", True) is False:
                continue
            out.append({
                "key": "GIGGM_" + str(z["key"]),
                "zone_key": str(z["key"]),
                "名称": "%s · %s 金币" % (game, z.get("名称") or z["key"]),
                "游戏": game,
                "game_sku": g.get("game_sku"),
                "server_id": str(sid),
                "折算系数": g.get("竞品价折算系数"),
                "页面": g.get("金币页面") or (BASE + "/poe-2-gold"),
                "单位": g.get("金币对标单位", GOLD_UNIT),
                "启用": True,
            })
    return out


def scrape_golds(cfg, log=print, games=None):
    """多游戏：按服务区抓金币行情 → 一条 `G:<服务区key>` 行（每万金价）"""
    out = []
    delay = float(((cfg.get("iggm") or {}).get("请求延迟秒", 0.8)) or 0.8)
    for t in gold_targets(cfg, games=games):
        try:
            game = t["游戏"]
            k = factor_of(cfg, game) if t.get("折算系数") is None else float(t["折算系数"])
            unit = float(t.get("单位") or GOLD_UNIT)
            d = goods_ajax_gold(t["game_sku"], t["server_id"], referer=t["页面"])
            g = d.get("one_goods") or {}
            per1 = _f(g.get("price"))
            if per1 is None:
                log("  [IGGM/金币] %s 没读到单价（可能被 Cloudflare 拦），跳过" % t["名称"])
                continue
            tiers = sorted([{"num": int(x.get("num") or 0), "all": _f(x.get("all"))}
                            for x in (d.get("result_goods") or [])], key=lambda x: x["num"])
            out.append({
                "goods_no": "G:" + t["zone_key"],
                "title": (g.get("title") or "").strip() or (t["名称"] + " Gold"),
                "cate_id": "golds",
                "cate_name": t["名称"],
                "target_key": t["key"],
                "server_id": t["server_id"],
                "游戏": game,
                "zone_key": t["zone_key"],
                # 每 1 金币价 × 10000 → 每万金币价（与我们对标档位同口径）
                "unit_price_usd": per1 * unit * k,
                "unit_price_raw_usd": per1 * unit,
                "list_price_usd": per1 * unit * k,
                "goods_price_usd": None,
                "discount": None,
                "min_num": None,
                "unit": "Gold",
                "stock": None,
                "status": 1,
                "sales": None,
                "ig_update_time": (d.get("result_goods") or [{}])[0].get("update_time") or "",
                "url": t["页面"],
            })
            log("  [IGGM/金币] %s 每万金 $%s（真价 $%s）"
                % (t["名称"], round(per1 * unit, 6), round(per1 * unit * k, 6)))
        except Exception as e:
            log("  [IGGM/金币] %s 抓取失败: %r" % (t.get("名称"), e))
        time.sleep(delay)
    return out


D4_GAME = "暗黑破坏神4"      # IGGM 主站分类（`目标` + `扩展分类`）固定归暗黑4


def scrape_all(cfg, log=print, games=None):
    """抓 config 里所有启用的目标（暗黑4 分类 + 多游戏服务区 + 多游戏金币）

    games: 只抓这些游戏（= 本轮按采集周期到期的那批）；None = 全抓（向后兼容）。
           主站分类（`目标` + `扩展分类`）固定归「暗黑破坏神4」。
    """
    targets = []
    if games is None or D4_GAME in games:
        targets = [t for t in cfg["iggm"].get("目标", []) if t.get("启用", True)]
        for x in (cfg["iggm"].get("扩展分类", {}) or {}).get("列表", []) or []:
            if x.get("启用"):
                targets.append({"key": "EXT_" + x["cate_id"], "名称": x["cate_name"],
                                "cate_id": x["cate_id"], "cate_name": x["cate_name"],
                                "页面": "%s/diablo-4-items?page=1&server_id=%s&cate_id=%s"
                                        % (BASE, cfg["iggm"]["server_id"], x["cate_id"]),
                                "启用": True})
    else:
        log("  [IGGM] %s 本轮未到期，跳过主站分类" % D4_GAME)
    out = []
    for t in targets:
        try:
            out += scrape_target(cfg, t, log=log)
        except Exception as e:
            log("  [IGGM] %s 抓取失败: %r" % (t.get("名称"), e))
        time.sleep(0.5)
    # 多游戏（POE2 …）：物品全量 + 金币
    try:
        out += scrape_zones(cfg, log=log, games=games)
    except Exception as e:
        log("  [IGGM] 多游戏服务区抓取失败: %r" % e)
    try:
        out += scrape_golds(cfg, log=log, games=games)
    except Exception as e:
        log("  [IGGM] 多游戏金币抓取失败: %r" % e)
    return out


if __name__ == "__main__":
    import os
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))
    rs = scrape_all(cfg)
    print("\n共 %d 条" % len(rs))
    for r in rs:
        print("  %-12s $%-9s min_num=%s upd=%s" % (r["goods_no"], r["unit_price_usd"],
                                                   r["min_num"], r["ig_update_time"]))
