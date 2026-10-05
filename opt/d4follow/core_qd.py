# -*- coding: utf-8 -*-
"""千岛采购成本抓取（暗黑4专区）

千岛接口带签名（x-request-sign / HMAC_SHA256），外部直接请求返回 405。
所以走 Playwright 打开页面、拦截页面自身的响应，让页面自己去算签名。

【区服切换】改写请求体而不是写 localStorage。2026-09-20 实测：千岛换了前端
（Naive UI 级联），localStorage 里已经没有 server-spec 键，老办法会静默失效
—— 四个区服抓回同一份数据。改写 specIds / filters 实测有效。

【两级取价】
  ① 平台聚合价 `currency-spu-price-list`.rmbPrice —— 滞后参考价，仅用来拿
     spuId 与名称映射；**不再作为进货成本**。
  ② 订单簿 `currency/spu-list-v2` —— 真实在售清单（带 stock 库存 /
     minBuyCount 起售量 / rmbPrice 单价），用「深度加权进价 DWC」算成本。
     2026-09-27 实测：强力巢穴钥匙聚合价 0.0362 时，订单簿最低可买价已 0.049，
     低价档 5 分钟内被买光 → 聚合价不可信。

【抓取成本】订单簿必须在页面上「打开某个 SPU」才会发请求。为把 5 个 SPU ×
N 个区服压到 **一次页面加载 + 一次点击**，用 page.route 的 `route.fetch()`
复用页面那条已鉴权的请求当模板，重放成任意 (spuId, 区服) 组合。
`route.fetch()` 只是把 body 换掉重放，签名头沿用页面原请求 —— 实测签名不覆盖 body。

【限流】千岛对高频访问会返回 405「您的手速也太快了」。命中即整轮放弃，
让上层沿用上一次快照，绝不写入 0。
"""
import json
import os
import time

API_MARK = "currency-spu-price-list"
BOOK_MARK = "spu-list-v2"

# ============================================================ 远端渲染后端
# 生产机是 CentOS 7.9（glibc 2.17），Playwright 的 Node driver 与 Chromium 要求
# glibc >= 2.27，在宿主机上装不起来。于是把「浏览器」这一段整体搬进 Docker 容器
# （mcr.microsoft.com/playwright/python），宿主机只通过 127.0.0.1:9223 调它。
# 容器不可用时自动回退本机 Playwright —— 所以本机执行器 / 旧机等环境行为完全不变。
RENDER_URL_DEFAULT = "http://127.0.0.1:9223"
_render_probe = {"url": "", "ts": 0.0, "ok": False}


def render_url(cfg=None):
    """返回可用的远端渲染服务地址；不可用返回 ""。

    优先级：环境变量 QD_RENDER_URL > config 千岛.渲染服务URL > 默认 127.0.0.1:9223。
    QD_RENDER_URL 显式设成 off/0/local/none/false/no 表示「强制本机」——容器内
    跑 core_qd 时必须这样，否则会自己调自己造成无限递归。
    探测结果缓存 60s，避免每次抓取都先探一次。
    """
    u = (os.environ.get("QD_RENDER_URL") or "").strip()
    if u.lower() in ("0", "off", "local", "none", "false", "no"):
        return ""
    if not u and cfg:
        try:
            u = str((cfg.get("千岛") or {}).get("渲染服务URL") or "").strip()
        except Exception:
            u = ""
    if not u:
        u = RENDER_URL_DEFAULT
    now = time.time()
    if _render_probe["url"] == u and now - _render_probe["ts"] < 60:
        return u if _render_probe["ok"] else ""
    ok = _render_alive(u)
    _render_probe.update({"url": u, "ts": now, "ok": ok})
    return u if ok else ""


def _render_alive(u, timeout=3):
    import urllib.request
    try:
        with urllib.request.urlopen(u.rstrip("/") + "/health", timeout=timeout) as r:
            return 200 <= int(getattr(r, "status", 200)) < 300
    except Exception:
        return False


def _render_post(u, path, payload, timeout=480):
    """调容器抓取。千岛一轮 1~2 分钟，超时给到 8 分钟。"""
    import urllib.request
    req = urllib.request.Request(
        u.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

# 暗黑4通货区服 id 全集（改写请求时用来识别「这一格就是区服」）
SPEC_POOL = ("278378", "278379", "278380", "278381", "278382", "278384")

SCROLL_JS = """() => {
  let n = 0;
  document.querySelectorAll('*').forEach(e => {
    const s = getComputedStyle(e);
    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') && e.scrollHeight > e.clientHeight + 20) {
      e.scrollTop = e.scrollHeight; n++;
    }
  });
  return n;
}
"""

# 在左侧列表里精确定位商品名并派发一次真实点击（比 Playwright 的 click 更耐操：
# 不受可操作性检查/遮挡影响；配合 closest('li') 命中商品卡片）
JS_OPEN_SPU = """(n) => {
  const all = [...document.querySelectorAll('div,span,a,li,p')];
  let c = all.filter(e => (e.textContent || '').trim() === n);
  if (!c.length) c = all.filter(e => (e.textContent || '').includes(n));
  if (!c.length) return 0;
  c.sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
  const el = c[0].closest('li') || c[0].parentElement || c[0];
  el.scrollIntoView({block: 'center'});
  el.dispatchEvent(new MouseEvent('click', {bubbles: true}));
  return 1;
}"""

THROTTLE_MARK = "手速太快"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DEFAULT_BOOK = {
    "起售阈值": 10,     # 起售量 >= 10 视为「整批卖」的卖家
    "批量档": 1000,     # 整批卖 → 我们按这个补货批量 Q 算单价
    "单件档": 50,       # 零售（可单个买）→ 按这个 Q 算单价
    "占比阈值": 0.5,    # 「整批卖」的库存量占比 >= 此值 → 判为批量档
    "跳过倍数": 2.0,    # 为凑剩余需求要买 > need×倍数 的整条 → 跳过
    "超深倍数": 3.0,    # Q > 全簿可售库存 × 此值 → 判定不适用，退回单件档
    "最大翻页": 8,
}


def canon_spec(label):
    """区服标签统一成「A / B / C」（带空格），否则两份数据落不到同一个键下"""
    parts = [p.strip() for p in str(label or "").split("/")]
    return " / ".join(p for p in parts if p)


def _int(v, d=0):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return d


def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


# ============================================================ 订单簿深度加权进价（DWC）
def sell_rows(rows):
    """只留真正可买、按单价升序的在售条目（direction=SELL 且单价 > 0）"""
    out = []
    for r in rows or []:
        if str(r.get("direction") or "SELL").upper() != "SELL":
            continue
        if _f(r.get("rmbPrice")) <= 0:
            continue
        out.append(r)
    out.sort(key=lambda r: _f(r.get("rmbPrice")))
    return out


def pick_q(rows, th=10, bulk_q=1000, single_q=50, share=0.5):
    """判档：这批货是「整批卖」还是「零售」。

    不写死起售量 —— 实测千岛起售量是任意整数（15/93/197/300/361/900…），
    所以按**库存量**加权：起售量 >= th 的那部分库存占比 >= share 就判批量档。
    返回 (Q, 批量占比, 全簿可售库存)
    """
    tot = bulk = 0
    for r in rows:
        stk = max(0, _int(r.get("stock")))
        if stk <= 0:
            continue
        tot += stk
        if max(1, _int(r.get("minBuyCount"), 1)) >= th:
            bulk += stk
    if tot <= 0:
        return single_q, 0.0, 0
    ratio = bulk / float(tot)
    return (bulk_q if ratio >= share else single_q), ratio, tot


def book_cost(rows, q, skip_ratio=2.0):
    """从低价往上吃深度，算加权均价（VWAP）。返回 (单价, 实吃量, 备注)

    用户口径的正式化：库存 300@1 元 + 700@1.5 元，Q=1000
    → (300×1 + 700×1.5) / 1000 = 1.35 元。
    """
    used, cost, skipped = 0, 0.0, 0
    for r in rows:
        if used >= q:
            break
        need = q - used
        pr = _f(r.get("rmbPrice"))
        stk = max(0, _int(r.get("stock")))
        moq = max(1, _int(r.get("minBuyCount"), 1))
        if stk <= 0 or moq > q:            # 买不到 / 起售量比我们的批量还大 → 跳过
            skipped += 1
            continue
        take = min(stk, need)
        if take < moq:                     # 剩余需求不足这一条的最小起售
            if moq > need * skip_ratio:    # 为一点点余量再吃一大坨 → 不值当
                skipped += 1
                continue
            take = min(stk, moq)           # 整条买下（会小幅超出 Q）
        cost += pr * take
        used += take
    if used <= 0:
        return None, 0, "无可吃深度"
    note = []
    if used < q:
        note.append("深度不足")
    if skipped:
        note.append("跳过%d档" % skipped)
    return cost / used, used, "/".join(note)


def book_price(rows, qcfg=None):
    """按 DWC 口径给一个 SPU 算进货单价。返回 dict 或 None"""
    c = dict(DEFAULT_BOOK)
    c.update(qcfg or {})
    rs = sell_rows(rows)
    if not rs:
        return None
    q, ratio, tot = pick_q(rs, _int(c["起售阈值"], 10), _int(c["批量档"], 1000),
                           _int(c["单件档"], 50), _f(c["占比阈值"], 0.5))
    tier = "批量档" if ratio >= _f(c["占比阈值"], 0.5) else "单件档"
    # 整簿都填不满 Q（或 Q 远超全簿深度）→ 批量口径的前提不成立，退回单件档。
    # 实测：腐化根藤全簿只有 811 个，却被判「批量档 Q=1000」→ 吃光全簿、单价虚高 172%。
    sup = _f(c.get("超深倍数"), 3.0)
    q_tier = q
    if tot > 0 and (tot < q_tier or q_tier > tot * sup):
        thin = tot < q_tier
        q = _int(c["单件档"], 50)
        tier = "整簿不足Q退回单件档" if thin else "退回单件档"
    v, u, n = book_cost(rs, q, _f(c.get("跳过倍数"), 2.0))
    if not v:
        return None
    return {"q": q, "vwap": v, "used": u, "depth": tot, "bulk_share": ratio,
            "n": len(rs), "lo": _f(rs[0].get("rmbPrice")),
            "note": "/".join(x for x in (n, tier) if x)}


# ============================================================ 平台聚合价（拿 spuId / 名称映射）
def _listener(bucket):
    def on_resp(r):
        if API_MARK not in r.url:
            return
        try:
            d = (r.json() or {}).get("data") or {}
        except Exception:
            return
        for it in (d.get("items") or []):
            bucket[it.get("spuId")] = it
    return on_resp


def _route(state):
    def handler(route):
        spec = state.get("spec")
        try:
            req = route.request
            if spec and req.post_data:
                body = json.loads(req.post_data)
                if "specIds" in body:
                    body["specIds"] = [str(spec)]
                    route.continue_(post_data=json.dumps(body))
                    return
        except Exception:
            pass
        route.continue_()
    return handler


def _collect(page, cfg_qd, bucket, first_wait_ms=25000, idle_rounds=4):
    """滚动 + 收数，直到「首条超时」或「连续 idle_rounds 轮无新增」。

    ⚠ 桶还空着的时候**不能**用「连续几轮无新增」判定收尾：首屏走 page.goto 冷启动，
    SPA 初始化慢，聚合价请求可能 10 秒后才发出；旧的「4 轮（≈2.8s）就 break」会让
    **第 1 个区服抓回 0 条**（2026-09-27 11:49 实测：对标区服 0 条 → 上层静默降级到
    「专家」硬核服取成本 → 成本虚高 10 倍、毛利率 -630%）。
    所以桶为空时改成等「首条超时」；一旦拿到数据，再按「无新增轮数」快速收尾。
    """
    t0 = time.time()
    last, stuck = -1, 0
    for _ in range(int(cfg_qd.get("最大滚动次数", 60))):
        try:
            page.evaluate(SCROLL_JS)
        except Exception:
            pass
        page.wait_for_timeout(700)
        n = len(bucket)
        if n == last:
            stuck += 1
            if n == 0:
                if (time.time() - t0) * 1000.0 >= float(first_wait_ms):
                    break
            elif stuck >= int(idle_rounds):
                break
        else:
            stuck = 0
        last = n
    return list(bucket.values())


def _throttled(page):
    """千岛限流页：HTTP 405 + 「您的手速也太快了」"""
    try:
        t = page.inner_text("body") or ""
    except Exception:
        return False
    return THROTTLE_MARK in t


def scrape(cfg, log=print, info=None):
    """返回聚合价原始条目列表（千岛接口原样），每条带 _spec_label / _spec_id

    info: 可选 dict，回填 {"missed": [区服标签...], "specs": {sid: 条数}}，供 fetch() 做护栏。
    """
    qd = cfg["千岛"]
    if not qd.get("enabled", True):
        log("  [千岛] 已关闭，跳过")
        return []
    _u = render_url(cfg)
    if _u:                                                 # 走容器（CentOS 7 唯一可行路径）
        try:
            log("  [千岛] 渲染后端 = 容器 %s" % _u)
            _r = _render_post(_u, "/scrape", {})
            for _l in (_r.get("log") or []):               # 回放容器内日志，运维可见性不变
                log(_l)
            if info is not None:
                info["missed"] = _r.get("missed") or []
                info["counts"] = _r.get("counts") or {}
            return _r.get("rows") or []
        except Exception as e:
            log("  [千岛] ⚠ 容器渲染后端异常(%r)，回退本机 Playwright" % (e,))
    from playwright.sync_api import sync_playwright        # 懒 import：不抓千岛时不依赖

    spec_map = {str(k): canon_spec(v) for k, v in (qd.get("区服") or {}).items()}
    specs = [str(x) for x in (qd.get("抓取区服") or [])]
    if not specs:
        log("  [千岛] config 没配「抓取区服」，跳过")
        return []

    rows, state = [], {"spec": specs[0]}
    missed, counts = [], {}
    with sync_playwright() as p:
        br = p.chromium.launch(headless=bool(qd.get("headless", True)),
                               args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1500, "height": 950}, locale="zh-CN",
                             user_agent=UA)
        page = ctx.new_page()
        bucket = {}
        page.on("response", _listener(bucket))
        page.route("**/%s*" % API_MARK, _route(state))
        for i, sid in enumerate(specs):
            label = spec_map.get(sid, sid)
            try:
                state["spec"] = sid
                bucket.clear()                    # 必须在 reload 之前清，否则清掉新首页
                if i == 0:
                    page.goto(qd["url"], wait_until="commit", timeout=120000)
                else:
                    page.reload(wait_until="commit", timeout=120000)
                page.wait_for_timeout(6500)
                if _throttled(page):
                    log("  [千岛] ⚠ 被限流（405 手速太快），本轮放弃")
                    ctx.close()
                    br.close()
                    return []
                items = _collect(page, qd, bucket)
                # ★ 单个区服 0 条 ≠「该区服没货」，是抓取失败 → 重载重试。
                #   首屏冷启动最容易中招（见 _collect 注释），第 2/3 个区服走 reload 很少掉。
                for attempt in range(2):
                    if items:
                        break
                    log("  [千岛] ⚠ %s 抓成 0 条，重试 %d/2" % (label, attempt + 1))
                    bucket.clear()
                    state["spec"] = sid
                    page.reload(wait_until="commit", timeout=120000)
                    page.wait_for_timeout(3000)
                    if _throttled(page):
                        log("  [千岛] ⚠ 被限流（405 手速太快），本轮放弃")
                        ctx.close()
                        br.close()
                        return []
                    items = _collect(page, qd, bucket)
                for it in items:
                    it["_spec_id"] = sid
                    it["_spec_label"] = label
                rows += items
                counts[label] = len(items)
                if items:
                    log("  [千岛] 区服=%s -> %d 条" % (label, len(items)))
                else:
                    missed.append(label)
                    log("  [千岛] ✘ 区服=%s -> 0 条（重试后仍空，该区服记为抓取失败）" % label)
            except Exception as e:
                missed.append(label)
                counts[label] = 0
                log("  [千岛] %s 抓取异常: %r" % (label, e))
            time.sleep(1.2)
        ctx.close()
        br.close()

    if info is not None:
        info["missed"] = missed
        info["counts"] = counts
    if missed:
        log("  [千岛] ⚠⚠ 本轮 %d 个区服抓成 0 条：%s —— 上层不得据此覆盖完整快照"
            % (len(missed), "、".join(missed)))

    # 兜底自检：两个区服指纹完全相同 = 改写失效（静默失败，最难发现）
    fp = {}
    for r in rows:
        fp.setdefault(r["_spec_label"], set()).add((r.get("spuName"), r.get("rmbPrice")))
    labs = list(fp.keys())
    if len(labs) >= 2:
        for a in range(len(labs)):
            for b in range(a + 1, len(labs)):
                if fp[labs[a]] and fp[labs[a]] == fp[labs[b]]:
                    log("  [千岛] ⚠ 区服 %s 与 %s 数据完全相同 → 区服切换可能已失效"
                        % (labs[a], labs[b]))
    return rows


# ============================================================ 缓存层（聚合价）
def _cache_path(cfg, key="缓存文件", default="data/qiandao_latest.json"):
    qd = cfg["千岛"]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), qd.get(key, default))


def load_cache(cfg, max_hours=None):
    path = _cache_path(cfg)
    if not os.path.exists(path):
        return None, None
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None, None
    ts = d.get("saved_at")
    if not ts:
        return None, None
    h = (time.time() - _epoch(ts)) / 3600.0
    lim = float(max_hours if max_hours is not None else cfg["千岛"].get("缓存最长小时", 3))
    if h > lim:
        return None, ts
    return d, ts


def save_cache(cfg, rows, ts):
    path = _cache_path(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"saved_at": ts, "rows": rows}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False)


def _epoch(iso):
    import datetime as dt
    try:
        return dt.datetime.fromisoformat(iso).timestamp()
    except Exception:
        return 0.0


def fetch(cfg, log=print, force=False, max_age_hours=None):
    """带缓存的聚合价取数。返回 (rows, ts, from_cache)"""
    import datetime as dt
    if not force:
        d, ts = load_cache(cfg, max_age_hours)
        if d:
            log("  [千岛] 命中缓存（%s），不重抓" % ts)
            return d["rows"], ts, True
    log("  [千岛] 开始抓取…")
    info = {}
    rows = scrape(cfg, log=log, info=info)
    ts = dt.datetime.now().isoformat(timespec="seconds")
    if rows:
        # ★ 按区服合并：本轮没抓到的区服，沿用上一份快照 ——
        #   绝不因为「部分成功」就把整份好快照覆盖成残缺快照。
        #   （2026-09-27 11:49 事故：284 条缺对标区服的数据覆盖了 552 条完整快照，
        #     导致成本被静默降级到「专家」参考区服，毛利率变成 -630%。）
        old, old_ts = load_cache(cfg, max_hours=1e9)
        old_rows = ((old or {}).get("rows")) or []
        want = {str(x) for x in (cfg["千岛"].get("抓取区服") or [])}
        got = {str(r.get("_spec_id")) for r in rows}
        keep = [r for r in old_rows if str(r.get("_spec_id")) not in got]
        if keep:
            labs = sorted({str(r.get("_spec_label")) for r in keep})
            log("  [千岛] ⚠ 本轮只抓到 %d/%d 个区服，沿用上一份快照（%s）补齐 %d 条：%s"
                % (len(got), len(want) or len(got), old_ts, len(keep), "、".join(labs)))
            rows = rows + keep
        still = want - {str(r.get("_spec_id")) for r in rows}
        if still:
            log("  [千岛] ✘✘ 补不齐的区服 %s —— 快照不完整，成本会走降级，看板必须告警"
                % (sorted(still),))
        save_cache(cfg, rows, ts)
    else:
        log("  [千岛] 本轮 0 条，保留上一次缓存不覆盖")
        d, _ = load_cache(cfg, max_hours=1e9)
        if d:
            return d["rows"], d["saved_at"], True
    return rows, ts, False


# ============================================================ 订单簿抓取
def _force_spec(body, sid, label, attr_id=""):
    """把请求体里的区服筛选项改成目标区服；改不到就自己塞一个。"""
    hit = False
    for f in (body.get("filters") or []):
        sv = f.get("selectedQueryValue") or {}
        for cv in (sv.get("candidateValues") or []):
            if str(cv.get("value")) in SPEC_POOL:
                cv["value"] = str(sid)
                cv["label"] = label
                hit = True
    if not hit and attr_id:
        body.setdefault("filters", [])
        body["filters"] = [f for f in body["filters"] if f.get("key") != attr_id]
        body["filters"].append({
            "key": attr_id, "keyType": "ATTRIBUTE", "filterOperType": "EQ",
            "isNot": False,
            "selectedQueryValue": {"candidateType": "SINGLE_VALUE",
                                   "candidateValues": [{"label": label, "value": str(sid)}]}})
    body["limit"] = 100
    return body


def scrape_books(cfg, targets, log=print, specs=None):
    """抓订单簿。targets: [(spu_id, 商品名), ...]  返回 (books, meta)

    books: {"<spec>|<spu_id>": {"items": [...], "total": n, "name": 商品名}}
    用一次页面加载 + 一次点击，靠 route.fetch 重放成全组合。
    """
    qd = cfg["千岛"]
    bk = dict(DEFAULT_BOOK)
    bk.update(qd.get("订单簿") or {})
    if not bk.get("enabled", True):
        return {}, {"ok": False, "err": "订单簿已关闭"}
    targets = [(str(s), n) for s, n in (targets or []) if s]
    if not targets:
        return {}, {"ok": False, "err": "无目标 SPU"}
    specs = [str(x) for x in (specs or qd.get("抓取区服") or [])]
    if not specs:
        return {}, {"ok": False, "err": "无区服"}
    spec_labels = {str(k): canon_spec(v) for k, v in (qd.get("区服") or {}).items()}
    attr_id = str(qd.get("attribute_id") or "")

    _u = render_url(cfg)
    if _u:                                                 # 走容器（CentOS 7 唯一可行路径）
        try:
            log("  [千岛·订单簿] 渲染后端 = 容器 %s" % _u)
            _r = _render_post(_u, "/scrape_books",
                              {"targets": [[s, n] for s, n in targets],
                               "specs": specs})
            for _l in (_r.get("log") or []):               # 回放容器内日志
                log(_l)
            return _r.get("books") or {}, _r.get("meta") or {}
        except Exception as e:
            log("  [千岛·订单簿] ⚠ 容器渲染后端异常(%r)，回退本机 Playwright" % (e,))

    from playwright.sync_api import sync_playwright
    state = {"busy": False, "done": False, "books": {}, "err": None, "blocked": False,
             "ms": 0}

    # ── 千岛订单簿 405 节流修复 2026-10-05 ──
    _gap = _f(bk.get("请求间隔秒"), 1.2)
    _try = _int(bk.get("退避重试"), 3)

    # ── 千岛订单簿 first 响应复用 2026-10-05 ──
    _first_box = {"r": None}

    def _fetch_book(route, body):
        """打一发订单簿请求。返回 (items, total, more, None) 或 (None, None, None, 原因)。

        首个成功响应会存进 _first_box 供 route.fulfill 复用 —— 原来为拿 first
        又额外打了一发，等于凭空多耗一份配额，本身就是加剧 405 的原因之一。
        """
        r = route.fetch(post_data=json.dumps(body, ensure_ascii=False))
        if r.status != 200:
            return None, None, None, "HTTP %s" % r.status
        try:
            d = (r.json() or {}).get("data") or {}
        except Exception as e:
            return None, None, None, "响应解析失败 %r" % (e,)
        if _first_box["r"] is None:
            _first_box["r"] = r
        got = d.get("items") or []
        return got, d.get("total"), bool(d.get("more")) and bool(got), None

    def route_book(route):
        if state["done"] or state["busy"]:
            return route.continue_()
        state["busy"] = True
        t0 = time.time()
        try:
            tmpl = json.loads(route.request.post_data or "{}")
            thin = []
            for spu, name in targets:
                for sid in specs:
                    body = json.loads(json.dumps(tmpl))
                    body["spuId"] = spu
                    body["offset"] = 0
                    _force_spec(body, sid, spec_labels.get(sid, sid), attr_id)
                    items, total, more, off, pages = [], None, True, 0, 0
                    why = None
                    while more and pages < _int(bk.get("最大翻页"), 8):
                        body["offset"] = off
                        got, total2, more2, err = None, None, False, "未发请求"
                        for a in range(_try):
                            if a:
                                time.sleep(_gap * (2 ** a))     # 指数退避
                            got, total2, more2, err = _fetch_book(route, body)
                            if err is None:
                                break
                        if err is not None:
                            why = err
                            break
                        items += got
                        total = total2 if total2 is not None else total
                        more = more2
                        off += 100
                        pages += 1
                        if more:
                            time.sleep(_gap)
                    if why or not items:
                        thin.append("%s/%s(%s)" % (name, spec_labels.get(sid, sid), why or "0 条"))
                    else:
                        log("    [千岛·订单簿] %s / %s -> %d 条"
                            % (name, spec_labels.get(sid, sid), len(items)))
                    state["books"]["%s|%s" % (sid, spu)] = {
                        "items": items, "total": total if total is not None else len(items),
                        "name": name}
                    time.sleep(_gap)                      # SPU/区服之间也节流
            state["done"] = True
            if thin:
                log("  ⚠️ [千岛·订单簿] %d/%d 个组合没抓到（上层将回退到滞后的聚合价）：%s"
                    % (len(thin), len(targets) * len(specs), "、".join(thin[:8])))
            if _first_box["r"] is not None:
                try:
                    route.fulfill(response=_first_box["r"])
                except Exception:
                    route.continue_()
            else:
                route.continue_()
        except Exception as e:
            state["err"] = repr(e)[:200]
            try:
                route.continue_()
            except Exception:
                pass
        finally:
            state["ms"] += int((time.time() - t0) * 1000)
            state["busy"] = False

    def route_price(route):
        try:
            b = json.loads(route.request.post_data or "{}")
            if "specIds" in b:
                b["specIds"] = [specs[0]]
            route.continue_(post_data=json.dumps(b, ensure_ascii=False))
        except Exception:
            route.continue_()

    with sync_playwright() as p:
        br = p.chromium.launch(headless=bool(qd.get("headless", True)),
                               args=["--disable-blink-features=AutomationControlled"])
        ctx = br.new_context(viewport={"width": 1500, "height": 950}, locale="zh-CN",
                             user_agent=UA)
        page = ctx.new_page()
        page.route("**/%s*" % API_MARK, route_price)
        page.route("**/%s*" % BOOK_MARK, route_book)
        try:
            page.goto(qd["url"], wait_until="commit", timeout=120000)
            page.wait_for_timeout(int(bk.get("打开等待毫秒", 12000)))
            if _throttled(page):
                state["blocked"] = True
                log("  [千岛·订单簿] ⚠ 被限流（405 手速太快），本轮放弃")
            else:
                names = [n for _, n in targets]
                for nm in names:
                    try:
                        if not page.evaluate(JS_OPEN_SPU, nm):
                            continue
                    except Exception as e:
                        log("  [千岛·订单簿] 点击 %s 异常 %r" % (nm, e))
                        continue
                    # 点一下让页面自己发第一条 spu-list-v2，route 里会重放全组合
                    for _ in range(int(bk.get("等待轮数", 40))):
                        page.wait_for_timeout(500)
                        if state["done"] or state["err"]:
                            break
                    if state["done"] or state["err"]:
                        break
                # 页面自己没有自动打开商品时，再点第一个候选名
                if not state["done"] and not state["err"] and not state["books"]:
                    try:
                        page.evaluate(JS_OPEN_SPU, names[0] if names else "")
                        for _ in range(40):
                            page.wait_for_timeout(500)
                            if state["done"] or state["err"]:
                                break
                    except Exception:
                        pass
        finally:
            ctx.close()
            br.close()

    meta = {"ok": bool(state["books"]), "n": len(state["books"]),
            "blocked": state["blocked"], "err": state["err"], "ms": state["ms"]}
    return state["books"], meta


# ---- 订单簿缓存（与聚合价缓存分开，TTL 独立）----
def load_book_cache(cfg, max_hours=None):
    path = _cache_path(cfg, "订单簿缓存文件", "data/qiandao_books.json")
    if not os.path.exists(path):
        return None, None
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None, None
    ts = d.get("saved_at")
    if not ts:
        return None, None
    bk = cfg["千岛"].get("订单簿") or {}
    lim = float(max_hours if max_hours is not None
                else bk.get("缓存小时", 1))
    if (time.time() - _epoch(ts)) / 3600.0 > lim:
        return None, ts
    return d.get("books") or {}, ts


def save_book_cache(cfg, books, ts):
    path = _cache_path(cfg, "订单簿缓存文件", "data/qiandao_books.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump({"saved_at": ts, "books": books}, open(path, "w", encoding="utf-8"),
              ensure_ascii=False)


def needed_spu(cfg, rows):
    """从对照项配置 + 聚合价行里，挑出真正要抓订单簿的 [(spu_id, 商品名)]"""
    names = set()
    for it in ((cfg.get("商品映射") or {}).get("对照项") or []):
        nm = (it.get("千岛") or {}).get("商品")
        if nm:
            names.add(nm)
    out = {}
    for r in (rows or []):
        nm = r.get("spuName") or r.get("name")
        spu = str(r.get("spuId") or r.get("spu_id") or "")
        if spu and nm in names:
            out[spu] = nm
    return sorted(out.items())


def _label2id(cfg):
    return {canon_spec(v): str(k) for k, v in ((cfg.get("千岛") or {}).get("区服") or {}).items()}


def norm_row(r, l2id):
    """把 SQLite 行（spu_id/name/price_cny）补成抓取器的键名，供 apply_books / save_qd 复用。"""
    if not r.get("spuId"):
        r["spuId"] = str(r.get("spu_id") or "")
    if not r.get("spuName"):
        r["spuName"] = r.get("name")
    if r.get("rmbPrice") is None:
        r["rmbPrice"] = _f(r.get("price_cny"))
    if not r.get("_spec_id"):
        r["_spec_id"] = l2id.get(canon_spec(r.get("spec")), "")
    if not r.get("_spec_label"):
        r["_spec_label"] = canon_spec(r.get("spec"))
    return r


def book_cache_info(cfg):
    """返回 (订单簿快照时间, 快照里有多少个 (区服,SPU))，不看 TTL。"""
    books, ts = load_book_cache(cfg, max_hours=1e9)
    return (ts, len(books or {})) if ts else (None, 0)


def apply_books(cfg, rows, log=print, force=False):
    """抓/取订单簿，把 DWC 单价写回 rows（改 rmbPrice 与 price_cny + 附加 _book_* 字段）。

    任何失败都**保持 rows 原样**（沿用聚合价/上一轮成本），绝不写 0、绝不中断。
    """
    import datetime as dt
    bk = (cfg["千岛"].get("订单簿") or {})
    rows = [norm_row(r, _label2id(cfg)) for r in (rows or [])]
    if not bk.get("enabled", True):
        return rows, {"src": "聚合价", "reason": "订单簿关闭", "hit": 0}
    targets = needed_spu(cfg, rows)
    if not targets:
        return rows, {"src": "聚合价", "reason": "无目标商品", "hit": 0}

    books, ts = (None, None) if force else load_book_cache(cfg)
    meta = {"src": "缓存"}
    if books is None:
        log("  [千岛·订单簿] 开始抓取 %d 个 SPU…" % len(targets))
        books, meta = scrape_books(cfg, targets, log=log)
        meta["src"] = "抓取"
        ts = dt.datetime.now().isoformat(timespec="seconds")
        if books:
            save_book_cache(cfg, books, ts)
        else:
            log("  [千岛·订单簿] 本轮 0 个订单簿（%s），沿用现有成本"
                % (meta.get("err") or ("被限流" if meta.get("blocked") else "页面未就绪")))
            meta.setdefault("hit", 0)
            return rows, meta
    else:
        log("  [千岛·订单簿] 命中缓存（%s），%d 个订单簿" % (ts, len(books)))

    qcfg = {k: v for k, v in bk.items() if k in DEFAULT_BOOK}
    hit = miss = 0
    for r in rows:
        key = "%s|%s" % (str(r.get("_spec_id") or ""), str(r.get("spuId") or ""))
        b = books.get(key)
        if not b:
            miss += 1
            continue
        info = book_price(b.get("items"), qcfg)
        if not info:
            miss += 1
            continue
        r["_agg_price"] = _f(r.get("rmbPrice"))         # 留档：改前的价
        r["rmbPrice"] = round(info["vwap"], 6)
        r["price_cny"] = r["rmbPrice"]
        r["_book_q"] = info["q"]
        r["_book_depth"] = info["depth"]
        r["_book_n"] = info["n"]
        r["_book_lo"] = info["lo"]
        r["_book_share"] = round(info["bulk_share"], 4)
        r["_book_note"] = info["note"]
        r["src"] = "book"
        hit += 1
    meta.update({"hit": hit, "miss": miss, "books": len(books),
                 "specs": len({k.split("|")[0] for k in books}),
                 "targets": len(targets), "ts": ts})
    log("  [千岛·订单簿] ✔ %d/%d 行改用订单簿价（%d 个 SPU × %d 区服，快照 %s）"
        % (hit, hit + miss, len(targets), meta["specs"], ts))
    return rows, meta


# ============================================================ 匹配
def pick(rows, spec_label, name_keywords):
    """在某个区服下按商品名匹配，返回该商品的最优报价。

    ⚠ 先**精确等于**，再退回**子串包含** —— 否则关键词「巢穴钥匙」会同时命中
    「强力巢穴钥匙 / 精良巢穴钥匙」，只能靠「取最低价」蒙对，缺货时会静默取错商品。
    """
    want = canon_spec(spec_label)
    exact, sub = [], []
    for r in rows:
        lab = canon_spec(r.get("_spec_label") or r.get("spec"))
        if lab != want:
            continue
        nm = str(r.get("spuName") or r.get("name") or "")
        pr = _f(r.get("rmbPrice") if r.get("rmbPrice") is not None
                else (r.get("price_cny") or 0))
        if pr <= 0:
            continue
        if any(nm == k for k in name_keywords):
            exact.append((pr, r))
        elif any(k in nm for k in name_keywords):
            sub.append((pr, r))
    cands = exact or sub
    if not cands:
        return None
    cands.sort(key=lambda x: x[0])
    r = dict(cands[0][1])
    r.setdefault("name", r.get("spuName"))
    r["price_cny"] = _f(r.get("rmbPrice") if r.get("rmbPrice") is not None
                        else (r.get("price_cny") or 0))
    r["_匹配"] = "精确" if exact else "子串"
    r["_低报价数"] = len(cands)
    return r


def pick_from_db(rows, spec_label, name_keywords):
    """给 SQLite 行用的薄封装（语义同上）"""
    return pick(rows, spec_label, name_keywords)


if __name__ == "__main__":
    root = os.path.dirname(os.path.abspath(__file__))
    cfg = json.load(open(os.path.join(root, "config.json"), encoding="utf-8"))
    rs, ts, cached = fetch(cfg, force=True)
    print("聚合价 %d 条 (ts=%s, cached=%s)" % (len(rs), ts, cached))
    rs, meta = apply_books(cfg, rs, force=True)
    print("订单簿:", meta)
    for r in rs[:40]:
        if r.get("src") == "book":
            print("  %-18s %-14s Q=%-6s 价格 %s→%s 深%s 档%s"
                  % (r["_spec_label"], r.get("spuName"), r.get("_book_q"),
                     r.get("_agg_price"), r.get("rmbPrice"), r.get("_book_depth"),
                     r.get("_book_note")))
