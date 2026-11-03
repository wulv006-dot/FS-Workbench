# -*- coding: utf-8 -*-
"""DD373 进货成本采集 —— 永恒之塔2（AION2）国际服 · 基纳（Kinah）。

用户口径
------------------------------------------------
【2026-10-02】「成本 = 综合排序后展示的第一条商品价格」—— 已废弃。
【2026-10-06 上午】老板原话：「你选择 2 亿数量的金币，然后算均价来定价格」。
【2026-10-06 晚 · 现行】老板改为 **1 亿** —— 「把 2 亿兜底改成 1 亿」。
   ⇒ 目标量 TARGET_WAN 2 亿 → 1 亿 → **5 亿（50000 万基纳，2026-10-12 老板定案）**；
     对应的「无货兜底」阈值（config `金币.定价策略.无货最小可买万基纳`）同步 20000 → 10000。

【2026-10-20 · **现行：订单簿与区服树全部改走官方 Api**（老板定案「就用这个接口吧，
   未雨绸缪」）】
   背景：官方 `ApiGetShopList` 早先对本专区返回空数组（见下方「三个坑」第 1 条），
     2026-10-20 实测**该坑已不存在** —— 接口已有数据：30 条结构化 JSON、按单价升序、
     无需登录/签名/cookie，返回的就是全网最便宜的 30 条。
   ⇒ ① **区服树**改走 `GameOther/List` 三层（区→种族→游戏区），每轮 11 次请求、
      每条带 GUID（`area_id`/`race_id`/`zone_id`），HTML 抓法保留为回落；
   ⇒ ② **订单簿**改走 `ApiGetShopList`（**30 条是硬上限**：PageIndex/pageSize/Count/
      Limit 等 10 种分页参数实测全部被忽略）；
   ⇒ ③ 新增**离群熔断** `BREAKOUT_RATIO = 3`（见 `orderbook_avg`）。
   老板口径原话：「5 亿门槛保持不变，宁愿那些冷门区没单子，也不能冒风险设低价被
     用户爆单」⇒ **熔断触发 = 该区判无报价**（走默认售价兜底），
     绝不拿「吃到一半」的残缺订单簿算成本。宁可丢单，不可爆单。
   ⚠ 字段口径（最容易误判，已踩过）：**可买量 = amount × number**
     （`number` = 发布件数，`price` 只是**单件**金额）。只按 `amount` 统计，
     107 个区里 63 个会被误判成「可买不足 5 亿」。
   ⚠ 30 条 > HTML 的 20 条 ⇒ 会暴露 HTML **物理上看不到**的第 21~30 条高价挂单。
     实测 欧服/魔族/Baba：前 21 条合计仅 3.11 亿，第 22 条单价 0.85 元/万 =
     首条的 **10 倍**却挂着 2.8 亿量；按「吃满 5 亿」必然吃它 ⇒ 成本 0.085 → 0.412。
     过去不爆**纯属侥幸**（HTML 只显示 20 条，看不到它）—— 这正是本次加熔断的原因。

【2026-10-14 · **现行：跳过最低 1 条**（老板定案；当日晚**扩展至 MSCW**）】老板原话：
   「新增一个 DD373 成本扒取的规则，跳过第一个挂售的订单，因为这些订单往往会挂
     很低价格影响整体价格预测」。
   ⇒ `SKIP_LOWEST_QUOTES = 1`：先按单价升序**整条剔除最低的 1 条**（价格与库存都
     不计入，可买量随之少算这一条），再从第 2 条起「吃」——
     够 5 亿就按量吃，**不足 5 亿则从第 2 条起按条数吃满 10 条**（见下面 TARGET 口径）。
   ⇒ 页面「综合排序」本身按价格升序给 ⇒「第一个挂售的订单」= 排序后最便宜的那条。
   ⇒ **取代** 2026-10-09 的两版口径（当天上午 skip=2、下午 skip=0）。

【2026-10-09 · 历史口径：「跳过最低 2 条」（**已被 2026-10-14 覆盖**，仅存档）】
   老板当时原话：
   「DD373 成本拉取过程中，跳过页面第一条与第二条的报价和库存，再向下遍历直至 1 亿库存；
     因为经常会出现 1、2 条超低价的情况，影响价格判断」。
   ⇒ 在 orderbook_avg 里先把单价**最低的 2 条整条剔除**（价格与库存都不计入，
     可买量随之少算这两条），再从第 3 条起「吃」满 1 亿。
   ⇒ 页面「综合排序」本身按价格升序给 ⇒「页面第 1、2 条」= 排序后最便宜的 2 条。
   ⚠ 【2026-10-14 晚更新】MSCW（扁平专区）**已改为同口径**：`_collect_flat_game`
     改读本专区配置 `FLAT_ZONES["MapleStory Classic World"]["skip_lowest"] = 1`
     （老板：冒险岛第一条超低价同样会把整区成本拉崩）。本条上午曾是 `skip_lowest=0`，
     现两专区（AION2 / MSCW）口径一致 = 跳过最低 1 条。
   ⚠ 薄区（可买挂单 ≤ 2 条）**不做兜底保留**：剔完即为空 ⇒ 按「无报价」进无货兜底。
     理由：那两条本来就是它唯一的挂单，宁可挂兜底价，也不拿一条可疑超低价去定价。

⇒ 成本口径 = **「买满 TARGET_WAN 基纳」的订单簿加权均价**（不是最小那一笔散单的单价）；
    2026-10-12 起 TARGET_WAN = 5 亿；**可买不足 5 亿的区改「按条数吃满 10 条」算成本**：
     · 收集该区**可买挂单**（2026-10-14 起**先整条剔除单价最低的 1 条**，
       见上面 2026-10-14 段）：**只取散单**（单笔不拆，可供量 = max）；
       ⛔ 热卖商城**已彻底剔除**（2026-10-13 老板口径：其价低、非全体可见、
          更新快，且我方采购**不会去那买**，算进来会严重低估成本）；
     · 按**单价从低到高**逐条「吃」，吃到 5 亿基纳（= 50000 万基纳）为止；
    · 成本单价 = Σ(吃掉的数量 × 该条单价) ÷ Σ(吃掉的数量)。
  「够不够 5 亿」由**第 1 页**可买总量判断（不足则改按条数吃满 10 条），缺口写进备注。

【2026-10-06 深夜 · **取消翻页**】老板原话：「那你取消翻页吧，如果说翻页了那大概率
   也会是首页已满 1 亿的量了」。
   ⇒ 订单簿**只取第 1 页**（不再请求 `?PageIndex=N`）。实测绝大多数区第 1 页就能凑满
     1 亿（面板「可买量」常年几十亿）⇒ 翻页属多余请求，且是撞风控的主因；
     薄区（首页不足 1 亿）也**不再翻页**：按首页挂单加权，缺口写进备注。
   ⇒ 每轮请求数从「86 次首屏 + 若干补页」降到**恒定 86 次**，风控余量大幅上升。

【2026-10-06 晚 · 匹配修复】DD373 把第三层「游戏区」名改成了 **「Kaisinel（天4）」**
   这种带全角括号后缀的写法（此前是裸名 `Kaisinel`）。旧 `_norm()` 只比对裸名，
   ⇒ 归一化后变成 `kaisinel（天4）`，与我方 `Kaisinel` 对不上，
   **86 个区里 70 个被判「DD373 无对应区（游戏区×大区）」→ 全部误挂 $19.9 兜底**。
   本次三处修复：
     ① `_norm()` 先**剥掉括号后缀**（全角/半角 + 中间空格）再比对；
     ② 补别名表 `NAME_ALIAS`（DD373 拼写 ↔ 游戏内拼写）；
     ③ `zone_tree()` 抓失败的**种族页/区服页要重试**，并把成功的树**落盘缓存**，
        本轮漏抓的条目用上次快照补齐 —— 原来一次 `_get` 失败就静默丢掉整个种族的
        全部游戏区（实测 NA East 天族 8 个区整批消失，且日志里一个字都没有）。

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
游戏区     区+种族之下还有第三层（Siel / Azphel / Nezekan / Zikel …）。
          2026-10-06 起 DD373 把这一层改写成 **「Kaisinel（天4）」这种带全角括号
          后缀的形态**（括号里 = 天/魔族 + 序号），全站约 97 条；我方是 86 个服务区，
          靠「剥括号 + 别名表」对齐（见下面 `_norm()` / `NAME_ALIAS`）。

商品页 URL（三段 seg，**不是**两段 —— 这是最容易写错的地方）
------------------------------------------------
    /s-1w9k8n-c-<品类seg>-<区seg>-<种族seg>-<游戏区seg>.html
    例 北美西/天族/Siel → /s-1w9k8n-c-2c2xs4-vshs5k-uwbf0m-m4rgrr.html

⚠ 三个踩过的坑（都实际浪费过时间，别再犯）
------------------------------------------------
1. ~~**官方商品 API 对这个专区返回空数组**（ApiGetMallShopList / ApiGetShopList 都是
   `ResultData:[]`），只有 HTML 页面里有货 ⇒ **这个游戏必须爬 HTML**~~
   ✅ **2026-10-20 实测该坑已消失**：`ApiGetShopList` 对本专区已返回 30 条真实数据，
     现为**主路径**（见文件头 2026-10-20 段）。HTML 抓法降级为 Api 异常时的回落。
     保留此条仅为追溯「为什么历史上一直在爬 HTML」。
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

② **热卖商城**（页面顶部 `hot-shopping`，大库存商家）
   ⛔ **2026-10-13 起完全剔除、不再解析。** 老板口径：其价明显偏低、非全体用户可见、
      更新极快，且我方实际采购**不会去那里下单** —— 算进成本会严重低估，已造成亏损。
   ⇒ 成本口径**只取 ① 散单订单簿**。此条说明保留仅供追溯。

③ 数量单位换算：`1 亿基纳 = 10000 万基纳`；本模块目标量 = **5 亿 = 50000 万基纳**（2026-10-12）。
"""
import gzip
import json
import os
import re
import ssl
import time
import urllib.parse
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

# ── 官方 Api（2026-10-20 起 AION2 主路径，见文件头 2026-10-20 段）───────────────
API_SHOP = "https://goods.dd373.com/Api/Goods/UserCenter/ApiGetShopList"
API_ROWS = 30               # **硬上限**：PageIndex/pageSize/Count/Limit 等 10 种
                            #   分页参数实测全部被忽略，30 条就是能拿到的最多量。
                            #   正好覆盖口径需求：最便宜的 30 条已经够吃满 5 亿
                            #   （107 个区里 63 个可直接凑满，其余走「按条数吃满 10 条」）。

# 我方大区名 → DD373 区名 + 区段
# ⚠ 这里的第二项只是**看板展示名**（我们自己的口径）；**匹配一律只认第 3 项的 Identify 段**，
#   绝不按 DD373 的显示名去匹配 —— DD373 会改名：
#     · 2026-10-06 实测：日服这一层 DD373 现在显示为 **「亚服」**（Identify 仍是 `heft1r`）；
#     · 同一时期第三层「游戏区」被加上「（天4）/（魔1）」后缀（见 _norm）。
#   因为按 Identify 匹配，DD373 再怎么改显示名都不影响我方映射。
AREA_MAP = {
    "Asia":          ("日服",   "heft1r"),      # DD373 现显示为「亚服」
    "NA West":       ("北美西", "vshs5k"),
    "NA East":       ("北美东", "6hw3s0"),
    "South America": ("南美",   "72kds4"),
    "EU":            ("欧服",   "n98us6"),
}

# ⛔ 别名表：DD373 上的拼写与我方（游戏内）不一致时，**以我方为准**，别去改我方命名。
#     键 = DD373 名剥掉括号后缀后的小写；值 = 我方小写名。
#     2026-10-02 实测 Nezakan；2026-10-06 实测 Fregio / Mumin
#     （DD373 自己各区还不一致：欧服写 Fregion，北美东写 Fregio）。
NAME_ALIAS = {
    "nezakan": "nezekan",     # 日服 / 北美东 / 南美：DD373 少一个 e
    "fregio":  "fregion",     # 北美东（天7）：DD373 少一个 n
    "mumin":   "munin",       # 欧服（魔13）：DD373 写成 Mumin
}

# DD373「区+种族」列表页里会混进「区名 / 种族名」自身（点进去是本组合的父页，
#   url_seg 与某个真游戏区相同）—— 这些不是游戏区，进树只会造成脏匹配，直接丢。
_JUNK_NAMES = {"天族", "魔族", "亚服", "欧服", "北美东", "北美西", "日服", "南美",
               "基纳", "国际服"}

# 「Kaisinel（天4）」这种全角/半角括号后缀（可能带前置空格）
_RE_BRACKET = re.compile(r"\s*[（(][^（()）]*[）)]")


def _norm(nm):
    """把 DD373 的游戏区名归一成「我方小写名」，供 `大区|名字` 做键。

    2026-10-06 起 DD373 的第三层名变成了「Kaisinel（天4）」，所以必须：
      ① 剥掉括号后缀（含括号前的空格）；
      ② 压掉残留空白（欧服有条目写成「Azphel （魔6）」，括号前带空格）；
      ③ 查别名表对齐拼写差异。
    """
    n = _RE_BRACKET.sub("", nm or "").strip().lower()
    n = re.sub(r"\s+", "", n)
    return NAME_ALIAS.get(n, n)


# ---------------------------------------------------------------------------
# 区服备注「天N / 魔N」（2026-10-12 · 老板口径）
# ---------------------------------------------------------------------------
#   老板原话：「把服务区增加备注，参考的天1 魔1 天2 天3 这种备注，方便我们查看对照」。
#   DD373 的第三层区名本来就带这个后缀（`Siel（天1）` / `Israphel（魔1）`），
#   看板只要把它取出来贴在服务区名旁边，86 个区就能跟 DD373 页面对着一张表看。
_RE_NOTE = re.compile(r"[（(]([^（()）]*)[）)]")


def note_of_zone_name(nm):
    """从 DD373 区名（`Siel（天1）`）里取括号内的备注（`天1`）；无括号后缀返回 ""。"""
    m = _RE_NOTE.search(str(nm or ""))
    return m.group(1).strip() if m else ""


_ZONE_NOTE = {"sig": None, "map": {}}


def zone_note_map():
    """`{(大区, 归一化服务器名): "天1"}` —— 取自 DD373 区服树的**磁盘快照**。

    ⚠ 特意读快照（`data/dd373_zone_tree.json`）而不是本轮采集结果：
      本轮没抓到报价的区也要有备注；快照缺失就返回空表，前端留空，**绝不编数**。
    缓存按文件 mtime/size 失效，免得每次请求都重读一遍。
    """
    try:
        st = os.stat(_TREE_FILE)
        sig = (st.st_mtime_ns, st.st_size)
    except Exception:                                   # noqa: BLE001
        sig = None
    if _ZONE_NOTE["map"] and _ZONE_NOTE["sig"] == sig:
        return _ZONE_NOTE["map"]
    out = {}
    for k, v in (_tree_disk_load() or {}).items():
        n = note_of_zone_name((v or {}).get("dd_name"))
        if n:
            out[k] = n
    _ZONE_NOTE["sig"] = sig
    _ZONE_NOTE["map"] = out
    return out


def zone_note(area, name):
    """单个服务区的「天N/魔N」备注；查不到返回 ""（键与区服树一致：`大区|归一化名`）。"""
    return zone_note_map().get("%s|%s" % (str(area or ""), _norm(name or "")), "")


def _get(url, referer=BASE + "/", timeout=25, tries=2):
    """GET + 手工 gzip 解压（这个站的坑，见模块 docstring 第 2 条）。

    `tries` 次重试（线性退避）—— 2026-10-06 实测：单次网络抖动会让区服树
    **静默丢掉一整个种族的全部游戏区**（NA East 天族 8 个区整批消失、日志里
    一个字都没有），所以「拿不到就少一块数据」的调用一律走这个重试。
    """
    last = None
    _t = max(1, int(tries))
    for _i in range(_t):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": referer, "Accept-Encoding": "identity",
                "Accept": "text/html,application/json,*/*",
            })
            with urllib.request.urlopen(req, timeout=timeout, context=_sslctx) as f:
                raw = f.read()
                if f.headers.get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw)
            return raw.decode("utf-8", "ignore")
        except Exception as e:                      # noqa: BLE001
            last = e
            if _i < _t - 1:
                time.sleep(2.0 + 2.0 * _i)
    raise last


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
# 官方商品接口（2026-10-20 起 AION2 主路径，见文件头 2026-10-20 段）
# ---------------------------------------------------------------------------
def _api_shop(area_id, zone_id):
    """调 `ApiGetShopList` 取该「大区_游戏区」的基纳订单簿（30 条，按单价升序）。

    返回 ResultData 原始 list（每项含 amount / number / singleprice / unit / title）。
    接口层异常（网络 / 风控滑块 / 非 JSON / StatusCode≠0）一律抛 RuntimeError ——
    调用方据此**回落 HTML**。🔴 绝不能把「接口挂了」当成「该区没货」：
    那会让整批区判成无报价、全挂默认售价，正是本模块反复强调的那个坑。
    """
    url = "%s?%s" % (API_SHOP, urllib.parse.urlencode({
        "GameId": GAME_GUID,
        "GameOtherId": "%s_%s" % (area_id, zone_id),
        "GameShopTypeId": KINAH_GUID,
    }))
    raw = _get(url, referer=BASE + "/")
    try:
        j = json.loads(raw)
    except Exception:                               # noqa: BLE001
        # ESA 软拦截时接口也会返回滑块页 HTML（不是 JSON）⇒ 必须与「无货」区分
        raise RuntimeError("商品接口返回非 JSON（疑似风控滑块页）：%r" % (raw[:80],))
    if str(j.get("StatusCode")) != "0":
        raise RuntimeError("商品接口 StatusCode=%s %s"
                           % (j.get("StatusCode"), j.get("StatusMsg")))
    st = j.get("StatusData") or {}
    if str(st.get("ResultCode")) != "0":
        raise RuntimeError("商品接口 ResultCode=%s %s"
                           % (st.get("ResultCode"), st.get("ResultMsg")))
    rd = st.get("ResultData")
    return rd if isinstance(rd, list) else []


def _api_rows_to_quotes(rows):
    """把 Api 的 30 条转成订单簿三元组 `[(可买量_万基纳, 单价_元每万基纳, "散单")]`。

    ⚠ 2026-10-20 实测校准的两个口径（不看清楚必然算错）：
      · **可买量 = amount × number**（`number` = 发布件数）。
        API 的 `1000×3 @0.069396` 正好对应 HTML 的 `3000 @0.069396` ——
        证明 HTML 里 input 的 `max` 就是两者之积。**只按 amount 统计**，
        107 个区里 63 个会被误判成「可买不足 5 亿」（口径直接崩）。
      · `singleprice` = **元/万基纳**（已与 HTML 的价格序列逐条比对，完全一致）；
        `price` 只是**单件**金额 = amount × singleprice，**不是**总价，别拿去算成本。
      · `unit` 自带「万基纳」⇒ 用它做单位自校验，比 HTML 正则更硬。
    单位不合规 / 数值非法的条目**直接丢弃**（绝不编数），并单独计数上报。
    返回 (quotes, 丢弃条数)。
    """
    out = []
    bad = 0
    for x in rows or []:
        u = str(x.get("unit") or "")
        if u and "万" not in u:                     # 站点若改成「亿基纳/个」⇒ 换算会错
            bad += 1
            continue
        try:
            amt = float(x.get("amount") or 0)
            num = float(x.get("number") or 1)
            pr = float(x.get("singleprice") or 0)
        except Exception:                           # noqa: BLE001
            bad += 1
            continue
        q = amt * (num if num > 0 else 1.0)
        if q > 0 and pr > 0:
            out.append((q, pr, "散单"))
        else:
            bad += 1
    return out, bad


_ID_MAP = {"ts": 0, "map": {}}


def _load_id_map():
    """建 `(区段, 游戏区段) -> (区GUID, 游戏区GUID)` 索引。**只在快照缺 Id 时用**。

    正常路径用不到：本轮抓到的树自带 GUID（见 `_crawl_tree_api`）。但磁盘快照可能
    是旧版本写的（没有 `area_id`/`zone_id`），首次合并时靠它反查一次，避免首轮
    全量回落 HTML。11 次请求 + 6h 缓存。
    """
    if _ID_MAP["map"] and time.time() - _ID_MAP["ts"] < 21600:
        return _ID_MAP["map"]
    m = {}
    try:
        areas = _api_list(GAME_GUID)
    except Exception:                               # noqa: BLE001
        return m
    for _our, (_dd, area_seg) in AREA_MAP.items():
        hit = next((a for a in areas if a.get("Identify") == area_seg), None)
        if not hit:
            continue
        try:
            for race in _api_list(hit["Id"]):
                for z in _api_list(race["Id"]):
                    zs = z.get("Identify")
                    if zs:
                        m[(area_seg, zs)] = (hit["Id"], z["Id"])
        except Exception:                           # noqa: BLE001
            continue
    if m:
        _ID_MAP["ts"] = time.time()
        _ID_MAP["map"] = m
    return m


def _api_ids(info):
    """取该区的 (区GUID, 游戏区GUID)；树条目缺 Id 就用 url_seg 反查。"""
    aid, zid = info.get("area_id"), info.get("zone_id")
    if aid and zid:
        return aid, zid
    seg = str(info.get("url_seg") or "").split("-")
    if len(seg) == 3:
        return _load_id_map().get((seg[0], seg[2])) or (None, None)
    return None, None


def _api_quotes(info):
    """官方接口取一个区的订单簿。返回 dict（取不到 Id 时抛 RuntimeError 让调用方回落）。

    `quotes` / `行数`（接口原始条数）/ `丢弃条数`。
    """
    aid, zid = _api_ids(info)
    if not (aid and zid):
        raise RuntimeError("该区缺 Api 的区/区服 GUID（且反查失败）")
    rows = _api_shop(aid, zid)
    quotes, bad = _api_rows_to_quotes(rows)
    return {"quotes": quotes, "行数": len(rows), "丢弃条数": bad}


# ---------------------------------------------------------------------------
# 区服树（区 → 种族 → 游戏区），带缓存
# ---------------------------------------------------------------------------
_TREE_CACHE = {"ts": 0, "data": None}

# 磁盘快照：进程内存缓存只活一次（重启即失），而 DD373 偶发抽风会让**整批区**丢失。
#   所以每次抓到就落盘；本轮没完整抓到的区，用上次快照补齐 —— 宁可用旧快照，
#   也别把一个真有货的区判成「DD373 无对应区」→ 误挂 $19.9 兜底。
_TREE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "data", "dd373_zone_tree.json")


def _tree_disk_load():
    try:
        with open(_TREE_FILE, encoding="utf-8") as f:
            j = json.load(f)
        t = j.get("tree") if isinstance(j, dict) else None
        return t if isinstance(t, dict) else {}
    except Exception:
        return {}


def _tree_disk_save(tree):
    try:
        _d = os.path.dirname(_TREE_FILE)
        if _d and not os.path.isdir(_d):
            os.makedirs(_d)
        _tmp = _TREE_FILE + ".tmp"
        with open(_tmp, "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "tree": tree}, f, ensure_ascii=False, indent=1)
        os.replace(_tmp, _TREE_FILE)
    except Exception:
        pass


def _is_br(name):
    return ("（" in (name or "")) or ("(" in (name or ""))


def _crawl_tree_api(log=None):
    """真抓一次区服树 —— **2026-10-20 起的主路径：官方 Api 三层**。

    区(GameOther?parentId=游戏GUID) → 种族(…?parentId=区GUID) → 游戏区(…?parentId=种族GUID)
    每轮 11 次请求（1 次区 + 5×2 次种族下游戏区），比 HTML 抓法更省、更稳、信息更全：
    每条都带 GUID（`area_id`/`race_id`/`zone_id`），商品接口直接用它，不用再解析 URL。

    返回 (tree, ok_areas)，结构对 `_crawl_tree_html` **完全同名兼容**，额外多 3 个 Id 字段。

    ⚠ 2026-10-20 实测：API 三层树与 HTML 树的**键集合 107/107 完全一致、url_seg 零差异**
      （含 `Nathara`/`Altgard` 这种本来就不带括号的），所以匹配规则（`_norm` 剥括号 +
      别名表）、`_is_br` 括号名优先策略**一字未改**地沿用。
    """
    out = {}
    ok_areas = set()
    try:
        areas = _api_list(GAME_GUID)
    except Exception as e:                          # noqa: BLE001
        if log:
            log("  [DD373] 区服树（Api 区列表）失败: %r" % (e,))
        return out, ok_areas
    if not areas:
        return out, ok_areas
    for our_area, (dd_area, area_seg) in AREA_MAP.items():
        hit = next((a for a in areas if a.get("Identify") == area_seg), None)
        if not hit:
            if log:
                log("  [DD373] 区服树里找不到「%s」（seg=%s）" % (dd_area, area_seg))
            continue
        try:
            races = _api_list(hit["Id"])
        except Exception as e:                      # noqa: BLE001
            if log:
                log("  [DD373] %s 种族列表（Api）失败: %r" % (dd_area, e))
            continue
        if not races:
            if log:
                log("  [DD373] %s 拿不到种族列表（Api 返回空），本区跳过" % dd_area)
            continue
        _ok_race = 0
        for race in races:
            r_seg, r_name = race.get("Identify"), race.get("Name")
            try:
                zones = _api_list(race["Id"])
            except Exception as e:                  # noqa: BLE001
                if log:
                    log("  [DD373] %s/%s 游戏区列表（Api）失败: %r" % (dd_area, r_name, e))
                continue
            _n = 0
            for z in zones:
                z_seg = z.get("Identify")
                dd_name = (z.get("Name") or "").strip()
                if not (z_seg and dd_name) or dd_name in _JUNK_NAMES:
                    continue
                nm = _norm(dd_name)
                if not nm:
                    continue
                k = "%s|%s" % (our_area, nm)
                old = out.get(k)
                # 同一条目可能以「裸名」和「带括号名」各出现一次
                #   ⇒ **带括号的（DD373 现行正式命名）优先**，别被裸名覆盖。
                if old and _is_br(old["dd_name"]) and not _is_br(dd_name):
                    continue
                out[k] = {
                    "url_seg": "%s-%s-%s" % (area_seg, r_seg, z_seg),
                    "dd_area": dd_area, "dd_race": r_name, "dd_name": dd_name,
                    "our_name": nm,
                    # 官方商品接口要的是 GUID（不是 seg）⇒ 建树时直接存下
                    "area_id": hit["Id"], "race_id": race["Id"], "zone_id": z.get("Id"),
                }
                _n += 1
            # 🔴 与 HTML 版同一条铁律：只有**真解析出游戏区**才算这个种族抓到了。
            #    Api 若被拦/改版返回空，`_n == 0` 一律不采信，交上轮快照兜底。
            if _n:
                _ok_race += 1
                if log:
                    log("  [DD373] 区服树 %s/%s → %d 个游戏区（Api）" % (dd_area, r_name, _n))
            else:
                if log:
                    log("  [DD373] 区服树 %s/%s → 0 个游戏区（Api 异常，本轮不采信，"
                        "交快照兜底）" % (dd_area, r_name))
            time.sleep(0.4)
        if _ok_race >= len(races):
            ok_areas.add(dd_area)
    return out, ok_areas


def _crawl_tree(log=None):
    """抓区服树：**Api 优先，Html 回落**（2026-10-20 起）。

    Api 拿到任何一条就算成功（极少返回空）；空则回落 HTML —— 双保险，
    因为区服树空了会导致 86 区全判「无对应区」全挂默认售价，这个坑踩过。
    """
    out, ok_areas = _crawl_tree_api(log=log)
    if out:
        return out, ok_areas
    if log:
        log("  [DD373] ⚠ Api 区服树为空，回落 HTML 抓取")
    return _crawl_tree_html(log=log)


def _crawl_tree_html(log=None):
    """真抓一次区服树（**HTML 抓法，Api 异常时的回落**）。

    返回 (tree, ok_areas)：
        tree     {"<我方大区>|<归一化名>": {...}}
        ok_areas 本轮**两个种族都抓到**的大区名集合（这些区完全以本轮为准，
                 没抓全的区交给上轮快照兜底 —— 见 zone_tree()）。

    ⚠ 2026-10-06：第三层名带「（天4）」括号后缀 → 靠 _norm() 剥掉再建键；
       抓失败的种族页**重试 3 次**，不再静默丢一整个种族。
    ⚠ 2026-10-20：降级为回落路径（主路径是 `_crawl_tree_api`）。**不回传 GUID**，
       所以走这条路时商品接口只能靠 `_load_id_map()` 反查 Id。
    """
    out = {}
    ok_areas = set()
    for our_area, (dd_area, area_seg) in AREA_MAP.items():
        try:
            areas = _api_list(GAME_GUID)
        except Exception as e:                      # noqa: BLE001
            if log:
                log("  [DD373] 区服树（区列表）失败: %r" % (e,))
            continue
        hit = next((a for a in areas if a.get("Identify") == area_seg), None)
        if not hit:
            if log:
                log("  [DD373] 区服树里找不到「%s」（seg=%s）" % (dd_area, area_seg))
            continue
        races = _api_list(hit["Id"])
        if not races:
            if log:
                log("  [DD373] %s 拿不到种族列表（API 返回空），本区跳过" % dd_area)
            continue
        _ok_race = 0
        for race in races:
            r_seg, r_name = race.get("Identify"), race.get("Name")
            page = "%s/s-%s-c-%s-%s-%s.html" % (BASE, GAME_SID, KINAH_SEG, area_seg, r_seg)
            try:
                h = _get(page, tries=3)
            except Exception as e:                  # noqa: BLE001
                if log:
                    log("  [DD373] %s/%s 第三层页抓取失败（已重试 3 次）: %r"
                        % (dd_area, r_name, e))
                continue
            pat = r"/s-%s-c-%s-[a-z0-9]{6}-[a-z0-9]{6}-([a-z0-9]{6})\.html\"[^>]*>([^<]+)<" % (
                GAME_SID, KINAH_SEG)
            _n = 0
            for m in re.finditer(pat, h):
                lv3_seg, dd_name = m.group(1), m.group(2).strip()
                if not dd_name or dd_name in _JUNK_NAMES:
                    continue
                nm = _norm(dd_name)
                if not nm:
                    continue
                k = "%s|%s" % (our_area, nm)
                old = out.get(k)
                # DD373 列表页里同一条目会以「裸名」和「带括号名」各出现一次
                #   ⇒ **带括号的（DD373 现行正式命名）优先**，别被裸名覆盖。
                if old and _is_br(old["dd_name"]) and not _is_br(dd_name):
                    continue
                out[k] = {
                    "url_seg": "%s-%s-%s" % (area_seg, r_seg, lv3_seg),
                    "dd_area": dd_area, "dd_race": r_name, "dd_name": dd_name,
                    "our_name": nm,
                }
                _n += 1
            # 🔴 2026-10-06：只有**真解析出游戏区**才算这个种族抓到了。
            #    `_get()` 成功 ≠ 页面正常 —— 被阿里云 ESA 软拦时返回 HTTP 200 + 滑块页，
            #    解析出 0 个区。原实现照样 `_ok_race += 1`，于是一整片大区被标成
            #    「本轮抓全」→ `zone_tree()` 把快照里该大区的键**全过滤掉**；
            #    5 个大区都被软拦时 out 为空 ⇒ 返回空树 ⇒ 86 区全判「无对应区」
            #    全挂 $19.9。实测复现：10 个种族页全报「0 个游戏区」、ok_areas 却
            #    收了 5 个大区、合并后 out = 0 键。
            #    ⇒ `_n == 0` 一律**不采信**，交上轮快照兜底。
            if _n:
                _ok_race += 1
                if log:
                    log("  [DD373] 区服树 %s/%s → %d 个游戏区" % (dd_area, r_name, _n))
            elif log:
                log("  [DD373] 区服树 %s/%s → 0 个游戏区（疑似风控/页面异常，"
                    "本轮不采信，交快照兜底）" % (dd_area, r_name))
            time.sleep(1.1)          # 分册 17：限流约 200 次/短窗口，这里很安全
        if _ok_race >= len(races):
            ok_areas.add(dd_area)
        time.sleep(1.1)
    return out, ok_areas


def zone_tree(max_age=21600, log=None):
    """返回 {"<我方大区>|<归一化名>": {"url_seg":..., "dd_area":..., "dd_race":...,
                                       "dd_name":..., "our_name":...}}

    合并策略（2026-10-06）：
      · 本轮**两个种族都抓到**的大区 → 完全以本轮为准（DD373 真下架的区会随之消失）；
      · 本轮没抓全的大区 → 用磁盘快照补齐，并在日志里点名（看到它 = 本轮抓取不完整）。
    """
    if _TREE_CACHE["data"] and time.time() - _TREE_CACHE["ts"] < max_age:
        return _TREE_CACHE["data"]
    disk = _tree_disk_load()
    fresh, ok_areas = _crawl_tree(log=log)
    out = {k: v for k, v in disk.items() if v.get("dd_area") not in ok_areas}
    _filled = len(out)
    out.update(fresh)
    if not out:
        if disk:
            # 双保险：合并后为空（本轮把所有大区都判成「抓全」、实际却 0 个区）时，
            #   直接用上次快照 —— **宁可用旧树，也绝不返回空树**（空树 = 86 区
            #   全判「无对应区」全挂 $19.9）。上一处修复已让这种组合不出现，
            #   这行是兜底，防止以后再从别的路径踩同一个坑。
            if log:
                log("  [DD373] ⚠ 本轮合并结果为空，改用上次快照兜底（%d 键）" % len(disk))
            return disk
        if log:
            log("  [DD373] 区服树本轮抓空且无快照 —— 返回空（本轮不产出成本）")
        return out
    if log and _filled:
        log("  [DD373] ⚠ 本轮有 %d 个键没抓全，已用上次快照补齐（%d 个区完全以本轮为准）"
            % (_filled, len(ok_areas)))
    _TREE_CACHE["ts"] = time.time()
    _TREE_CACHE["data"] = out
    if ok_areas:
        _tree_disk_save(out)
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
# 2026-10-06 · 成本口径 = 「买满 TARGET_WAN 万基纳的订单簿加权均价」
#   ⚠ 当天晚些时候老板把目标量从 2 亿改成 **1 亿**（「把 2 亿兜底改成 1 亿」）。
#     配套的「无货兜底」阈值见 config `金币.定价策略.无货最小可买万基纳`（同为 10000）。
# ═══════════════════════════════════════════════════════════════════════════
TARGET_WAN = 50000.0        # 目标采购量：5 亿基纳 = 50000 万基纳（2026-10-12 老板定案：1亿 -> 5亿）
FALLBACK_ITEMS = 10         # 可买量不足目标量时，改「按条数」吃满 N 条（老板口径「抓满10条为准」）
                            #   ⚠ 2026-10-22 起 **AION2 不再用本值**（改为「全量吃满」，见 GATE_WAN）；
                            #     仍被 MSCW 扁平专区沿用（_collect_flat_game → orderbook_avg 默认值）。

# ── 2026-10-22 老板定案：AION2 成本口径改「全量吃满」
#   · 不论可买量多少（含 < 2 亿的薄区），成本一律 = 按订单簿吃满
#       **min(TARGET_WAN = 5 亿, 全部可买量)** 的加权均价：
#       够 5 亿就吃满 5 亿；不足 5 亿（2.3 / 3 / 3.4 亿，甚至 2000 万）就把这批挂单
#       **全部吃掉**算均价 —— 不再退回「只吃 10 条」（旧 FALLBACK_ITEMS 口径）。
#       仍沿用「跳过最低 1 条」。
#   · ⚠ 2026-10-22 二次定案（老板纠正）：**$4.99/M 是挂单价、不是成本**。
#       薄区（可买 < 2 亿）的售价由 core_gold 直接挂 $4.99/M（config `薄区挂单价_USD每M`），
#       成本照常按上面的全量加权算出来、两者互不替代。
#   · 离群熔断（BREAKOUT_RATIO）只对可买量 ≥ GATE_WAN（2 亿）的区生效；
#       薄区（< 2 亿）**跳过熔断**，直接采用「熔断前已吃部分」的加权均价作成本
#       （薄区售价已被钉在 $4.99，熔断只会把成本变成无报价、进而把售价误判成 $19.9）。
GATE_WAN = 20000.0          # 2 亿 = 20000 万基纳（与 config `金币.定价策略.无货最小可买万基纳` 同值）

# ── 2026-10-14 **老板重新定案：跳过最低 1 条** ⇒ 1（第一个挂售订单整条剔除，
#    价格与库存都不计入成本）。理由：「这些订单往往会挂很低价格影响整体价格预测」。
#    · 沿革：2026-10-09 上午设 2 → 当天下午改成 0（前两条一样抓）→ **2026-10-14 定 1**。
#    · AION2 走本常量默认值；**MSCW（扁平专区）2026-10-14 晚起同口径** ——
#      _collect_flat_game 读 FLAT_ZONES[...]["skip_lowest"]（当前 = 1，缺省回落本常量）。
SKIP_LOWEST_QUOTES = 1

# ── 2026-10-20 **老板定案：离群熔断**（「宁愿那些冷门区没单子，也不能冒风险设低价
#    被用户爆单」）。吃单过程中，若**下一条**的单价 > 已吃部分的加权均价 × 本倍数
#    ⇒ **立即停止吃单，该区判「无报价」**（走默认售价兜底），绝不拿残缺订单簿算成本。
#    · 为什么需要：吃满 5 亿时可能被迫吃进「价格断层」后面的天价挂单。
#      实测 欧服/魔族/Baba 第 22 条 0.85 元/万 = 首条的 10 倍、却挂 2.8 亿量 ⇒
#      成本 0.085 → 0.412（+382%）。HTML 只显示 20 条，过去**物理上看不到**它。
#    · 阈值依据（86 区全量实测）：3x 只触发 3 个薄区（Baba / Kromede / 南美 Zikel），
#      4x 触发 1 个，1.5x 会误伤正常区。**取 3** —— 三个区都是「剩余可买 ≤ 2000 万」
#      的冷门薄区，判无价正合老板口径（兜底价 $9.9/M 远高于其真实成本 $1.1~2.1/M，
#      是**涨价**方向，不会造成低价爆单）。
#    · 设 0 或 None = 关闭熔断（回滚开关）。
BREAKOUT_RATIO = 3.0

# ═══════════════════════════════════════════════════════════════════════════
# 2026-10-22 · **双侧离群过滤（软过滤）** —— 老板原话：
#   「你设置一个算法，滤过那些天价单，过高过低的都移除」
#
# 为什么要在「熔断」之外再做一层：熔断是**硬**的（一碰就把整个区判无报价 →
#   挂 $19.9 兜底），而现实里绝大多数区只是**尾部**混了几条不合理的挂单，
#   前面 10~20 条都是真实可比价的。硬熔断等于把「有货的区」白扔了。
#   ⇒ 改成：**先把离谱高/离谱低的整条剔掉，剩下的照常吃满算加权均价**。
#
# 两类要剔的挂单：
#   ① **天价单**（> 基准 × 3.0）：价格断层之后的挂单 —— 清仓尾货 / 挂错 / 钓鱼。
#      实测 `NA East · Meslamtaeda` 最后一条 **78.80 元/万 = 中位数的 909 倍**
#      （挂 1000 万量）；`EU · Ludra` 1.00 元/万 = 12.5 倍；`EU · Kromede` 0.286 = 4.7 倍。
#      吃进去成本虚高 → 售价虚高（方向安全），但会把整区拖进熔断 → 反而挂兜底价。
#   ② **超低价单**（< 基准 × 0.35）：占位 / 引流 / 挂错单。
#      吃进去成本虚低 ⇒ 售价虚低 ⇒ **被用户爆单**（这才是真正要防的方向）。
#      ⚠ 与 `SKIP_LOWEST_QUOTES=1`（跳过最低 1 条）**叠加**：那条是老板钉的业务口径
#        （「第一个挂售的订单不计入」），本过滤负责第 2、3 条及以后的异常低价。
#
# 基准 = **按「条数」的价格中位数**（不是数量加权）：
#   天价单/占位单的特征是**条数少**；而 DD373 经常一笔挂 8~16 亿的大额单，
#   用数量加权中位数会被那一条直接拽走 ⇒ 基准失效。条数中位数天然抗「少条巨额」。
#
# 阈值依据（2026-10-22 全区扫描 85 个 AION2 区，Api 返回的最便宜 30 条）：
#   · 常态 span（max/min）只有 1.1~1.3x ⇒ 本过滤在正常区**几乎不触发**（空转 = 不改价）；
#   · 只有「挂单总数 < 30 条」的冷门区才会把天价单暴露进来（Api 只给最便宜 30 条，
#     大区天然把它挡在外面）⇒ 这一层本质是**冷门区断层保险**；
#   · 三组候选（0.35/3.0、0.50/2.5、0.30/4.0）在实测里改动几乎完全一致，
#     取最宽松的一组（误伤最小）：0.35 / 3.0。
OUTLIER_LOW_RATIO = 0.35     # < 基准 × 0.35 ⇒ 判「超低价/占位单」，整条剔除
OUTLIER_HIGH_RATIO = 3.0     # > 基准 × 3.0  ⇒ 判「天价单」，整条剔除
OUTLIER_MIN_KEEP = 2         # 剔完剩不下 2 条 ⇒ **放弃过滤、保留原样**
                             #   ⚠ 方向性理由（关键）：不过滤 → 成本可能偏高 → 售价偏高
                             #     ⇒ 不会爆单；强行过滤到只剩 1 条 → 成本被单条绑架、
                             #     且可买量骤降，风险更大。宁可保守。
OUTLIER_ENABLED = True       # 总开关（设 False = 全线回到「不滤」的旧行为）

REQ_BUDGET = 400            # 单轮总请求预算（含每个区的首屏）；用尽则剩余区沿用上一轮快照
                            #   2026-10-06 深夜（取消翻页后）：每轮 ≈ 86 区 × 1 次首屏
                            #   = 86 次，距站点「约 200 次/短窗口」的限流线余量充足。
                            #   （翻页时代为 86 + 若干补页 ≈ 162 次，是撞风控的主因）


# ═══════════════════════════════════════════════════════════════════════════
# 分页 —— **2026-10-06 深夜已停用**（老板：「取消翻页吧，翻页大概率首页已满 1 亿」）。
#   下面这段是当时的**调研留档**，仅备将来万一要恢复翻页时查证，代码里不再使用：
#     · 长 URL（页面分页条给出的 href）：
#         /s-{sid}-{区}-{种族}-{游戏区}-0-0-{品类}-0-0-0-0-0-{页}-0-0-0.html
#       ⇒ 被阿里云 ESA **按 URL 形态无条件拦**（11956 字节 AliyunCaptcha 无痕验证页，
#         sceneId 19x5u7lo、region sgp）；换 Referer / 子域 / 加 ?_=1 全拦。
#     · ?page=N / -N.html / ?pageSize=100 ⇒ 站点**忽略**（「当前页」恒为 1、内容逐条相同）。
#     · ✅ 唯一能用的是 短 URL + 单个 query 键 **`?PageIndex=N`**（PageIndex 是站点内嵌
#         `#invisibleData` requestModel 的真实字段名）⇒ 不被拦、各页内容互不重复。
#        ⚠ **只能带这一个键**：再加 PageSize / Order / Issearch 立刻变拦页。
#   为什么停用：实测绝大多数区第 1 页就能凑满 1 亿（可买量常年几十亿），翻页纯属
#     多余请求，且是撞 DD373 速率风控的主因 ⇒ 改为**只读第 1 页**（见 fetch_costs）。
#   挂单数仍取站点权威总数（第 1 页「为您找到 N 条」）。
# ═══════════════════════════════════════════════════════════════════════════
_RE_SITE_TOTAL = re.compile(r"为您找到\s*<span[^>]*>\s*(\d+)\s*</span>\s*条记录")
_RE_SITE_PAGES = re.compile(r'hot-sum">\s*(\d+)\s*<')
_RE_SITE_PER = re.compile(r"(\d+)\s*条/页")


def _site_stat(html):
    """第 1 页里的站点权威统计 {总数, 页数, 每页}；取不到给 None（**不编数**）。"""
    def _one(rx):
        m = rx.search(html or "")
        return int(m.group(1)) if m else None
    return {"总数": _one(_RE_SITE_TOTAL), "页数": _one(_RE_SITE_PAGES),
            "每页": _one(_RE_SITE_PER)}


def _parse_quotes(html):
    """把一页里的**订单簿散单**解析出来（⛔ 热卖商城已剔除，见文件头 ②）。

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
    # ② 热卖商城：⛔ **已彻底剔除、不再解析**（2026-10-13 老板口径）
    #    其价低、非全体可见、更新快，且我方采购**不会去那买**
    #    ⇒ 算进成本会严重低估 ⇒ 成本口径**只取上方 ① 散单订单簿**。
    return out


def filter_outliers(quotes, low_ratio=OUTLIER_LOW_RATIO, high_ratio=OUTLIER_HIGH_RATIO,
                    min_keep=OUTLIER_MIN_KEEP):
    """**双侧离群过滤**：把「天价单」与「超低价单」整条剔除（2026-10-22 老板定案）。

    入参 quotes = [(可供量_万基纳, 单价_元每万, 来源) ...]（顺序无关）。
    返回 (过滤后的 quotes, 报告 dict)；`报告["已过滤"] == False` ⇒ 原数据一字未动。

    算法（3 步，只看**单价**，与数量无关 —— 数量另由「吃满」环节处理）：
      ① 基准 P0 = **按条数的价格中位数**（偶数条取中间两条的均值）；
      ② 围栏 `[P0 × low_ratio, P0 × high_ratio]`：落在两端的**整条剔除**
         （单价与可供量都不再参与成本；可买量随之减少，这会让该区自然地
          变「薄区/不足量」，从而被 GATE_WAN 那套兜底逻辑接住）；
      ③ 保险：剔完剩 < max(2, min_keep) 条 ⇒ **撤销过滤、原样返回**
         （方向性理由见 OUTLIER_MIN_KEEP：宁可成本偏高，也不判无货/被单条绑架）。

    ⚠ 这条函数**不做兜底编数**：输入为空就返回空 + None，由调用方判无报价。
    """
    qs = list(quotes or [])
    if not qs or (not low_ratio and not high_ratio):
        return qs, None
    prices = sorted(float(p) for _, p, _ in qs)
    n = len(prices)
    base = prices[n // 2] if n % 2 else (prices[n // 2 - 1] + prices[n // 2]) / 2.0
    lo = float(base) * float(low_ratio) if low_ratio else 0.0
    hi = float(base) * float(high_ratio) if high_ratio else float("inf")
    keep, drop_hi, drop_lo = [], [], []
    for t in qs:
        p = float(t[1])
        if p > hi:
            drop_hi.append(t)
        elif p < lo:
            drop_lo.append(t)
        else:
            keep.append(t)
    _need = max(2, int(min_keep or 0))
    rep = {"已过滤": False, "基准": base, "下限": lo, "上限": hi, "原始条数": n,
           "剔除条数": 0, "剔除量": 0.0, "高价条数": 0, "低价条数": 0,
           "剔除明细": []}
    if not drop_hi and not drop_lo:
        rep["说明"] = ("无离群挂单（价格带 %.4f~%.4f，基准 %.4f，围栏 %.4f~%.4f）"
                       % (prices[0], prices[-1], base, lo, hi))
        return qs, rep
    if len(keep) < _need:
        # ⚠ 撤销也要**留证据**：把「本来想剔哪些」记进报告，否则面板上看不出为什么没滤
        rep.update({
            "剔除条数": len(drop_hi) + len(drop_lo),
            "剔除量": sum(float(q) for q, _, _ in drop_hi + drop_lo),
            "高价条数": len(drop_hi), "低价条数": len(drop_lo),
            "剔除明细": ["%.0f万@%.4f(%s%s)" % (q, p, src, "·天价" if p > hi else "·超低")
                         for q, p, src in (drop_hi + drop_lo)][:6],
        })
        rep["说明"] = ("离群 %d 条（天价 %d / 超低 %d），但剔完只剩 %d 条（< %d）"
                       "⇒ **撤销过滤**，原样保留 %d 条"
                       "（宁可成本偏高，也不判无货 / 不被单条绑架）"
                       % (len(drop_hi) + len(drop_lo), len(drop_hi), len(drop_lo),
                          len(keep), _need, n))
        return qs, rep
    dropped = drop_hi + drop_lo
    _drop_wan = sum(float(q) for q, _, _ in dropped)
    _keep_wan = sum(float(q) for q, _, _ in keep)
    rep.update({
        "已过滤": True,
        "剔除条数": len(dropped),
        "剔除量": _drop_wan,
        "高价条数": len(drop_hi), "低价条数": len(drop_lo),
        "剔除明细": ["%.0f万@%.4f(%s%s)" % (q, p, src, "·天价" if p > hi else "·超低")
                     for q, p, src in dropped][:6],
        "剩余条数": len(keep), "剩余量": _keep_wan,
        "说明": ("基准 %.4f/万 ⇒ 围栏 [%.4f, %.4f]；剔掉 %d 条"
                 "（天价 %d 条 / 超低 %d 条，共 %.0f 万基纳），"
                 "剩 %d 条 %.0f 万继续算"
                 % (base, lo, hi, len(dropped), len(drop_hi), len(drop_lo),
                    _drop_wan, len(keep), _keep_wan)),
    })
    return keep, rep


def orderbook_avg(quotes, target_wan=TARGET_WAN, skip_lowest=SKIP_LOWEST_QUOTES,
                  fallback_items=FALLBACK_ITEMS, breakout_ratio=BREAKOUT_RATIO,
                  consume_all_below_target=False, outlier_filter=False,
                  outlier_low=OUTLIER_LOW_RATIO, outlier_high=OUTLIER_HIGH_RATIO,
                  outlier_min_keep=OUTLIER_MIN_KEEP):
    """按单价升序吃满 target_wan（万基纳）→ 数量加权均价。

    `skip_lowest`（2026-10-14 现行 = 1）：先**整条剔除单价最低的 N 条**（价格与库存都
      不计入，可买量也随之少算），再从第 N+1 条起向下「吃」。默认取模块常量 = 1 ——
      页面「综合排序」按价格升序给，所谓「第一个挂售的订单」就是排序后最便宜的 1 条；
      这类挂单常是超低价占位/挂错，留着会把整区成本拉低（老板口径）。AION2 与 MSCW
      （扁平专区）**现均取 1**（2026-10-14 晚 MSCW 已对齐）。
      ⚠ 与 `fallback_items` 的关系：**先跳过、再决定吃法** —— 剔掉最低 1 条后若剩余
        可买量仍 ≥ 目标量则按量吃满；不足则从第 2 条起按条数吃满 `fallback_items` 条。

    返回 None = 一条有效报价都没有（**剔完为空也算 None** ⇒ 调用方按无货兜底处理）；
    否则 dict：
      均价 / 参与条数 / 报价条数 / 可供量(剔完 skip 后剩下的全部可买) / 缺口 / 够量 /
      明细 / 跳过条数 / 原始条数 / 跳过明细 / 熔断 / 可用
    「明细」留前 6 条被吃掉的档位、「跳过明细」留被剔掉的条目，供面板/日志核对
    （这一条最值钱：能看到钱花在哪、以及跳掉了什么）。

    🔴 `breakout_ratio`（2026-10-20 老板定案「宁可冷门区没单子，也不冒风险设低价」）：
      吃单时若**下一条**单价 > 已吃均价 × 该倍数 ⇒ 立即停、`熔断` 非空。
      调用方**必须**把「熔断非空」当「无报价」处理（`可用` 已给出结论），
      绝不能拿吃到一半的订单簿算成本 —— 那正是「数据不可信却仍定价」的来源。
      传 0/None 即关闭熔断。

    🔴 `outlier_filter`（2026-10-22 老板定案「滤过那些天价单，过高过低的都移除」）：
      在「跳过最低 N 条」之后、吃单之前，先调 `filter_outliers()` 把**天价单**与
      **超低价单**整条剔掉，剩多少吃多少（可买量按剔完的算）。
      ⚠ **过滤一旦生效就不再熔断** —— 两者是同一件事的软/硬两版，同时开会互相打架
        （过滤后剩下的最高价仍可能 > 已吃均价 × 3，于是又被判无货，前功尽弃）；
        过滤被撤销（剔完条数不够）时**熔断照旧**，作为最后一道硬保险。
      返回 dict 里带 `离群过滤` 报告（基准/围栏/剔了谁），供面板与日志逐条核对。
    """
    qs = sorted(quotes or [], key=lambda x: x[1])
    _n_all = len(qs)
    _skip = int(skip_lowest or 0)
    if _skip < 0:
        _skip = 0
    skipped = []
    if _skip:
        # ⚠ 这里**刻意不做「至少留一条」的兜底**：剔完为空就该判「无报价」，
        #   由调用方按无货兜底价处理 —— 宁可挂兜底高价，也不拿一条可疑超低价定价。
        skipped = qs[:_skip]
        qs = qs[_skip:]
    # ── 2026-10-22 双侧离群过滤：先剔天价单 / 超低价单，再按量吃满 ──────────────
    #    顺序很重要：**先 skip_lowest、再算中位数** —— 否则基准会被那条超低价带偏，
    #    围栏整体下移，反而把正常单当成天价剔掉。
    _of = None
    if outlier_filter and OUTLIER_ENABLED:
        qs, _of = filter_outliers(qs, low_ratio=outlier_low, high_ratio=outlier_high,
                                  min_keep=outlier_min_keep)
    all_avail = sum(q for q, _, _ in qs)
    need = float(target_wan)
    # 2026-10-12 老板定案：可买量不足目标量（5 亿基纳）时不再按量吃，改为
    #   按条数吃满前 fallback_items 条（单价升序）—— 老板原话「不足 5 亿的区按条数
    #   计算，抓满 10 条为准」。避免薄区被一条大额挂单「一吃就满」而把成本算低。
    _fi = int(fallback_items or 0)
    # 2026-10-22：AION2 传 `consume_all_below_target=True` ⇒ 可买不足目标量时**不再按条数降级**，
    #   直接走下面的「按量」分支把 qs 全部吃完（need 吃完仍有剩无妨，循环自然结束）
    #   ⇒ 均价 = 这批挂单的**全量加权均价**。MSCW 不传该参数，行为与改造前完全一致。
    _by_items = (not consume_all_below_target) and (all_avail < need - 1e-6) and _fi > 0
    # ── 离群熔断（2026-10-20）：每吃一条前先看「这一条是不是贵得离谱」────────────
    #    只在**已吃到东西**之后才判（第 1 条没有基准，永远放行），
    #    基准 = 已吃部分的**数量加权均价**（不是首条价，避免首条异常把基准带偏）。
    _bo = float(breakout_ratio or 0)
    # 2026-10-22：过滤**已生效** ⇒ 关掉吃单熔断（软过滤替代硬熔断，避免二次误判无货）；
    #   过滤**被撤销**（原样返回）或根本没开 ⇒ 熔断照旧兜底。
    if _of and _of.get("已过滤"):
        _bo = 0.0
    _brk = None                       # 触发时记下证据，供面板 / 日志逐条追溯
    cost = got = 0.0
    used = []
    if _by_items:
        for q, pr, src in qs[:_fi]:
            if _bo and got > 0 and pr > (cost / got) * _bo:
                _brk = {"单价": pr, "已吃均价": cost / got, "倍数": pr / (cost / got),
                        "序号": len(used) + 1, "可买": q, "已吃量": got,
                        "缺口": max(0.0, float(target_wan) - got), "方式": "按条数"}
                break
            cost += q * pr
            got += q
            used.append("%.0f万@%.4f(%s)" % (q, pr, src))
    else:
        for q, pr, src in qs:
            if need <= 0:
                break
            if _bo and got > 0 and pr > (cost / got) * _bo:
                _brk = {"单价": pr, "已吃均价": cost / got, "倍数": pr / (cost / got),
                        "序号": len(used) + 1, "可买": q, "已吃量": got,
                        "缺口": need, "方式": "按量"}
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
        # 2026-10-12：把「吃单方式」如实带出去（按量 / 按条数），日志与工单可核对
        "吃单方式": ((("按条数吃满%d条" % _fi) if _by_items
                      else ("按量吃满%.0f万" % (float(target_wan)
                                                if all_avail >= float(target_wan) - 1e-6
                                                else all_avail)))
                     + (("·熔断于第%d条" % _brk["序号"]) if _brk else "")
                     + (("·剔除离群%d条" % _of["剔除条数"])
                        if (_of and _of.get("已过滤")) else "")),
        "按条数": bool(_by_items),
        "目标条数": (_fi if _by_items else None),
        "明细": used[:6],
        # 2026-10-09：把「剔了谁」如实带出去，面板/日志可逐条核对（成本是定价输入，必须可追溯）
        "跳过条数": len(skipped),
        "原始条数": _n_all,
        "跳过明细": ["%.0f万@%.4f(%s)" % (q, pr, src) for q, pr, src in skipped],
        # 2026-10-22：双侧离群过滤的报告（基准/围栏/剔了谁），无离群时也带一份说明
        "离群过滤": _of,
        # 2026-10-20：离群熔断的结论与证据（调用方**必须**按「可用=False」判无报价）
        "熔断": _brk,
        "可用": not _brk,
        "熔断说明": (None if not _brk else
                     "⛔ 离群熔断：吃到第 %d 条时，下一条单价 %.4f 元/万 = 已吃均价 %.4f 的"
                     " %.1f 倍（阈值 %gx）⇒ 停止吃单，本区判无报价、走默认售价兜底。"
                     "熔断前已吃 %.0f 万，缺口 %.0f 万"
                     % (_brk["序号"], _brk["单价"], _brk["已吃均价"], _brk["倍数"], _bo,
                        _brk["已吃量"], _brk["缺口"])),
    }


def parse_first(html, unit_name="万基纳", unit_kw=("万", "10000", "w", "W")):
    """取**综合排序第一条**的单价。抓不到返回 None（**不编数**）。

    `unit_name` 是页面上的单位串（AION2 = 「万基纳」，MSCW = 「万金」）；
    自校验 ② 原本写死「万基纳」，2026-10-08 参数化 —— MSCW 页面单位是「万金」，
    写死会把**每一个区**都判成「单位口径异常，已丢弃」，MSCW 一条成本都采不到。
    """
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
    # 自校验 ②：**单位必须 = unit_name**。若站点改成「亿基纳」「个」或别的量纲，
    #   下面的 ×wan_per_unit 换算就会错 10~10000 倍 —— 所以单位必须校验。
    bad = []
    if out["每元可买"]:
        exp = 1.0 / price if price else None
        if exp and abs(out["每元可买"] - exp) / exp > 0.01:
            bad.append("单价与比例不自洽（1元=%s%s vs 1/%s）"
                       % (out["每元可买"], unit_name, price))
    un = (out["单位"] or "")
    for _t in (unit_name, "基纳", "金"):
        un = un.replace(_t, "")
    un = un.replace(" ", "")
    if un and un not in unit_kw:
        bad.append("⚠单位不是「%s」而是「%s」—— 换算会错，**本条不可用**"
                   % (unit_name, out["单位"]))
    if bad:
        out["自校验"] = "；".join(bad)
        out["不可用"] = any("不可用" in b for b in bad)
    return out


# ---------------------------------------------------------------------------
# 单位换算：元/万{单位} → 美元/前端单位
# ---------------------------------------------------------------------------
# AION2：1 M 基纳 = 1,000,000 基纳 = 100 ×「万基纳」⇒ 每「M」合 100 个万。
WAN_PER_M = 100.0


def to_usd_per_unit(price_yuan_per_wan, rate, wan_per_unit=WAN_PER_M):
    """元/万{单位} → 美元/**前端单位**。rate = 汇率（USD→CNY）。

    `wan_per_unit` = 前端 1 个单位合多少个「万」：
      · AION2    前端单位 = M 基纳 = 100 万基纳 ⇒ 100
      · MSCW     前端单位 = K 金   = 1,000 金 = 0.1 万金 ⇒ **0.1**
        （1 万金 = 10,000 金 = 10 K ⇒ 1 K = 0.1 万金）
    ⚠ AION2 与 MSCW 的「万」都指 10000 个货币，但**前端单位不同**（M vs K），
      所以这个系数必须按专区配，不能共用 100 —— 共用会把 MSCW 成本放大 1000 倍。
    """
    if price_yuan_per_wan is None or not rate:
        return None
    return float(price_yuan_per_wan) * float(wan_per_unit) / float(rate)


def to_usd_per_m(price_yuan_per_wan, rate):
    """元/万基纳 → 美元/百万基纳（AION2 专用，保留旧签名）。"""
    return to_usd_per_unit(price_yuan_per_wan, rate, WAN_PER_M)


# ═══════════════════════════════════════════════════════════════════════════
# 扁平专区（2026-10-08 新增）—— MapleStory Classic World（冒险岛怀旧服国际服）
# ═══════════════════════════════════════════════════════════════════════════
# 与 AION2 的差别：**没有「区 → 种族 → 游戏区」三层**，只有「北美NA / 欧洲EU」两个
#   子区段，货币在 global 内互通 ⇒ 两个子区**合并成一本订单簿**再算加权均价。
#
# 实测（2026-10-08，服务器出口 IP 47.85.224.112 · 未被风控）：
#   · 北美NA 段 `k5faqj`：117 条 / 6 页，第 1 页可买 **75 万金**（< 100 万 ⇒ 必须翻页）
#     【2026-10-12 复测】北美NA **203 条 / 11 页**，第 1 页可买 **1653 万金**（≥ 500 万 ⇒ 首页即够）；
#       欧洲EU 仍恒为 0 条；6 页合计可买 1.15 亿金（余量充足）。
#   · 欧洲EU 段 `sphpwv`：**0 条挂单**（页面正常渲染，非风控；并入后不改变结果）
#   · 单价口径：`<input class="goods-num" max="3" singleprice="16.6112957">`
#       ⇒ singleprice = **元/万金**，页面单位串 = 「万金」
#       自校验：`1元=0.0602万金` 与 singleprice 互为倒数（0.0602 ≈ 1/16.611）✓
#   · 分页：❌ `?PageIndex=N` 被阿里云 ESA 拦（11956 字节滑块页，实测 blocked=True）；
#           ✅ **只改长 URL 的第 13 段**（`…-0-0-0-et9e1b-0-0-0-0-0-{页}-0-0-0.html`）
#              实测 page=2 内容与 page=1 不重复、可正常解析（page2 首单价 18.0 vs page1 16.61）
#
# 🔴 目标量：
#   2026-10-08 用户口径：「以存货 100W 货币为兜底，遍历页面直到够 100w 金币，
#                         然后计算这 100w 金币的平均价」⇒ target_wan = 100 万金。
#   2026-10-12 用户口径：**拉高到 500 万金**（「由 100w 提高至 500w」）⇒ target_wan = 500 万金。
#   2026-10-12 晚 用户口径：**再拉高到 800 万金**（「500 万改 800 万」）⇒ target_wan = 800 万金。
#     实测（2026-10-12 · 服务器出口 IP 47.85.224.112）：北美NA 首页即可买 **1653 万金**、
#     前 3 条单价同为 6.373490 元/万金 ⇒ **800 万仍在第 1 页内吃满**，请求数不变（仍 2 次/轮）。
#     （不是 AION2 的 1 亿 = 10000 万基纳；两者目标量本来就不同。）
#   2026-10-14 晚 用户口径：**800 万 → 1000 万**（「将 800w 换成 1000w」）⇒ target_wan = 1000 万金。
#     ⚠ 同日起**跳过订单簿最低 1 条**（「跟 aion2 一样」，老板：AION2 曾因第一条超低价
#       把整区成本拉崩）。首页可买量远超 1000 万 ⇒ 剔掉最低 1 条后仍在第 1 页内吃满，请求数不变。
#   🔴 2026-11-03 用户口径：**目标量 800 万 → 500 万金（5M），并要求订单簿最低 10 条**
#     （原话：「成本抓取还是从 DD373 抓，抓取总额要满5M，条数最低10条」）。
#     ⇒ target_wan = 500.0、新增 min_quotes = 10：
#       ① 加权均价只吃「够 500 万金」的挂单（不够 500 万继续翻页续抓）；
#       ② **同时要求参与订单簿的挂单 ≥ 10 条**才算够 —— 只够量不够条数就继续翻页补条数，
#          避免少数几条大单把整区均价定死（AION2 踩过同类坑）。
#     实测（2026-11-03 · 183 出网）：首页可买 889~1339 万金、挂单 133~160 条 ⇒
#     5M + 10 条在第 1 页内即可满足（仍只请求 2 次/轮：NA + EU 各 1 页）。
#
# ⚠ `wan_per_unit` = 前端 1 个单位合多少个「万」：
#     前端单位是 **K**（档位 10/20/…/500，data-unit="K"）⇒ 1 K = 1000 金 = 0.1 万金。
#     填 0.1（不是 100）。填错会把成本放大 1000 倍、目标价被兜底线整个顶飞。
FLAT_ZONES = {
    "MapleStory Classic World": {
        "sid": "063g3j",            # 专区「新枫之谷经典版冒险岛怀旧服」
        "cate_seg": "46qwx3",       # 品类/子区上一层段（AION2 的对应位是 2c2xs4）
        "type_seg": "et9e1b",       # 商品类型段（游戏币）
        "unit_name": "万金",        # 页面上的单位串（parse_first 自校验用）
        "wan_per_unit": 0.1,        # 前端单位 = K ⇒ 1 K = 0.1 万金
        "target_wan": 500.0,        # 目标：买满 500 万金（2026-11-03 老板定案 800w → 500w = 5M；不足 500 万自动翻页续抓，取订单簿加权均价）
        "min_quotes": 10,           # 2026-11-03 老板定案：订单簿挂单**最低 10 条**（不够条数即使够量也继续翻页续抓）
        "skip_lowest": 1,           # 2026-10-14 老板：跳过订单簿最低 1 条（与 AION2 同口径）
        "max_pages": 6,             # 够量且够条数才停；首页可买量远超目标 ⇒ 通常仍只请求 1 页
        "sub": {                    # 我方「大区」→ (DD373 子区展示名, URL 段)
            "Global": ("北美NA+欧洲EU", "k5faqj"),
        },
        # 合并统计的子区段（**两个都抓**，用户口径：global 内货币互通）
        "sub_segs": [("北美NA", "k5faqj"), ("欧洲EU", "sphpwv")],
    },
}


def _flat_url(z, sub_seg, page=1):
    """扁平专区（MSCW）的商品页长 URL。

    段位顺序是**从用户给的线上页面抄的**，别自己推：
      /s-{sid}-{品类段}-{子区段}-0-0-0-{商品类型段}-0-0-0-0-0-{页}-0-0-0.html
    ⚠ 翻页**只能改第 13 段**；`?PageIndex=N` 在本专区被 ESA 拦（与 AION2 正好相反）。
    """
    return "%s/s-%s-%s-%s-0-0-0-%s-0-0-0-0-0-%d-0-0-0.html" % (
        BASE, z["sid"], z["cate_seg"], sub_seg, z["type_seg"], max(1, int(page)))


def _collect_flat_game(game, rate, log=None, gap=1.3):
    """把扁平专区的**全部子区合并**成一本订单簿，「吃」满目标量后返回成本记录。

    返回 (记录 dict, {子区名: 站点统计})。记录结构对 AION2 的记录**保持同名兼容**
    （成本_元每万基纳 / 成本_USD每M / 可供量_万基纳 / 库存 / 商品条数 / 依据 / URL …），
    这样 store.save_gold_cost、看板、app.py 的注入链一行都不用改。

    ⚠ 字段名里的「基纳」在本专区实为「金」（沿用旧字段名是为了不改下游）。
    """
    z = FLAT_ZONES[game]
    subs = list(z.get("sub_segs") or list((z.get("sub") or {}).values()))
    tgt = float(z.get("target_wan") or 500.0)
    # 2026-11-03 老板定案：订单簿**最低条数**（MSCW = 10）。够量但不够条数 ⇒ 继续翻页补。
    #   0 / 缺失 = 不设条数门槛（旧行为）。
    min_quotes = int(z.get("min_quotes") or 0)
    unit_name = z.get("unit_name") or "万金"
    wpu = float(z.get("wan_per_unit") or WAN_PER_M)
    quotes = []
    pages_used = 0
    site = {"总数": None, "页数": None, "每页": None}
    urls = []
    notes = []
    _chk = None
    for page in range(1, int(z.get("max_pages") or 6) + 1):
        for dd_area, seg in subs:
            url = _flat_url(z, seg, page)
            try:
                html = _get(url, referer=BASE + "/", tries=2)
            except Exception as e:                 # noqa: BLE001
                notes.append("%s p%d 抓取失败(%r)" % (dd_area, page, e))
                continue
            if _blocked(html):
                # 被风控 ≠ 没货 ⇒ **整轮中止**，别把剩下几页打成「无报价」
                return ({"ok": False, "依据": "被 DD373 风控拦截（不是无货）",
                         "备注": "返回阿里云 ESA 滑块验证页；本轮已停止采集，"
                                 "沿用上一轮快照", "URL": url}, site)
            pages_used += 1
            urls.append(url)
            _q = _parse_quotes(html)
            quotes.extend(_q)
            # 站点统计取**有数据那一页**的（欧洲EU 永远是 0，取它会把总数写成 0）
            _s = _site_stat(html)
            for _k in ("总数", "页数", "每页"):
                if _s.get(_k) and not site.get(_k):
                    site[_k] = _s[_k]
            if _chk is None and _q:
                _chk = parse_first(html, unit_name)
                if _chk and _chk.get("不可用"):
                    # 单位口径异常 ⇒ **整轮丢弃**，宁缺勿错（成本是兜底线输入）
                    return ({"ok": False, "依据": "单位口径异常，已丢弃（不写脏值）",
                             "备注": _chk.get("自校验"), "URL": url}, site)
            if gap:
                time.sleep(gap)
        # 本页（两个子区）都吃完了：够量就停（用户口径「遍历页面直到够目标量」）
        # 🔴 2026-11-03：**量 + 条数 双条件**。只够量但挂单不足 min_quotes 条 ⇒ 继续翻页补条数，
        #   避免「少数几条大单把整区均价定死」（老板口径：条数最低 10 条）。
        if (sum(q for q, _, _ in quotes) >= tgt - 1e-6
                and (not min_quotes or len(quotes) >= min_quotes)):
            break
        if pages_used == 0:
            break                       # 一页都没抓到（全失败）→ 别空转到底
    # ✅ 2026-10-14 晚：MSCW **改为一并跳过最低 N 条**（老板：「跳过订单簿的第一条，
    #   跟 aion2 一样，之前 aion2 因为第一条超低价导致价格崩了」）。
    #   数值取自本专区配置 `skip_lowest`，缺省回落模块常量 SKIP_LOWEST_QUOTES（=1）。
    _skip = int(z.get("skip_lowest", SKIP_LOWEST_QUOTES))
    # 2026-10-20：MSCW **同步启用离群熔断**（与 AION2 同一口径、同一阈值，
    #   可在 FLAT_ZONES 里用 `breakout_ratio` 单独覆盖；设 0 即关闭）。
    _bo = float(z.get("breakout_ratio", BREAKOUT_RATIO) or 0)
    ob = orderbook_avg(quotes, tgt, skip_lowest=_skip, breakout_ratio=_bo)
    if not ob:
        return ({"ok": False, "依据": "DD373 该专区暂无在售商品",
                 "备注": "页面正常渲染（未被风控）；两子区合并后 0 条可买挂单；"
                         + ("；".join(notes) if notes else "站点共 %s 条记录"
                            % (site.get("总数") if site.get("总数") is not None else 0)),
                 "URL": urls[0] if urls else ""}, site)
    if not ob.get("可用", True):
        # 价格结构断裂 ⇒ 判无报价（老板口径：宁可不卖，不冒险设低价）
        _bk = ob.get("熔断") or {}
        if log:
            log("  [DD373] %-24s %s" % (z.get("sub", {}).get("Global", ("", "-"))[0],
                                         ob.get("熔断说明")))
        return ({"ok": False,
                 "依据": "离群熔断：下一条 ￥%.4f = 已吃均价 ￥%.4f 的 %.1f 倍"
                         % (_bk.get("单价", 0), _bk.get("已吃均价", 0), _bk.get("倍数", 0)),
                 "备注": ob.get("熔断说明"),
                 "可供量_万基纳": ob["可供量"],
                 "URL": urls[0] if urls else ""}, site)
    _pr = ob["均价"]
    _usd = to_usd_per_unit(_pr, rate, wpu)
    _tot = site.get("总数")
    _short = (None if ob["够量"] else
              "该专区 %d 页内仅可买 %.0f 万金（< %.0f 万），均价按现有挂单加权"
              % (pages_used, ob["可供量"], tgt))
    # 2026-11-03：条数是否达标（老板口径「条数最低 10 条」）—— 供定价侧判「数据够不够用」
    _short_q = (None if (not min_quotes or ob["报价条数"] >= min_quotes) else
                "该专区 %d 页内仅 %d 条挂单（< %d 条），样本偏薄"
                % (pages_used, ob["报价条数"], min_quotes))
    rec = {
        "ok": True,
        "成本_元每万基纳": _pr,
        "单位": unit_name,
        "成本_USD每M": _usd,                       # ⚠ 本专区实为 $/K（前端单位就是 K）
        "前端单位": "K",
        "可供量_万基纳": ob["可供量"], "够量": ob["够量"],
        "目标量_万金": tgt,                        # 2026-11-03：本轮买满目标（5M = 500 万金）
        "条数下限": min_quotes or None,            # 2026-11-03：挂单条数门槛（10 条）
        "条数够": (not min_quotes) or ob["报价条数"] >= min_quotes,
        "参与条数": ob["参与条数"],
        "库存": "可买%.0f万金" % ob["可供量"],
        "起售": None,
        "商品条数": (_tot if _tot is not None else ob["报价条数"]),
        "本页条数": len(quotes),
        "解析条数": ob["报价条数"],
        "站点页数": site.get("页数"),
        "翻页数": pages_used,
        "DD区": z.get("sub", {}).get("Global", ("", ""))[0],
        "DD种族": "-", "DD游戏区": "Global（NA+EU 合并）",
        "跳过条数": ob.get("跳过条数", 0),
        "跳过明细": ob.get("跳过明细") or [],
        "依据": "北美NA+欧洲EU 合并 · 买满 %.0f 万金订单簿加权(吃%d/%d条·翻%d页%s%s)"
                % (tgt, ob["参与条数"], ob["报价条数"], pages_used,
                   ("·跳过最低%d条" % ob["跳过条数"]) if ob.get("跳过条数") else "",
                   ("·要求≥%d条" % min_quotes) if min_quotes else ""),
        "URL": urls[0] if urls else "",
    }
    _own = "；".join(x for x in ((_chk or {}).get("自校验"), _short, _short_q,
                                 ("单价口径：元/万金 ÷ 汇率 ÷ 10 = $/K"
                                  "（1 万金 = 10 K，前端单位 K）"),
                                 ("；".join(notes) if notes else None)) if x)
    if _own:
        rec["备注"] = _own
    if log:
        log("  [DD373] %-24s 买满 %.0f 万金 → %.6f 元/万金 = $%.6f/K "
            "(吃%d/%d条·翻%d页%s%s·可买%.0f万金%s)"
            % (z.get("sub", {}).get("Global", ("", "-"))[0], tgt, _pr, _usd or 0,
               ob["参与条数"], ob["报价条数"], pages_used,
               ("·跳过最低%d条" % ob["跳过条数"]) if ob.get("跳过条数") else "",
               ("·要求≥%d条" % min_quotes) if min_quotes else "",
               ob["可供量"],
               "" if ob["够量"] else "·不足%.0f万" % tgt))
    return (rec, site)


def _fetch_costs_flat(servers, rate, log=None, gap=1.3, game=None):
    """扁平专区（MSCW）：整个游戏**共用一本订单簿**，结果写给该游戏全部服务区。"""
    g = game or (servers[0].get("游戏") if servers else None)
    if g not in FLAT_ZONES:
        if log:
            log("  [DD373] 扁平专区未登记：%r" % (g,))
        return {}
    svs = [s for s in (servers or []) if s.get("key")]
    if not svs:
        return {}
    rec, _site = _collect_flat_game(g, rate, log=log, gap=gap)
    return {s.get("key"): dict(rec) for s in svs}


# ---------------------------------------------------------------------------
# 主入口（按游戏分发：AION2 三层树+首屏；MSCW 扁平子区+合并翻页）
# ---------------------------------------------------------------------------
def fetch_costs(servers, rate, log=None, gap=1.3, refresh_tree=False, game=None):
    """给一批服务区取 DD373 成本 —— **按游戏分发**。

    · 游戏 ∈ FLAT_ZONES（MSCW）⇒ `_fetch_costs_flat`（扁平子区 + 合并 + 翻页到够量）；
    · 其余（AION2 / 未指定）    ⇒ `_fetch_costs_aion2`（原逻辑，一字未改）。

    ⚠ 调用方一次**只传一个游戏**的服务区（app.py 按游戏循环）；
      混游戏传入时按 `servers[0].游戏` 分发 —— 别依赖这个兜底。
    """
    svs = [s for s in (servers or []) if s.get("key")]
    if not svs:
        return {}
    g = game or svs[0].get("游戏") or ""
    if g in FLAT_ZONES:
        return _fetch_costs_flat(svs, rate, log=log, gap=gap, game=g)
    return _fetch_costs_aion2(svs, rate, log=log, gap=gap, refresh_tree=refresh_tree)


def _fetch_costs_aion2(servers, rate, log=None, gap=1.3, refresh_tree=False):
    """给一批服务区取 DD373 成本。

    servers : [{key, 大区, 名称或 g2g_服务区}] —— 直接传 config.金币.服务区 里的条目
    rate    : 汇率（USD→CNY），用于折成 $/M
    返回   : {key: {...}}，每条含
               ok            布尔
              成本_元每万基纳  **5 亿订单簿加权均价**（元/万基纳，面板主显）
              成本_USD每M     折算后（算利润率、做成本兜底都用它）
              可供量_万基纳   已翻页码内可买总量（判断够不够 5 亿）
              够量           布尔（可供量 ≥ 5 亿）
               参与条数       被吃进订单簿的档位数
               商品条数       **站点权威挂单总数**（第 1 页「为您找到 N 条记录」，只数散单）
                              ⚠ 面板「挂单数」= 这个；热卖商城已剔除，口径与散单解析条数一致
               本页条数       第 1 页解析到的挂单条数（诊断用）
               解析条数       已翻页去重后解析到的挂单条数（诊断用）
               站点页数       站点给出的总页数
               翻页数         本轮实际翻到的页数（2026-10-06 起取消翻页，恒为 1）
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
            # 退一步：**同一大区内**只按名字找（万一大区名写法有出入）。
            # 🔴 2026-10-06 实测踩过，这里**必须限定同一大区**：
            #   DD373 列表页里有「裸名」重复条目（如 `EU|azphel`、`South America|zikel`），
            #   旧版 fallback 不限大区 ⇒「唯一同名候选」会跨大区命中 ⇒
            #   日服 / 北美东 / 南美的 Azphel 全部被套上**欧服** Azphel 的进货价、
            #   其余 Zikel 全被套上**南美** Zikel 的价 —— 实测 7 行错配**并已出单改价**。
            #   宁可判成「无对应区」（→ 走 $19.9 兜底），也绝不取错大区的价。
            cand = [v for k, v in tree.items()
                    if k.split("|", 1)[0] == area and k.split("|", 1)[1] == _norm(nm)]
            if len(cand) == 1:
                info = cand[0]
                if log:
                    log("  [DD373] %-24s · 精确键未命中，用同大区同名兜底 → %s"
                        % (key, info["url_seg"]))
            elif log:
                log("  [DD373] %-24s · 精确键未命中；同大区同名候选 %d 个 "
                    "（拒绝跨大区兜底）" % (key, len(cand)))
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
        # ══ 取订单簿：**Api 优先，Html 回落**（2026-10-20）════════════════════════
        #   Api  : 30 条结构化 JSON、按单价升序（= 全网最便宜的 30 条）、无需鉴权；
        #          不吃 ESA 滑块页，从根上消除「被拦当成没货」的误判。
        #   Html : **完整保留为回落**（下面 else 分支，缩进后一字未改）——
        #          Api 一旦改版/被拦/网络抖动，行为与改造前完全一致，不至于全线停摆。
        _budget["n"] -= 1
        _src, _q1, _chk = "api", None, None
        _site = {"总数": None, "页数": None, "每页": None}
        url = _short_url(info["url_seg"])
        try:
            _r = _api_quotes(info)
            _q1 = _r["quotes"]
            if _r["丢弃条数"]:
                # 个别条目单位/数值不合规 ⇒ 只丢该条、不丢整区，但要在备注里点名
                _chk = {"自校验": "Api 有 %d 条单位/数值不合规已丢弃（接口共 %d 条）"
                                  % (_r["丢弃条数"], _r["行数"])}
        except Exception as e:                      # noqa: BLE001
            _q1 = None
            if log:
                log("  [DD373] %-24s · Api 取单失败，回落 HTML：%r" % (key, e))
        if _q1 is None:
            # ──────────── 回落 HTML（改造前的原逻辑）────────────
            _src = "html"
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
            _q1 = _parse_quotes(html)
            _site = _site_stat(html)
        # ── 订单簿：**只读第 1 页 / 只取最便宜的前 30 条**────────────────────────
        #    历史三版：
        #      ① 旧版只读第 1 页（当时误以为口径偏小）；
        #      ② 打通 `?PageIndex=N` 后改成**翻完站点全部页** ⇒ 拿到全市场最便宜的 1 亿，
        #         但每轮请求膨胀到约 162 次，紧贴「约 200 次/短窗口」限流线，实测撞过风控；
        #      ③ 「够 1 亿即停」⇒ 请求降到 86~120 次，但薄区仍会继续翻页。
        #    现在：**只取第 1 页**。理由（老板原话）：
        #      「如果翻页了那大概率也会是首页已满 1 亿的量了」——
        #      实测绝大多数区可买量就是几十亿，翻页拿不到更便宜的均价，
        #      纯属多余请求、且是撞风控的主因 ⇒ 恒定 86 次请求，风控余量最大。
        #    薄区（不足目标量）也不再翻：按现有挂单加权 + 离群熔断兜住，缺口写进备注。
        _pages = 1                     # 只读第 1 页（取消翻页）；字段「翻页数」兼容保留
        # 2026-10-22：新增 `outlier_filter=True` —— 吃单之前先剔掉天价单/超低价单
        #   （老板：「滤过那些天价单，过高过低的都移除」）。MSCW 不传，行为不变。
        ob = orderbook_avg(_q1, consume_all_below_target=True, outlier_filter=True)
        if not ob:
            _n0 = _site["总数"] if _site["总数"] is not None else 0
            if SKIP_LOWEST_QUOTES > 0 and _q1:
                # 🔴 2026-10-14：**有挂单、但被「跳过最低 N 条」剔空了** —— 必须与
                #    「站点真的 0 条」区分开。原来统一报「暂无在售商品」，等于把我们
                #    主动跳过说成站点没货，面板会误导人。
                _sk = sorted(_q1, key=lambda x: x[1])[:SKIP_LOWEST_QUOTES]
                out[key] = {
                    "ok": False,
                    "依据": "跳过最低 %d 条后已无可买挂单（原 %d 条）"
                            % (len(_sk), len(_q1)),
                    "备注": "该区首页仅 %d 条可买挂单，被 2026-10-14 新口径"
                            "「跳过最低 %d 条」整条剔除后为空 ⇒ 按无报价处理"
                            "（不足目标量 ⇒ 无货兜底）；剔除明细：%s"
                            % (len(_q1), len(_sk),
                               "；".join("%.0f万@%.4f(%s)" % t for t in _sk)),
                    "URL": url}
                if log:
                    log("  [DD373] %-24s · 跳过最低 %d 条后无剩余挂单（原 %d 条）"
                        % (key, len(_sk), len(_q1)))
            else:
                out[key] = {"ok": False, "依据": "DD373 该游戏区暂无在售商品",
                            "备注": "页面正常渲染（未被风控），站点共 %s 条记录" % _n0,
                            "URL": url}
                if log:
                    log("  [DD373] %-24s · 无报价（0 条挂单，非风控）" % key)
            time.sleep(gap)
            continue
        # 🔴 离群熔断（2026-10-20 老板定案）：价格结构断裂 ⇒ **本区判无报价**。
        #    绝不拿「吃到一半」的订单簿算成本 —— 那正是「数据不可信却仍定价」的来源。
        #    老板原话：「宁愿那些冷门区没单子，也不能冒风险设低价被用户爆单」
        #    ⇒ 走默认售价兜底。实测这类薄区真实成本仅 $1.1~2.1/M，兜底价是**涨价**方向。
        # 🔴 2026-10-22 二次定案修订：**薄区（可买量 < 2 亿）不熔断**。
        #    薄区售价已在 core_gold 钉死 $4.99/M（薄区挂单价），成本只作展示/核算；
        #    在这里熔断只会把成本变成「无报价」，进而让售价被误判成 $19.9，与老板口径冲突。
        #    ⇒ 薄区直接用 ob["均价"]（未触发熔断时 = 全量加权均价；
        #      触发熔断时 = 熔断前已吃部分的加权均价，宁可偏低也不判无货）。
        _thin_zone = ob["可供量"] < GATE_WAN - 1e-6
        if not ob.get("可用", True) and not _thin_zone:
            _bk = ob.get("熔断") or {}
            out[key] = {
                "ok": False,
                "依据": "离群熔断：下一条 ￥%.4f = 已吃均价 ￥%.4f 的 %.1f 倍"
                        % (_bk.get("单价", 0), _bk.get("已吃均价", 0), _bk.get("倍数", 0)),
                "备注": ob.get("熔断说明"),
                "可供量_万基纳": ob["可供量"],
                "URL": url,
            }
            if log:
                log("  [DD373] %-24s %s" % (key, ob.get("熔断说明")))
            time.sleep(gap)
            continue
        _pr = ob["均价"]
        # 站点权威统计（第 1 页就有）：挂单总数 / 总页数。
        #   注意：「为您找到 N 条」= 散单挂单总数（热卖商城已剔除，口径一致）。
        #   ⚠ 只读第 1 页（20 条/页）⇒「解析条数」通常**小于**站点总数，这是本口径的
        #     **预期现象**、不是解析漏了（「挂单数」照样取站点权威总数）。
        #   ⚠ 2026-10-20 起 Api 模式**没有总数字段**（只给前 30 条）⇒「挂单数」退化为
        #     接口返回条数（面板会显示 ≤30），真实总数大于它，这是已知的信息损失。
        _tot_n = (_site["总数"] if _site["总数"] is not None
                  else (len(_q1) if _src == "api" else ob["报价条数"]))
        _pgs_n = _site["页数"]
        _pgs_s = "%d" % _pgs_n if _pgs_n is not None else "?"
        # 2026-10-22 起：不足 5 亿不再「按条数吃 10 条」，改为**按全部可买量全量加权**
        _short_note = (None if ob["够量"] else
                       "该区可买挂单仅 %.0f 万基纳（< %g 亿），成本按**全部可买量**加权"
                       % (ob["可供量"], float(TARGET_WAN) / 10000.0))
        if _thin_zone:
            _short_note = ((_short_note or "") +
                           "；薄区（< %g 亿）跳过离群熔断%s"
                           % (GATE_WAN / 10000.0,
                              "，采用熔断前已吃部分均价" if not ob.get("可用", True) else ""))
        # 2026-10-09：把「跳过了哪 2 条」写进备注 —— 老板要看的就是这两条是不是超低价
        _skip_note = (None if not ob["跳过条数"] else
                      "⏭ 已跳过**单价最低的 %d 条**（= 综合排序第一个挂售订单；"
                      "价格与库存都不计入成本）：%s"
                      % (ob["跳过条数"], "；".join(ob["跳过明细"] or []) or "-"))
        # 2026-10-22：把「剔掉了哪几条离群单」写进备注 —— 天价单/占位单必须可追溯
        #   （老板核对成本时看的就是这条：到底剔了哪几条、剔完剩多少量）
        _of = ob.get("离群过滤") or {}
        _of_note = None
        if _of.get("已过滤"):
            _of_note = ("🧹 **离群过滤**：%s；剔除明细：%s"
                        % (_of.get("说明") or "",
                           "；".join(_of.get("剔除明细") or []) or "-"))
        elif _of.get("剔除条数"):
            _of_note = "🧹 离群过滤未应用：%s" % (_of.get("说明") or "")
        if SKIP_LOWEST_QUOTES:
            _skip_cap = ("2026-10-14 起**跳过最低 %d 条**（第一个挂售的订单不计入），"
                         "原始 %d 条 → 参与 %d 条"
                         % (SKIP_LOWEST_QUOTES, ob["原始条数"], ob["报价条数"]))
        else:
            _skip_cap = ("**不跳过任何条**，原始 %d 条全部参与"
                         % ob["报价条数"])
        # 2026-10-22：口径里明写「双侧离群过滤」，面板上能直接看到规则
        _of_cap = ("**双侧离群过滤**（> 基准×%g 判天价、< 基准×%g 判超低，整条剔除）"
                   % (OUTLIER_HIGH_RATIO, OUTLIER_LOW_RATIO)) if OUTLIER_ENABLED else ""
        if _src == "api":
            _cap_note = ("口径：成本/可买量 = **官方 Api 返回的最便宜 %d 条**散单订单簿"
                         "（2026-10-20 起走 Api；接口硬上限 %d 条、分页参数无效；"
                         "热卖商城不在返回内，天然剔除；%s；%s）；"
                         "接口不提供挂单总数 ⇒「挂单数」= 接口返回条数 %d"
                         % (len(_q1), API_ROWS, _skip_cap, _of_cap or "-", _tot_n))
        else:
            _cap_note = ("口径：成本/可买量 = **第 1 页**订单簿（2026-10-06 起取消翻页；%s；%s）；"
                         "挂单数 = 站点权威总数。站点「为您找到 %d 条」只数散单、"
                         "热卖商城已剔除、只取散单（该区站点共 %s 页）"
                         % (_skip_cap, _of_cap or "-", _tot_n, _pgs_s))
        rec = {
            "ok": True,
            "成本_元每万基纳": _pr,
            "单位": "万基纳",
            "成本_USD每M": to_usd_per_m(_pr, rate),
            "可供量_万基纳": ob["可供量"], "够量": ob["够量"],
            "参与条数": ob["参与条数"],
            # 兼容旧字段（面板 / gold_cost 表沿用）：
            #   stock 文本里的「可买X万基纳」被 app.py._avail_wan() 正则读取 → 保留字样
            "库存": "可买%.0f万基纳" % ob["可供量"], "起售": None,
            # 面板「挂单数」= 站点权威总数
            "商品条数": _tot_n,
            "本页条数": len(_q1),                # 第 1 页解析到的条数（诊断用）
            "解析条数": ob["报价条数"],           # 参与计算的条数（= 第 1 页，诊断用）
            "站点页数": _pgs_n,
            "翻页数": _pages,                    # 取消翻页后恒为 1（字段保留以兼容旧表）
            "DD区": info["dd_area"], "DD种族": info["dd_race"], "DD游戏区": info["dd_name"],
            # 依据列保持简短（太长会把右侧「改价操作」挤出可视区）：区/种族/游戏区 + 口径
            "依据": "%s / %s / %s · %s订单簿加权(吃%d/%d条·跳过%d条·%s·挂单%d)"
                    % (info["dd_area"], info["dd_race"], info["dd_name"],
                       ob.get("吃单方式") or "买满",
                       ob["参与条数"], ob["报价条数"], ob["跳过条数"],
                       ("Api%d条" % len(_q1)) if _src == "api" else "仅第1页", _tot_n),
            "URL": url,
        }
        _own = "；".join(x for x in ((_chk or {}).get("自校验"), _skip_note, _of_note,
                                     _short_note, _cap_note) if x)
        if _own:
            rec["备注"] = _own
        out[key] = rec
        if log:
            log("  [DD373] %-24s %-10s %.6f 元/万基纳 → $%.4f/M  "
                "(%s订单簿 吃%d/%d条·跳过%d条·%s%d条，可买 %.0f万基纳%s)"
                % (key, rec["DD游戏区"], _pr, rec["成本_USD每M"] or 0,
                       ob.get("吃单方式") or "买满",
                   ob["参与条数"], ob["报价条数"], ob["跳过条数"],
                   "Api" if _src == "api" else "页面", len(_q1),
                   ob["可供量"], "" if ob["够量"] else "·不足目标量"))
            if ob["跳过条数"]:
                log("  [DD373] %-24s ⏭ 跳过最低 %d 条：%s"
                    % (key, ob["跳过条数"], "；".join(ob["跳过明细"] or [])))
            if _of.get("已过滤"):
                log("  [DD373] %-24s 🧹 %s" % (key, _of.get("说明") or ""))
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
    game = sys.argv[2] if len(sys.argv) > 2 else "AION2"
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    g = cfg.get("金币", {})
    rate = (g.get("汇率") or cfg.get("汇率", {}).get("USDCNY")) or 6.65
    svs = [s for s in g.get("服务区", []) if s.get("游戏") == game]
    print("%s %d 个服务区，汇率 %.4f，采集 DD373 成本 …" % (game, len(svs), rate))
    res = fetch_costs(svs, rate, log=print, refresh_tree=True, game=game)
    ok = sum(1 for v in res.values() if v.get("ok"))
    _full = sum(1 for v in res.values() if v.get("ok") and v.get("够量"))
    print("\n成功 %d / %d（其中买满目标量 %d 个区）" % (ok, len(svs), _full))
    print(json.dumps(summarize(res, {}), ensure_ascii=False, indent=1))
