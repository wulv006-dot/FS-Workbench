# -*- coding: utf-8 -*-
"""金币（Gold / Currency）跟价专线 —— 与物品分开的一条链路。

为什么要单独一个模块
--------------------
金币和物品在后台是**两套机制**（2026-09-24 探明并实测通过）：

| | 物品 | 金币 |
|---|---|---|
| 后台页 | 产品价格管理 | 金币价格管理 |
| 一行 = | 一个产品 | **一个服务区** |
| 可改字段 | `$每个价格`(unit_price) | **采购成本**(costprice) |
| 写接口 | POST `goodsEdit`（JSON 数组） | POST `itemEdit?ids=<行ID>`（urlencoded） |
| 改完还要 | 无 | **必须点「同步价格」**（且 🔴 绝不勾「所有区」） |

换算（4/4 服务区校验通过，与后台页面自己写的公式一致）：

    b2c($/M) = 采购成本(￥/M) ÷ 汇率 ÷ (1 − 利润率)
    前端展示价(档位 N) = b2c × N              ← b2c 就是前端「每 M 单价」
    反用：目标采购成本 = 目标每M价 × 汇率 × (1 − 利润率)

本项目实测：汇率 6.65、利润率 0.20 ⇒ 除数 5.32。

跟价口径（用户确认）：**我方前端每 M 价 = IGGM 每 M 价**（持平）。

抓法
----
  IGGM 金币：`GET /goods/goods_ajax?template_type=golds&server_id=<sid>&cate_id=0`
      ⚠ 与物品的 `template_type=items&game_sku=…` **不是同一个接口**；
        且必须先 GET 一次 `/diablo-4-gold` 拿 Cloudflare cookie，否则 403。
        返回 `data.one_goods.price` = 每单位价（$/M），`data.result_goods[].all` = 各档总价。
        服务器（机房 IP）抓到的价 = 客户真价 × 1.1 → 用 `iggm.竞品价折算系数` 还原。
  我方前端金币：`POST https://www.mmoexp.com/ajax/goods`
      form: `Game_id=456&top_cid=1&aid=<服务区aid>&cid=&site_id=`
      返回 `goods.index.list[0].goods_list{num:{num,price,price_discount,discount}}`。
      ⚠ **按服务区逐个取**：各服务区档位集合不同（100M / 1000M / 5000M / 10000M 起），
        不能假设都有某个档 —— 取「最接近目标档位」的那一档折算每 M 价。

只读：本模块全部是 GET / 只查询的 POST，**不写任何价格**。
"""
import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
IGGM_BASE = "https://www.iggm.com"
FRONT_URL = "https://www.mmoexp.com/ajax/goods"

# 缺省服务区表（config.金币.服务区 未配时用它；后台行ID == 服务区ID）
DEFAULT_SERVERS = [
    {"key": "GOLD_S15_SC", "中文名": "赛季普通 (S15 Softcore)",
     "后台行ID": "15711", "后台商品ID": "1354083", "前端aid": 15943, "iggm_sid": 27589},
    {"key": "GOLD_S15_HC", "中文名": "赛季专家 (S15 Hardcore)",
     "后台行ID": "15712", "后台商品ID": "1354135", "前端aid": 15945, "iggm_sid": 27591},
    {"key": "GOLD_ET_SC", "中文名": "永恒普通 (Eternal Softcore)",
     "后台行ID": "11914", "后台商品ID": "321686", "前端aid": 11916, "iggm_sid": 11507},
    {"key": "GOLD_ET_HC", "中文名": "永恒专家 (Eternal Hardcore)",
     "后台行ID": "11916", "后台商品ID": "1021653", "前端aid": 15403, "iggm_sid": 11509},
]

# ---- 多游戏参数表（2026-10-01 接入 Aion 2 时新增）-----------------------------
# 金币专线原先把 D4 的抓取参数**写死在代码里**（IGGM 金币页 / 前台 Game_id / 前台系数）。
# 接入第二个游戏时把它们收敛到这张表：**按服务区的「游戏」字段取**，
# 可用 `config.金币.游戏参数.<游戏>` 覆盖（键名与下表一致）。
#
# ⚠ 四套参数互不通用，照抄会「抓错页面 / 读错游戏的前台价 / 目标价偏 5%」：
#   · IGGM金币页：必须先 GET 这一页拿 __cf_bm，否则 goods_ajax 一律 403
#   · 前台GameId/cid/site_id：Aion 2 必须带 cid=6527&site_id=266（D4 留空即可）
#   · 前台系数：D4 前台价 = 后台 b2c ÷ 0.95（×1.0526）；Aion 2 实测 = b2c（1.0）
#   · 展示倍率：D4 单价 5e-4 量级 → 按「每 10 万 M」才好读；Aion 2 本身就是 $/M
GAME_PARAMS = {
    "暗黑破坏神4": {
        "IGGM金币页": "/diablo-4-gold",
        "前台GameId": "456", "前台top_cid": "1", "前台cid": "", "前台site_id": "",
        "前台Referer": "https://www.mmoexp.com/Diablo-4/Gold.html",
        "前台系数": 1.052631579,
        "展示倍率": 100000,
    },
    "AION2": {
        "IGGM金币页": "/aion-2/kinah",
        "前台GameId": "891", "前台top_cid": "1", "前台cid": "6527", "前台site_id": "266",
        "前台Referer": "https://www.mmoexp.com/Aion-2/Kinah.html",
        "前台系数": 1.0,          # 2026-10-01 实测：前台每M价 == 后台 b2c（TW/KR 1:1）
        "展示倍率": 1,            # Aion 2 单价即 $/M（IGGM 5.99 / 我方 10.99）
    },
}
DEFAULT_GAME = "暗黑破坏神4"


def server_game(cfg, sv):
    """服务区属于哪个游戏（config.金币.服务区[].游戏；缺省 = 暗黑破坏神4）。"""
    return (sv or {}).get("游戏") or DEFAULT_GAME


def finite_number(value):
    """Reject invalid numeric inputs without converting missing values to zero."""
    import math
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def positive_number(value):
    number = finite_number(value)
    return number if number is not None and number > 0 else None


def discount_display(value):
    """Missing display value defaults to 3%; an explicit 0% stays zero."""
    return 0.03 if value is None else value


def gold_cost_for_dispatch(cfg, value):
    from gold_numeric_guard import write_cost
    return write_cost(value, cfg)


def raw_cost_inputs_valid(cfg, sv, game):
    """Check declared numeric types before legacy normalization erases bools."""
    g = cfg_gold(cfg)
    over = (g.get("游戏参数") or {}).get(game) or {}
    values = [g.get("成本除数"), g.get("汇率"),
              ((cfg or {}).get("汇率") or {}).get("USDCNY"),
              g.get("前台系数"), over.get("前台系数"), sv.get("利润率")]
    return all(v in (None, "") or finite_number(v) is not None for v in values)


def _tier_values(tier, field):
    count = _tier_count(tier.get("num"))
    price = positive_number(tier.get(field))
    return (count, price) if count is not None and price is not None else (None, None)


def _tier_count(raw):
    number = positive_number(raw)
    if number is None:
        return None
    try:
        count = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count == number else None


def pricing_policy(cfg, game=None):
    """⭐ 定价策略解析（2026-10-02 老板定案）—— **唯一入口**，别在业务代码里自己读 config。

    返回 None = 该游戏走**默认口径**（暗黑4 永远是 None，一个字节都不受影响）。
    返回 dict 时：

        {"模式": "dd373_markup" | "multisrc",
         "加价比例": 0.05,
         "口径": "……人话描述，写进快照与看板",
         "成本源": "DD373" | ""}

    两种模式（config.金币.定价策略.模式 一键切换，这就是「日后重新启用」的开关）：

    ┌ dd373_markup（2026-10-02 起，短期策略）──────────────────────────┐
    │ 售价 = DD373 该区推荐价（综合排序第 1 条）折成 $/M × (1 + 加价比例)│
    │ G2G / ELD / IGGM **照旧采集监控并展示，但完全不参与定价**。       │
    └─────────────────────────────────────────────────────────────────┘
    ┌ multisrc（2026-10-01 旧策略，已归档，需要时可一键切回）──────────┐
    │ 基准 = min(G2G, ELD)，IGGM 更低则取 IGGM，两站无数据用同大区均价  │
    │ 兜底；目标 = 基准 × (1 − 让价百分比)                              │
    └─────────────────────────────────────────────────────────────────┘
    ┌ g2g_cheapold（2026-10-05 起，老板定案 A「永远优先 cheapold」）────┐
    │ 每个子服务器进 G2G：有卖家 cheapold → 目标 = cheapold价×(1−3%)；  │
    │ 无 → 目标 = min(推荐第1位, 推荐第2位) × (1−3%)。                  │
    │ DD373 / ELD / IGGM 照旧采集监控，不参与定价。                     │
    └─────────────────────────────────────────────────────────────────┘

    ⚠ **DD373 无报价的区不推算、不兜底**（沿用 2026-10-02 用户口径）——
      该区本轮不出目标价、动作 hold，看板显示「无报价」。
    """
    p = (cfg_gold(cfg).get("定价策略") or {})
    if not isinstance(p, dict):
        return None
    games = p.get("适用游戏") or []
    g = game or ""
    if g and games and g not in games:
        return None                       # 不在适用名单 → 走默认口径
    mode = str(p.get("模式") or "").strip()
    if not mode:
        return None
    if mode == "dd373_markup":
        try:
            mk = float(p.get("加价比例", 0.05))
        except (TypeError, ValueError):
            mk = 0.05
        return {"模式": mode, "加价比例": mk, "成本源": "DD373",
                # 三级兜底（2026-10-02 老板补充口径）
                "次源": str(p.get("次源") or "G2G"),
                "次源加价": (float(p.get("次源加价") or 0.0)
                             if str(p.get("次源加价") or "0") not in ("", None) else 0.0),
                "默认售价_USD每M": _f(p.get("默认售价_USD每M") or 9.9),
                "口径": "售价 = DD373 该区推荐价(综合排序第1条)折 $/M × %.2f%%；"
                        "G2G/ELD/IGGM 继续采集监控并展示，但定价上不主动参与 "
                        "（仅 DD373 无报价时按顺序兜底）" % (mk * 100)}
    if mode == "multisrc":
        return {"模式": mode, "加价比例": None, "成本源": "",
                "口径": "基准 = min(G2G, ELD)，IGGM 更低则取 IGGM，"
                        "两站无数据用同大区均价兜底；目标 = 基准 × (1−让价百分比)"}
    if mode == "g2g_cheapold":
        disc = finite_number(p.get("下浮比例", 0.03))
        if disc is None:
            return {"模式": mode, "下浮比例": None, "乘数": None,
                    "错误": "下浮比例必须为有限数值", "口径": "参数无效：不出目标价"}
        if disc < 0:
            disc = 0.0
        if positive_number(1.0 - disc) is None:
            return {"模式": mode, "下浮比例": disc, "乘数": None,
                    "错误": "策略乘数必须为有限正数", "口径": "参数无效：不出目标价"}
        _cn = str(p.get("cheapold卖家") or "cheapold")
        return {"模式": mode, "下浮比例": disc, "乘数": 1.0 - disc, "成本源": "",
                "cheapold卖家": _cn,
                "口径": ("每个子服务器进 G2G 取价：有卖家 %s → 目标 = %s价 × (1−%.1f%%)；"
                        "无 → 目标 = min(推荐第1, 推荐第2) × (1−%.1f%%)"
                        % (_cn, _cn, disc * 100, disc * 100))}
    return None


def multisrc(cfg, log=None, cache_ttl=None):
    """AION2 三源基准（G2G/ELD/IGGM）—— 可选，失败/未启用返回 None。

    2026-10-01 新增：AION2 金币口径从「跟我方 IGGM 价持平下浮 5%」改成
    「基准 = min(G2G, ELD)，IGGM 更低才取 IGGM；无数据区同大区均价兜底」
    （用户原话见 core_multi 模块头）。封装成懒加载，**暗黑4 走不到这里**：
    config 里没有 `金币.多源基准` 段 → core_multi 的 启用 兜底为 False → 返回 None。
    """
    try:
        import core_multi
    except Exception as e:                        # noqa: BLE001
        if log:
            log("  [金币/多源] core_multi 不可用，退回纯 IGGM 口径：%r" % e)
        return None
    try:
        ms = core_multi.MultiSource(cfg, log=log, cache_ttl=cache_ttl)
        if not ms.enabled_flag:
            return None
        return ms
    except Exception as e:                        # noqa: BLE001
        if log:
            log("  [金币/多源] 初始化失败，退回纯 IGGM 口径：%r" % e)
        return None


def game_names(cfg):
    """金币专线覆盖到的**全部**游戏（按 config.金币.服务区 的先后去重）。

    2026-10-01 多游戏改造：金币服务区不再只属于一个「挂载游戏」，
    暗黑4 与 AION2 可以同时挂在同一条专线上。调用方（调度、看板、控制台）
    用这个函数判断「金币这一轮要不要跑 / 有哪些游戏段」，别再读 挂载游戏 单值。
    """
    out = []
    for sv in servers_of(cfg):
        g = server_game(cfg, sv)
        if g and g not in out:
            out.append(g)
    return out


def game_param(cfg, game=None):
    """按游戏取抓取参数：内置表 GAME_PARAMS ← config.金币.游戏参数.<游戏> 覆盖。"""
    g = game or DEFAULT_GAME
    out = dict(GAME_PARAMS.get(g) or GAME_PARAMS[DEFAULT_GAME])
    over = (cfg_gold(cfg).get("游戏参数") or {}).get(g) or {}
    if isinstance(over, dict):
        out.update({k: v for k, v in over.items() if not str(k).startswith("_")})
    return out


def _f(v):
    """安全转 float。⚠ 不要用「str 再正则」的写法：科学计数法会被截断
    （str(3.09e-05) 会被匹配成 3.09）。IGGM 的 unit_price 正是科学计数法。"""
    try:
        if isinstance(v, bool) or v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return None


def cfg_gold(cfg):
    return (cfg or {}).get("金币") or {}


# ---- 展示口径（2026-09-27 用户要求）------------------------------------------
# 用户原话：「后台展示的金币单价是 4.5364e-4 这种科学计数法，看不明白，
#            你改成以 100000M 为单位的展示好了」。
# 所以**所有给人看的金币单价一律走 per_100k()**（每 M 价 × 100000），
# 配 2 位小数就是「$4.54 / 10万M」这种能读的数字；任何地方都不要再吐 4.5364e-4。
PER_100K = 100000.0


def per_100k(v, mult=None):
    """每 M 价 → 展示单位价（默认「每 10 万 M」）。给人和看板用，别用科学计数法。

    `mult` 按游戏取（D4 = 100000、Aion 2 = 1），见 GAME_PARAMS.展示倍率。
    """
    f = _f(v)
    if f is None:
        return None
    return f * (float(mult) if mult else PER_100K)


def display_mult_of(cfg, game=None):
    """该游戏的展示倍率（每 M 价乘多少才好看）。"""
    try:
        v = float(game_param(cfg, game).get("展示倍率") or 0)
    except (TypeError, ValueError):
        v = 0
    return v if v > 0 else PER_100K


def unit_label(mult=None):
    """展示单位的中文名：10万M / M。"""
    try:
        m = float(mult or PER_100K)
    except (TypeError, ValueError):
        m = PER_100K
    if abs(m - PER_100K) < 1:
        return "10万M"
    if abs(m - 1.0) < 1e-9:
        return "M"
    return "%gM" % m


def fmt_money(v, nd=2):
    """金额/单价一律**定点**输出，永不出现 8.0E-06 这种科学计数法。"""
    f = _f(v)
    if f is None:
        return "-"
    if f == 0:
        return "0"
    a = abs(f)
    if a >= 1:
        return "%.*f" % (nd, f)
    if a >= 0.01:
        return "%.*f" % (max(nd, 4), f)
    return "%.6f" % f


def enabled(cfg):
    return bool(cfg_gold(cfg).get("启用", True))


def servers_of(cfg):
    """金币服务区表：优先 config.金币.服务区，缺省用内置表"""
    got = cfg_gold(cfg).get("服务区")
    if isinstance(got, list) and got:
        return got
    return DEFAULT_SERVERS


def tier_of(cfg):
    try:
        return int(cfg_gold(cfg).get("对标档位", 10000))
    except (TypeError, ValueError):
        return 10000


def rate_of(cfg):
    """金币换算用的汇率：config.金币.汇率 优先，否则 汇率.USDCNY"""
    r = _f(cfg_gold(cfg).get("汇率"))
    if r:
        return r
    return _f(((cfg or {}).get("汇率") or {}).get("USDCNY")) or 6.65


def allowance_of(cfg):
    """金币让价系数 = 1 − 金币.让价百分比/100。

    与物品同一口径：**我方前端每M价 = IGGM 每M价 × 该系数**（默认 5% ⇒ 低 5%）。
    单独一个配置字段（`金币.让价百分比`），改金币不动物品、反之亦然。
    """
    try:
        g = float(cfg_gold(cfg).get("让价百分比", 0.0) or 0.0)
    except (TypeError, ValueError):
        g = 0.0
    g = max(0.0, min(g, 90.0))
    return 1.0 - g / 100.0


def front_factor_of(cfg, game=None):
    """前台系数：**前台显示的每 M 价 = 后台 b2c 列 × 该系数**。

    2026-09-27 实测（把后台「金币价格管理」的 b2c 列与前端 `/ajax/goods` 的每M价对齐）：

    | 服务区 | 后台行 | 采购成本 | 后台 b2c | 前端每M价 | 前端 ÷ b2c |
    |---|---|---|---|---|---|
    | 永恒专家 | 11916 | 0.043491 | 0.008175 | 0.008605 | **1.0526** |
    | 永恒普通 | 11914 | 0.001833 | 0.000345 | 0.000363 | **1.0522** |
    | 赛季专家 | 15712 | 0.002293 | 0.000431 | 0.000454 | **1.0534** |

    ⇒ 后台自己写的 `b2c = 采购成本 ÷ 汇率 ÷ (1 − 利润率)`（= 5.32 那条）**不是**
      客户看到的价；前台还要再 ÷0.95（≡ ×1.05263）。

    🔴 这就是「我方金币价总比 IGGM 高」的根因：引擎按 5.32 反推采购成本，
      写进去后前台又多出 5.26%，**正好把「让价 5%」整条吃掉**
      （实测 3/4 服务区前端价 = IGGM 折算后价，逐位相同）：
          前端每M = 采购成本 ÷ 5.32 × 1.05263 = 采购成本 ÷ 5.054
      反过来要「前端每M = 目标 T」，采购成本必须写成 `T × 5.054`，不是 `T × 5.32`。

    可用 `金币.前台系数` 覆盖；实测值 1.052631579（= 1/0.95）。
    """
    # ① 该游戏在 config.金币.游戏参数.<游戏>.前台系数 里显式指定（多游戏接入用这个）
    over = (cfg_gold(cfg).get("游戏参数") or {}).get(game or DEFAULT_GAME) or {}
    if isinstance(over, dict):
        v = _f(over.get("前台系数"))
        if v and v > 0:
            return v
    # ② 全局 金币.前台系数（D4 现值就在这里 —— 保持向后兼容，行为不变）
    v = _f(cfg_gold(cfg).get("前台系数"))
    if v and v > 0:
        return v
    # ③ 内置表兜底
    v = _f(game_param(cfg, game).get("前台系数"))
    if v and v > 0:
        return v
    return 1.0 / 0.95


def cost_divisor_of(cfg, rl, game=None):
    """「目标前端每 M 价 → 目标采购成本」的换算除数。

        采购成本 = 目标前端每M价 × 成本除数
        成本除数 = 汇率 × (1 − 利润率) ÷ 前台系数        （见 front_factor_of）
                 = 6.65 × 0.80 ÷ 1.0526316 = 5.0540        （本项目实测值）

    可用 `金币.成本除数` 直接指定（前台系数一旦变化，用这个一键覆盖）。
    ⚠ 不要再用旧的 `汇率 × (1−利润率)`（= 5.32）—— 那会把采购成本写高 5.3%。
    """
    d = _f(cfg_gold(cfg).get("成本除数"))
    if d and d > 0:
        return d
    return rate_of(cfg) * (1.0 - rl) / front_factor_of(cfg, game)


def factor_of(cfg):
    """竞品价折算系数（IGGM 抓到价 → 北美客户实付价）。

优先读 **金币.IGGM折算系数**（金币专用字段）。

    2026-09-25 用户定案：**与物品统一口径** —— 金币价由服务器（机房 IP）抓，
    IGGM 对机房 IP 加价 1.10，故取 1/1.1 = 0.909090909（与 config.iggm.竞品价折算系数 同值）。
    🔴 改前为 0.9385113269（2026-09-24 按「本机(中国) $3.09 vs 美国电脑 $2.90」实测），
    那属于**中国/美国**维度，与「机房/家用」不是一回事，已按要求废弃。
    金币走独立字段，改它不会影响物品跟价；没配时退回全局值。
    本地家用 IP 跑调试可传 --factor 1.0 覆盖。
    """
    g = cfg_gold(cfg).get("IGGM折算系数")
    if g is not None:
        try:
            k = float(g)
            if k > 0:
                return k
        except (TypeError, ValueError):
            pass
    try:
        k = float(((cfg or {}).get("iggm") or {}).get("竞品价折算系数", 1.0))
    except (TypeError, ValueError):
        k = 1.0
    return k if k > 0 else 1.0


# ------------------------------------------------------------------ 竞品：IGGM 金币
class IggmGold(object):
    """IGGM 金币抓取（带 Cloudflare cookie 的会话来抓）。

    ⚠ 与 core_iggm 的物品抓取**不能共用会话**：
      物品接口裸请求即可；金币接口不带 cookie 一律 403。
    """

    def __init__(self, log=print, timeout=40):
        self.log = log or (lambda *a: None)
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self._warmed = set()          # 按「金币页路径」分别记 —— 多游戏各要一次 cookie

    def warm(self, force=False, page=None):
        """先 GET 一次该游戏的金币页，拿 __cf_bm / SESS_ID，否则 goods_ajax 返回 403。

        ⚠ cookie 是**按游戏页**取的：D4 是 /diablo-4-gold、Aion 2 是 /aion-2/kinah。
        """
        page = page or GAME_PARAMS[DEFAULT_GAME]["IGGM金币页"]
        if page in self._warmed and not force:
            return True
        try:
            self.op.open(urllib.request.Request(
                IGGM_BASE + page,
                headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}), timeout=self.timeout).read()
            self._warmed.add(page)
            return True
        except Exception as e:
            self.log("  [金币/IGGM] 取 cookie 失败（%s）：%r" % (page, e))
            self._warmed.discard(page)
            return False

    def fetch(self, server_id, page=None, retry=3):
        """返回 {"unit_price": 每M价, "goods_no":..., "title":..., "tiers":[{num,all}], "update_time":...}

        `page` = 该游戏的金币页路径（同时决定 Referer 与 cookie 预热页），缺省 = D4。
        """
        page = page or GAME_PARAMS[DEFAULT_GAME]["IGGM金币页"]
        url = (IGGM_BASE + "/goods/goods_ajax?template_type=golds&server_id=%s&cate_id=0"
               % server_id)
        h = {"User-Agent": UA, "Referer": IGGM_BASE + page,
             "X-Requested-With": "XMLHttpRequest"}
        last = None
        for i in range(retry):
            self.warm(force=(i > 0), page=page)
            try:
                b = self.op.open(urllib.request.Request(url, headers=h),
                                 timeout=self.timeout).read()
                d = (json.loads(b.decode("utf-8", "replace")) or {}).get("data") or {}
                g = d.get("one_goods") or {}
                tiers = [{"num": int(x.get("num") or 0), "all": _f(x.get("all")),
                          "market_price": _f(x.get("market_price"))}
                         for x in (d.get("result_goods") or [])]
                tiers.sort(key=lambda x: x["num"])
                return {"unit_price": _f(g.get("price")), "raw_unit_price": _f(g.get("price")),
                        "goods_no": g.get("goods_no"), "title": (g.get("title") or "").strip(),
                        "rule": g.get("rule"), "tiers": tiers,
                        "update_time": (d.get("result_goods") or [{}])[0].get("update_time")}
            except Exception as e:
                last = e
                time.sleep(1.5 * (i + 1))
        raise last


# ------------------------------------------------------------------ 我方前端金币
def fetch_front_gold(cfg, aid, game=None, log=print, retry=4, timeout=45):
    """抓我方前端一个服务区的金币全部档位。

    返回 [{"num": 档位M数, "unit": "M", "price": 标价, "price_discount": 折后价(前端展示), "discount": 折扣}]
    每 M 单价应取 `price_discount / num`（前端展示的是折后价）。

    ⚠ 前台参数**按游戏取**（见 GAME_PARAMS）：Aion 2 必须带 `cid=6527&site_id=266`，
      否则拿不到 Kina 商品（D4 这两个参数留空即可）。
    """
    gp = game_param(cfg, game)
    body = urllib.parse.urlencode({"Game_id": gp["前台GameId"], "top_cid": gp["前台top_cid"],
                                   "aid": str(aid), "cid": gp["前台cid"],
                                   "site_id": gp["前台site_id"]}).encode()
    last = None
    for i in range(retry):
        try:
            req = urllib.request.Request(
                FRONT_URL, data=body,
                headers={"User-Agent": UA,
                         "Referer": gp["前台Referer"],
                         "X-Requested-With": "XMLHttpRequest",
                         "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                d = json.loads(r.read().decode("utf-8", "replace"))
            idx = ((d.get("goods") or {}).get("index") or {})
            lst = idx.get("list") or []
            if not lst:
                return []
            gl = lst[0].get("goods_list") or {}
            out = [{"num": _tier_count(v.get("num") if v.get("num") not in (None, "") else k), "unit": lst[0].get("unit") or "M",
                    "price": _f(v.get("price")), "price_discount": _f(v.get("price_discount")),
                    "discount": v.get("discount")} for k, v in gl.items()]
            out = [v for v in out if v["num"] is not None]
            out.sort(key=lambda x: x["num"])
            return out
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def per_m(tiers, target, field="price_discount"):
    """取「与目标档位最接近的那一档」的每 M 单价。

    返回 (档位M数, 每M价)；没有可用档位返回 (None, None)。
    ⚠ 必须容错：各服务区起始档不同（100M / 1000M / 5000M / 10000M），不能硬取某一档。
    """
    best = None
    for t in tiers or []:
        n, p = _tier_values(t, field)
        if not n or p is None:
            continue
        d = abs(n - int(target))
        if best is None or d < best[0]:
            best = (d, n, p / n)
    return (best[1], best[2]) if best else (None, None)


def biggest_tier(tiers, field="price_discount"):
    """取**最大档位**的 (M数, 该档总价, 每M价)。

    为什么要单列一个「最大档」：
      ① 用户口径（2026-09-27）：「金币单位大，看起来不方便，找个最大的金币选项
         对照价格变化」—— 最大档总价是**一个能直接看的美元数字**（如 $4.635），
         而 8.4e-06/M 这种谁也读不出来。
      ② 精度：前端档位总价**只显示 2 位小数**，取整误差按档位放大 ——
         500000M 档误差 ≤ 0.001%，10000M 档却有 0.05%，小档（100M）能到 5%。
         所以「无效果闸」「达标判定」一律用最大档比，别用接近对标档的小档。
    """
    best = None
    for t in tiers or []:
        n, p = _tier_values(t, field)
        if not n or p is None:
            continue
        if best is None or n > best[0]:
            best = (n, p)
    if not best:
        return (None, None, None)
    return (best[0], best[1], best[1] / best[0])


def iggm_biggest_tier(tiers):
    """IGGM 侧最大档：(M数, 该档总价, 每M价)。IGGM 每M价是线性的，取总价/档位即可。"""
    best = None
    for t in tiers or []:
        n, a = _tier_values(t, "all")
        if not n or a is None:
            continue
        if best is None or n > best[0]:
            best = (n, a)
    if not best:
        return (None, None, None)
    return (best[0], best[1], best[1] / best[0])


# ------------------------------------------------------------------ 计划
def build_plan(cfg, log=print, iggm_obj=None, front_fn=None, servers=None, known=None,
               dd373_costs=None):
    """抓双方价 → 算每个服务区的目标采购成本。**只算不改。**

    返回 {"ts","tier","rate","items":[...]}，items 每项：
      key / 中文名 / 后台行ID / 后台商品ID / 前端aid / iggm_sid /
      利润率 / 采购成本_旧(本机执行器回传的真值，没回传时为 None) / 采购成本_新(目标) /
      我方前端每M / IGGM每M / 差距倍数 / 动作

    ⭐ dd373_costs（2026-10-02 新增，**可选**）：{key: {"ok":bool, "usd_per_m":float,
       "cny_per_wan":float, "n_items":int, "dd_zone":str, "basis":str}}
       —— 由调用方从 gold_cost 表读出注入。**为什么用注入而不是在这里联网抓**：
         ① 成本采集已经有独立的调度与风控处理（撞风控要整轮中止沿用旧快照），
            在这里再抓一次会绕过那套保护，且 34 个区要再等 ~45 秒；
         ② build_plan 保持「纯算不联网」，单测与 dry-run 不用依赖 DD373。
       传 None/{} 时该区按「无报价」处理（不出目标价、动作 hold）。
    """
    import datetime as dt
    ig = iggm_obj or IggmGold(log=log)
    ff = front_fn or (lambda aid: fetch_front_gold(cfg, aid, log=log))
    svs = servers if servers is not None else servers_of(cfg)
    tier = tier_of(cfg)
    rate = rate_of(cfg)
    k = factor_of(cfg)
    apo = allowance_of(cfg)          # 让价系数：我方前端价 = IGGM 价 × apo
    dec = int(cfg_gold(cfg).get("采购成本小数位", 6) or 6)
    _known = known or {}
    _costs = dd373_costs or {}
    if _known:
        # ⚠ 这里也不能用 %.6g：赛季普通的采购成本是 4.3e-05，会打成 "4.3e-05"。
        #   采购成本单位是 ￥/M，纯小数，用定点 8 位足够（0.00004300），人去读得懂。
        log("  [金币] 已知现行采购成本（本机执行器回传）：%s"
            % "、".join("%s=%.8f" % (kk, float(vv)) for kk, vv in sorted(_known.items())
                        if isinstance(vv, (int, float))))
    # ── 2026-10-02 定价策略（老板定案 · 短期策略）────────────────────────
    # 售价 = DD373 该区推荐价 × (1 + 加价比例)；G2G/ELD/IGGM 只监控不参与定价。
    # 🔴 **按游戏逐个解析**（`_pol_by_game`），不要图省事只算一个全局值 ——
    #    那样会把 DD373 定价漏到暗黑4 上（本地预演实测抓到过这个 bug：
    #    D4 的「定价模式」会变成 dd373_markup、目标价被 DD373 成本顶掉）。
    #    pricing_policy() 对不在 适用游戏 名单里的游戏返回 None → 走默认口径。
    _pol_by_game = {g: pricing_policy(cfg, g) for g in
                    {server_game(cfg, s) for s in svs}}
    _pricing_mode = (_pol_by_game.get("AION2") or {}).get("模式") or ""
    _mk = (_pol_by_game.get("AION2") or {}).get("加价比例")
    if _pricing_mode == "dd373_markup":
        log("  [金币/定价] AION2 走「DD373 推荐价 + %.1f%%」模式（%s）"
            % ((_mk or 0) * 100, (_pol_by_game.get("AION2") or {}).get("口径")))
        if not _costs:
            log("  [金币/定价] ⚠ 本轮没有注入 DD373 成本（dd373_costs 为空）"
                "⇒ 全部 AION2 服务区不出目标价、动作 hold（不会退回旧口径乱改价）")
        else:
            log("  [金币/定价] 已注入 DD373 成本 %d 条，其中有效 %d 条"
                % (len(_costs), sum(1 for v in _costs.values() if (v or {}).get("ok"))))
    elif _pricing_mode == "multisrc":
        log("  [金币/定价] AION2 走「三源比价 multisrc」模式（2026-10-01 旧策略）")
    elif _pricing_mode == "g2g_cheapold":
        _pol_a = _pol_by_game.get("AION2") or {}
        log("  [金币/定价] AION2 走「G2G cheapold 跟价」模式（下浮 %.1f%%）：%s"
            % (discount_display(_pol_a.get("下浮比例")) * 100, _pol_a.get("口径")))
    # G2G cheapold 模式的子服务器抓取器（懒加载；失败不致命，逐区 hold）
    _g2gcb = None
    if _pricing_mode == "g2g_cheapold":
        try:
            import core_g2g as _cg
            _g2gcb = _cg.cheapold_base
        except Exception as _e:                    # noqa: BLE001
            log("  [金币/G2G] ⚠ core_g2g 载入失败：%r → 本轮全部 AION2 区不出目标价" % _e)

    # ── 2026-10-01：AION2 三源基准（G2G / ELD / IGGM）─────────────────────
    # 只对配置了 `金币.多源基准` 的游戏生效（当前 = AION2）；暗黑4 拿到 None，行为不变。
    # ⚠ 2026-10-02 起即使定价改用 DD373，本段**仍然要跑**：G2G/ELD 继续采集并展示，
    #   只是它们的产物不再喂给目标价（见下面 _tgt_from_base 的分支）。
    _ms = multisrc(cfg, log=log)
    _ms_need = set()
    if _ms:
        for _s in svs:
            if server_game(cfg, _s) == "AION2" and _s.get("跟价", True) is not False:
                _ms_need.add(_s.get("key"))
        if _ms_need:
            log("  [金币/多源] AION2 采集三源价（G2G/ELD/IGGM），覆盖 %d 个服务区"
                "（%s）" % (len(_ms_need),
                          "仅监控展示，不参与定价" if _pricing_mode in ("dd373_markup", "g2g_cheapold")
                          else "参与定价"))
            _ms.refresh()
        else:
            _ms = None
    items = []
    for sv in svs:
        if sv.get("跟价", True) is False:
            log("  [金币] %s 未勾选跟价，跳过" % sv.get("中文名"))
            continue
        gm = server_game(cfg, sv)                  # 该服务区属于哪个游戏（多游戏接入）
        gp = game_param(cfg, gm)
        _dm = display_mult_of(cfg, gm)             # 展示倍率（D4 = 1e5 / Aion 2 = 1）
        _ul = unit_label(_dm)                      # 展示单位名（10万M / M）
        rl = _f(sv.get("利润率"))
        rl = 0.20 if rl is None else rl
        rec = {"key": sv.get("key"), "中文名": sv.get("中文名"), "游戏": gm,
               "后台行ID": str(sv.get("后台行ID") or ""), "后台商品ID": str(sv.get("后台商品ID") or ""),
               "前端aid": sv.get("前端aid"), "iggm_sid": sv.get("iggm_sid"),
               # 2026-09-26（patch11）：本机执行器回传的真值（服务器读不到后台）。
               # 只用于展示/留证，不参与判定。
               "采购成本_旧": _known.get(sv.get("key")),
               "利润率": rl, "对标档位": tier,
               "展示倍率": _dm, "展示单位": _ul}
        try:
            igd = ig.fetch(sv.get("iggm_sid"), page=gp["IGGM金币页"])
            rec["IGGM每M"] = igd.get("unit_price")
            rec["IGGM档位"] = igd.get("tiers")
            rec["IGGM标题"] = igd.get("title")
            rec["IGGM更新时间"] = igd.get("update_time")
            _bn, _ba, _bpm = iggm_biggest_tier(igd.get("tiers"))
            rec["IGGM最大档"] = _bn            # 用户口径：用最大档位对照价格
            rec["IGGM最大档总价"] = _ba
            rec["IGGM最大档每M"] = _bpm
        except Exception as e:
            rec["IGGM每M"] = None
            rec["错误"] = "IGGM 抓取失败：%r" % e
            log("  [金币/IGGM] %s 抓取失败：%r" % (sv.get("中文名"), e))
        try:
            # 前台参数**按游戏取**；外部传入的 front_fn 保持原签名不动（向后兼容）
            if front_fn:
                tiers = front_fn(sv.get("前端aid"))
            else:
                tiers = fetch_front_gold(cfg, sv.get("前端aid"), game=gm, log=log)
            n, pm = per_m(tiers, tier)
            rec["我方前端每M"] = pm
            rec["我方前端档位"] = n
            rec["我方档位集合"] = [t.get("num") for t in (tiers or [])]
            _mn, _ma, _mpm = biggest_tier(tiers)
            rec["我方最大档"] = _mn
            rec["我方最大档总价"] = _ma
            rec["我方最大档每M"] = _mpm
            rec["我方前端折扣"] = (tiers[0].get("discount") if tiers else None)
        except Exception as e:
            rec["我方前端每M"] = None
            rec["错误"] = (rec.get("错误") or "") + "；前端抓取失败：%r" % e
            log("  [金币/前端] %s 抓取失败：%r" % (sv.get("中文名"), e))

        igp = _f(rec.get("IGGM每M"))
        # 机房抓取价 → 客户真价（IGGM 对机房 IP 加价 1.1）
        if igp is not None and k and k != 1:
            igp = igp * k
            rec["IGGM每M_折算后"] = igp
        rec["IGGM每M_跟价用"] = igp
        # ── 基准价 / 目标价 ────────────────────────────────────────────────
        # 三条互斥路径（**顺序不能换**）：
        #  ① dd373_markup（2026-10-02 起 · AION2 当前生效）**三级顺延**：
        #     第1级  DD373 该区推荐价(综合排序第1条) 折 $/M × (1 + 加价比例)
        #     第2级  DD373 **无报价** → 用 G2G 最低价（通常 +2%）   ← 老板 2026-10-02 补充
        #     第3级  G2G 也**没数据** → 用默认售价 9.9 $/M 顶上去，绝不让该区空着
        #     ELD / IGGM 照旧采集展示，但**不参与**这三级顺延。
        #  ② multisrc（2026-10-01 旧策略，已归档；config 切模式即可复活）
        #     基准 = min(G2G, ELD)，IGGM 更低则取 IGGM，两站无数据用同大区均价兜底。
        #  ③ 纯 IGGM × 让价系数 —— **只有暗黑4 走这条**，行为一字不变。
        _base_src = "IGGM"
        _base_detail = ""
        _tgt_from_base = None
        _mode_used = ""
        # ① 新策略：DD373 加价 + G2G/默认价顺延（**仅限适用游戏**）
        _row_pol = _pol_by_game.get(gm) or {}
        _row_mode = _row_pol.get("模式") or ""
        if _row_mode == "dd373_markup":
            _mode_used = "dd373_markup"
            rec["定价模式"] = "dd373_markup"
            _mk = _row_pol.get("加价比例")
            rec["加价比例"] = _mk
            _sec_src = str(_row_pol.get("次源") or "G2G")
            _sec_mk = _f(_row_pol.get("次源加价")) or 0.0
            _def_m = _f(_row_pol.get("默认售价_USD每M"))
            if _def_m is None:
                _def_m = 9.9
            _c = _costs.get(sv.get("key")) or {}
            _cusd = _f(_c.get("usd_per_m"))
            rec["DD373成本_USD每M"] = _cusd
            rec["DD373成本_元每万基纳"] = _c.get("cny_per_wan")
            rec["DD373挂单数"] = _c.get("n_items")
            rec["DD373游戏区"] = _c.get("dd_zone")
            rec["DD373依据"] = _c.get("basis")
            # 三源明细照旧算（看板要展示 G2G/ELD/IGGM 与差距对比），
            # 其中 **G2G 价**是新策略第 2 级兜底的输入。
            _g2g = None
            if _ms and sv.get("key") in _ms_need:
                _bv_ms, _bd_ms, _bdet_ms = _ms.resolve_base(sv, iggm_price=igp, apo=apo)
                rec["多源明细"] = _bdet_ms
                rec["竞品基准价"] = _bv_ms          # 仅供参考，不参与定价
                rec["竞品基准来源"] = _bdet_ms.get("取谁") or "-"
                _g2g = _f(_bdet_ms.get("G2G"))
            else:
                _bdet_ms = {}
            rec["G2G_USD每M"] = _g2g
            if _cusd is not None and _c.get("ok"):
                # ── 第 1 级：DD373 推荐价 + 加价 ──────────────────────────
                _tgt_from_base = _cusd * (1.0 + (_mk or 0.0))
                _base_src = "DD373"
                rec["定价来源级别"] = 1
                _base_detail = ("DD373 %s 综合排序第1条 %s 元/万基纳 = $%.4f/M，+%.1f%%"
                                % (_c.get("dd_zone") or sv.get("中文名"),
                                   _c.get("cny_per_wan"), _cusd, (_mk or 0) * 100))
                rec["基准价"] = _cusd
                rec["基准来源"] = "DD373推荐价"
            elif _g2g is not None:
                # ── 第 2 级：DD373 无报价 → 用 G2G 最低价（+次源加价）──────
                _tgt_from_base = _g2g * (1.0 + _sec_mk)
                _base_src = _sec_src
                rec["定价来源级别"] = 2
                _base_detail = ("DD373 无报价（%s）→ 顺延用 %s 最低价 $%.4f/M%s"
                                % (_c.get("basis") or "该区无挂单", _sec_src, _g2g,
                                   (" +%.1f%%" % (_sec_mk * 100)) if _sec_mk else ""))
                rec["基准价"] = _g2g
                rec["基准来源"] = "%s(兜底)" % _sec_src
                rec["说明_顺延"] = "DD373 无报价，本轮定价来自 %s" % _sec_src
            else:
                # ── 第 3 级：G2G 也没数据 → 用默认售价顶上去（不留空）──────
                _tgt_from_base = _def_m
                _base_src = "默认售价"
                rec["定价来源级别"] = 3
                _base_detail = ("DD373 无报价、%s 也无数据 → 用默认售价 $%.2f/M"
                                % (_sec_src, _def_m))
                rec["基准价"] = _def_m
                rec["基准来源"] = "默认售价"
                rec["说明_顺延"] = ("DD373 无报价且 %s 无数据 → 用默认售价 $%.2f/M"
                                    % (_sec_src, _def_m))
        # ①' 2026-10-05 新模式：G2G cheapold 跟价（**永远优先 cheapold**，用户定案 A）
        #     · 有 cheapold ⇒ 目标 = cheapold 价 × (1−下浮%)
        #     · 无 cheapold ⇒ 目标 = min(推荐第1, 推荐第2) × (1−下浮%)
        #     · 抓不到 / 无报价 ⇒ 本轮不出目标价，**绝不回落旧口径**（同 DD373 口径）
        #     · G2G/ELD/IGGM 三源照旧采集展示（多源明细），只是不再喂目标价。
        elif _row_mode == "g2g_cheapold":
            _mode_used = "g2g_cheapold"
            rec["定价模式"] = "g2g_cheapold"
            _disc = _row_pol.get("下浮比例")
            if _disc is None:
                _disc = 0.03
            _mult = _row_pol.get("乘数")
            if _mult is None:
                _mult = 1.0 - _disc
            rec["下浮比例"] = _disc
            # 三源明细照旧（看板继续显示 G2G/ELD/IGGM + 差距对比）
            if _ms and sv.get("key") in _ms_need:
                try:
                    _bv_ms, _bd_ms, _bdet_ms = _ms.resolve_base(sv, iggm_price=igp, apo=apo)
                    rec["多源明细"] = _bdet_ms
                    rec["竞品基准价"] = _bv_ms
                    rec["竞品基准来源"] = _bdet_ms.get("取谁") or "-"
                    rec["G2G_USD每M"] = _f(_bdet_ms.get("G2G"))
                except Exception as _e:            # noqa: BLE001
                    log("  [金币/多源] %s 三源解析失败：%r" % (sv.get("中文名"), _e))
            # 子服务器 G2G 取价（cheapold 优先）
            _ds = str(sv.get("g2g_dataset") or "").strip()
            _cb = None
            if _row_pol.get("错误"):
                rec["G2G跟价错误"] = _row_pol["错误"]
            elif not _g2gcb:
                rec["G2G跟价错误"] = "core_g2g 不可用"
            elif not _ds:
                rec["G2G跟价错误"] = "config 缺 g2g_dataset（无法定位 G2G 子服务器入口）"
            else:
                try:
                    _cb = _g2gcb(_ds, sv.get("大区") or "", log=None)
                except Exception as _e:            # noqa: BLE001
                    rec["G2G跟价错误"] = "抓取失败：%r" % _e
                    log("  [金币/G2G] %s 抓取失败：%r" % (sv.get("中文名"), _e))
            if _cb:
                rec["G2G_cheapold价"] = _cb.get("cheapold")
                rec["G2G_推荐1"] = _cb.get("t1")
                rec["G2G_推荐1卖家"] = _cb.get("t1_u")
                rec["G2G_推荐2"] = _cb.get("t2")
                rec["G2G_推荐2卖家"] = _cb.get("t2_u")
                rec["G2G_卖家数"] = _cb.get("n")
                rec["G2G_取价卖家"] = _cb.get("who")
                _valid_base = positive_number(_cb.get("base"))
                if _valid_base is not None and positive_number(_mult) is not None:
                    _issrc = (_cb.get("src") == "cheapold")
                    _base_src = "G2G·cheapold" if _issrc else "G2G·推荐前二"
                    rec["基准价"] = _valid_base
                    rec["基准来源"] = _base_src
                    rec["定价来源级别"] = 1 if _issrc else 2
                    _tgt_from_base = positive_number(_valid_base * _mult)
                    _base_detail = (
                        "G2G %s %s：$%.4f/M × (1−%.1f%%)"
                        % (sv.get("大区") or "",
                           ("cheapold 卖家" if _issrc
                            else "推荐前二较低者(%s)" % _cb.get("who")),
                           _valid_base, _disc * 100))
                else:
                    rec["G2G跟价错误"] = "该子服务器本轮 0 条有效报价"
        # ② 旧策略：三源比价（保留，可通过 config 一键切回）
        elif _ms and sv.get("key") in _ms_need and _row_mode != "dd373_markup":
            _mode_used = "multisrc"
            rec["定价模式"] = "multisrc"
            _bv, _bd, _bdet = _ms.resolve_base(sv, iggm_price=igp, apo=apo)
            rec["多源明细"] = _bdet
            _base_src = _bdet.get("取谁") or "-"
            _base_detail = _bd
            rec["基准价"] = _bv
            rec["基准来源"] = _base_src
            rec["竞品基准价"] = _bv
            rec["竞品基准来源"] = _base_src
            if _bv is not None:
                _tgt_from_base = _bv * apo
        if _tgt_from_base is not None:
            tgt_m = _tgt_from_base
            if _mode_used == "dd373_markup":
                rec["目标前端每M_口径"] = "%s $%.4f/M × (1 + %.1f%%)" % (
                    {"DD373": "DD373推荐价"}.get(_base_src, _base_src),
                    rec.get("基准价") or 0.0, (_mk or 0) * 100)
            elif _mode_used == "g2g_cheapold":
                rec["目标前端每M_口径"] = "%s $%.4f/M × (1 − %.1f%%)" % (
                    _base_src, rec.get("基准价") or 0.0, discount_display(_disc) * 100)
            else:
                rec["目标前端每M_口径"] = "基准(%s) × 让价系数 %.4f" % (_base_src, apo)
        elif _mode_used == "dd373_markup":
            # DD373 无报价 → **明确不退回旧口径**（否则会拿 IGGM 定价，与新策略冲突）
            tgt_m = None
            rec["目标前端每M_口径"] = "DD373 无报价 → 本轮不出目标价（不推算、不兜底）"
        elif _mode_used == "g2g_cheapold":
            # G2G 抓不到/无报价 → **明确不退回旧口径**（绝不拿 IGGM 顶价）
            tgt_m = None
            rec["目标前端每M_口径"] = ("G2G 无报价/抓取失败 → 本轮不出目标价"
                                       "（不回落旧口径）")
        else:
            # 退回旧口径（纯 IGGM × 让价系数）—— D4 走这条
            tgt_m = (igp * apo) if igp else None
            rec["目标前端每M_口径"] = "IGGM × 让价系数 %.4f（旧口径）" % apo
        rec["让价系数"] = apo
        rec["目标前端每M"] = tgt_m
        # ── 差距对比（2026-10-02 新增列）──────────────────────────────────
        # 「我方价格 与 当前竞品最低价 的差距」—— 三源里**有数的**那些取最小。
        # ⚠ 这是**展示**用的：新策略下 G2G/ELD/IGGM 不参与定价，但用户要在看板上看
        #   「我方比竞品贵还是便宜」，所以照样算、照样存。
        #   口径统一在「客户真价」上：IGGM 传进来的 igp 已经 ×1/1.1 折算过。
        _cand = {"G2G": _f((rec.get("多源明细") or {}).get("G2G")),
                 "ELD": _f((rec.get("多源明细") or {}).get("ELD")),
                 "IGGM": _f(igp)}
        _cand = {kk: vv for kk, vv in _cand.items() if vv is not None}
        _oup_pre = _f(rec.get("我方前端每M"))     # 我方现价（前端读回的真实售价）
        if _cand:
            _lo_src = min(_cand, key=_cand.get)
            _lo = _cand[_lo_src]
            rec["竞品最低价"] = _lo
            rec["竞品最低来源"] = _lo_src
            if _oup_pre is not None and _lo:
                rec["差距_对竞品最低"] = round(_oup_pre - _lo, 6)
                rec["差距_对竞品最低_百分比"] = round((_oup_pre / _lo - 1.0) * 100.0, 3)
        else:
            rec["竞品最低价"] = None
            rec["竞品最低来源"] = None
            rec["差距_对竞品最低"] = None
            rec["差距_对竞品最低_百分比"] = None
        # 🔴 成本除数：**必须**走 cost_divisor_of（= 汇率×(1−利润率)÷前台系数 ≈ 5.054），
        #    不能再用 汇率×(1−利润率)（= 5.32）。原因见 front_factor_of 的注释：
        #    前台还比 b2c 高 5.26%，按 5.32 写采购成本会把这份溢价留在价上，
        #    正好把「让价 5%」整条吃掉（实测 3/4 服务区我方前端价 = IGGM 折算后价）。
        _raw_valid = raw_cost_inputs_valid(cfg, sv, gm)
        _div = (None if _mode_used == "g2g_cheapold" and not _raw_valid
                else cost_divisor_of(cfg, rl, gm))
        rec["成本除数"] = _div
        oup = _f(rec.get("我方前端每M"))
        if _mode_used == "g2g_cheapold":
            _thr_valid = finite_number(cfg_gold(cfg).get("持平阈值", 0.005))
            _cost_valid = (positive_number(tgt_m * _div)
                           if positive_number(tgt_m) is not None and positive_number(_div) is not None
                           else None)
            if (positive_number(oup) is None or _thr_valid is None or _cost_valid is None
                    or gold_cost_for_dispatch(cfg, round(_cost_valid, dec)) is None):
                tgt_m = None
                rec["目标前端每M"] = None
                rec["G2G跟价错误"] = "目标/现价/成本/阈值无效：本轮不出目标价"
        if tgt_m and oup:
            rec["差距倍数"] = oup / tgt_m
            _thr = float(cfg_gold(cfg).get("持平阈值", 0.005))
            _gap_pct = (oup / tgt_m - 1.0) * 100.0
            if abs(oup / tgt_m - 1.0) < _thr:
                rec["动作"] = "hold"
            else:
                rec["动作"] = "follow_down" if oup / tgt_m > 1 else "follow_up"
            rec["采购成本_新"] = round(tgt_m * _div, dec)
            # ── 最大档对照（用户口径 2026-09-27）─────────────────────────────
            # 「金币单位大，看起来不方便 → 用最大的那个金币选项对照价格的变化」。
            # 取**我方前端最大的那个档位**当尺子（那就是用户眼里的「最大的金币选项」，
            # 例如赛季普通的 500000M），把两侧都换算到**同一个档位**再比总额 ——
            # ⚠ 两侧档位梯度不同（我方 500000M / IGGM 900000M），绝不能用各自的「最大档」
            #   互相对，那是拿 500000M 的价去比 900000M 的价（差 80%）。
            #   两侧每 M 价都是线性的，所以「某档总价 = 每M价 × 该档 M 数」一定成立。
            _n_ref = rec.get("我方最大档") or rec.get("IGGM最大档")
            if _n_ref and igp:
                _n = float(_n_ref)
                _ig_true = igp * _n                      # IGGM 真价（折算后）在该档的总额
                _tgt_big = tgt_m * _n                    # 我方改完应达到的总额
                rec["对照档位"] = int(_n_ref)
                rec["对照_IGGM总价"] = round(igp / (k or 1.0) * _n, 4)   # 机房抓取口径
                rec["对照_IGGM真价"] = round(_ig_true, 4)
                rec["对照_我方现价"] = round(oup * _n, 4)
                rec["对照_我方改后"] = round(_tgt_big, 4)
                rec["对照_IGGM最大档"] = rec.get("IGGM最大档")
                if _ig_true:
                    # 正数 = 改后比 IGGM 真价低几个百分点（目标 ≈ 让价百分比 5%）
                    rec["对照_改后低于IGGM"] = round((1.0 - _tgt_big / _ig_true) * 100.0, 3)
                    rec["达标"] = bool(_tgt_big <= _ig_true * apo + 1e-9)
            if rec["动作"] == "hold":
                rec["说明"] = ("目标 $%s/%s（基准 %s $%s/%s − %.1f%%），我方 $%s/%s"
                              "（%+.2f%%，在 ±%.1f%% 持平区间内）→ 不动"
                              % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                                 _base_src, fmt_money(per_100k(igp, _dm)), _ul,
                                 (1.0 - apo) * 100.0, fmt_money(per_100k(oup, _dm)), _ul,
                                 _gap_pct, _thr * 100))
            else:
                # ── 无效果闸（2026-09-26 patch7）──────────────────────────────
                # 判「方向」是**相对差 %**，但**能不能真的改出一个不同的价**取决于
                # 前端的显示精度：档位总价只显示 N 位小数，目标价与现价在 N 位下相同
                # ⇒ 客户看到的价一模一样 ⇒ 白改（还白清一次缓存）。
                # 实测：赛季普通 10000M 档真实 $0.18797 被显示成 $0.19，我方每M 读回
                # 1.9e-05（真实 1.8797e-05），取整把真实 +0.37% 放大成 +1.46% 越过
                # 0.5% 阈值 → 出单；而目标采购成本 round(6) 后恰好 = 现值 0.0001
                # ⇒ 「改前 = 改后」，每小时白出一张单。
                _nd = int(cfg_gold(cfg).get("前端显示小数位", 2) or 2)
                _n0 = rec.get("我方最大档") or rec.get("我方前端档位")
                _tgt_total = tgt_m * float(_n0 or 0.0)
                _cur_total = oup * float(_n0 or 0.0)
                if _n0 and round(_tgt_total, _nd) == round(_cur_total, _nd):
                    rec["动作"] = "hold"
                    rec["无效果"] = True
                    rec["说明"] = ("目标 $%s/%s（基准 %s $%s/%s − %.1f%%），我方 $%s/%s"
                                  "（%+.2f%%，超 ±%.1f%% 阈值），"
                                  "但 %dM 档前端显示价同为 $%.*f"
                                  "（目标 %.*f / 现在 %.*f）⇒ 改了也看不出，无效果 → 不动"
                                  % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                                     _base_src, fmt_money(per_100k(igp, _dm)), _ul,
                                     (1.0 - apo) * 100.0, fmt_money(per_100k(oup, _dm)), _ul,
                                     _gap_pct, _thr * 100,
                                     int(_n0), _nd, round(_cur_total, _nd),
                                     _nd, round(_tgt_total, _nd), _nd, round(_cur_total, _nd)))
                else:
                    _d = ""
                    if rec.get("对照档位"):
                        _d = ("｜最大档 %sM：我方 $%s → 改后 $%s（%s 真价 $%s，改后低 %s%%）"
                              % (rec["对照档位"], fmt_money(rec.get("对照_我方现价")),
                                 fmt_money(rec.get("对照_我方改后")), _base_src,
                                 fmt_money(rec.get("对照_IGGM真价")),
                                 fmt_money(rec.get("对照_改后低于IGGM"), 1)))
                    _bd_txt = ("（%s）" % _base_detail) if _base_detail else ""
                    rec["说明"] = ("目标 $%s/%s（基准 %s $%s/%s − %.1f%%%s），我方 $%s/%s"
                                  "（%+.2f%%）→ 采购成本应改为 ￥%.6f/M"
                                  "（= 目标每M × 成本除数 %.4f）%s"
                                  % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                                     _base_src, fmt_money(per_100k(igp, _dm)), _ul,
                                     (1.0 - apo) * 100.0, _bd_txt,
                                     fmt_money(per_100k(oup, _dm)), _ul, _gap_pct,
                                     rec["采购成本_新"], _div, _d))
            # ── 2026-10-02：DD373 加价模式下把「说明」改写成 DD373 口径 ──────
            # 上面那两句是三源时代的文案（会写「基准 IGGM $x − 5%」），
            # 在新策略里会误导 —— 目标价跟 G2G/ELD/IGGM 一点关系都没有。
            if _mode_used == "dd373_markup":
                _cusd0 = rec.get("DD373成本_USD每M")
                _lvl = rec.get("定价来源级别")
                # ⚠ 每级要显示的**基准值**必须各取各的：第1级取 DD373 成本，
                #   第2级取 G2G 兜底价（不是 DD373 —— 它是 None，会显示成「$-/M」），
                #   第3级取默认售价。原来三档都塞 _cusd0，第2/3级就打出「兜底 $-/M」。
                if _lvl == 1:
                    _lbl, _lbl_v = "DD373 推荐价", _cusd0
                elif _lvl == 2:
                    _lbl = "%s 兜底" % _row_pol.get("次源", "G2G")
                    _lbl_v = rec.get("G2G_USD每M")
                else:
                    _lbl, _lbl_v = "默认售价", _def_m
                _pre = "目标 $%s/%s（第%d级·%s $%s/%s → $%s/%s）｜我方 $%s/%s（%+.2f%%）" % (
                    fmt_money(per_100k(tgt_m, _dm)), _ul, _lvl or 0, _lbl,
                    fmt_money(per_100k(_lbl_v, _dm)), _ul,
                    fmt_money(per_100k(tgt_m, _dm)), _ul,
                    fmt_money(per_100k(oup, _dm)), _ul, _gap_pct)
                if rec["动作"] == "hold":
                    rec["说明"] = _pre + "（在 ±%.1f%% 持平区间内）→ 不动" % (_thr * 100)
                else:
                    rec["说明"] = _pre + "→ 采购成本应改为 ￥%.6f/M（= 目标每M × 成本除数 %.4f）" % (
                        rec["采购成本_新"], _div)
                    if _lvl == 1:
                        rec["说明"] += "｜DD373 综合排序第1条 %s 元/万基纳（%s 条挂单）" % (
                            rec.get("DD373成本_元每万基纳"),
                            rec.get("DD373挂单数")
                            if rec.get("DD373挂单数") is not None else "?")
                    else:
                        rec["说明"] += "｜%s" % (rec.get("说明_顺延") or "")
            # ── 2026-10-05：G2G cheapold 模式下把「说明」改写成 G2G 口径 ──────
            if _mode_used == "g2g_cheapold":
                _lvl = rec.get("定价来源级别")
                if _lvl == 1:
                    _lbl = "cheapold 卖家"
                else:
                    _lbl = "推荐前二较低者(%s)" % (rec.get("G2G_取价卖家") or "-")
                _pre = ("目标 $%s/%s（G2G %s $%s/%s × (1−%.1f%%)）｜我方 $%s/%s（%+.2f%%）"
                        % (fmt_money(per_100k(tgt_m, _dm)), _ul, _lbl,
                           fmt_money(per_100k(rec.get("基准价"), _dm)), _ul,
                           discount_display(_disc) * 100,
                           fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                _gz = ("｜cheapold $%s｜推荐1 $%s(%s)｜推荐2 $%s(%s)｜卖家 %s 家"
                       % (fmt_money(rec.get("G2G_cheapold价")), fmt_money(rec.get("G2G_推荐1")),
                          rec.get("G2G_推荐1卖家") or "-", fmt_money(rec.get("G2G_推荐2")),
                          rec.get("G2G_推荐2卖家") or "-", rec.get("G2G_卖家数")))
                if rec["动作"] == "hold":
                    rec["说明"] = _pre + "（在 ±%.1f%% 持平区间内）→ 不动%s" % (_thr * 100, _gz)
                else:
                    rec["说明"] = (_pre + "→ 采购成本应改为 ￥%.6f/M"
                                          "（= 目标每M × 成本除数 %.4f）%s"
                                   % (rec["采购成本_新"], _div, _gz))
        else:
            rec["差距倍数"] = None
            rec["动作"] = "hold"
            rec["采购成本_新"] = None
            if _mode_used == "dd373_markup":
                # 三级顺延都拿不到 → 说清是「没报价」而不是「数据缺失」
                rec["错误"] = None
                rec["说明"] = ("DD373 无报价（%s）且兜底链也未取到价 → 本轮不出目标价"
                               % (rec.get("DD373依据") or rec.get("说明_顺延") or "该区无挂单"))
            elif _mode_used == "g2g_cheapold":
                rec["错误"] = None
                rec["说明"] = ("G2G 未取到价（%s）→ 本轮不出目标价"
                               % (rec.get("G2G跟价错误") or "该子服务器无有效报价"))
            elif not rec.get("错误"):
                rec["错误"] = "双方价有一侧没抓到，无法算目标价"
        _ko = _known.get(sv.get("key"))
        if _ko is not None and rec.get("说明"):
            try:
                rec["说明"] = "现行采购成本 ￥%.6f（本机回传）｜ %s" % (float(_ko), rec["说明"])
            except (TypeError, ValueError):
                pass
        items.append(rec)
        time.sleep(float(cfg_gold(cfg).get("请求延迟秒", 0.8) or 0.8))
    _games = sorted({server_game(cfg, s) for s in svs})
    return {"ts": dt.datetime.now().isoformat(timespec="seconds"), "tier": tier,
            "rate": rate, "折算系数": k, "让价系数": apo,
            "让价百分比": round((1.0 - apo) * 100.0, 4),
            "前台系数": front_factor_of(cfg),
            "成本除数": cost_divisor_of(cfg, 0.20),
            "展示单位": int(PER_100K),
            # 多游戏（2026-10-01）：展示层按**每个游戏各自的**前台系数/成本除数/展示倍率取值，
            # 不要再用上面那三个「全局值」去套所有游戏（那是 D4 的口径）。
            "游戏参数": {g: {"前台系数": front_factor_of(cfg, g),
                             "成本除数": cost_divisor_of(cfg, 0.20, g),
                             "展示倍率": display_mult_of(cfg, g),
                             "展示单位": unit_label(display_mult_of(cfg, g)),
                             "IGGM金币页": game_param(cfg, g).get("IGGM金币页")}
                         for g in _games},
            # ⭐ 定价策略留证（2026-10-02）：看板/接口直接读这段显示当前口径，
            #   不用去猜「这次到底按什么算的」。模式可由 config.金币.定价策略.模式 切换。
            "定价策略": {
                # **按游戏**给，别只给 AION2 —— 暗黑4 必须是 None（默认口径）
                "按游戏": {g: p for g, p in _pol_by_game.items() if p},
                "AION2": _pol_by_game.get("AION2"),
                "说明": ("当前 AION2 走「G2G cheapold 跟价」；G2G/ELD/IGGM 继续采集监控并展示，"
                         "定价只取该子服务器的 cheapold（无则推荐前二较低者）×(1−下浮%)。"
                         "改 config.金币.定价策略.模式 即可切回 DD373 或三源比价。"
                         if _pricing_mode == "g2g_cheapold" else
                         ("当前 AION2 走「DD373 推荐价 + 加价%」；G2G/ELD/IGGM 继续采集监控并展示，"
                          "但不参与定价。旧策略（三源比价 multisrc）已归档，"
                          "改 config.金币.定价策略.模式 即可切回。"
                          if _pricing_mode == "dd373_markup" else "默认口径（纯 IGGM × 让价系数）")),
                "可切换": ["dd373_markup（DD373 推荐价加价）",
                           "multisrc（旧·三源比价）",
                           "g2g_cheapold（G2G cheapold 跟价）"],
            },
            "口径": "我方前端每M价 = IGGM 每M价 × (1 − 让价百分比)；"
                    "目标采购成本 = 目标每M价 × 成本除数；"
                    "成本除数 = 汇率 × (1−利润率) ÷ 前台系数"
                    "（前台每M价 = 后台b2c × 前台系数：D4 实测 1/0.95，Aion 2 实测 1.0）；"
                    "展示倍率按游戏取（D4 = 每 100000M，Aion 2 = 每 M）",
            "多源基准": ({
                "启用": True,
                "参与定价": (_pricing_mode not in ("dd373_markup", "g2g_cheapold")),
                "口径": ("⚠ 仅监控展示，**不参与定价**（当前策略 = G2G cheapold 跟价）"
                         if _pricing_mode == "g2g_cheapold" else
                         ("⚠ 仅监控展示，**不参与定价**（当前策略 = DD373 推荐价加价）"
                          if _pricing_mode == "dd373_markup" else
                          "基准 = min(G2G, ELD)，IGGM 更低则取 IGGM；"
                          "两站都没数据的区用同大区均价兜底；目标 = 基准 × (1−让价百分比)")),
                "明细": {it.get("key"): {"基准来源": it.get("基准来源"),
                                        "基准价": it.get("基准价"),
                                        "竞品最低价": it.get("竞品最低价"),
                                        "竞品最低来源": it.get("竞品最低来源"),
                                        "差距_对竞品最低": it.get("差距_对竞品最低"),
                                        "差距_对竞品最低_百分比": it.get("差距_对竞品最低_百分比"),
                                        "多源明细": {kk: vv for kk, vv in
                                                     (it.get("多源明细") or {}).items()
                                                     if kk != "兜底值"}}
                         for it in items if it.get("基准来源")},
            } if _ms else {"启用": False}),
            "items": items}


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="金币跟价 DRY-RUN（只算不改）")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                     "config.json"))
    ap.add_argument("--factor", type=float, help="覆盖竞品价折算系数（本机调试传 1.0）")
    ap.add_argument("--dd373-db", help="从该 SQLite 读 gold_cost 最新成本注入（DD373 定价模式用）")
    ap.add_argument("--out")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    if a.factor is not None:
        cfg.setdefault("iggm", {})["竞品价折算系数"] = a.factor
    _costs = {}
    if a.dd373_db:
        # dry-run 也要能看到真实 DD373 成本，否则新策略下 34 个区全是 hold、验不出东西
        import sqlite3 as _sq
        _con = _sq.connect(a.dd373_db)
        _con.row_factory = _sq.Row
        for _r in _con.execute(
                "SELECT key, ok, cny_per_wan, usd_per_m, n_items, dd_zone, basis, note"
                " FROM gold_cost WHERE ts=(SELECT MAX(ts) FROM gold_cost)"):
            _costs[_r["key"]] = {"ok": _r["ok"], "cny_per_wan": _r["cny_per_wan"],
                                 "usd_per_m": _r["usd_per_m"], "n_items": _r["n_items"],
                                 "dd_zone": _r["dd_zone"], "basis": _r["basis"],
                                 "note": _r["note"]}
        _con.close()
        print("已从 %s 注入 DD373 成本 %d 条（有效 %d）"
              % (a.dd373_db, len(_costs), sum(1 for v in _costs.values() if v.get("ok"))))
    p = build_plan(cfg, dd373_costs=_costs)
    _gp = p.get("游戏参数") or {}
    print("=" * 138)
    print("金币跟价 DRY-RUN ｜ 对标 %dM ｜ 汇率 %.2f ｜ 折算系数 %s ｜ 让价 %.1f%%"
          % (p["tier"], p["rate"], p["折算系数"], p.get("让价百分比", 0.0)))
    for _g, _v in _gp.items():
        print("  · %-14s 前台系数 %.6f ｜ 成本除数 %.4f ｜ 单价按「每 %s」展示 ｜ IGGM %s"
              % (_g, _v.get("前台系数", 1.0), _v.get("成本除数", 0.0),
                 _v.get("展示单位", "10万M"), _v.get("IGGM金币页")))
    print("（单价一律定点输出，不再出现科学计数法：D4 按每 100000M、Aion 2 按每 M）")
    print("=" * 138)
    print("%-22s %-7s %-10s %-10s %-10s %-8s %-7s %-7s %-12s %-11s %s" %
          ("服务区", "游戏", "IGGM单价", "我方单价", "目标单价", "单位", "差距", "成本除数",
           "目标采购成本", "最大档达标", "动作"))
    print("-" * 138)
    for it in p["items"]:
        _md = it.get("展示倍率")
        print("%-22s %-7s %-10s %-10s %-10s %-8s %-7s %-7s %-12s %-11s %s" %
              (it.get("中文名"), it.get("游戏") or "-",
               fmt_money(per_100k(it.get("IGGM每M_跟价用"), _md)),
               fmt_money(per_100k(it.get("我方前端每M"), _md)),
               fmt_money(per_100k(it.get("目标前端每M"), _md)),
               ("$/每%s" % (it.get("展示单位") or "10万M")),
               ("x%.4f" % it["差距倍数"]) if it.get("差距倍数") else "-",
               "%.4f" % it["成本除数"] if it.get("成本除数") else "-",
               ("%.6f" % it["采购成本_新"]) if it.get("采购成本_新") is not None else "-",
               ("✔低%.2f%%" % it["对照_改后低于IGGM"]) if it.get("达标")
               else (("✘低%.2f%%" % it["对照_改后低于IGGM"])
                     if it.get("对照_改后低于IGGM") is not None else "-"),
               it.get("动作") or "-"))
        if it.get("对照档位"):
            print("      └ 对照档 %sM：IGGM真价 $%s ｜ 我方现价 $%s → 改后 $%s"
                  % (it["对照档位"], fmt_money(it.get("对照_IGGM真价")),
                     fmt_money(it.get("对照_我方现价")), fmt_money(it.get("对照_我方改后"))))
        if it.get("错误"):
            print("      ⚠ %s" % it["错误"])
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
        print("\n已存：%s" % a.out)
