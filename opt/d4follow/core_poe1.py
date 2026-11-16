# -*- coding: utf-8 -*-
"""流放之路 1（PoE1）神圣石专线 · DD373 成本 → 后台物品标价。

为什么单独一条专线（与 core_gold 同级别，不进 engine 的对照项评估）
------------------------------------------------------------------
engine.evaluate 的定价基数是 **IGGM 竞品价**，而本商品的口径是
**「DD373 挂单加权均价 ÷ (1−利润率)」**，没有 IGGM 对标、也不吃千岛成本。
硬塞进 对照项 还会连带 前端匹配 / 货架自检 / 折扣换算 三条链路，风险远大于收益。
所以按 core_gold 的做法做成「专线」：自己采集、自己算价、自己出工单，
但**调度、工单队列、执行器、日志、改价记录全部沿用 RPG 系统现成的那套**。

口径（用户 2026-11-16 定案 · 2026-11-16 合并进 RPG 时利润率改为 30%）
------------------------------------------------------------------
来源：https://www.dd373.com/s-mnh4dv-c-94vje2-n75hgf-n4p04e.html
  · 取一页 20 条挂单（接口按单价升序给的 30 条里取前 20 = 页面一页）
  · **跳过第 1 条**（最便宜那条多为钓鱼单，会把均价拉崩）
  · 剩 19 条：加权均价 = 总价 ÷ 总数量 = 成本价（￥/个）
售价：成本 ÷ (1 − 利润率)，再 ÷ 汇率换成后台的美元口径
      —— 与金币链路同一个公式：b2c($) = 成本(￥) ÷ (1−利润率) ÷ 汇率
后台：gid=157 / aid=18858 / cid=76
  · 38588451 Divine Orb               = P
  · 71488529 Divine Orb(20+1 Free)    = **20 × P**（用户强调：搞错会亏钱）

⚠ gid 157 = 流放之路 1，与 PoE2（gid 552）是两套独立商品，本模块不复用 PoE2 任何配置。
"""

import datetime as dt
import json
import os
import re
import time
import urllib.parse
import urllib.request

GAME = "流放之路1"
SECTION = "POE1定价"
STATE_FILE = "poe1_state.json"
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")

API_SHOP = "https://goods.dd373.com/Api/Goods/UserCenter/ApiGetShopList"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# DD373「流放之路（国际服）」—— 2026-11-16 实测的稳定标识
DD = {
    "GameId": "a3b786c4-31db-4857-8686-6a55dc95f6dd",          # 流放之路（国际服）
    "GameOtherId": ("14bb3f32-73d7-46b9-88d6-2443ded32523"
                    "_865b86e20a834011864f881dff692549"),       # POE1 _ 巫影(标准)
    "GameShopTypeId": "db288737-c4ff-48a8-8c6d-d06d8cd011d3",  # 神圣石
}

DEFAULTS = {
    "启用": True,
    "游戏": GAME,
    "利润率": 0.30,
    "汇率USDCNY": 6.65,
    "采样条数": 20,
    "跳过最低条数": 1,
    "最小条数": 5,
    "最大单轮变动": 0.35,
    "最小改价幅度": 0.002,
    "清缓存": True,
    "后台": {"gid": "157", "aid": "18858", "cid": "76"},
    "商品": [],
}


# --------------------------------------------------------------------- 配置
def _p(cfg):
    d = dict(DEFAULTS)
    d.update((cfg or {}).get(SECTION) or {})
    if not d.get("DD373"):
        d["DD373"] = dict(DD)
    return d


def enabled(cfg):
    return bool(_p(cfg).get("启用"))


def game_names(cfg):
    """给 app.track_games 用：让本专线进入 RPG 的周期调度。"""
    return [GAME] if enabled(cfg) else []


# --------------------------------------------------------------------- 取数
def quotes(cfg, log=print):
    """DD373 神圣石挂单（接口给 30 条，按单价升序）。异常一律抛错，绝不吞成空。"""
    p = _p(cfg)
    d = p["DD373"]
    url = "%s?%s" % (API_SHOP, urllib.parse.urlencode({
        "GameId": d["GameId"], "GameOtherId": d["GameOtherId"],
        "GameShopTypeId": d["GameShopTypeId"]}))
    last = None
    for attempt in (1, 2, 3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Accept-Encoding": "identity",
                "Referer": "https://www.dd373.com/"})
            raw = urllib.request.urlopen(req, timeout=25).read().decode("utf-8")
            if raw.lstrip()[:1] not in ("{", "["):
                raise RuntimeError("返回非 JSON（疑似风控滑块页）：%r" % raw[:80])
            j = json.loads(raw)
            if str(j.get("StatusCode")) != "0":
                raise RuntimeError("StatusCode=%s %s" % (j.get("StatusCode"),
                                                         j.get("StatusMsg")))
            st = j.get("StatusData") or {}
            if str(st.get("ResultCode")) != "0":
                raise RuntimeError("ResultCode=%s %s" % (st.get("ResultCode"),
                                                         st.get("ResultMsg")))
            rd = st.get("ResultData")
            if not isinstance(rd, list):
                raise RuntimeError("ResultData 不是数组")
            return rd
        except Exception as e:                       # noqa: BLE001
            last = e
            log("  [PoE1] DD373 第 %d 次取数失败：%r" % (attempt, e))
            time.sleep(2 * attempt)
    raise RuntimeError("DD373 取数连续失败：%r" % (last,))


def compute_cost(cfg, rows):
    """前 N 条 → 跳过最低 k 条 → 剩余按「数量加权」算均价（￥/个）。"""
    p = _p(cfg)
    n, skip = int(p["采样条数"]), int(p["跳过最低条数"])
    picked = []
    for x in (rows or [])[:n]:
        try:
            amt = float(x.get("amount") or 0)       # 该条挂单的个数
            price = float(x.get("price") or 0)      # 该条挂单总价（￥）
            sp = float(x.get("singleprice") or 0)   # 单价（￥/个），自校验用
        except (TypeError, ValueError):
            continue
        if amt <= 0 or price <= 0:
            continue
        picked.append({"amount": amt, "price": price, "sp": sp,
                       "title": x.get("title"), "shopno": x.get("shopno")})
    if len(picked) < int(p["最小条数"]):
        raise RuntimeError("有效挂单只有 %d 条（<%s），不写价"
                           % (len(picked), p["最小条数"]))
    used = picked[skip:]
    if len(used) < int(p["最小条数"]):
        raise RuntimeError("跳过 %d 条后只剩 %d 条，不写价" % (skip, len(used)))
    q = sum(x["amount"] for x in used)
    pz = sum(x["price"] for x in used)
    if q <= 0:
        raise RuntimeError("总数量为 0，不写价")
    dev = 0.0
    for x in used:
        if x["sp"] > 0:
            dev = max(dev, abs(x["price"] / x["amount"] - x["sp"]) / x["sp"])
    return {"cost_rmb": pz / q, "总数量": q, "总价": pz, "用条数": len(used),
            "跳过": skip, "自校验最大偏差": round(dev, 6),
            "样本": [{"title": x["title"], "amount": x["amount"], "price": x["price"]}
                     for x in used[:3] + used[-2:]]}


# --------------------------------------------------------------------- 状态
def state_path():
    return os.path.join(DATA, STATE_FILE)


def load_state():
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(d):
    try:
        os.makedirs(DATA, exist_ok=True)
        tmp = state_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, state_path())
    except OSError:
        pass


# --------------------------------------------------------------------- 算价
def price_targets(cfg, cost_rmb):
    p = _p(cfg)
    rate = 1.0 - float(p["利润率"])
    fx = float(p["汇率USDCNY"])
    base = round(cost_rmb / rate / fx, 5)
    out = {}
    for it in p.get("商品") or []:
        out[str(it["id"])] = round(base * float(it.get("倍数") or 1), 5)
    return base, out


def build_plan(cfg, log=print, known=None, need_retry=False):
    """采成本 + 算目标价 + 判定动作。任何闸门不过都**抛错**（调用方决定 hold）。

    need_retry=True：上一张 PoE1 工单没确认成功（执行器没跑完 / 写失败 / 结果待核实）
    ⇒ 本轮无视「最小改价幅度」重新出单，避免价格卡在旧值上永远不动。
    """
    p = _p(cfg)
    st = known if isinstance(known, dict) else load_state()
    rows = quotes(cfg, log=log)
    log("  [PoE1] DD373 返回 %d 条挂单" % len(rows))
    info = compute_cost(cfg, rows)
    cost = info["cost_rmb"]
    log("  [PoE1] 成本口径：前 %d 条跳过 %d 条 → 用 %d 条，总数量 %g 个 / 总价 ￥%.2f"
        " → 均价 ￥%.5f/个"
        % (int(p["采样条数"]), info["跳过"], info["用条数"],
           info["总数量"], info["总价"], cost))
    if not (0.05 <= cost <= 200):
        raise RuntimeError("成本 ￥%.4f 不在合理区间（0.05~200），疑似口径漂移" % cost)

    last_cost = st.get("cost_rmb")
    if last_cost:
        dev = abs(cost / float(last_cost) - 1)
        if dev > float(p["最大单轮变动"]):
            blocked = int(st.get("blocked") or 0) + 1
            st["blocked"] = blocked
            save_state(st)
            msg = ("成本相对上次 ￥%.5f 偏离 %.1f%% > %.0f%%"
                   % (float(last_cost), dev * 100, float(p["最大单轮变动"]) * 100))
            if blocked >= 4:
                log("  [PoE1] ⚠ %s；已连续 %d 轮 → 按新成本执行（请人工扫一眼 DD373）"
                    % (msg, blocked))
                st["blocked"] = 0
            else:
                raise RuntimeError(msg + "，本轮不改价（第 %d 次；连续 4 次后自动放行）"
                                   % blocked)
        else:
            log("  [PoE1] 成本相对上次 ￥%.5f 变动 %.2f%%（闸门 %.0f%% 内）"
                % (float(last_cost), dev * 100, float(p["最大单轮变动"]) * 100))
            if st.get("blocked"):
                st["blocked"] = 0

    base, targets = price_targets(cfg, cost)
    log("  [PoE1] 售价：Divine Orb = $%.5f（￥%.5f ÷ %.2f ÷ %.2f）"
        % (base, cost, 1 - float(p["利润率"]), float(p["汇率USDCNY"])))

    items, written = [], {}
    old_map = st.get("targets") or {}
    # 20 倍不变量：两个商品必须严格 20 倍。历史记录里破了就无条件重写。
    _ids = [str(it["id"]) for it in (p.get("商品") or [])]
    inv_ok = True
    if len(_ids) >= 2 and old_map.get(_ids[0]) and old_map.get(_ids[1]):
        try:
            inv_ok = abs(float(old_map[_ids[1]]) - 20 * float(old_map[_ids[0]])) <= 1e-4
        except (TypeError, ValueError):
            inv_ok = True
    if not inv_ok:
        log("  [PoE1] ⚠ 记录里的 20 倍关系已不成立（%s / %s）→ 本轮强制重写"
            % (old_map.get(_ids[0]), old_map.get(_ids[1])))
    min_step = float(p["最小改价幅度"])

    for it in p.get("商品") or []:
        rid = str(it["id"])
        want = targets[rid]
        old = old_map.get(rid)
        pct = None
        if old:
            try:
                pct = abs(want / float(old) - 1)
            except (TypeError, ValueError, ZeroDivisionError):
                pct = None
        if old and pct is not None and pct < 1e-9 and not need_retry and inv_ok:
            act, why = "保持", "已是目标价"
        elif (old and pct is not None and pct <= min_step
              and not need_retry and inv_ok):
            act, why = "保持", ("变动 %.3f%% ≤ %.1f%%" % (pct * 100, min_step * 100))
        else:
            act = "改价"
            why = ("首次定价" if not old else "变动 %.2f%%" % ((pct or 0) * 100))
            if need_retry:
                why += "（上单未确认，本轮重出）"
        log("  [PoE1] %-24s $%s → $%.5f ｜ %s（%s）"
            % (it.get("名称"), old if old else "—", want, act, why))
        items.append({"id": rid, "key": it.get("key") or ("POE1_" + rid),
                      "title": it.get("名称") or rid, "倍数": it.get("倍数") or 1,
                      "gid": str(p["后台"]["gid"]), "aid": str(p["后台"]["aid"]),
                      "cid": str(p["后台"]["cid"]),
                      "old": old, "new": want, "动作": act, "原因": why})
        written[rid] = want

    return {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "游戏": [GAME],
        "成本_元每个": round(cost, 5), "DD373_挂单数": len(rows),
        "总数量": info["总数量"], "总价": info["总价"],
        "用条数": info["用条数"], "跳过条数": info["跳过"],
        "自校验最大偏差": info["自校验最大偏差"],
        "利润率": float(p["利润率"]), "汇率USDCNY": float(p["汇率USDCNY"]),
        "倍数关系": "×20", "样本": info["样本"],
        "items": items,
        "targets": written,
        "next_state": {"ts": dt.datetime.now().isoformat(timespec="seconds"),
                       "cost_rmb": round(cost, 6), "base_usd": base,
                       "targets": written, "blocked": 0},
    }
