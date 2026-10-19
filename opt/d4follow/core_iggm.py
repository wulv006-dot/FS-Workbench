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

⭐ Cloudflare 挑战（2026-09-27 首见 / 2026-10-09 加固）：
- IGGM 对「裸打 ajax（无 cookie）」的请求返回 403 + CF 挑战页；
  先 GET 一次品类页拿到 `__cf_bm` 等 cookie 再打 ajax 即可 200。
- 见 `_prime()` / `_get()`；cookie 由进程级 CookieJar 持有。

⭐ 2026-10-09 加固（起因：10-09 02:28:56~08:45 连续 13 轮采集全灭）
实测：机房 IP 被 CF 下发 **JS 挑战页**（403 + 约 1.46MB，含 cf_chl_opt），
封锁约 6.5 小时后**自动解除** —— 不是永久 IP 封禁。原实现有三个致命点：
  ① 撞挑战只置 `_PRIMED["ok"]=False`，**从不重建 CookieJar** ⇒ jar 里留下失效的
     `__cf_bm`（寿命约 30 分钟）后，每次 prime 都带着这个坏 cookie 发出去、继续 403，
     **永不恢复，直到进程重启** ← 这是「一封就连续十几轮」的直接原因。
  ② 撞挑战不熔断：每个 target / 每一页各重试 3 次，一轮打几百次请求，越打越黑。
  ③ 节奏偏快：全局 0.8 秒间隔、无抖动。
本版修法：
  `_reset_session()` 会话自愈（清 jar + 重建 opener + 重 prime）
  + `IGGMBlocked` 熔断退避（30min→1h→2h→4h，成功即归零）
  + `_sleep()` 降速抖动（下限 1.5s + 0~0.8s 随机）
  + `_HEADERS` 补全浏览器请求头。
⚠ 熔断时 `scrape_all` **整轮返回 []**（让上层沿用上一份完整快照），
  绝不写「半个快照」—— 半份快照会让看板缺行、下一轮比价基线断。
"""
import http.cookiejar
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
import net_util  # 2026-10-16 统一出网：收干净连接 + 唯一出口开关

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
class _Sess(object):
    """一条独立的抓取会话：**自己的** CookieJar + 预热状态 + 熔断计数。

    2026-10-19 新增（分缸）。为什么必须分：
      · 物品全量一轮上千次 ajax（暗黑4 分类 + 多游戏物品），最容易撞上
        CF 的速率阈值 ⇒ 403/挑战 ⇒ 熔断；
      · 金币只有十几个服务区、量小，但它是**改价基准**，缺一轮就没价可跟。
      原来两者共用同一 CookieJar + 同一熔断器 ⇒ 物品侧一被封，金币侧
      **零网络请求**直接放弃 ⇒ 冒险岛（IGGM 是它唯一价源）「隔一轮断一次」。
    分缸后：物品被封只影响物品，金币用自己干净的 cookie 继续抓。
    """

    def __init__(self, name):
        self.name = name
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.primed_ok = False
        self.primed_ts = 0.0
        self.fails = 0
        self.until = 0.0

    def reset(self):
        """清 jar + 重建 opener（撞拦截后会话必已被污染）。"""
        self.cj = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cj))
        self.primed_ok = False
        self.primed_ts = 0.0


# 两个主缸：物品（默认）与金币；另可 new_session() 临时开干净会话
_ITEM = _Sess("items")
_GOLD = _Sess("gold")
ITEM_SESSION = _ITEM        # 对外暴露（core_gold 等模块显式指定用哪条会话）
GOLD_SESSION = _GOLD
CF_MARK = "cf_chl_opt"          # 挑战页里必有的标记；正常 JSON 不会出现
CF_TTL = 300                    # ⭐ __cf_bm 寿命约 30min，取 5min 保守刷新（原 600s 太赌）
SLEEP_FLOOR = 1.5               # ⭐ 单请求最小间隔（原 0.8 太激进）
SLEEP_JITTER = 0.8              # ⭐ 抖动上限，打散固定节奏
BACKOFF_STEPS = (1800, 3600, 7200, 14400)   # 30min → 1h → 2h → 4h

# 补全浏览器头，降低 CF bot score（原实现只有 User-Agent）
# ⚠ 故意**不发 Accept-Encoding**：urllib 不会自动解压，发了 gzip 会让 json 解析失败。
_HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Chromium";v="126", "Not:A-Brand";v="24", "Google Chrome";v="126"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


class IGGMBlocked(RuntimeError):
    """撞上 Cloudflare 挑战 / 被限 —— 调用方必须**立刻停止本轮所有 IGGM 请求**。"""


# 熔断状态：fails = 连续失败次数；until = 冷却截止时间戳（已搬进 _Sess）


def new_session(name="adhoc"):
    """给调用方一条**干净独立**的会话（不共享 cookie / 不共享熔断）。"""
    return _Sess(name)


def _reset_session(sess=None):
    """⭐ 关键修复：清空 CookieJar 并重建 opener。

    原实现撞挑战时只清 `_PRIMED` 标志，jar 里那个失效的 `__cf_bm` 会被一直带着发出去，
    导致 prime 永远 403 —— 这就是「一封就连续十几轮、且不会自愈」的根因。
    """
    (sess or _ITEM).reset()


def _backoff(blocked=True, sess=None):
    """失败 → 递增冷却；成功 → 归零。返回本次冷却秒数。"""
    s = sess or _ITEM
    if not blocked:
        s.fails = 0
        s.until = 0.0
        return 0
    s.fails += 1
    wait = BACKOFF_STEPS[min(s.fails, len(BACKOFF_STEPS)) - 1]
    s.until = time.time() + wait
    return wait


def _blocked_now(sess=None):
    """冷却期内 → True（调用方应直接放弃，一次网络都不要打）。"""
    return time.time() < (sess or _ITEM).until


def breaker_state(sess=None):
    """给看板/日志看熔断状态（只读）。缺省 = 物品侧（保持老调用方行为）。"""
    s = sess or _ITEM
    return {"sess": s.name, "fails": s.fails,
            "cooling": _blocked_now(s),
            "remain_s": max(0, int(s.until - time.time()))}


def breaker_state_all():
    """两条主缸的熔断状态（采集日志 / 看板用）。"""
    return {"items": breaker_state(_ITEM), "gold": breaker_state(_GOLD)}


def _sleep(base=None):
    """降速 + 抖动：不低于 SLEEP_FLOOR，再叠一个随机抖动。"""
    try:
        b = float(base if base is not None else 0.8)
    except (TypeError, ValueError):
        b = 0.8
    time.sleep(max(b, SLEEP_FLOOR) + random.uniform(0, SLEEP_JITTER))


def _prime(referer, timeout=30, force=False, sess=None):
    """请求一次页面拿 Cloudflare cookie；失败会**清 jar 重建**后重试一次。"""
    s = sess or _ITEM
    now = time.time()
    if not force and s.primed_ok and (now - s.primed_ts) < CF_TTL:
        return True
    url = referer or (BASE + "/")
    for attempt in (0, 1):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with s.opener.open(req, timeout=timeout) as r:
                body = r.read()
            if CF_MARK.encode("utf-8") in body:      # HTTP 200 也可能是挑战页
                raise RuntimeError("prime 拿到挑战页（len=%d）" % len(body))
            s.primed_ok = True
            s.primed_ts = time.time()
            return True
        except Exception:
            # ⭐ 每次都从干净会话重试，绝不复用失效 cookie
            s.reset()
            if attempt == 0:
                time.sleep(1.0)
    return False


def _get(url, referer=None, timeout=30, retry=3, sess=None):
    """打 ajax。撞 CF 挑战 → 会话自愈重试；仍失败 → 抛 `IGGMBlocked`（调用方须停轮）。

    sess：走哪条会话（缺省 = 物品侧 _ITEM；金币侧传 GOLD_SESSION）。
          会话自带熔断，所以金币不会被物品侧的冷却拖住。
    """
    s = sess or _ITEM
    if _blocked_now(s):
        raise IGGMBlocked("IGGM(%s) 熔断冷却中（剩余 %.0f 分钟）"
                          % (s.name, (s.until - time.time()) / 60.0))
    headers = dict(_HEADERS)
    if referer:
        headers["Referer"] = referer
        headers["X-Requested-With"] = "XMLHttpRequest"
    last, cf_fail = None, 0
    for i in range(retry):
        try:
            if referer:             # 先补页面 cookie 再打 ajax（挑战拦截的解法）
                if not _prime(referer, timeout, force=(i > 0), sess=s):
                    raise IGGMBlocked("prime 失败（页面被 CF 拦）")
            req = urllib.request.Request(url, headers=headers)
            with s.opener.open(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
            if CF_MARK in body:     # HTTP 200 也可能是挑战页
                raise IGGMBlocked("撞上 Cloudflare 挑战页（len=%d）" % len(body))
            _backoff(blocked=False, sess=s)         # ⭐ 成功即把连续失败归零
            return body
        except urllib.error.HTTPError as e:
            net_util.drain_close(e)   # 2026-10-16 修 socket 泄漏：403 响应体不读就抛会把连接卡在 Recv-Q
            if e.code in (403, 429, 503):
                s.reset()                   # ⭐ 拦截态 → 会话已被污染，重建
                last, cf_fail = IGGMBlocked("HTTP %d（CF 拦截）" % e.code), cf_fail + 1
            else:
                s.primed_ok = False
                last = e
        except IGGMBlocked as e:
            s.reset()
            last, cf_fail = e, cf_fail + 1
        except Exception as e:              # 网络抖动：不清 jar，重试
            s.primed_ok = False
            last = e
        if cf_fail >= 2:                    # ⭐ 连续 2 次拦截判定 = 已被封，别再多打
            break
        time.sleep(min(1.5 * (i + 1), 5))
    if isinstance(last, IGGMBlocked):
        wait = _backoff(blocked=True, sess=s)
        raise IGGMBlocked("%s ｜ %s 已熔断，冷却 %.0f 分钟"
                          % (last, s.name, wait / 60.0))
    raise last


def goods_ajax(game_sku, server_id, cate_id, page=1, referer=None):
    qs = urllib.parse.urlencode({
        "template_type": "items", "server_id": str(server_id), "cate_id": str(cate_id),
        "game_sku": game_sku, "sort": 0, "goods_name": "", "tag": "", "page": page,
    })
    body = _get(BASE + "/goods/goods_ajax?" + qs, referer=referer)
    return (json.loads(body) or {}).get("data") or {}


def goods_ajax_gold(game_sku, server_id, referer=None):
    """金币行情（golds 模板）。返回 data 原样（含 one_goods / result_goods）

    ⚠ 2026-10-19：固定走金币缸（GOLD_SESSION），与物品全量抓取互不影响。
    """
    qs = urllib.parse.urlencode({
        "template_type": "golds", "server_id": str(server_id), "cate_id": 0,
        "game_sku": game_sku,
    })
    body = _get(BASE + "/goods/goods_ajax?" + qs, referer=referer, sess=_GOLD)
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
        _sleep(ig.get("请求延迟秒", 0.8))       # 2026-10-09：降速 + 抖动
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
        if _blocked_now():                          # ⭐ 已熔断 → 一个都别再打
            log("  [IGGM] ⛔ 熔断冷却中，中止本轮其余服务区")
            break
        try:
            rows = scrape_target(cfg, t, log=log)
            for r in rows:
                r["zone_key"] = t["key"][5:]        # 去掉 IGGM_ 前缀 → 配置里的服务区 key
            out += rows
        except IGGMBlocked as e:
            log("  [IGGM] ⛔ 被 CF 拦，中止本轮其余服务区：%s" % e)
            break
        except Exception as e:
            log("  [IGGM] %s 抓取失败: %r" % (t.get("名称"), e))
        _sleep(delay)
    return out


# 上一轮 scrape_all 的结果摘要（2026-10-19）
# 为什么要它：`scrape_all` 返回 [] 有**两种完全不同的原因** ——
#   ① 被 CF 拦（blocked = True，需要告警 + 金币兜底）；
#   ② 本轮到期的游戏本来就没有 IGGM 目标（例如只有 AION2 / 冒险岛到期，
#      它们的价走 core_gold 那条线，不走 scrape_all）⇒ 0 条是**正常**。
# 上层只看 rows 会把 ② 当成 ①，一晚上发十几条误报的告警。
LAST_RUN = {"ts": "", "blocked": False, "rows": 0, "reason": ""}


def last_run():
    """上一轮 scrape_all 的结果摘要（只读副本）。"""
    return dict(LAST_RUN)


def _mark_run(blocked, rows, reason=""):
    LAST_RUN.update({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "blocked": bool(blocked), "rows": int(rows or 0),
                     "reason": reason or ""})


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
    """多游戏：按服务区抓金币行情 → 一条 `G:<服务区key>` 行（每万金价）

    ⚠ 2026-10-19：整段走**金币缸**（GOLD_SESSION）—— cookie 与熔断都与物品侧分开，
      物品全量被抓也不会拖停金币。
    """
    out = []
    delay = float(((cfg.get("iggm") or {}).get("请求延迟秒", 0.8)) or 0.8)
    for t in gold_targets(cfg, games=games):
        if _blocked_now(_GOLD):                     # ⭐ 金币缸熔断 → 一个都别再打
            log("  [IGGM/金币] ⛔ 金币侧熔断冷却中，中止本轮其余金币区")
            break
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
        except IGGMBlocked as e:
            log("  [IGGM/金币] ⛔ 被 CF 拦，中止本轮其余金币区：%s" % e)
            break
        except Exception as e:
            log("  [IGGM/金币] %s 抓取失败: %r" % (t.get("名称"), e))
        _sleep(delay)
    return out


D4_GAME = "暗黑破坏神4"      # IGGM 主站分类（`目标` + `扩展分类`）固定归暗黑4


def scrape_golds_only(cfg, log=print, games=None):
    """**只抓金币**的独立通道（2026-10-19 新增）。

    背景：`scrape_all` 一旦物品侧被 CF 拦，就整轮返回 []（合同：杜绝"半份快照"）。
    但金币侧只有十几个区、量小得多，物品被封时它往往还是通的；而金币是改价基准，
    丢了这一轮就没价可跟。上层（app.task_collect）在 0 条时调这里补一次：
    抓到的金币行用于覆盖快照里的 G:xxx 行，其余行由 carryover 沿用上一份。

    返回 rows（可能为空，不抛异常）。
    """
    try:
        return scrape_golds(cfg, log=log, games=games)
    except IGGMBlocked as e:
        log("  [IGGM/金币] ⛔ 独立通道也被拦：%s" % e)
    except Exception as e:
        log("  [IGGM/金币] 独立通道异常：%r" % e)
    return []


def scrape_all(cfg, log=print, games=None):
    """抓 config 里所有启用的目标（暗黑4 分类 + 多游戏服务区 + 多游戏金币）

    games: 只抓这些游戏（= 本轮按采集周期到期的那批）；None = 全抓（向后兼容）。
           主站分类（`目标` + `扩展分类`）固定归「暗黑破坏神4」。
    """
    if _blocked_now():                              # ⭐ 熔断中 → 整轮直接放弃
        log("  [IGGM] ⛔ 熔断冷却中（%s），本轮整轮跳过，沿用上一份快照"
            % breaker_state())
        _mark_run(True, 0, "熔断冷却中（上一轮已被拦）")
        return []
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
    out, blocked = [], False
    for t in targets:
        if _blocked_now():
            blocked = True
            break
        try:
            out += scrape_target(cfg, t, log=log)
        except IGGMBlocked as e:
            log("  [IGGM] ⛔ 被 CF 拦，中止本轮其余主站分类：%s" % e)
            blocked = True
            break
        except Exception as e:
            log("  [IGGM] %s 抓取失败: %r" % (t.get("名称"), e))
        _sleep(0.5)
    # 多游戏（POE2 …）：物品全量 + 金币（已被拦则整轮都不再打）
    if not blocked:
        try:
            out += scrape_zones(cfg, log=log, games=games)
        except IGGMBlocked as e:
            log("  [IGGM] ⛔ 多游戏服务区被拦：%s" % e)
            blocked = True
        except Exception as e:
            log("  [IGGM] 多游戏服务区抓取失败: %r" % e)
    if not blocked:
        try:
            out += scrape_golds(cfg, log=log, games=games)
        except IGGMBlocked as e:
            log("  [IGGM] ⛔ 多游戏金币被拦：%s" % e)
            blocked = True
        except Exception as e:
            log("  [IGGM] 多游戏金币抓取失败: %r" % e)
    # 🔴 被拦时整轮返回 []：让上层沿用上一份**完整**快照。
    #   绝不返回「半个快照」—— 半份会让看板缺行、下一轮比价基线断。
    if blocked:
        log("  [IGGM] ⛔ 本轮被 CF 拦，整轮返回 0 条（上层沿用上一份完整快照）")
        _mark_run(True, 0, "本轮被 CF 拦")
        return []
    _mark_run(False, len(out), "" if out else "本轮无到期 IGGM 目标（正常空）")
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
