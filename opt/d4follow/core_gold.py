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
        ⭐ 2026-10-09：金币链路改为**复用 core_iggm 的 CF 加固会话**（会话自愈
          + 熔断退避；`__cf_bm` 是域级 cookie，与物品采集共用）—— 见 `IggmGold`。
  我方前端金币：`POST https://www.mmoexp.com/ajax/goods`
      form: `Game_id=456&top_cid=1&aid=<服务区aid>&cid=&site_id=`
      返回 `goods.index.list[0].goods_list{num:{num,price,price_discount,discount}}`。
      ⚠ **按服务区逐个取**：各服务区档位集合不同（100M / 1000M / 5000M / 10000M 起），
        不能假设都有某个档 —— 取「最接近目标档位」的那一档折算每 M 价。

只读：本模块全部是 GET / 只查询的 POST，**不写任何价格**。
"""
import datetime
import http.cookiejar
import json
import os
import re
import time
import urllib.parse
import urllib.request

import core_iggm as _ci            # IGGM 会话（CF 挑战加固）：金币与物品共用同一
                                   # CookieJar + 熔断器 —— 见下方 IggmGold

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
    # ── 2026-10-08 接入第三个游戏：MapleStory Classic World（冒险岛怀旧服国际服）──
    # ⚠ 前台单位是 **K**（不是 M）：档位 data-num = 10/20/…/500（单位 K ），
    #   后台行 21754 的 b2c 就是 $/K（实测「产品价格管理」$每个价格 = 8.59291100 逐位相同）。
    #   ⇒ 前台系数 = 1.0、展示倍率 = 1（单价直接按 $/K 显示）、展示单位名 = "K"。
    # ⚠ IGGM 折算系数必须**单独覆盖成 1.0**：全局 0.909090909 是「机房 IP 加价 1.1」的还原，
    #   2026-10-08 实测这个游戏本机与机房抓到的价**完全一致**（都是 0.499）⇒ 无机房加价。
    #   照抄全局值会把目标价凭空压低 9.1%。
    "MapleStory Classic World": {
        "IGGM金币页": "/maplestory-classic-world/mesos",
        "前台GameId": "1333", "前台top_cid": "1", "前台cid": "9661", "前台site_id": "266",
        "前台Referer": "https://www.mmoexp.com/Maplestory-classic-world/Mesos.html",
        "前台系数": 1.0,          # 2026-10-08 实测：前台 $每个价格 == 后台 b2c（8.59291100 逐位相同）
        "展示倍率": 1,            # 前台单位 K，b2c 即 $/K
        "展示单位名": "K",        # 展示时写「$/K」，别套 D4 的「10万M」
        "IGGM折算系数": 1.0,      # 实测无机房加价（本机抓 0.499 = 机房抓 0.499）
        "对标档位": 500,          # 前台最大档 500K（用最大档做达标对照，精度最高）
    },
}
DEFAULT_GAME = "暗黑破坏神4"


def server_game(cfg, sv):
    """服务区属于哪个游戏（config.金币.服务区[].游戏；缺省 = 暗黑破坏神4）。"""
    return (sv or {}).get("游戏") or DEFAULT_GAME


# ═══════════════════════════════════════════════════════════════════════════
# 2026-10-09 · 时段加价（老板定案）
#   原话：「北京时间 凌晨2点至09:00，临时增加利润率至30%…持续7个小时，
#          7小时候回归正常策略」（复核口径后定案：加价比例 0.25 → **0.35**）
#   实现要点：
#     · 套在 pricing_policy() 里 ⇒ **所有下游（build_plan / 看板 / 钉钉 / 自检）
#       自动同步**；不用另开定时任务 —— 到点后下一轮调价自然回到常规值；
#     · 时间**固定按 UTC+8 算**，不读服务器时区（哪天机器时区被改，
#       也不会把「凌晨提价」跑到白天去）；
#     · 只对**带「加价比例」的模式**（dd373_only / dd373_markup）生效；
#       MSCW 的 iggm_undercut 走的是「让价比例」，不受影响。
# ═══════════════════════════════════════════════════════════════════════════
_BJ_TZ_HOURS = 8.0


def hhmm_to_min(s):
    """'02:00' → 120（当天第几分钟）；非法/空 → None（**不猜**）。"""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(s or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return h * 60 + mi


def beijing_minute(now_utc=None):
    """当前北京时间 = 当天第几分钟（0~1439）。固定 UTC+8，不依赖服务器时区。"""
    n = now_utc or (datetime.datetime.utcnow() + datetime.timedelta(hours=_BJ_TZ_HOURS))
    return n.hour * 60 + n.minute


def _win_hours(win):
    """窗口小时数（跨天也对）；取不到返回 '?'。"""
    a, b = hhmm_to_min((win or {}).get("起")), hhmm_to_min((win or {}).get("止"))
    if a is None or b is None:
        return "?"
    return "%g" % (((b - a) % 1440) / 60.0)


def _time_markup(block, game, ret):
    """给「加价比例」类策略套一层**时段覆盖**（config `金币.定价策略.时段加价`）。

    命中窗口 ⇒ 返回一份副本：加价比例换成窗口值，并带上 时段加价 / 加价比例_常规 /
    时段加价_结束 与口径说明（看板与日志都读它）；未命中 ⇒ 原样返回。

    配置形状：
        "时段加价": {
          "启用": true,
          "适用游戏": ["AION2"],
          "区间": [{"起": "02:00", "止": "09:00", "加价比例": 0.35}]
        }
    「起 > 止」按**跨天**处理；区间左闭右开（02:00 生效、09:00 整点失效）。
    """
    tk = (block or {}).get("时段加价")
    if not isinstance(tk, dict) or not tk.get("启用"):
        return ret
    _games = tk.get("适用游戏") or []
    if _games and game and game not in _games:
        return ret
    if ret.get("加价比例") is None:          # 乘法类模式才有时段加价
        return ret
    _base = ret.get("加价比例")
    _now = beijing_minute()
    for win in (tk.get("区间") or []):
        if not isinstance(win, dict):
            continue
        a, b = hhmm_to_min(win.get("起")), hhmm_to_min(win.get("止"))
        if a is None or b is None:
            continue
        hit = (a <= _now < b) if a <= b else (_now >= a or _now < b)
        if not hit:
            continue
        try:
            mk2 = float(win.get("加价比例"))
        except (TypeError, ValueError):
            continue
        if mk2 < 0:
            continue
        out = dict(ret)
        out["加价比例_常规"] = _base
        out["加价比例"] = mk2
        out["时段加价"] = "%s-%s" % (win.get("起"), win.get("止"))
        out["时段加价_结束"] = str(win.get("止"))
        _mg = (1.0 - 1.0 / (1.0 + mk2)) if mk2 > 0 else 0.0
        out["口径"] = ("⏰ 时段加价生效（北京时间 %s，每天 %s 小时）：加价比例由 %.4g "
                       "临时提到 %.4g（看板利润率 %.1f%%），到 %s 自动回归常规策略。"
                       % (out["时段加价"], _win_hours(win), float(_base or 0), mk2,
                          _mg * 100, win.get("止")))
        if ret.get("口径"):
            out["口径"] += " ｜ " + str(ret["口径"])
        return out
    return ret


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
    ┌ dd373_only（2026-10-06 起，老板定案「只跟 DD373 进货价 +7%」）────┐
    │ 目标售价 $/M = DD373 该区进货成本 $/M × (1 + 加价比例)。           │
    │ **不跟 G2G、不跟 IGGM** —— 三源只采集展示（G2G最低/ELD最低/IGGM）。│
    │ DD373 无有效报价 **或 可买量 < 1 亿基纳** ⇒ 统一挂「无货兜底售价」 │
    │ （默认 $19.9/M），等该区有货（≥1 亿）下一轮自动跟回成本×加价。     │
    │ ⚠ 无货兜底价**不受「成本兜底 / 利润率下限」影响**（老板口径：     │
    │   「没挂单的统一调 19.9」= 严格统一，兜底价只看 无货兜底售价_USD每M）│
    └─────────────────────────────────────────────────────────────────┘
    ┌ g2g_cheapold（2026-10-05 起，老板定案 A「永远优先 cheapold」）────┐
    │ 每个子服务器进 G2G：有卖家 cheapold → 目标 = cheapold价×(1−下浮)。│
    │ 无 cheapold 卖家 → 目标 = 本区 DD373 成本 × 1.30（保 30% 利润）； │
    │ 🔴 2026-10-09 定案：**不再跟推荐前二**，该区与 G2G 竞品价脱钩。    │
    │ 🔴 2026-10-06 **成本兜底**（老板定案，仅对有 cheapold 的区）：      │
    │   · 基准价 < 我方 DD373 成本价（买满 1 亿的订单簿加权均价）        │
    │     ⇒ 不再跟降，**目标 = 成本价**（不下浮）；                      │
    │   · 最后按 **利润率下限（默认 +20%）强制兜底**：利润率 < 20% ⇒        │
    │     抬到 成本 ÷ 0.8（2026-10-09 由「−10% 亏损下限」升级；            │
    │     含成本兜底那批；货源闸行除外）。                                  │
    │   ⇒ DD373 成本由此**升级为定价输入**（此前仅监控）。               │
    └─────────────────────────────────────────────────────────────────┘

    ┌ iggm_undercut（2026-10-08 起 · MSCW 冒险岛怀旧服国际服）──────────┐
    │ 目标前端单价 = IGGM 真价 × (1 − 让价比例 10%)   ← **无成本加价上限**│
    │ 唯一一道闸 = 利润率下限 +15%：目标 < 成本÷(1−15%)=成本÷0.85 ⇒ 抬回。│
    │ ⚠ 这是**正利润率**下限（与 AION2 的 −10% 亏损下限方向相反）；       │
    │   「IGGM 低于成本就不跟」由这道闸自动实现，无需单独分支。          │
    │ 成本源仍是 DD373（买满 100 万金的订单簿加权均价），但**只做兜底**。│
    └─────────────────────────────────────────────────────────────────┘

    ⚠ 多游戏并存的写法（2026-10-08）：`金币.定价策略.按游戏.<游戏>` ——
      命中就用那一份（不看顶层 适用游戏 名单），未命中才回落到顶层单份逻辑。
      ⇒ MSCW(iggm_undercut) 与 AION2(dd373_only) 可以同时生效、互不干扰。

    ⚠ **DD373 无报价的区不推算、不兜底**（沿用 2026-10-02 用户口径）——
      该区本轮不出目标价、动作 hold，看板显示「无报价」。
    """
    g = game or ""
    _root = (cfg_gold(cfg).get("定价策略") or {})
    if not isinstance(_root, dict):
        return None
    # ⭐ 2026-10-08（多游戏各走各的模式）：**按游戏覆盖**。
    #   `金币.定价策略.按游戏.<游戏>` 存在 ⇒ 就用那一份（**不再看顶层 适用游戏 名单**）；
    #   不存在 ⇒ 完全沿用原来的「顶层单份 + 适用游戏 名单」逻辑
    #   ⇒ D4 / AION2 一个字节的行为都不变。
    #   为什么要它：MSCW 要跑 iggm_undercut，而 AION2 还在跑 dd373_only，
    #   原来的结构只有一份顶层 模式，切一个会连带切掉另一个。
    _per = _root.get("按游戏")
    p = None
    if g and isinstance(_per, dict) and isinstance(_per.get(g), dict):
        p = _per[g]
    if p is None:
        p = _root
        _games = p.get("适用游戏") or []
        if g and _games and g not in _games:
            return None                   # 不在适用名单 → 走默认口径
    mode = str(p.get("模式") or "").strip()
    if not mode:
        return None
    if mode == "dd373_markup":
        try:
            mk = float(p.get("加价比例", 0.05))
        except (TypeError, ValueError):
            mk = 0.05
        # 2026-10-09：套一层「时段加价」覆盖（命中则加价比例临时提高，见 _time_markup）
        return _time_markup(p, g, {
                "模式": mode, "加价比例": mk, "成本源": "DD373",
                # 三级兜底（2026-10-02 老板补充口径）
                "次源": str(p.get("次源") or "G2G"),
                "次源加价": (float(p.get("次源加价") or 0.0)
                             if str(p.get("次源加价") or "0") not in ("", None) else 0.0),
                "默认售价_USD每M": _f(p.get("默认售价_USD每M") or 9.9),
                "口径": "售价 = DD373 该区推荐价(综合排序第1条)折 $/M × %.2f%%；"
                        "G2G/ELD/IGGM 继续采集监控并展示，但定价上不主动参与 "
                        "（仅 DD373 无报价时按顺序兜底）" % (mk * 100)})
    if mode == "multisrc":
        return {"模式": mode, "加价比例": None, "成本源": "",
                "口径": "基准 = min(G2G, ELD)，IGGM 更低则取 IGGM，"
                        "两站无数据用同大区均价兜底；目标 = 基准 × (1−让价百分比)"}
    if mode == "g2g_cheapold":
        try:
            disc = float(p.get("下浮比例", 0.03))
        except (TypeError, ValueError):
            disc = 0.03
        if disc < 0:
            disc = 0.0
        _cn = str(p.get("cheapold卖家") or "cheapold")
        # 2026-10-06 老板定案：成本兜底 + 利润率下限（闸门落在 build_plan）
        # 2026-10-09 升级：利润率下限由「−10% 亏损下限」改为 **+20% 利润下限**
        #   （老板：「如果跟了 cheapold，利润率低于 20%，则强制调价到 20%」）。
        #   ⇒ 现在**正负都支持**（公式 P ≥ 成本 ÷ (1−下限) 一支通用），不再钳到 0。
        try:
            _mlim = float(p.get("利润率下限", 0.20))
        except (TypeError, ValueError):
            _mlim = 0.20
        if _mlim >= 1.0:                 # 100% 利润率 ⇒ 售价无穷大，无意义 ⇒ 夹到 90%
            _mlim = 0.90
        if _mlim <= -2.0:                # 亏损下限低于 −200% 也无意义（售价会是成本的 1/3）
            _mlim = -2.0
        # 2026-10-09 二次定案：**DD373 货源闸** —— 无有效报价 或 可买量 < 阈值 ⇒ 挂保护价。
        #   判据用 **DD373 的货源**（老板明确「货源不足指的是 DD373 的货源不够」），
        #   与 G2G 有没有报价无关。
        _park = _f(p.get("无货兜底售价_USD每M"))
        if _park is None or _park <= 0:
            _park = 19.9
        _need = _f(p.get("无货最小可买万基纳"))
        if _need is None or _need < 0:
            _need = 10000.0
        # 🔴 2026-10-09 三次定案 · **无 cheapold 卖家 ⇒ 按成本保 30% 利润**：
        #   老板原话「该区无 cheapold 卖家，则保持30%的利润」，并确认
        #   ① 利润公式 = **售价 = 成本 × 1.3**（成本加价 30%，不是 ÷0.7 口径）；
        #   ② 与「推荐前二」是**替换**关系（该区直接与 G2G 竞品价脱钩）。
        #   ⇒ 该区不再取 G2G 推荐前二价，目标 = 本区 DD373 成本 × 系数。
        #   ⚠ 系数走配置，方便日后微调；非法/缺失一律回落 1.30。
        _nc = _f(p.get("无cheapold加价系数"))
        if _nc is None or _nc <= 1.0:
            _nc = 1.30
        return {"模式": mode, "下浮比例": disc, "乘数": 1.0 - disc, "成本源": "DD373",
                "cheapold卖家": _cn, "利润率下限": _mlim,
                "无货兜底售价_USD每M": _park, "无货最小可买万基纳": _need,
                "无cheapold加价系数": _nc,
                "口径": ("每个子服务器进 G2G 取价：有卖家 %s → 目标 = %s价 × (1−%.1f%%)；"
                        "无 %s 卖家 → 目标 = 本区 DD373 成本 × %.2f"
                        "（老板口径「保持 30%% 的利润」，不再跟推荐前二）。"
                        "⚠ DD373 货源闸（2026-10-09）：DD373 无有效报价 或 可买量 < %.0f 万基纳"
                        "（不足 1 亿）⇒ 该区统一挂 $%.2f/M 高价保护（等有货自动跟回）。"
                        "⚠ 成本兜底（2026-10-06 保留）：基准价 < 我方 DD373 成本价"
                        "（= 买满 1 亿基纳的订单簿加权均价）时**不再跟降，直接按成本价定价**；"
                        "⚠ **利润率下限 %.0f%%（2026-10-09 新增）**：目标价算完后，"
                        "若利润率 (售价−成本)÷售价 < %.0f%% ⇒ **强制抬到 成本 ÷ %.2f**"
                        "（对**所有** g2g_cheapold 行生效，含成本兜底那批；货源闸行除外）"
                        % (_cn, _cn, disc * 100, _cn, _nc, _need, _park,
                           _mlim * 100, _mlim * 100, 1.0 - _mlim))}
    if mode == "dd373_only":
        # 2026-10-06 老板定案：**只跟 DD373 进货成本**，加价 7%；
        #   无有效报价 / 可买量不足 1 亿 ⇒ 统一挂「无货兜底售价」（默认 $19.9/M）。
        #   G2G最低价 / ELD最低价 / IGGM **仅采集展示，不参与定价**。
        try:
            mk = float(p.get("加价比例", 0.07))
        except (TypeError, ValueError):
            mk = 0.07
        if mk < 0:
            mk = 0.0
        _park = _f(p.get("无货兜底售价_USD每M"))
        if _park is None or _park <= 0:
            _park = 19.9
        _need = _f(p.get("无货最小可买万基纳"))
        if _need is None or _need < 0:
            _need = 10000.0
        # 2026-10-09：套一层「时段加价」覆盖（北京时间 02:00-09:00 提到 0.35）
        return _time_markup(p, g, {
                "模式": mode, "加价比例": mk, "成本源": "DD373",
                "无货兜底售价_USD每M": _park, "无货最小可买万基纳": _need,
                "口径": ("目标售价 $/M = DD373 该区进货成本 $/M × (1+%.1f%%)；"
                        "DD373 无有效报价 或 可买量 < %.0f 万基纳（不足 1 亿）"
                        "⇒ 统一挂 $%.2f/M（等有货自动跟回）。"
                        "G2G最低价/ELD最低价/IGGM 仅采集展示，不参与定价。"
                        % (mk * 100, _need, _park))})
    if mode == "iggm_undercut":
        # ── 2026-10-08 老板定案（MapleStory Classic World · 冒险岛怀旧服国际服）──────
        # 用户原话：
        #   「以 IGGM 的价格为对标，在保证 15% 利润兜底的情况下，永远比 IGGM 的售价低 10%；
        #     若 IGGM 价格低于成本价格，不跟随，按照最低 15% 利润率兜底，不再跟进。」
        #   「取消 30% 利润上限，只无脑跟 IGGM 的价就行，利润兜底保留。」
        # ⇒ 目标前端单价 = IGGM 真价 × (1 − 让价比例 10%)，**没有成本加价/上限**；
        #    唯一的一道闸 = 利润率下限 15%（售价 ≥ 成本 ÷ (1−15%) = 成本 ÷ 0.85）。
        #    「IGGM 低于成本就不跟」不需要单独写代码：IGGM×0.9 必然 < IGGM，
        #    IGGM < 成本时目标价一定跌破兜底线，被自动抬回成本线 ⇒ 等价于「不跟随」。
        # ⚠ 利润率下限是**正数**（+15%），与 AION2 的 −10%（亏损下限）方向相反，
        #    所以下面 build_plan 里走的是**独立**的兜底段，不复用 AION2 那段
        #    （AION2 那段有 `_lim < 0` 的前置判断，两者不会互相干扰）。
        try:
            disc = float(p.get("让价比例", 0.10))
        except (TypeError, ValueError):
            disc = 0.10
        disc = max(0.0, min(disc, 0.90))
        try:
            _lim2 = float(p.get("利润率下限", 0.15))
        except (TypeError, ValueError):
            _lim2 = 0.15
        if _lim2 < 0:
            _lim2 = 0.0
        if _lim2 >= 1.0:
            _lim2 = 0.90
        return {"模式": mode, "让价比例": disc, "乘数": 1.0 - disc, "成本源": "DD373",
                "利润率下限": _lim2,
                "口径": ("目标前端单价 = IGGM 真价 × (1−%.0f%%)（**无成本加价上限**，"
                        "老板口径「无脑跟 IGGM」）；"
                        "随后按 **利润率下限 %.0f%%** 兜底："
                        "目标低于 成本 ÷ (1−%.2f) = 成本 × %.4f 时抬回成本线"
                        "（IGGM 低于成本时即被这道闸挡住，不再跟降）。"
                        % (disc * 100, _lim2 * 100, _lim2, 1.0 / (1.0 - _lim2)))}
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
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
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


def unit_label(mult=None, name=None):
    """展示单位的中文名：10万M / M / K。

    `name`（2026-10-08 新增，可选）= 游戏参数里的「展示单位名」，**优先于倍率推导**。
    MSCW 的倍率与 AION2 同为 1，但单位是 K 不是 M —— 只靠倍率推不出来，
    所以允许游戏显式声明（`游戏参数.<游戏>.展示单位名 = "K"`）。
    """
    if name:
        return str(name)
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


def margin_of(cfg, game=None):
    """定价引擎算「成本除数」用的**该游戏利润率**。

    为什么必须有它（2026-10-08 查出的隐患）：
        后台公式 `b2c = 采购成本 ÷ 汇率 ÷ (1 − 利润率)`，而 b2c 就是前台每单位价
        （MSCW 实测前台系数 = 1.0），所以造价时必须**用后台那一行的利润率**把公式反推回去：
            采购成本 = 目标前台价 × 汇率 × (1 − 利润率) ÷ 前台系数
                     = 目标前台价 × cost_divisor_of(cfg, 该行利润率, 游戏)
        以前 app.py / 展示层一律硬编码 `0.20` —— 那只是 **D4 / AION2 后台行的值**，
        MSCW 后台行 21754 的利润率 = **0.30**，照抄 0.20 会把成本除数算成
        6.65×0.80 = 5.32（应为 6.65×0.70 = **4.655**），页面「已生效售价」虚低 12.5%。

    取法：该游戏**第一条**服务区条目的 `利润率`；取不到回落 0.20（= 历史硬编码值，
    D4 / AION2 一字不变 ⇒ 零回归）。
    """
    g = game or DEFAULT_GAME
    for sv in (cfg_gold(cfg).get("服务区") or []):
        if not isinstance(sv, dict):
            continue
        if server_game(cfg, sv) != g:
            continue
        v = _f(sv.get("利润率"))
        if v is not None:
            return v
    return 0.20


def cost_divisor_for_game(cfg, game=None):
    """该游戏的成本除数（= 用**它自己的**利润率走 cost_divisor_of）。

        D4 = 6.65×0.80÷1.0526316 = 5.0540    AION2 = 6.65×0.80÷1.0 = 5.3200
        MSCW = 6.65×0.70÷1.0     = 4.6550（利润率 0.30，2026-10-08 接入）

    多游戏场景一律用这个，**不要**再硬编码 0.20 传进 cost_divisor_of。
    """
    return cost_divisor_of(cfg, margin_of(cfg, game), game)


def factor_of(cfg, game=None):
    """竞品价折算系数（IGGM 抓到价 → 北美客户实付价）。

    三级（2026-10-08 加第 ① 级，向后兼容）：

      ① `游戏参数.<游戏>.IGGM折算系数`（内置于 GAME_PARAMS 或 config 覆盖）
         —— **按游戏**覆盖。MSCW 实测无机房加价 ⇒ 必须 = 1.0，否则目标价凭空低 9.1%；
      ② `金币.IGGM折算系数`（全局，本项目现值 0.909090909 = 1/1.1）
         —— D4 / AION2 走这级，行为一字不变；
      ③ 全局 `iggm.竞品价折算系数`。

优先读 **金币.IGGM折算系数**（金币专用字段）。

    2026-09-25 用户定案：**与物品统一口径** —— 金币价由服务器（机房 IP）抓，
    IGGM 对机房 IP 加价 1.10，故取 1/1.1 = 0.909090909（与 config.iggm.竞品价折算系数 同值）。
    🔴 改前为 0.9385113269（2026-09-24 按「本机(中国) $3.09 vs 美国电脑 $2.90」实测），
    那属于**中国/美国**维度，与「机房/家用」不是一回事，已按要求废弃。
    金币走独立字段，改它不会影响物品跟价；没配时退回全局值。
    本地家用 IP 跑调试可传 --factor 1.0 覆盖。
    """
    v = _f((game_param(cfg, game) or {}).get("IGGM折算系数"))
    if v and v > 0:
        return v
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


# core_iggm 撞 CF 拦截时抛的异常类（基线版本可能没有 → 空元组，永不匹配）
_IGGM_BLOCKED_CLS = getattr(_ci, "IGGMBlocked", ())


def _is_iggm_blocked(e):
    """该异常是否 = core_iggm 的「撞 CF 拦截」信号（用于停止后续 IGGM 抓取）。"""
    return bool(_IGGM_BLOCKED_CLS) and isinstance(e, _IGGM_BLOCKED_CLS)


# ------------------------------------------------------------------ 竞品：IGGM 金币
class IggmGold(object):
    """IGGM 金币抓取 —— 复用 core_iggm 的 CF 加固会话（2026-10-09 改造）。

    原先自己维护 CookieJar/opener，与 core_iggm 物品侧**同源缺陷**：
      · 撞 403/挑战页只丢弃预热标记、**不清 jar** ⇒ 失效的 __cf_bm 被反复带出、
        不重启进程就永不自愈；
      · warm 无 TTL、不识别挑战页；fetch 每个区各重试 3 次、**无熔断**
        （一轮打几百次请求，越打越黑）。
    现改为薄封装：**会话自愈 / 熔断退避 / 降速 / 浏览器请求头**全部交给 core_iggm。
    ⚠ __cf_bm 是**域级** cookie ⇒ 金币与物品可共用同一 CookieJar 与熔断器：
      物品侧已预热过就无需再 GET 金币页；同一 IP 被 CF 拦时两边同步熔断。

    ⚠ 撞 CF 拦截时由 core_iggm 抛 `IGGMBlocked`（基线无该类则抛普通异常）；
      熔断期内再 fetch 会**零网络请求**直接抛错 —— 调用方 catch 即可。
    """

    def __init__(self, log=print, timeout=40):
        self.log = log or (lambda *a: None)
        self.timeout = timeout

    def warm(self, force=False, page=None):
        """预热金币页拿 Cloudflare cookie（幂等；由 core_iggm 按 CF_TTL 缓存）。

        ⚠ 原来是「按金币页路径分别记 _warmed」，现统一交给 core_iggm 的进程级会话
          —— cookie 是域级，预热过任意页面即全站可用。
        """
        page = page or GAME_PARAMS[DEFAULT_GAME]["IGGM金币页"]
        ok = _ci._prime(IGGM_BASE + page, timeout=self.timeout, force=force)
        if not ok:
            self.log("  [金币/IGGM] 取 cookie 失败（%s）" % page)
        return ok

    def fetch(self, server_id, page=None, retry=3):
        """返回 {"unit_price": 每M价, "goods_no":..., "title":..., "tiers":[{num,all}], "update_time":...}

        `page` = 该游戏的金币页路径（同时决定 Referer 与 cookie 预热页），缺省 = D4。
        URL 与改造前**逐字一致**（golds 模板不带 game_sku）；
        重试 / 会话自愈 / 熔断由 core_iggm 负责（`retry` 透传给 core_iggm._get）。
        """
        page = page or GAME_PARAMS[DEFAULT_GAME]["IGGM金币页"]
        qs = urllib.parse.urlencode({
            "template_type": "golds", "server_id": str(server_id), "cate_id": 0,
        })
        body = _ci._get(IGGM_BASE + "/goods/goods_ajax?" + qs,
                        referer=IGGM_BASE + page, timeout=self.timeout, retry=retry)
        d = (json.loads(body) or {}).get("data") or {}
        g = d.get("one_goods") or {}
        tiers = [{"num": int(x.get("num") or 0), "all": _f(x.get("all")),
                  "market_price": _f(x.get("market_price"))}
                 for x in (d.get("result_goods") or [])]
        tiers.sort(key=lambda x: x["num"])
        return {"unit_price": _f(g.get("price")), "raw_unit_price": _f(g.get("price")),
                "goods_no": g.get("goods_no"), "title": (g.get("title") or "").strip(),
                "rule": g.get("rule"), "tiers": tiers,
                "update_time": (d.get("result_goods") or [{}])[0].get("update_time")}


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
            out = [{"num": int(v.get("num") or k), "unit": lst[0].get("unit") or "M",
                    "price": _f(v.get("price")), "price_discount": _f(v.get("price_discount")),
                    "discount": v.get("discount")} for k, v in gl.items()]
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
        n, p = int(t.get("num") or 0), _f(t.get(field))
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
        n, p = int(t.get("num") or 0), _f(t.get(field))
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
        n, a = int(t.get("num") or 0), _f(t.get("all"))
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
            % ((_pol_a.get("下浮比例") or 0.03) * 100, _pol_a.get("口径")))
    elif _pricing_mode == "dd373_only":
        _pol_a = _pol_by_game.get("AION2") or {}
        log("  [金币/定价] AION2 走「**只跟 DD373 进货成本 + %.1f%%**」模式：%s"
            % ((_pol_a.get("加价比例") or 0.07) * 100, _pol_a.get("口径")))
        if not _costs:
            log("  [金币/定价] ⚠ 本轮没有注入 DD373 成本（dd373_costs 为空）"
                "⇒ 全部 AION2 服务区按「无货兜底 $%.2f/M」出价（不会退回 G2G/IGGM）"
                % float(_pol_a.get("无货兜底售价_USD每M") or 19.9))
        else:
            _nok = sum(1 for v in _costs.values() if (v or {}).get("ok"))
            _nn = sum(1 for v in _costs.values()
                      if (v or {}).get("avail_wan") is not None
                      and float(v["avail_wan"]) >= float(_pol_a.get("无货最小可买万基纳") or 10000))
            log("  [金币/定价] 已注入 DD373 成本 %d 条：有报价 %d 条，其中买满 1 亿 %d 条"
                "（其余走无货兜底）" % (len(_costs), _nok, _nn))
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
    _blk_hit = [False]        # 本轮 IGGM 是否已撞熔断（只记第一条日志）
    for sv in svs:
        if sv.get("跟价", True) is False:
            log("  [金币] %s 未勾选跟价，跳过" % sv.get("中文名"))
            continue
        gm = server_game(cfg, sv)                  # 该服务区属于哪个游戏（多游戏接入）
        gp = game_param(cfg, gm)
        _k_row = factor_of(cfg, gm)                # ⭐ 折算系数**按游戏**（MSCW = 1.0）
        _dm = display_mult_of(cfg, gm)             # 展示倍率（D4 = 1e5 / Aion 2 = 1）
        # 展示单位名（10万M / M / K）—— 优先用游戏参数里的显式声明（MSCW = "K"；
        #   MSCW 倍率与 AION2 同为 1，光靠倍率推不出「K」）。
        _ul = unit_label(_dm, gp.get("展示单位名"))
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
            if _is_iggm_blocked(e):
                # ⭐ 撞 CF 拦截 → 后续 fetch 在熔断期内零网络请求直接抛错，
                #   这里只记第一条日志，避免刷屏；本区 IGGM 价留空（不误写价）。
                rec["错误"] = "IGGM 熔断：%r" % e
                if not _blk_hit[0]:
                    _blk_hit[0] = True
                    log("  [金币/IGGM] 撞 CF 拦截 → 本轮停止后续 IGGM 抓取"
                        "（冷却剩余 %ss）：%r"
                        % (_ci.breaker_state().get("remain_s"), e))
            else:
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
            # ── 2026-10-08 新增（只增不改，原有字段含义不动）──────────────────────
            # 前台定价定律（实证）：**客户实付价 = 后台 b2c × (该档位 discount ÷ 100)**，
            #   discount 是**逐档位**折扣（MSCW 10→500K 对应 100→95；AION2 全 100；D4 90~99）。
            # ⇒ 成本除数必须用**对标档位那一档**的折扣：
            #       成本除数 = 汇率 × (1−利润率) ÷ (discount/100)
            #   这里把「实际参与定价的那一档折扣」记进快照，并跟 config 假定值对一下账，
            #   后台若改了折扣就能一眼看出来（不用再去翻前台 API）。
            _disc_used = None
            for _t in (tiers or []):
                if int(_t.get("num") or 0) == int(n or -1):
                    _disc_used = _t.get("discount")
                    break
            rec["我方前端折扣_对标档位"] = _disc_used
            rec["我方前端折扣_对标档位名"] = n
            try:
                _assumed = round(front_factor_of(cfg, gm) * 100.0, 4)
                rec["前台折扣_假定值"] = _assumed
                if _disc_used and abs(float(_disc_used) - _assumed) > 0.5:
                    rec["前台折扣不符提醒"] = (
                        "对标档位 %s 的前台折扣 = %s%%，而 config 前台系数假定 %s%% ⇒ "
                        "成本除数需同步调整，否则客户实付价偏 %+.1f%%"
                        % (n, _disc_used, _assumed,
                           (float(_disc_used) / _assumed - 1.0) * 100.0))
            except Exception:
                pass
        except Exception as e:
            rec["我方前端每M"] = None
            rec["错误"] = (rec.get("错误") or "") + "；前端抓取失败：%r" % e
            log("  [金币/前端] %s 抓取失败：%r" % (sv.get("中文名"), e))

        igp = _f(rec.get("IGGM每M"))
        # 机房抓取价 → 客户真价（IGGM 对机房 IP 加价 1.1）
        # ⚠ 2026-10-08：折算系数**按行游戏取**（_k_row）。D4/AION2 = 0.909090909，
        #   MSCW = 1.0（实测无机房加价）—— 用全局值会把 MSCW 目标价压低 9.1%。
        if igp is not None and _k_row and _k_row != 1:
            igp = igp * _k_row
            rec["IGGM每M_折算后"] = igp
        rec["IGGM折算系数"] = _k_row
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
        # ①'' 2026-10-06 新模式：**只跟 DD373 进货成本 + 加价**（老板定案）
        #      · 目标售价 $/M = DD373 该区进货成本 $/M × (1 + 加价比例)，默认 +7%
        #      · DD373 无有效报价 **或 可买量 < 1 亿基纳** ⇒ 统一挂「无货兜底售价」
        #        （默认 $19.9/M）；等该区有货（≥1 亿）下一轮自动跟回。
        #      · **不回落 G2G / 不回落 IGGM**；三源只采集展示（G2G最低/ELD最低/IGGM）。
        #      · 同时**跳过 cheapold 子服务器抓取**（新模式不需要，省 86 次请求/轮）。
        elif _row_mode == "dd373_only":
            _mode_used = "dd373_only"
            rec["定价模式"] = "dd373_only"
            _mk = _row_pol.get("加价比例")
            if _mk is None:
                _mk = 0.07
            rec["加价比例"] = _mk
            _park = _f(_row_pol.get("无货兜底售价_USD每M"))
            if _park is None or _park <= 0:
                _park = 19.9
            _need = _f(_row_pol.get("无货最小可买万基纳"))
            if _need is None or _need < 0:
                _need = 10000.0
            rec["无货兜底售价_USD每M"] = _park
            _c = _costs.get(sv.get("key")) or {}
            _cusd = _f(_c.get("usd_per_m"))
            _avail = _f(_c.get("avail_wan"))          # 可买量（万基纳），app.py 从 stock 文本解析
            _ok = bool(_c.get("ok")) and _cusd is not None and _cusd > 0
            # 够不够 1 亿：avail 拿不到（旧快照/解析失败）⇒ **按有货处理**（宁可正常定价，
            #   也不要把一个真有货的区误挂成 $19.9）。
            _enough = bool(_ok) and (_avail is None or _avail >= _need)
            rec["DD373成本_USD每M"] = _cusd
            rec["DD373成本_元每万基纳"] = _c.get("cny_per_wan")
            rec["DD373可买_万基纳"] = _avail
            rec["DD373挂单数"] = _c.get("n_items")
            rec["DD373游戏区"] = _c.get("dd_zone")
            rec["DD373依据"] = _c.get("basis")
            # 三源明细照旧（看板展示 G2G最低价 / ELD最低价 / IGGM），但**不参与定价**
            if _ms and sv.get("key") in _ms_need:
                try:
                    _bv_ms, _bd_ms, _bdet_ms = _ms.resolve_base(sv, iggm_price=igp, apo=apo)
                    rec["多源明细"] = _bdet_ms
                    rec["竞品基准价"] = _bv_ms
                    rec["竞品基准来源"] = _bdet_ms.get("取谁") or "-"
                except Exception as _e:            # noqa: BLE001
                    log("  [金币/多源] %s 三源解析失败：%r" % (sv.get("中文名"), _e))
            if _enough:
                _tgt_from_base = _cusd * (1.0 + float(_mk or 0.0))
                _base_src = "DD373进货成本"
                rec["定价来源级别"] = 1
                rec["基准价"] = _cusd
                rec["基准来源"] = "DD373进货成本"
                _base_detail = ("DD373 %s 买满1亿订单簿均价 %s 元/万基纳 = $%.4f/M，+%.1f%%"
                                % (_c.get("dd_zone") or sv.get("中文名"),
                                   _c.get("cny_per_wan"), _cusd, float(_mk or 0) * 100))
            else:
                _tgt_from_base = _park
                _base_src = "无货兜底"
                rec["定价来源级别"] = 3
                rec["基准价"] = None
                rec["基准来源"] = "无货兜底"
                if not _ok:
                    _why = "DD373 无有效报价（%s）" % (_c.get("basis") or "该区无挂单")
                else:
                    _why = ("DD373 可买量 %.0f 万基纳 < %.0f（不足 1 亿）"
                            % (_avail or 0.0, _need))
                rec["无货兜底说明"] = ("%s ⇒ 本轮统一挂 $%.2f/M，"
                                       "等该区有货（≥%.0f 万基纳）下一轮自动跟回"
                                       % (_why, _park, _need))
                _base_detail = rec["无货兜底说明"]
        # ①' 2026-10-05 新模式：G2G cheapold 跟价（**永远优先 cheapold**，用户定案 A）
        #     · 有 cheapold ⇒ 目标 = cheapold 价 × (1−下浮%)
        #     · 无 cheapold ⇒ 目标 = min(推荐第1, 推荐第2) × (1−下浮%)
        #     · 抓不到 / 无报价 ⇒ 本轮不出目标价，**绝不回落旧口径**（同 DD373 口径）
        #     · G2G/ELD/IGGM 三源照旧采集展示（多源明细），只是不再喂目标价。
        #  🔴 2026-10-06 成本兜底（老板定案）：
        #     ① 基准价 < 我方 DD373 成本价（买满 1 亿基纳的订单簿加权均价）
        #        ⇒ 竞品在**亏本甩**，跟下去我方也亏 ⇒ 不再跟降，**目标 = 成本价**（不下浮）；
        #        （成本价旁证见 core_dd373_cost；DD373 由此从「仅监控」升级为「定价输入」）
        #     ② 利润率下限兜底（默认 −10%）在下面统一做，见「利润率下限兜底」段。
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
            # 我方 DD373 成本（1 亿订单簿加权均价）—— 成本兜底与利润率下限都要用它
            _cost = _costs.get(sv.get("key")) or {}
            _cusd = _f(_cost.get("usd_per_m"))
            _cost_ok = bool(_cost.get("ok")) and _cusd is not None and _cusd > 0
            rec["DD373成本_USD每M"] = _cusd
            rec["DD373成本_元每万基纳"] = _cost.get("cny_per_wan")
            rec["DD373可买"] = _cost.get("stock")
            rec["DD373依据"] = _cost.get("basis")
            # 🔴 2026-10-09 二次定案 · **DD373 货源闸**：判据是 **DD373 的货源**，与 G2G 有没有
            #   报价无关（老板明确「若该区域货源不足，还是以 19.9 进行高价保护」＋
            #   「货源不足指的是 DD373 的货源不够」）。不足 ⇒ 该区买不到货 ⇒ 统一挂保护价，
            #   且**不再抓 G2G**（省一次请求）。
            _park = _f(_row_pol.get("无货兜底售价_USD每M"))
            if _park is None or _park <= 0:
                _park = 19.9
            _need = _f(_row_pol.get("无货最小可买万基纳"))
            if _need is None or _need < 0:
                _need = 10000.0
            _avail = _f(_cost.get("avail_wan"))
            #   「够不够」沿用 dd373_only 的同一口径：avail 拿不到（旧快照/解析失败）⇒
            #   按有货处理 —— 宁可正常跟价，也不要把一个真有货的区误挂成 $19.9。
            _enough = bool(_cost_ok) and (_avail is None or _avail >= _need)
            rec["无货兜底售价_USD每M"] = _park
            rec["DD373可买_万基纳"] = _avail
            if not _cost_ok:
                rec["成本兜底_说明"] = ("本轮无 DD373 成本（%s）⇒ 触发货源闸，挂保护价"
                                        % (_cost.get("basis") or "未采到"))
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
            if not _enough:
                # ── 货源闸命中：DD373 买不到货（无报价 / 不足 1 亿）⇒ 挂保护价，不抓 G2G ──
                # 老板口径「没挂单的统一挂 19.9」= 严格统一，故保护价只看
                # 「无货兜底售价_USD每M」，不走成本兜底、也不受利润率下限影响（见下方闸门）。
                _tgt_from_base = _park
                _base_src = "无货兜底"
                rec["定价来源级别"] = 3
                rec["基准价"] = None
                rec["基准来源"] = "无货兜底"
                if not _cost_ok:
                    _why = "DD373 无有效报价（%s）" % (_cost.get("basis") or "该区无挂单")
                else:
                    _why = ("DD373 可买量 %.0f 万基纳 < %.0f（不足 1 亿）"
                            % (_avail or 0.0, _need))
                rec["无货兜底说明"] = ("%s ⇒ 本轮统一挂 $%.2f/M 高价保护，"
                                       "等该区有货（≥%.0f 万基纳）下一轮自动跟回"
                                       % (_why, _park, _need))
                _base_detail = rec["无货兜底说明"]
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
                if _cb.get("base") is not None:
                    _issrc = (_cb.get("src") == "cheapold")
                    _base_src0 = "G2G·cheapold" if _issrc else "G2G·推荐前二"
                    _who_txt = ("cheapold 卖家" if _issrc
                                else "推荐前二较低者(%s)" % _cb.get("who"))
                    _base0 = _cb["base"]
                    # 🔴 2026-10-09（老板定案）· **无 cheapold 卖家 ⇒ 按成本保 30% 利润**
                    #   老板原话「该区无 cheapold 卖家，则保持30%的利润」，并已明确两点：
                    #     ① 利润公式 = **售价 = 成本 × 1.30**（成本加价 30%）；
                    #     ② 与「推荐前二」是**替换**关系 —— 该区从此与 G2G 竞品价脱钩。
                    #   ⇒ 不再取 G2G 推荐前二价，目标 = 本区 DD373 成本 × 系数（**不下浮**）。
                    #   走到这里 _cost_ok 必为真（无成本 / 货不足的区已被上面「货源闸」拦掉），
                    #   仍留 _cost_ok 守卫：万一配置漂移，也不至于算出一个没有成本支撑的假价。
                    if not _issrc and _cost_ok and _cusd:
                        _nc = _f(_row_pol.get("无cheapold加价系数"))
                        if _nc is None or _nc <= 1.0:
                            _nc = 1.30
                        _cb_base = _cusd * _nc
                        # 看板「跟价基准」列口径 = **我方真正在跟的价** ⇒ 落成本价；
                        # G2G 给的那个推荐前二价单独存进「无cheapold基准」仅作留证。
                        rec["基准价_原竞品"] = _cb_base
                        rec["基准来源_原竞品"] = "成本×%.2f" % _nc
                        rec["基准价"] = _cb_base
                        rec["基准来源"] = "成本×%.2f" % _nc
                        _base_src = rec["基准来源"]
                        rec["定价来源级别"] = 2
                        rec["目标来自成本兜底"] = False
                        rec["无cheapold成本加价"] = _nc
                        rec["无cheapold基准"] = _base0
                        _tgt_from_base = _cb_base
                        _base_detail = ("该区无 cheapold 卖家（G2G 推荐前二较低者 $%.4f/M 不跟）"
                                        "⇒ 目标 = 本区 DD373 成本 $%.4f/M × %.2f"
                                        "（成本加价 %.0f%%，利润率 %.1f%%）"
                                        % (_base0, _cusd, _nc,
                                           (_nc - 1.0) * 100, (1.0 - 1.0 / _nc) * 100))
                    else:
                        rec["基准价_原竞品"] = _base0
                        rec["基准来源_原竞品"] = _base_src0
                        _cost_floor = False
                        if _cost_ok and _base0 < _cusd:
                            # ⛔ 成本兜底：竞品比我们的进货成本还低 → 不跟降，直接按成本价定价
                            _base0 = _cusd
                            _base_src = "%s→成本价" % _base_src0
                            _cost_floor = True
                            rec["成本兜底"] = ("竞品 $%.4f/M < 我方成本 $%.4f/M ⇒ 不再跟降，"
                                               "按成本价定价（不下浮）" % (_cb["base"], _cusd))
                        else:
                            _base_src = _base_src0
                        rec["基准价"] = _base0
                        rec["基准来源"] = _base_src
                        rec["定价来源级别"] = 1 if _issrc else 2
                        rec["目标来自成本兜底"] = bool(_cost_floor)
                        if _cost_floor:
                            # 老板口径：「按成本价来定价」—— 成本兜底时**不再下浮**
                            _tgt_from_base = _base0
                            _base_detail = ("G2G %s %s $%.4f/M < 成本 $%.4f/M → 直接按成本价定价"
                                            % (sv.get("大区") or "", _who_txt, _cb["base"], _cusd))
                        else:
                            _tgt_from_base = _base0 * _mult
                            _base_detail = ("G2G %s %s：$%.4f/M × (1−%.1f%%)"
                                            % (sv.get("大区") or "", _who_txt, _cb["base"],
                                               _disc * 100))
                else:
                    rec["G2G跟价错误"] = "该子服务器本轮 0 条有效报价"
        # ①''' 2026-10-08 老板定案（MapleStory Classic World）：**无脑跟 IGGM 的价 ×(1−10%)**，
        #      只保留 +15% 利润兜底。原口径「成本 ×(1+30%) 与 IGGM×(1−10%) 取低、15% 利润兜底」
        #      已被老板 2026-10-08 明确推翻：「取消 30% 利润上限，只无脑跟 IGGM 的价就行，
        #      利润兜底保留」。
        #      · 目标前端单价 = IGGM **真价**（已按该游戏折算系数还原）× (1 − 让价比例 10%)；
        #      · **无成本加价 / 无上限** —— 成本只作为**兜底线**参与；
        #      · 兜底在下面「利润率下限兜底（iggm_undercut 段）」统一做：
        #          目标 < 成本 ÷ (1−15%) = 成本 ÷ 0.85 ⇒ 抬到成本线。
        #        用户原话「若 IGGM 价格低于成本价格，不跟随，按最低 15% 利润率兜底，
        #        不再跟进」—— IGGM×0.9 必然 < IGGM，IGGM < 成本时目标一定跌破兜底线，
        #        被自动抬回 ⇒ 等价于「不跟随」，无需单独分支。
        #      · IGGM 抓不到 ⇒ 本轮不出目标价（**不回落任何别的口径**）。
        elif _row_mode == "iggm_undercut":
            _mode_used = "iggm_undercut"
            rec["定价模式"] = "iggm_undercut"
            _disc2 = _f(_row_pol.get("让价比例"))
            if _disc2 is None:
                _disc2 = 0.10
            rec["让价比例"] = _disc2
            # DD373 成本：本模式下**只作兜底参照**（不是定价基准），但仍完整落进快照
            _cost3 = _costs.get(sv.get("key")) or {}
            _cu3 = _f(_cost3.get("usd_per_m"))
            rec["DD373成本_USD每M"] = _cu3
            rec["DD373成本_元每万基纳"] = _cost3.get("cny_per_wan")
            rec["DD373可买"] = _cost3.get("stock")
            rec["DD373可买_万基纳"] = _f(_cost3.get("avail_wan"))
            rec["DD373挂单数"] = _cost3.get("n_items")
            rec["DD373游戏区"] = _cost3.get("dd_zone")
            rec["DD373依据"] = _cost3.get("basis")
            # 三源明细照旧采集展示（看板仍要 G2G/ELD/IGGM 三列 + 差距对比）
            if _ms and sv.get("key") in _ms_need:
                try:
                    _bv_ms, _bd_ms, _bdet_ms = _ms.resolve_base(sv, iggm_price=igp, apo=apo)
                    rec["多源明细"] = _bdet_ms
                    rec["竞品基准价"] = _bv_ms
                    rec["竞品基准来源"] = _bdet_ms.get("取谁") or "-"
                    rec["G2G_USD每M"] = _f(_bdet_ms.get("G2G"))
                except Exception as _e:            # noqa: BLE001
                    log("  [金币/多源] %s 三源解析失败：%r" % (sv.get("中文名"), _e))
            if igp:
                _tgt_from_base = igp * (1.0 - float(_disc2))
                _base_src = "IGGM"
                rec["基准价"] = igp
                rec["基准来源"] = "IGGM真价"
                rec["定价来源级别"] = 1
                _base_detail = ("IGGM 真价 $%s/%s × (1−%.0f%%)（无成本加价）"
                                % (fmt_money(per_100k(igp, _dm)), _ul, float(_disc2) * 100))
            else:
                rec["基准来源"] = ""
                rec["定价来源级别"] = None
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
                if rec.get("基准来源") == "无货兜底":
                    rec["目标前端每M_口径"] = (
                        "DD373 货源不足（无有效报价 / 不足 1 亿）→ 统一挂 $%.2f/M 高价保护"
                        "（等有货自动跟回）" % float(rec.get("无货兜底售价_USD每M") or 0))
                elif rec.get("无cheapold成本加价"):
                    # 2026-10-09：无 cheapold 卖家的区改走「成本 × 系数」，不再是推荐前二×下浮。
                    _nc_t = rec.get("无cheapold成本加价") or 1.30
                    rec["目标前端每M_口径"] = (
                        "该区无 cheapold 卖家（G2G 推荐前二 $%.4f/M 不跟）⇒ "
                        "目标 = **成本价** $%.4f/M × %.2f（成本加价 %.0f%%，利润率 %.1f%%）"
                        % (rec.get("无cheapold基准") or 0.0,
                           rec.get("DD373成本_USD每M") or 0.0, _nc_t,
                           (_nc_t - 1.0) * 100, (1.0 - 1.0 / _nc_t) * 100))
                elif rec.get("目标来自成本兜底"):
                    rec["目标前端每M_口径"] = (
                        "竞品 %s $%.4f/M 低于我方成本 $%.4f/M → 目标 = **成本价**（不下浮）"
                        % (rec.get("基准来源_原竞品") or "G2G",
                           rec.get("基准价_原竞品") or 0.0, rec.get("基准价") or 0.0))
                else:
                    rec["目标前端每M_口径"] = "%s $%.4f/M × (1 − %.1f%%)" % (
                        _base_src, rec.get("基准价") or 0.0, (_disc or 0.03) * 100)
            elif _mode_used == "dd373_only":
                if rec.get("定价来源级别") == 1:
                    rec["目标前端每M_口径"] = (
                        "DD373 进货成本 $%.4f/M × (1 + %.1f%%)"
                        % (rec.get("基准价") or 0.0, float(rec.get("加价比例") or 0) * 100))
                else:
                    rec["目标前端每M_口径"] = (
                        "DD373 无货（无报价/不足1亿）→ 统一挂 $%.2f/M（等有货自动跟回）"
                        % float(rec.get("无货兜底售价_USD每M") or 0))
            elif _mode_used == "iggm_undercut":
                rec["目标前端每M_口径"] = (
                    "IGGM 真价 $%.6f%s × (1 − %.0f%%)（无成本加价上限）"
                    % (rec.get("基准价") or 0.0, rec.get("展示单位") or "",
                       (_disc2 or 0.10) * 100))
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
        elif _mode_used == "iggm_undercut":
            # IGGM 抓不到 → **明确不退回旧口径**（也绝不拿 DD373 顶价）
            tgt_m = None
            rec["目标前端每M_口径"] = ("IGGM 无报价/抓取失败 → 本轮不出目标价"
                                       "（不回落旧口径）")
        else:
            # 退回旧口径（纯 IGGM × 让价系数）—— D4 走这条
            tgt_m = (igp * apo) if igp else None
            rec["目标前端每M_口径"] = "IGGM × 让价系数 %.4f（旧口径）" % apo
        # iggm_undercut 用自己的 让价比例（10%），别把全局的 2% 记到 MSCW 行上误导看板
        rec["让价系数"] = ((1.0 - float(_disc2)) if _mode_used == "iggm_undercut" else apo)
        rec["目标前端每M"] = tgt_m
        # ── 2026-10-09 利润率下限兜底（老板定案 · 仅 AION2 · g2g_cheapold）────────
        # 老板原话：「我发现也不能无脑跟 cheapold，有些跟了 cheapold，利润率非常低，
        #   你新增一个 20% 的利润率兜底吧，如果跟了 cheapold，利润率低于 20%，
        #   则强制调价到 20%」，并已确认：
        #     ① 20% = **平台口径利润率** (售价−成本)÷售价 = 20% ⇒ 售价 = 成本 ÷ 0.8；
        #     ② **成本兜底的那批（cheapold 价 < 我方成本，原按成本价保本 = 0%）也一起抬到 20%**。
        #   推导：(P−C)/P ≥ lim ⇒ P(1−lim) ≥ C ⇒ P ≥ C ÷ (1−lim)；
        #        lim=+0.20 ⇒ P ≥ C/0.80 = 1.25C（利润率正好 20%）；
        #        lim=−0.10 ⇒ P ≥ C/1.10（旧的「亏损下限 −10%」，公式同一支，本闸向下兼容）。
        #   ⚠ 2026-10-06 起本闸由「负下限（防亏）」升级为「正下限（保 20% 利润）」，
        #     所以原来的 `_lim < 0` 前置判断已去掉 —— 否则新的正下限根本不会生效。
        #   ⚠ 只在 g2g_cheapold 模式下生效：老板口径是「跟了 cheapold 才受这条约束」；
        #     切回 dd373_only / multisrc 时**不吃这条闸**（那些模式各有自己的加价比例，
        #     例如 dd373_only 成本×(1+7%) 的平台利润率只有 6.5%，若被 20% 闸拦下会
        #     凭空改变那个模式的价格 —— 绝不能让它悄悄串味）。
        #   ⚠ 无货兜底行（货源闸）不受本闸影响：兜底价由「无货兜底售价_USD每M」唯一决定
        #     （老板口径「没挂单的统一调为 19.9」）。
        if (tgt_m and gm == "AION2" and _mode_used == "g2g_cheapold"
                and rec.get("基准来源") != "无货兜底"):
            _cost2 = _costs.get(sv.get("key")) or {}
            _cu2 = _f(_cost2.get("usd_per_m"))
            _lim = _row_pol.get("利润率下限")
            if _lim is None:
                _lim = 0.20
            try:
                _lim = float(_lim)
            except (TypeError, ValueError):
                _lim = 0.20
            if _cu2 and _cu2 > 0 and abs(_lim) > 1e-9:
                _mg = (float(tgt_m) - _cu2) / float(tgt_m)
                rec["利润率_兜底前"] = round(_mg, 6)
                rec["利润率下限"] = _lim
                if _mg < _lim - 1e-9:
                    # P ≥ C ÷ (1−lim)：lim=0.20 ⇒ C÷0.80（1.25C）；lim=−0.10 ⇒ C÷1.10
                    _floor_price = _cu2 / (1.0 - _lim)
                    _pre_t = float(tgt_m)
                    tgt_m = _floor_price
                    rec["目标前端每M"] = tgt_m
                    rec["利润率下限前目标价"] = _pre_t
                    rec["利润率下限触发"] = (
                        "按 $%.4f/M 卖利润率 %.2f%% 低于下限 %.0f%% ⇒ 抬到 $%.4f/M"
                        "（= 成本 $%.4f ÷ %.2f）"
                        % (_pre_t, _mg * 100, _lim * 100, _floor_price, _cu2, 1.0 - _lim))
                    rec["目标前端每M_口径"] = (rec.get("目标前端每M_口径") or "") + \
                        "；随后被利润率下限 %.0f%% 兜底 → $%.4f/M" % (_lim * 100, _floor_price)
                    # 看板「跟价来源」列要能看出「这行的价被 20% 利润闸抬过」——
                    # 把标记并进「基准来源」，前端据此加一句红字提示（不改表结构）。
                    rec["基准来源"] = "%s｜利润下限%.0f%%" % (
                        rec.get("基准来源") or "-", _lim * 100)
        # ── 2026-10-08 利润率下限兜底（老板定案 · MSCW iggm_undercut 专用）─────────
        # 口径：利润率 = (售价 − 成本) ÷ 售价（同 AION2，**可为负**）。
        #   下限是**正数 +15%**：P(1−lim) ≥ C ⇒ 目标价 ≥ 成本 ÷ (1−lim) = 成本 ÷ 0.85。
        #   例：成本 $0.2707 → 最低售价 $0.3184（利润率正好 15%）；低于这条线就抬回来。
        # ⚠ 与上面 AION2 那段的区别：① 适用模式不同（本段只看 iggm_undercut，
        #   上面那段只看 g2g_cheapold）⇒ 两者**永远只有一段会执行**，互不影响；
        #   ② AION2 段的下限现在是**正数 +20%**（2026-10-09 起，原来 −10% 的亏损下限已升级）。
        # ⚠ 这正是用户口径「若 IGGM 价格低于成本价格，不跟随，按最低 15% 利润率兜底」
        #   的落地方式 —— 无需单独判断「IGGM 是否低于成本」，兜底线自动完成这件事
        #   （IGGM×0.9 一定 < IGGM；IGGM < 成本时目标必然跌破 成本÷0.85，被抬回）。
        if tgt_m and _mode_used == "iggm_undercut":
            _cost4 = _costs.get(sv.get("key")) or {}
            _cu4 = _f(_cost4.get("usd_per_m"))
            _lim2 = _row_pol.get("利润率下限")
            if _lim2 is None:
                _lim2 = 0.15
            try:
                _lim2 = float(_lim2)
            except (TypeError, ValueError):
                _lim2 = 0.15
            rec["利润率下限"] = _lim2
            if _cu4 and _cu4 > 0 and _lim2 > 0:
                _mg2 = (float(tgt_m) - _cu4) / float(tgt_m)
                rec["利润率_兜底前"] = round(_mg2, 6)
                if _mg2 < _lim2 - 1e-9:
                    _floor2 = _cu4 / (1.0 - _lim2)
                    _pre2 = float(tgt_m)
                    tgt_m = _floor2
                    rec["目标前端每M"] = tgt_m
                    rec["利润率下限前目标价"] = _pre2
                    rec["利润率下限触发"] = (
                        "按 $%.6f/%s 卖利润率 %.2f%% 低于下限 %.0f%% ⇒ 抬到 $%.6f/%s"
                        "（= 成本 $%.6f ÷ %.2f）"
                        % (_pre2, _ul, _mg2 * 100, _lim2 * 100, _floor2, _ul,
                           _cu4, 1.0 - _lim2))
                    rec["目标前端每M_口径"] = (rec.get("目标前端每M_口径") or "") + \
                        "；随后被利润率下限 %.0f%% 兜底 → $%.6f/%s" % (
                            _lim2 * 100, _floor2, _ul)
            else:
                rec["利润率下限_说明"] = ("本轮无 DD373 成本 ⇒ 只能按 IGGM × (1−%.0f%%) 定价，"
                                        "成本线兜底本轮不生效（下一轮有成本时自动恢复）"
                                        % ((_disc2 or 0.10) * 100))
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
        _div = cost_divisor_of(cfg, rl, gm)
        rec["成本除数"] = _div
        oup = _f(rec.get("我方前端每M"))
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
                rec["对照_IGGM总价"] = round(igp / (_k_row or 1.0) * _n, 4)   # 机房抓取口径
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
            #    2026-10-06 补：成本兜底 / 利润率下限两个闸触发时，文案要如实写出来，
            #    否则日志里仍显示「G2G × (1−3%)」，会让人以为没生效。
            if _mode_used == "g2g_cheapold":
                _lvl = rec.get("定价来源级别")
                _lbl = ("cheapold 卖家" if _lvl == 1
                        else ("本区 DD373 成本" if rec.get("无cheapold成本加价")
                              else "推荐前二较低者(%s)" % (rec.get("G2G_取价卖家") or "-")))
                # 2026-10-09 补：DD373 **货源闸**命中的区压根**没抓 G2G**（基准价 = None）。
                #   原来会落进下面那个 G2G 分支 ⇒ 说明写成「G2G 推荐前二较低者 $-/M × (1−1.0%)」，
                #   与真实口径（统一挂保护价）不符：目标明明是 $19.9，读起来却像闸门没生效。
                _park_note = ("｜%s" % (rec.get("无货兜底说明") or "")
                              if rec.get("基准来源") == "无货兜底" else "")
                if rec.get("基准来源") == "无货兜底":
                    _pre = ("目标 $%s/%s（⛔ 无货兜底：DD373 货源不足 ⇒ 统一挂 $%.2f/M 高价保护）"
                            "｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                               float(rec.get("无货兜底售价_USD每M") or 0),
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                elif rec.get("目标来自成本兜底"):
                    # 2026-10-09 补：这批（竞品 < 成本）也归 20% 利润闸管。
                    #   抬价后 tgt_m 不再是成本价（R4：$1.25 ≠ $1.00），
                    #   若照旧写「按成本价定价」，页面第一眼的价与句子就对不上了。
                    if rec.get("利润率下限触发"):
                        _cb_tail = ("，原定成本价 $%s/%s 利润率仅 %.2f%% ⇒ 被利润率下限 %.0f%% "
                                    "强制抬到 成本÷%.2f"
                                    % (fmt_money(per_100k(rec.get("利润率下限前目标价"), _dm)),
                                       _ul, (rec.get("利润率_兜底前") or 0) * 100,
                                       (rec.get("利润率下限") or 0.20) * 100,
                                       1.0 - (rec.get("利润率下限") or 0.20)))
                    else:
                        _cb_tail = " ⇒ 按成本价定价，不下浮"
                    _pre = ("目标 $%s/%s（⛔ 成本兜底：竞品 %s $%s/%s < 我方成本 $%s/%s"
                            "%s）｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul, _lbl,
                               fmt_money(per_100k(rec.get("基准价_原竞品"), _dm)), _ul,
                               fmt_money(per_100k(_cusd, _dm)), _ul, _cb_tail,
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                elif rec.get("利润率下限触发"):
                    # 🆕 2026-10-09：被 20% 利润闸抬过的行，tgt_m 已不是「基准 ×(1−下浮)」
                    #   的乘积（R7：cheapold $1.10 × 0.99 = $1.089，实际被抬到 $1.25）。
                    #   若沿用下面那句算式，页面第一眼看到的数字和算式对不上 ⇒ 显式写明
                    #   「原算得多少 → 为什么抬 → 抬到多少（= 成本÷(1−下限)）」。
                    _fl_lim = float(rec.get("利润率下限") or 0.20)
                    _pre = ("目标 $%s/%s（⛔ 利润率下限 %.0f%%：原算得 $%s/%s 利润率仅 %.2f%% "
                            "⇒ 强制抬到 成本÷%.2f）｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul, _fl_lim * 100,
                               fmt_money(per_100k(rec.get("利润率下限前目标价"), _dm)), _ul,
                               (rec.get("利润率_兜底前") or 0) * 100, 1.0 - _fl_lim,
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                elif rec.get("无cheapold成本加价"):
                    # 🆕 2026-10-09：该区无 cheapold 卖家 ⇒ 改按成本保 30% 利润定价
                    _nc_l = rec["无cheapold成本加价"]
                    _pre = ("目标 $%s/%s（🆕 无 cheapold 卖家：G2G 推荐前二 $%s/%s **不跟** "
                            "⇒ 按本区成本 $%s/%s × %.2f 定价，成本加价 %.0f%%、利润率 %.1f%%）"
                            "｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                               fmt_money(per_100k(rec.get("无cheapold基准"), _dm)), _ul,
                               fmt_money(per_100k(_cusd, _dm)), _ul, _nc_l,
                               (_nc_l - 1.0) * 100, (1.0 - 1.0 / _nc_l) * 100,
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                else:
                    _pre = ("目标 $%s/%s（G2G %s $%s/%s × (1−%.1f%%)）｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul, _lbl,
                               fmt_money(per_100k(rec.get("基准价"), _dm)), _ul,
                               (_disc or 0.03) * 100,
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                _gz = ("｜cheapold $%s｜推荐1 $%s(%s)｜推荐2 $%s(%s)｜卖家 %s 家"
                       "｜DD373成本 $%s/M"
                       % (fmt_money(rec.get("G2G_cheapold价")), fmt_money(rec.get("G2G_推荐1")),
                          rec.get("G2G_推荐1卖家") or "-", fmt_money(rec.get("G2G_推荐2")),
                          rec.get("G2G_推荐2卖家") or "-", rec.get("G2G_卖家数"),
                          fmt_money(rec.get("DD373成本_USD每M")) or "-"))
                if _park_note:
                    # 货源闸命中时 G2G 三列全是「-」（本轮没抓），换成 DD373 货源说明
                    _gz = _park_note
                if rec.get("利润率下限触发"):
                    _gz += "｜%s" % rec["利润率下限触发"]
                if rec["动作"] == "hold":
                    rec["说明"] = _pre + "（在 ±%.1f%% 持平区间内）→ 不动%s" % (_thr * 100, _gz)
                else:
                    rec["说明"] = (_pre + "→ 采购成本应改为 ￥%.6f/M"
                                          "（= 目标每M × 成本除数 %.4f）%s"
                                   % (rec["采购成本_新"], _div, _gz))
            # ── 2026-10-06：dd373_only 模式下把「说明」改写成「只跟 DD373」口径 ──
            if _mode_used == "dd373_only":
                _lvl = rec.get("定价来源级别")
                if _lvl == 1:
                    _pre = ("目标 $%s/%s（DD373 进货成本 $%s/%s × (1+%.1f%%)）"
                            "｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                               fmt_money(per_100k(rec.get("基准价"), _dm)), _ul,
                               float(rec.get("加价比例") or 0) * 100,
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                    _gz = ("｜DD373 %s 元/万基纳｜可买 %s 万基纳｜%s"
                           % (rec.get("DD373成本_元每万基纳"),
                              ("%.0f" % float(rec["DD373可买_万基纳"]))
                              if rec.get("DD373可买_万基纳") is not None else "-",
                              rec.get("DD373依据") or "-"))
                else:
                    _pre = ("目标 $%s/%s（⛔ 无货兜底：DD373 无报价/不足 1 亿 ⇒ 统一挂 $%.2f/M）"
                            "｜我方 $%s/%s（%+.2f%%）"
                            % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                               float(rec.get("无货兜底售价_USD每M") or 0),
                               fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                    _gz = "｜%s" % (rec.get("无货兜底说明") or "")
                if rec["动作"] == "hold":
                    rec["说明"] = _pre + "（在 ±%.1f%% 持平区间内）→ 不动%s" % (_thr * 100, _gz)
                else:
                    rec["说明"] = (_pre + "→ 采购成本应改为 ￥%.6f/M"
                                          "（= 目标每M × 成本除数 %.4f）%s"
                                   % (rec["采购成本_新"], _div, _gz))
            # ── 2026-10-08：iggm_undercut 模式下把「说明」改写成「跟 IGGM −10%」口径 ──
            #    触发利润率下限时如实写出来，否则日志里仍显示「IGGM × 0.9」，
            #    会让人以为兜底没生效。
            if _mode_used == "iggm_undercut":
                _pre = ("目标 $%s/%s（IGGM 真价 $%s/%s × (1−%.0f%%)，无成本加价）"
                        "｜我方 $%s/%s（%+.2f%%）"
                        % (fmt_money(per_100k(tgt_m, _dm)), _ul,
                           fmt_money(per_100k(rec.get("基准价"), _dm)), _ul,
                           (_disc2 or 0.10) * 100,
                           fmt_money(per_100k(oup, _dm)), _ul, _gap_pct))
                _gz = ""
                if rec.get("DD373成本_USD每M"):
                    _gz += ("｜DD373成本 $%s/%s（%s 元/万金｜可买 %s 万金）"
                            % (fmt_money(per_100k(rec.get("DD373成本_USD每M"), _dm)), _ul,
                               rec.get("DD373成本_元每万基纳"),
                               ("%.0f" % float(rec["DD373可买_万基纳"]))
                               if rec.get("DD373可买_万基纳") is not None else "-"))
                else:
                    _gz += "｜DD373 本轮无成本（成本线兜底本轮不生效）"
                if rec.get("利润率下限触发"):
                    _gz += "｜⛔ %s" % rec["利润率下限触发"]
                elif rec.get("DD373成本_USD每M"):
                    _mgx = ((float(tgt_m) - float(rec["DD373成本_USD每M"]))
                            / float(tgt_m))
                    _gz += "｜利润率 %.2f%%（下限 %.0f%%）" % (
                        _mgx * 100, (rec.get("利润率下限") or 0.15) * 100)
                if rec["动作"] == "hold":
                    rec["说明"] = _pre + "（在 ±%.1f%% 持平区间内）→ 不动%s" % (_thr * 100, _gz)
                else:
                    rec["说明"] = (_pre + "→ 采购成本应改为 ￥%.6f（每%s）"
                                          "（= 目标每%s × 成本除数 %.4f）%s"
                                   % (rec["采购成本_新"], _ul, _ul, _div, _gz))
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
            # 2026-10-08：改走 cost_divisor_for_game（按游戏取**该区行的利润率**）。
            # 无 game ⇒ DEFAULT_GAME（暗黑4，利润率 0.20）⇒ 仍 5.0540，与旧值一致。
            "成本除数": cost_divisor_for_game(cfg),
            "展示单位": int(PER_100K),
            # 多游戏（2026-10-01）：展示层按**每个游戏各自的**前台系数/成本除数/展示倍率取值，
            # 不要再用上面那三个「全局值」去套所有游戏（那是 D4 的口径）。
            "游戏参数": {g: {"前台系数": front_factor_of(cfg, g),
                             "成本除数": cost_divisor_for_game(cfg, g),
                             "展示倍率": display_mult_of(cfg, g),
                             "展示单位": unit_label(display_mult_of(cfg, g),
                                                    game_param(cfg, g).get("展示单位名")),
                             "IGGM折算系数": factor_of(cfg, g),
                             "IGGM金币页": game_param(cfg, g).get("IGGM金币页")}
                         for g in _games},
            # ⭐ 定价策略留证（2026-10-02）：看板/接口直接读这段显示当前口径，
            #   不用去猜「这次到底按什么算的」。模式可由 config.金币.定价策略.模式 切换。
            "定价策略": {
                # **按游戏**给，别只给 AION2 —— 暗黑4 必须是 None（默认口径）
                "按游戏": {g: p for g, p in _pol_by_game.items() if p},
                "AION2": _pol_by_game.get("AION2"),
                # 2026-10-08 多游戏：先把「每个游戏当前走什么模式」列全，
                # 再接原来的 AION2 单游戏说明（原文案一字不改，看板照旧读得懂）。
                "说明": (
                    ("【按游戏】"
                     + "；".join("%s = %s" % (g, (pp.get("模式") or "-"))
                                 for g, pp in sorted(_pol_by_game.items()) if pp)
                     + "。") if len([pp for pp in _pol_by_game.values() if pp]) > 1 else ""
                ) + (
                    "当前 AION2 走「**只跟 DD373 进货成本 × (1+加价%%)**」；DD373 无报价"
                         "或可买量不足 1 亿的区统一挂无货兜底价（默认 $19.9/M）；"
                         "G2G最低价/ELD最低价/IGGM 仅采集展示，**不参与定价**。"
                         "改 config.金币.定价策略.模式 即可切回 G2G cheapold 或三源比价。"
                         if _pricing_mode == "dd373_only" else
                         ("当前 AION2 走「G2G cheapold 跟价」；G2G/ELD/IGGM 继续采集监控并展示，"
                          "定价只取该子服务器的 cheapold ×(1−下浮%)；"
                          "**该区无 cheapold 卖家 ⇒ 改按本区成本 ×1.30 保 30% 利润**"
                          "（2026-10-09，不再跟推荐前二）；"
                          "**跟了 cheapold 但利润率 < 20% ⇒ 强制抬到 成本÷0.8（利润率 20%）**"
                          "（2026-10-09 新增；含成本兜底那批，货源闸除外）。"
                          "改 config.金币.定价策略.模式 即可切回 DD373 或三源比价。"
                          if _pricing_mode == "g2g_cheapold" else
                          ("当前 AION2 走「DD373 推荐价 + 加价%」；G2G/ELD/IGGM 继续采集监控并展示，"
                           "但不参与定价。旧策略（三源比价 multisrc）已归档，"
                           "改 config.金币.定价策略.模式 即可切回。"
                           if _pricing_mode == "dd373_markup" else "默认口径（纯 IGGM × 让价系数）")
                )),
                "可切换": ["dd373_only（只跟 DD373 进货成本 + 加价，2026-10-06 现行 · AION2）",
                           "iggm_undercut（无脑跟 IGGM ×(1−10%) + 15% 利润兜底，"
                           "2026-10-08 现行 · MSCW 冒险岛怀旧服国际服）",
                           "g2g_cheapold（G2G cheapold 跟价）",
                           "dd373_markup（DD373 推荐价加价 + 三级顺延）",
                           "multisrc（旧·三源比价）"],
                "按游戏覆盖": ("`金币.定价策略.按游戏.<游戏>` —— 命中就用那一份"
                               "（不再看顶层 适用游戏 名单），未命中回落到顶层单份逻辑。"
                               "多游戏可各走各的模式，互不干扰（MSCW=iggm_undercut，"
                               "AION2=顶层 dd373_only）。"),
            },
            "口径": "我方前端每M价 = IGGM 每M价 × (1 − 让价百分比)；"
                    "目标采购成本 = 目标每M价 × 成本除数；"
                    "成本除数 = 汇率 × (1−利润率) ÷ 前台系数"
                    "（前台每M价 = 后台b2c × 前台系数：D4 实测 1/0.95，Aion 2 实测 1.0，"
                    "MSCW 实测 1.0 且前台单位是 **K**）；"
                    "展示倍率按游戏取（D4 = 每 100000M，Aion 2 = 每 M，MSCW = 每 K）；"
                    "IGGM 折算系数按游戏取（D4/AION2 = 0.909090909 机房加价还原，MSCW = 1.0 无加价）",
            "多源基准": ({
                "启用": True,
                "参与定价": (_pricing_mode not in ("dd373_markup", "g2g_cheapold", "dd373_only")),
                "口径": ("⚠ 仅监控展示，**不参与定价**（当前策略 = 只跟 DD373 进货成本加价）"
                         if _pricing_mode == "dd373_only" else
                         ("⚠ 仅监控展示，**不参与定价**（当前策略 = G2G cheapold 跟价）"
                          if _pricing_mode == "g2g_cheapold" else
                          ("⚠ 仅监控展示，**不参与定价**（当前策略 = DD373 推荐价加价）"
                           if _pricing_mode == "dd373_markup" else
                           "基准 = min(G2G, ELD)，IGGM 更低则取 IGGM；"
                           "两站都没数据的区用同大区均价兜底；目标 = 基准 × (1−让价百分比)"))),
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
        import re as _re
        import sqlite3 as _sq
        _con = _sq.connect(a.dd373_db)
        _con.row_factory = _sq.Row

        def _av(_s):
            # 与 app.py 注入时同一套解析（gold_cost 只有文本型的「可买N万基纳」）
            _m = _re.search(r"可买\s*([0-9]+(?:\.[0-9]+)?)\s*万基纳", str(_s or ""))
            return float(_m.group(1)) if _m else None

        for _r in _con.execute(
                "SELECT key, ok, cny_per_wan, usd_per_m, n_items, dd_zone, basis, stock"
                " FROM gold_cost WHERE ts=(SELECT MAX(ts) FROM gold_cost)"):
            _costs[_r["key"]] = {"ok": _r["ok"], "cny_per_wan": _r["cny_per_wan"],
                                 "usd_per_m": _r["usd_per_m"], "n_items": _r["n_items"],
                                 "dd_zone": _r["dd_zone"], "basis": _r["basis"],
                                 "stock": _r["stock"], "avail_wan": _av(_r["stock"])}
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
        # 2026-10-06 dd373_only：把「为什么是这个价」打出来（第1级成本加价 / 第3级无货兜底）
        if it.get("定价模式") == "dd373_only":
            _lv = it.get("定价来源级别")
            if _lv == 1:
                print("      └ 第1级：DD373 成本 %s 元/万基纳（可买 %s 万基纳）× (1+%.1f%%)"
                      " → 目标前端 $%s/M"
                      % (it.get("DD373成本_元每万基纳"),
                         ("%.0f" % it["DD373可买_万基纳"])
                         if it.get("DD373可买_万基纳") is not None else "-",
                         float(it.get("加价比例") or 0) * 100,
                         "%.4f" % it["目标前端每M"] if it.get("目标前端每M") else "-"))
            else:
                print("      └ 第3级·无货兜底：%s" % (it.get("无货兜底说明") or ""))
        elif it.get("定价模式"):
            print("      └ 模式 %s ｜ 级别 %s ｜ 基准来源 %s"
                  % (it.get("定价模式"), it.get("定价来源级别"), it.get("基准来源")))
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=1)
        print("\n已存：%s" % a.out)
