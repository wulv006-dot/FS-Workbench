# -*- coding: utf-8 -*-
"""DD373 进货成本采集 —— 永恒之塔2（AION2）国际服 · 基纳（Kinah）。

用户口径
------------------------------------------------
【2026-10-02】「成本 = 综合排序后展示的第一条商品价格」—— 已废弃。
【2026-10-06 · 现行】老板原话：「你选择 2 亿数量的金币，然后算均价来定价格」。

⇒ 成本口径 = **「买满 2 亿基纳」的订单簿加权均价**（不是最小那一笔散单的单价）：
     · 收集该区**全部可买挂单**：散单（单笔不拆，可供量 = max）+
       热卖商城（数量行 data-max，单位万基纳）；
     · 按**单价从低到高**逐条「吃」，吃到 2 亿基纳（= 20000 万基纳）为止；
     · 成本单价 = Σ(吃掉的数量 × 该条单价) ÷ Σ(吃掉的数量)。
   「够不够 2 亿」由整页（+不足时的后续页）可买总量判断，缺口写进备注。

⚠ 2026-10-06 起成本**参与定价**（不再只是监控）：
   core_gold.build_plan 在 AION2 线上模式（g2g_cheapold）里读它做两件事 ——
     ① **成本兜底**：竞品（cheapold）价 < 成本价 ⇒ 不再跟降，直接按成本价定价；
     ② **利润率下限**：目标价算完若利润率 < −10% ⇒ 抬到 成本 ÷ 1.1。
   ⇒ 本模块仍**只读**（不写 gold_price、不进工单），但它的产物是定价输入。

站点结构（2026-10-02 实测，与官方 API 一致）
------------------------------------------------
专区      永恒之塔2国际服  Identify=1w9k8n
          游戏 GUID = b392a002e316467fb25133c2110a61c4
商品类型  基纳  GUID = 76c9f6b688934f8283dae5e643c2da99（Property=游戏币）
区（5）    日服 heft1r / 北美西 vshs5k / 北美东 6hw3s0 / 南美 72kds4 / 欧服 n98us6
种族（2）  天族 / 魔族，每区各一套
游戏区     区+种族之下还有第三层（Siel / Azphel / Nezekan / Zikel …），
          全站共 36 个，正好一一对应我方 34 个服务区（日服多 Vaizel/Triniel/Nezakan）

商品页 URL（三段 seg，**不是**两段 —— 这是最容易写错的地方）
------------------------------------------------
    /s-1w9k8n-c-<品类seg>-<区seg>-<种族seg>-<游戏区seg>.html
    例 北美西/天族/Siel → /s-1w9k8n-c-2c2xs4-vshs5k-uwbf0m-m4rgrr.html

⚠ 三个踩过的坑（都实际浪费过时间，别再犯）
------------------------------------------------
1. **官方商品 API 对这个专区返回空数组**（ApiGetMallShopList / ApiGetShopList 都是
   `ResultData:[]`），只有 HTML 页面里有货 ⇒ **这个游戏必须爬 HTML**，不能用分册 17
   的 API 正路。区服树仍走 API（那个稳定）。
2. **响应是 gzip 的**。`urllib` 不会自动解压，若不手动 `gzip.decompress`，
   拿到的就是二进制乱码（表现为「页面里一个标签都搜不到」，很容易误判成被 WAF 拦）。
   做法：请求头带 `Accept-Encoding: identity`，并且仍对 `\x1f\x8b` 兜底解压。
3. 🔴 **风控是「软拦截」，返回 200 + 滑块页，不报 302**（详见下面 `_blocked()`）。
   本机 IP 已被阿里云 ESA 拦（浏览器里直接出「滑动验证页面」）；
   **服务器 IP 仍通畅**。所以这个模块只在服务器上跑。
   最要命的是：滑块页里也**没有** `goods-list-item`，症状与「该区 0 条挂单」
   **完全一样** —— 不判风控就会得出「34 个区全部无报价」的错误结论。

单价口径
------------------------------------------------
    `<input class="goods-num" ... singleprice="0.118">` + `<span>万基纳</span>`
    → singleprice = **元 / 万基纳**（不是元/个，也不是元/亿）。
    同一块里 `1元=8.4746万基纳` 与 `1万基纳=0.1180元` 互为倒数，可自校验。
    换算成统一口径（$/M）：`元/万基纳 ÷ 10000 × 1000000 = 元/万基纳 × 100`，
    再除汇率 → USD/M。**注意 1M 基纳 = 100 万基纳 = 100 个「万基纳」**。

挂单结构（2026-10-06 实测，算订单簿就靠这两块）
------------------------------------------------
① **散单**（页面下方 `goods-list-item`，默认 20 条/页，带分页）
   `<input type="number" class="goods-num" value="2100" min="2100" max="2100" singleprice="0.057">`
   副标题写「单笔交易 / 不支持部分」⇒ **一笔必须整买**：可供量 = `max`（单位**万基纳**）。
   页面按价格升序给（第一条最便宜），但我们**自己按单价排序**，不依赖站点顺序。

② **热卖商城**（页面顶部 `hot-shopping`，大库存商家，可能没有）
   同一个档位在 HTML 里出现**两条 input**：
     · 数量模式 `<input id="hotInputNum…" data-min="200" data-max="50000"
        data-pricetype="1" data-singleprice="0.100000">`  ⇒ 单位**万基纳**（这里要的）
     · 金额模式 `data-min="20.00" data-max="5000.00" … data-maxnum="50000"`
        ⇒ 单位**元**（data-max 带小数！）
   ⛔ **必须靠「带不带小数点」把金额行剔掉**，否则 5000「元」会被当成 5000「万基纳」，
      把可买量算小、单价算错。

③ 数量单位换算：`1 亿基纳 = 10000 万基纳`；本模块目标量 2 亿 = **20000 万基纳**。
"""
import gzip
import json
import os
import re
import ssl
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
_SSL = ssl._create_default_https_context
_sslctx = _SSL(_SSL.PROTOCOL_TLS_CLIENT) if hasattr(_SSL, "PROTOCOL_TLS_CLIENT") else _SSL()

BASE = "https://www.dd373.com"
GAME_GUID = "b392a002e316467fb25133c2110a61c4"      # 永恒之塔2国际服
GAME_SID = "1w9k8n"
KINAH_GUID = "76c9f6b688934f8283dae5e643c2da99"    # 基纳
KINAH_SEG = "2c2xs4"                                 # 基纳的 URL 段名

# 我方大区名 → DD373 区名 + 区段
AREA_MAP = {
    "Asia":          ("日服",   "heft1r"),
    "NA West":       ("北美西", "vshs5k"),
    "NA East":       ("北美东", "6hw3s0"),
    "South America": ("南美",   "72kds4"),
    "EU":            ("欧服",   "n98us6"),
}

# ⛔ 别名表：DD373 上有拼写与游戏内名不一致的，**必须靠它对齐**，别改我方命名。
#     日服天族 DD373 写「Nezakan」（缺 e），游戏内是「Nezekan」。2026-10-02 实测。
NAME_ALIAS = {
    ("Asia", "Nezekan"): "Nezakan",
}

# 归一化：把 DD373 的游戏区名统一成我方命名（含大小写与拼写差异）
def _norm(nm):
    n = (nm or "").strip().lower()
    for canon in ("nezekan", "siel", "vaizel", "kaisinel", "meslamtaeda", "fregion",
                  "yustiel", "ariel", "israphel", "zikel", "triniel", "lumiel",
                  "azphel", "beritra", "ereshkigal", "marchutan"):
        if n == canon:
            return canon
    if n in ("nezakan",):            # DD373 日服拼写
        return "nezekan"
    return n


def _get(url, referer=BASE + "/", timeout=25):
    """GET + 手工 gzip 解压（这个站的坑，见模块 docstring 第 2 条）。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Referer": referer, "Accept-Encoding": "identity",
        "Accept": "text/html,application/json,*/*",
    })
    with urllib.request.urlopen(req, timeout=timeout, context=_sslctx) as f:
        raw = f.read()
        if f.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
    return raw.decode("utf-8", "ignore")


def _api_list(parent_id):
    """区服树走官方 API（稳定，一次拿全）。返回 list[dict]。"""
    url = "https://game.dd373.com/Api/GameOther/List?parentId=%s" % parent_id
    j = json.loads(_get(url, referer=BASE + "/"))
    if str(j.get("StatusCode")) != "0":
        return []
    rd = (j.get("StatusData") or {}).get("ResultData")
    if isinstance(rd, dict):
        for _k, v in rd.items():
            if isinstance(v, list) and v:
                return v
        return []
    return rd if isinstance(rd, list) else []


# ---------------------------------------------------------------------------
# 区服树（区 → 种族 → 游戏区），带缓存
# ---------------------------------------------------------------------------
_TREE_CACHE = {"ts": 0, "data": None}


def zone_tree(max_age=21600, log=None):
    """返回 {"<我方大区>|<归一化名>": {"url_seg":..., "dd_area":..., "dd_race":...,
                                       "dd_name":..., "our_name":...}}"""
    if _TREE_CACHE["data"] and time.time() - _TREE_CACHE["ts"] < max_age:
        return _TREE_CACHE["data"]
    out = {}
    for our_area, (dd_area, area_seg) in AREA_MAP.items():
        try:
            areas = _api_list(GAME_GUID)
        except Exception as e:
            if log:
                log("  [DD373] 区服树失败: %r" % (e,))
            return out
        hit = next((a for a in areas if a.get("Identify") == area_seg), None)
        if not hit:
            continue
        for race in _api_list(hit["Id"]):
            r_seg, r_name = race.get("Identify"), race.get("Name")
            # 区+种族 页里列出了该组合下的全部游戏区（第三层）
            try:
                h = _get("%s/s-%s-c-%s-%s-%s.html" % (BASE, GAME_SID, KINAH_SEG, area_seg, r_seg))
            except Exception:
                continue
            pat = r"/s-%s-c-%s-[a-z0-9]{6}-[a-z0-9]{6}-([a-z0-9]{6})\.html\"[^>]*>([^<]+)<" % (
                GAME_SID, KINAH_SEG)
            for m in re.finditer(pat, h):
                lv3_seg, dd_name = m.group(1), m.group(2).strip()
                if not dd_name or dd_name == "基纳":
                    continue
                nm = _norm(dd_name)
                out["%s|%s" % (our_area, nm)] = {
                    "url_seg": "%s-%s-%s" % (area_seg, r_seg, lv3_seg),
                    "dd_area": dd_area, "dd_race": r_name, "dd_name": dd_name,
                    "our_name": nm,
                }
            time.sleep(1.1)          # 分册 17：限流约 200 次/短窗口，这里很安全
        time.sleep(1.1)
    _TREE_CACHE["ts"] = time.time()
    _TREE_CACHE["data"] = out
    return out


# ---------------------------------------------------------------------------
# 🔴 风控判据 —— **必须先判这个，否则会把「被拦」当成「没货」**
# ---------------------------------------------------------------------------
# 2026-10-02 实测：阿里云 ESA 滑块风控是**软拦截** —— 返回 HTTP 200 + 一个
# 12KB 的「滑动验证页面」HTML，**不报 302、不报错**。若不判，会全盘误判成
# 「DD373 上该游戏区 0 条挂单」，面板上 34 个区全显示"无报价"，而真相是 IP 被限。
#
# 可靠判据（本项目 8 次采样 8/8 命中）：
#     被风控 = 有滑块页特征 且 **没有** `sell-btn-box`（商品筛选导航）
#     真没货 = **有** sell-btn-box（页面正常渲染）但没有 goods-list-item
# 三个滑块特征串：滑动验证 / nocaptcha / aliyunCaptcha
def _blocked(html):
    if not html:
        return True
    if "goods-list-item" in html:
        return False                      # 已经有货了，别的都不用看
    if "sell-btn-box" in html:
        return False                      # 页面正常渲染 ⇒ 真的是 0 条
    return any(k in html for k in ("滑动验证", "nocaptcha", "aliyunCaptcha", "captcha")) or True



def _short_url(url_seg):
    """区+种族+游戏区 的短页（商品在这里渲染，且**页面上带全部排序链接**）。"""
    return "%s/s-%s-c-%s-%s.html" % (BASE, GAME_SID, KINAH_SEG, url_seg)


# 页面上「综合排序」那个 <a>：/s-{sid}-{区}-{种族}-{游戏区}-0-0-{品类}-0-0-0-0-0-1-0-1-0.html
# ⚠ 段位顺序是**从页面抄的**，别自己推 —— 品类段在第 3 位（我推错过，返回空壳页）。
_RE_SORTLINK = re.compile(
    r'href="(/s-%s-[a-z0-9]{6}-[a-z0-9]{6}-[a-z0-9]{6}-0-0-[a-z0-9]{6}-0-0-0-0-0-1-0-1-0\.html)"[^>]*>\s*综合排序'
    % GAME_SID)


def _sort_url_of(html, url_seg, base=BASE):
    """从短页里取「综合排序」的真实链接；取不到就退回短页（排序由站点默认给）。"""
    m = _RE_SORTLINK.search(html or "")
    if m:
        return base + m.group(1)
    return _short_url(url_seg)


_RE_PRICE = re.compile(r'class="goods-num"[^>]*?singleprice="([\d.]+)"')
# input 是 HTML5 空元素、可能 `/>` 也可能 `>` 收尾 ⇒ 两种都放过（实测这个站是 `>`）。
_RE_UNIT = re.compile(
    r'class="goods-num"[^>]*?>\s*<i class="goods-icon-clear dn"></i>\s*<span>([^<]+)</span>')
_RE_RATIO = re.compile(r'1</span>元=<span class="colorFF5">([\d.]+)</span>([^<]*)')
_RE_STOCK = re.compile(r'库存：<span[^>]*>([^<]+)</span>')
_RE_MIN = re.compile(r'起售：<span[^>]*>([^<]+)</span>')

# ═══════════════════════════════════════════════════════════════════════════
# 2026-10-06 · 成本口径改为「买满 2 亿基纳的订单簿加权均价」
# ═══════════════════════════════════════════════════════════════════════════
TARGET_WAN = 20000.0        # 目标采购量：2 亿基纳 = 20000 万基纳
MAX_PAGES = 3               # 单区最多翻 MAX_PAGES 页散单（首屏通常是 20 条/页）
REQ_BUDGET = 150            # 单轮总请求预算（含首屏）；用尽则剩余区沿用上一轮快照

# 散单列表的「下一页」链接（分页条）；第 1 页是短页，不带这个格式
_RE_PAGE = re.compile(
    r'href="(/s-%s-[a-z0-9]{6}-[a-z0-9]{6}-[a-z0-9]{6}-0-0-[a-z0-9]{6}'
    r'-0-0-0-0-0-(\d+)-0-0-0\.html)"' % GAME_SID)


def _page_urls(html):
    """从分页条里取 {页码: 完整URL}（第 1 页不含在内）。"""
    out = {}
    for href, pg in _RE_PAGE.findall(html or ""):
        try:
            out[int(pg)] = BASE + href
        except ValueError:
            continue
    return out


def _parse_quotes(html):
    """把一页里的**全部可买挂单**解析出来（散单 + 热卖商城）。

    返回 [(可供量_万基纳, 单价_元每万基纳, 来源) ...]，解析不出的条目**直接丢弃**，
    绝不用默认值编数。单位不合规的页面由调用方（fetch_costs 的自校验）拦。
    """
    out = []
    # ① 散单：class="goods-num"（单笔不拆 ⇒ 可供量 = max）
    for tag in re.findall(r'<input[^>]*class="goods-num"[^>]*>', html or ""):
        m = re.search(r'\bmax="(\d+)"', tag)
        p = re.search(r'\bsingleprice="([\d.]+)"', tag)
        if not (m and p):
            continue
        q, pr = float(m.group(1)), float(p.group(1))
        if q > 0 and pr > 0:
            out.append((q, pr, "散单"))
    # ② 热卖商城：data-singleprice 的 input（区分数量模式/金额模式）
    for tag in re.findall(r'<input[^>]*data-singleprice="[\d.]+"[^>]*>', html or ""):
        mn = re.search(r'\bdata-min="([\d.]+)"', tag)
        mx = re.search(r'\bdata-max="([\d.]+)"', tag)
        sp = re.search(r'\bdata-singleprice="([\d.]+)"', tag)
        if not (mn and mx and sp):
            continue
        # ⛔ 金额模式（单位「元」，data-min/max 带小数点）→ 必须剔除
        if "." in mn.group(1) or "." in mx.group(1):
            continue
        q, pr = float(mx.group(1)), float(sp.group(1))
        if q > 0 and pr > 0:
            out.append((q, pr, "热卖商城"))
    return out


def orderbook_avg(quotes, target_wan=TARGET_WAN):
    """按单价升序吃满 target_wan（万基纳）→ 数量加权均价。

    返回 None = 一条有效报价都没有；否则 dict：
      均价 / 参与条数 / 报价条数 / 可供量(全部可买) / 缺口 / 够量 / 明细
    「明细」留前 6 条被吃掉的档位，供面板/日志核对（这一条最值钱：能看到钱花在哪）。
    """
    qs = sorted(quotes or [], key=lambda x: x[1])
    all_avail = sum(q for q, _, _ in qs)
    need = float(target_wan)
    cost = got = 0.0
    used = []
    for q, pr, src in qs:
        if need <= 0:
            break
        take = min(q, need)
        cost += take * pr
        got += take
        need -= take
        used.append("%.0f万@%.4f(%s)" % (take, pr, src))
    if got <= 0:
        return None
    return {
        "均价": cost / got,
        "参与条数": len(used),
        "报价条数": len(qs),
        "可供量": all_avail,
        "缺口": max(0.0, float(target_wan) - all_avail),
        "够量": all_avail >= float(target_wan) - 1e-6,
        "明细": used[:6],
    }


def parse_first(html):
    """取**综合排序第一条**的单价。抓不到返回 None（**不编数**）。"""
    i = html.find("goods-list-item")
    if i < 0:
        return None
    s = html.rfind("<div", 0, i)
    j = html.find("goods-list-item", i + 40)
    seg = html[s:j if j > 0 else len(html)]
    m = _RE_PRICE.search(seg)
    if not m:
        return None
    price = float(m.group(1))
    unit = _RE_UNIT.search(seg)
    ratio = _RE_RATIO.search(seg)
    stock = _RE_STOCK.search(seg)
    mn = _RE_MIN.search(seg)
    out = {
        "单价_元每万基纳": price,
        "单位": (unit.group(1) if unit else ""),
        "每元可买": (float(ratio.group(1)) if ratio else None),
        "每元单位": (ratio.group(2) if ratio else None),
        "库存": (stock.group(1) if stock else None),
        "起售": (mn.group(1) if mn else None),
        "商品条数": html.count("goods-list-item"),
    }
    # 自校验 ①：singleprice 与「1元=X万基纳」应互为倒数（差 1% 内算通过）。
    #   这一条能挡住「解析到了错误的块」这类静默 bug。
    # 自校验 ②：**单位必须是「万基纳」**。若站点改成「亿基纳」或「个」，
    #   下面的 ×100 换算就会错 10~10000 倍 —— 所以单位必须校验，不能只当展示字段。
    bad = []
    if out["每元可买"]:
        exp = 1.0 / price if price else None
        if exp and abs(out["每元可买"] - exp) / exp > 0.01:
            bad.append("单价与比例不自洽（1元=%s万基纳 vs 1/%s）"
                       % (out["每元可买"], price))
    un = (out["单位"] or "").replace("基纳", "").replace(" ", "")
    if un and un not in ("万", "10000", "w", "W"):
        bad.append("⚠单位不是「万基纳」而是「%s」—— 换算会错，**本条不可用**" % out["单位"])
    if bad:
        out["自校验"] = "；".join(bad)
        out["不可用"] = any("不可用" in b for b in bad)
    return out


# ---------------------------------------------------------------------------
# 单位换算：元/万基纳 → USD/M
# ---------------------------------------------------------------------------
# 1 M 基纳 = 1,000,000 基纳 = 100 × 「万基纳」
WAN_PER_M = 100.0


def to_usd_per_m(price_yuan_per_wan, rate):
    """元/万基纳 → 美元/百万基纳。rate = 汇率（USD→CNY）。"""
    if price_yuan_per_wan is None or not rate:
        return None
    return float(price_yuan_per_wan) * WAN_PER_M / float(rate)


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def fetch_costs(servers, rate, log=None, gap=1.3, refresh_tree=False):
    """给一批服务区取 DD373 成本。

    servers : [{key, 大区, 名称或 g2g_服务区}] —— 直接传 config.金币.服务区 里的条目
    rate    : 汇率（USD→CNY），用于折成 $/M
    返回   : {key: {...}}，每条含
               ok            布尔
               成本_元每万基纳  **2 亿订单簿加权均价**（元/万基纳，面板主显）
               成本_USD每M     折算后（算利润率、做成本兜底都用它）
               可供量_万基纳   该区全部挂单可买总量（判断够不够 2 亿）
               够量           布尔（可供量 ≥ 2 亿）
               参与条数       被吃进订单簿的档位数
               依据/备注/URL
    ⚠ 本函数仍**只读**；但 2026-10-06 起它的产物是定价输入（成本兜底 + 利润率下限）。
    """
    if refresh_tree:
        _TREE_CACHE["ts"] = 0
    tree = zone_tree(log=log)
    if not tree:
        if log:
            log("  [DD373] 区服树为空 —— 本轮不产出成本（不写空值）")
        return {}
    out = {}
    _budget = {"n": REQ_BUDGET}       # 本轮的请求预算（含首屏；防触发 DD373 限流）
    for sv in servers or []:
        key = sv.get("key")
        nm = (sv.get("g2g_服务区") or sv.get("名称") or "")
        nm = nm.split(" - ")[0].strip()
        area = sv.get("大区") or ""
        tk = "%s|%s" % (area, _norm(nm))
        info = tree.get(tk)
        if not info:
            # 退一步：只按名字找（万一大区名写法有出入）
            cand = [v for k, v in tree.items() if k.split("|", 1)[1] == _norm(nm)]
            if len(cand) == 1:
                info = cand[0]
        if not info:
            out[key] = {"ok": False, "依据": "DD373 无对应区（游戏区×大区）",
                        "备注": "区服名 %s 在 DD373 专区里找不到" % nm}
            if log:
                log("  [DD373] %-24s ✗ 无对应区（%s / %s）" % (key, area, nm))
            continue
        if _budget["n"] <= 0:
            out[key] = {"ok": False, "依据": "本轮请求预算用尽（防 DD373 限流）",
                        "备注": "沿用上一轮快照；下一轮会继续"}
            if log:
                log("  [DD373] %-24s · 本轮请求预算用尽，跳过（沿用上一轮）" % key)
            continue
        # 🔴 先走短页：它有两个作用 —— ① 商品在这里渲染 ② 页面上带「综合排序」真实链接。
        #    直接拼长 URL 有两个坑：段位顺序易错、且长 URL 路径更容易撞 ESA 软拦截。
        _budget["n"] -= 1
        try:
            html = _get(_short_url(info["url_seg"]))
        except Exception as e:
            out[key] = {"ok": False, "依据": "抓取失败", "备注": repr(e)[:120],
                        "URL": _short_url(info["url_seg"])}
            if log:
                log("  [DD373] %-24s ✗ %r" % (key, e))
            time.sleep(gap)
            continue
        if _blocked(html):
            # 被风控 ≠ 没货。**这一轮就此打住**，别把剩下 30 个区也打成"无报价"。
            out[key] = {"ok": False, "依据": "被 DD373 风控拦截（不是无货）",
                        "备注": "返回阿里云 ESA 滑块验证页；本轮已停止采集，"
                                "沿用上一轮快照", "URL": _short_url(info["url_seg"])}
            if log:
                log("  [DD373] %-24s ⚠ 撞上风控（滑块页）—— 本轮停止采集，"
                    "不写空值，沿用上一轮快照" % key)
            return out
        url = _sort_url_of(html, info["url_seg"])
        # ── 自校验（沿用）：按第一条挂单验「单位必须 = 万基纳」+ 单价与比例互为倒数。
        #    这一条能挡住「站点改成亿基纳 / 解析到错误块」这类静默 bug —— 一旦异常，
        #    该区**丢弃不写脏值**（成本是定价输入，宁缺勿错）。
        _chk = parse_first(html)
        if _chk and _chk.get("不可用"):
            out[key] = {"ok": False, "依据": "单位口径异常，已丢弃（不写脏值）",
                        "备注": _chk.get("自校验"), "URL": url}
            if log:
                log("  [DD373] %-24s ✗ 单位异常：%s" % (key, _chk.get("自校验")))
            time.sleep(gap)
            continue
        # ── 订单簿：本页 + （不足 2 亿时）后续页，按单价升序吃满 2 亿基纳 ──────
        quotes = _parse_quotes(html)
        ob = orderbook_avg(quotes)
        _pages = 1
        _page_note = ""
        if ob and not ob["够量"]:
            _pg = _page_urls(html)
            for _n in range(2, MAX_PAGES + 1):
                if _n not in _pg or _budget["n"] <= 0:
                    break
                _budget["n"] -= 1
                try:
                    _h2 = _get(_pg[_n])
                except Exception:
                    break
                if _blocked(_h2):
                    # 🔴 2026-10-06 改：翻页用的是**长 URL**（分页条链接），比首屏短页
                    #    更容易被阿里云 ESA 软拦，且长页 DOM 与短页不同、_blocked()
                    #    那条判据（无 goods-list-item 且无 sell-btn-box ⇒ 判拦）在长页上
                    #    极易**误判**。上一版这里是 `return out`（整轮中止），实测一误判
                    #    就把整轮 86 区的成本全废掉（2026-10-06 11:56 那轮即是）。
                    #    ⇒ 改为**只放弃本区补页**，用首屏已拿到的订单簿（可能 < 2 亿，
                    #    按现有挂单加权），继续跑其余区。首屏被拦才整轮中止（那才是真 IP 封锁）。
                    _page_note = "·第%d页被拦(用首屏)" % _n
                    if log:
                        log("  [DD373] %-24s ⚠ 翻第 %d 页被拦（长URL/风控）—— "
                            "本区改用首屏订单簿（可能不足 2 亿），继续采集其余区"
                            % (key, _n))
                    break
                quotes += _parse_quotes(_h2)
                _pages = _n
                ob = orderbook_avg(quotes)
                if ob and ob["够量"]:
                    break
                time.sleep(gap)
        if not ob:
            out[key] = {"ok": False, "依据": "DD373 该游戏区暂无在售商品",
                        "备注": "页面正常渲染（未被风控），第 1~%d 页 0 条挂单" % _pages,
                        "URL": url}
            if log:
                log("  [DD373] %-24s · 无报价（0 条挂单，非风控）" % key)
            time.sleep(gap)
            continue
        _pr = ob["均价"]
        _short_note = (None if ob["够量"] else
                       "该区挂单仅可买 %.0f 万基纳（< 2 亿），均价按现有挂单加权"
                       % ob["可供量"])
        rec = {
            "ok": True,
            "成本_元每万基纳": _pr,
            "单位": "万基纳",
            "成本_USD每M": to_usd_per_m(_pr, rate),
            "可供量_万基纳": ob["可供量"], "够量": ob["够量"],
            "参与条数": ob["参与条数"],
            # 兼容旧字段（面板 / gold_cost 表沿用）：库存改为「可买多少」
            "库存": "可买%.0f万基纳" % ob["可供量"], "起售": None,
            "商品条数": ob["报价条数"],
            "DD区": info["dd_area"], "DD种族": info["dd_race"], "DD游戏区": info["dd_name"],
            # 依据列保持简短（太长会把右侧「改价操作」挤出可视区）：只留 区/种族/游戏区 + 口径
            "依据": "%s / %s / %s · 买满2亿订单簿加权(吃%d/%d条·翻%d页%s)"
                    % (info["dd_area"], info["dd_race"], info["dd_name"],
                       ob["参与条数"], ob["报价条数"], _pages, _page_note),
            "URL": url,
        }
        _own = "；".join(x for x in ((_chk or {}).get("自校验"), _short_note) if x)
        if _own:
            rec["备注"] = _own
        out[key] = rec
        if log:
            log("  [DD373] %-24s %-10s %.6f 元/万基纳 → $%.4f/M  "
                "(2亿订单簿 %d 条%s，可买 %.0f万基纳)"
                % (key, rec["DD游戏区"], _pr, rec["成本_USD每M"] or 0,
                   ob["参与条数"], "" if ob["够量"] else "·不足2亿", ob["可供量"]))
        time.sleep(gap)
    return out


def summarize(costs, our_price_by_key):
    """给面板汇总区用：逐区算「最终售价 / 成本 / 利润率」。

    our_price_by_key : {key: 最终售价 USD/M}（改价后的目标价，没有就传我方现价）
    利润率可以为负 —— 这是**真实结论**，不要截断成 0。
    """
    rows = []
    for key, c in (costs or {}).items():
        price = our_price_by_key.get(key)
        cost_usd = c.get("成本_USD每M")
        margin = None
        if price and cost_usd:
            margin = (float(price) - float(cost_usd)) / float(price)
        rows.append({
            "key": key, "售价_USD每M": price, "成本_元每万基纳": c.get("成本_元每万基纳"),
            "成本_USD每M": cost_usd, "利润率": margin,
            "ok": c.get("ok"), "依据": c.get("依据"), "备注": c.get("备注"),
        })
    rows.sort(key=lambda r: (r["利润率"] is None, r["利润率"] if r["利润率"] is not None else 0))
    return rows


if __name__ == "__main__":
    import sys
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    g = cfg.get("金币", {})
    rate = (g.get("汇率") or cfg.get("汇率", {}).get("USDCNY")) or 6.65
    svs = [s for s in g.get("服务区", []) if s.get("游戏") == "AION2"]
    print("AION2 %d 个服务区，汇率 %.4f，采集 DD373 成本 …" % (len(svs), rate))
    res = fetch_costs(svs, rate, log=print, refresh_tree=True)
    ok = sum(1 for v in res.values() if v.get("ok"))
    _full = sum(1 for v in res.values() if v.get("ok") and v.get("够量"))
    print("\n成功 %d / %d（其中可买满 2 亿 %d 个区）" % (ok, len(svs), _full))
    print(json.dumps(summarize(res, {}), ensure_ascii=False, indent=1))
