# -*- coding: utf-8 -*-
"""Dark and Darker 金币 —— 与 IGGM 真价持平，自动写后台标价

2026-10-29 第二版（用户改口径）
------------------------------
第一版是「订单利润率反推」（抓发货记录推成本、让利润率落在 25%~30%）。
同日用户改成：**金币价格直接跟 IGGM 真价持平即可，不再从后台抓订单利润。**
所以本版只做一件事：把后台 Gold 标价写成 IGGM 真价，一步到位，不算利润率。

口径
----
IGGM 真价 = `iggm_price` 表里 `goods_no='G:DND_MS'` 的最新 `price_usd`。
  · 该字段入库前已按 `iggm.多游戏.Dark and Darker.竞品价折算系数`（0.909 = 1/1.1）
    折成「客户实付价」；`raw_usd`（0.129）是机房 IP 打页面看到的价格，不是真价。
后台标价 = IGGM 真价 ÷ (后台折扣 ÷ 100)。当前 Gold 折扣 100 ⇒ 两者直接相等。

与 engine 的关系
----------------
本商品在 config 里 `跟价=false`（= 只展示），且 `engine.autopriced_keys(cfg)`
把它的改价权让给本模块 —— engine 永远不会给它出价，两边不打架。
IGGM 价照旧由 `task_collect` 采集入库；本模块只读库、不自己抓站（避免撞 CF 风控）。

护栏
----
1) 已在目标价（偏离 ≤ 最大偏离百分比，默认 0.5%）→ 不写；
2) 单轮变动上限 ±30%（防数据错配把价打穿）；
3) IGGM 数据超过 `数据最长时效小时`（默认 12）没更新 → 不写，只告警；
4) 后台读不到 / 写失败 / 读回不一致 → hold，不猜、不用旧价硬凑。
"""

import json
import os
import sqlite3
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "data", "iggm_follow.db")
BASE = "https://order.p2pah.cn"

DEFAULT = {
    "启用": True,
    "商品key": "DND_GOLD",
    "p2pah": {"gid": "588", "aid": "15529"},
    "IGGM金币goods_no": "G:DND_MS",
    "让价百分比": 0.0,
    "最大偏离百分比": 0.5,
    "单轮最大变动": 0.30,
    "数据最长时效小时": 12,
}


def params_of(cfg):
    blk = (cfg.get("金币固定跟价") or {}).get("Dark and Darker") or {}
    out = dict(DEFAULT)
    out.update({k: v for k, v in blk.items() if not str(k).startswith("_")})
    return out


# --------------------------------------------------------------- 存储
def _db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS dnd_gold_follow(
        ts TEXT, action TEXT, iggm_price REAL, iggm_ts TEXT, iggm_age_h REAL,
        cur_price REAL, target_price REAL, new_price REAL, dev_pct REAL,
        ok INTEGER, msg TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS dnd_gold_write(
        ts TEXT PRIMARY KEY, price_old REAL, price_new REAL, operator TEXT)""")
    conn.commit()
    return conn


def record(conn, d):
    conn.execute(
        "INSERT INTO dnd_gold_follow(ts, action, iggm_price, iggm_ts, iggm_age_h,"
        " cur_price, target_price, new_price, dev_pct, ok, msg)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (time.strftime("%Y-%m-%dT%H:%M:%S"), d.get("action"), d.get("iggm_price"),
         d.get("iggm_ts"), d.get("iggm_age_h"), d.get("cur_price"),
         d.get("target_price"), d.get("new_price"), d.get("dev_pct"),
         1 if d.get("ok") else 0, d.get("msg")))
    conn.commit()


def record_write(conn, old, new):
    conn.execute("INSERT OR REPLACE INTO dnd_gold_write(ts, price_old, price_new, operator)"
                 " VALUES(?,?,?,?)",
                 (time.strftime("%Y-%m-%dT%H:%M:%S"), old, new, "dnd_gold_margin.py"))
    conn.commit()


def record_display(conn, key, d, cur_price, cfg):
    """写一条 decisions 台账 —— 控制台「道具监控」的说明列直接可见。只 INSERT。"""
    try:
        conn.execute(
            "INSERT INTO decisions(ts,key,title,action,iggm_old,iggm_new,ours_old,"
            "ours_new,target_usd,cost_usd,margin_old,margin_new,mode,applied,reason,"
            "装量,suggest) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), key,
             "Dark and Darker · Main Server · Gold（每 1 K）",
             d.get("action") or "hold", d.get("iggm_price"), d.get("iggm_price"),
             cur_price, d.get("new_price"), d.get("target_price"), None,
             None, None, ((cfg.get("跟价") or {}).get("模式") or "AUTO"),
             1 if d.get("action") in ("up", "down") and d.get("ok") else 0,
             "IGGM持平｜%s" % (d.get("msg") or ""), 1, None))
        conn.commit()
    except Exception:
        pass


# --------------------------------------------------------------- 读 IGGM 价
def iggm_price_of(conn, p):
    """库里最新的 IGGM 金币真价 → (price, ts, age_hours)"""
    no = str(p.get("IGGM金币goods_no") or "G:DND_MS")
    row = conn.execute(
        "SELECT price_usd, ts FROM iggm_price WHERE goods_no=? AND price_usd>0"
        " ORDER BY rowid DESC LIMIT 1", (no,)).fetchone()
    if not row or not row[0]:
        return None, None, None
    try:
        age = (time.time() - time.mktime(
            time.strptime(row[1][:19], "%Y-%m-%dT%H:%M:%S"))) / 3600.0
    except Exception:
        age = None
    return float(row[0]), row[1], age


# --------------------------------------------------------------- 计算
def compute(cfg, cur_price, disc, iggm, iggm_ts, age_h, p):
    """返回判定 dict。target/new 都是**标价**口径（= 后台「$每个价格」）。"""
    d = {"action": "hold", "cur_price": cur_price, "iggm_price": iggm,
         "iggm_ts": iggm_ts,
         "iggm_age_h": None if age_h is None else round(age_h, 2), "ok": False}

    if not iggm or iggm <= 0:
        d["msg"] = "库里没有 IGGM 金币价，保持不动"
        return d
    if age_h is not None and age_h > float(p.get("数据最长时效小时") or 12):
        d["msg"] = ("IGGM 金币价已 %.1f 小时没更新（阈值 %s h），不拿陈价调价"
                    % (age_h, p.get("数据最长时效小时")))
        return d
    if not cur_price or cur_price <= 0:
        d["msg"] = "读不到后台 Gold 标价，保持不动"
        return d

    gap = float(p.get("让价百分比") or 0.0)
    _disc = float(disc or 1.0) or 1.0
    target = iggm * (1.0 - gap / 100.0) / _disc
    d["target_price"] = round(target, 6)

    dev = (cur_price - target) / target
    d["dev_pct"] = round(dev * 100, 3)
    if abs(dev) <= float(p.get("最大偏离百分比") or 0.5) / 100.0:
        d["ok"] = True
        d["msg"] = "现标价 $%.5f 与 IGGM 真价折算后的 $%.5f 差 %+.2f%%，已持平" % (
            cur_price, target, dev * 100)
        return d

    cap = float(p.get("单轮最大变动") or 0.30)
    new = round(max(cur_price * (1 - cap), min(cur_price * (1 + cap), target)), 5)
    if abs(new - cur_price) / cur_price < 0.002:
        d["ok"] = True
        d["msg"] = "本轮变动过小（<0.2%），跳过"
        return d
    d.update({"action": "down" if new < cur_price else "up", "new_price": new,
              "msg": "IGGM 真价 $%.5f（%s，%.1f 小时前）→ 目标标价 $%.5f；"
                     "现标价 $%.5f 偏离 %+.2f%%，改为 $%.5f"
                     % (iggm, iggm_ts, age_h or 0, target, cur_price,
                        dev * 100, new)})
    return d


# --------------------------------------------------------------- 清缓存 / 前台
def clear_cache(cli, log=print):
    """真正推前台的清缓存：POST /admin/setting/clearcachepost.html（「清除全部」）。
    实测回执里出现「缓存已更新」；前台 5~15 分钟才生效。"""
    for method in ("POST", "GET"):
        try:
            if method == "POST":
                raw = cli.request("/admin/setting/clearcachepost.html", data=b"",
                                  method="POST", referer="/admin/setting/clearcache.html")
            else:
                raw = cli.request("/admin/setting/clearcachepost.html",
                                  referer="/admin/setting/clearcache.html")
        except Exception as e:
            log("  [缓存] %s 失败：%r" % (method, e))
            continue
        txt = raw or ""
        if ("缓存已更新" in txt) or ("已更新" in txt) or ("成功" in txt):
            log("  [缓存] 已清除（%s，回执命中关键词）" % method)
            return True
        log("  [缓存] %s 返回 %d 字节，未见「缓存已更新」回执" % (method, len(txt)))
    return False


def front_price(cfg):
    """前台金币真实挂牌价（美元/单位），读 /ajax/goods"""
    import core_front
    g = ((cfg.get("iggm") or {}).get("多游戏") or {}).get("Dark and Darker") or {}
    game_id = str(g.get("前台Game_id") or "589")
    cid = str(g.get("前台金币cid") or "1507")
    top = str(g.get("前台金币top_cid") or "1")
    aid = ""
    for z in (g.get("服务区") or []):
        aid = str(z.get("前台金币aid") or z.get("前台aid") or "")
        break
    try:
        lst = core_front.ajax_goods(
            cfg, game_id, aid, cid, top_cid=top,
            referer="https://www.mmoexp.com/Dark-And-Darker/Gold.html")
    except Exception:
        return None
    for x in lst:
        try:
            v = float(x.get("unit_price"))
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return None


# --------------------------------------------------------------- 执行
def run(cfg, apply=False, log=print):
    from core_p2pah import P2PAHClient

    p = params_of(cfg)
    key = str(p.get("商品key") or "DND_GOLD")
    if not p.get("启用"):
        log("  [金币持平] 已停用（config.金币固定跟价.Dark and Darker.启用 = false）")
        return {"ok": False, "msg": "disabled"}

    conn = _db()
    cli = P2PAHClient(cfg, log=log)
    gid = str((p.get("p2pah") or {}).get("gid") or cli.gid_of(key))
    aid = str((p.get("p2pah") or {}).get("aid") or "")
    html = cli.request(cli.list_url(gid=gid, aid=aid),
                       headers={"Accept": "text/html,*/*;q=0.8"})
    cur = next((r for r in cli.parse_items(html)
                if str(r.get("id")) in cli.ids_of(key)), None)
    if not cur:
        log("  [金币持平] 后台读不到 %s 的行（ids=%s）" % (key, cli.ids_of(key)))
        conn.close()
        return {"ok": False, "msg": "no_backend_row"}
    cur_price = float(cur.get("unit_price") or 0)
    disc = float(cur.get("discount") or 100) / 100.0
    log("  [后台] %s 现标价 $%.5f（折扣 %s）" % (key, cur_price, cur.get("discount")))

    iggm, iggm_ts, age_h = iggm_price_of(conn, p)
    log("  [IGGM] 真价 $%s（%s，%s 小时前）"
        % ("-" if iggm is None else "%.5f" % iggm, iggm_ts,
           "-" if age_h is None else "%.1f" % age_h))

    d = compute(cfg, cur_price, disc, iggm, iggm_ts, age_h, p)
    log("  [判定] %s | %s" % (d.get("action"), d.get("msg")))

    if d.get("action") not in ("up", "down"):
        record(conn, d)
        if apply:
            record_display(conn, key, d, cur_price, cfg)
        conn.close()
        return d

    if not apply:
        log("  [DRY-RUN] 会提交 unit_price=%s（id=%s gid=%s）"
            % (d["new_price"], cli.ids_of(key), gid))
        record(conn, dict(d, msg="DRY-RUN: " + str(d.get("msg"))))
        conn.close()
        return d

    res = cli.set_price_by_key(key, d["new_price"], gid=gid, min_qty=0)
    log("  [写后台] ok=%s msg=%s" % (res.get("ok"), res.get("msg")))
    if not res.get("ok"):
        d.update({"ok": False, "msg": "写后台失败：%s" % res.get("msg")})
        record(conn, d)
        conn.close()
        return d

    record_write(conn, cur_price, d["new_price"])

    try:
        html2 = cli.request(cli.list_url(gid=gid, aid=aid),
                            headers={"Accept": "text/html,*/*;q=0.8"})
        back = next((r for r in cli.parse_items(html2)
                     if str(r.get("id")) in cli.ids_of(key)), None)
        read_back = float(back.get("unit_price") or 0) if back else None
    except Exception:
        read_back = None
    d["read_back"] = read_back
    ok = read_back is not None and abs(read_back - d["new_price"]) < 1e-6
    log("  [读回] 后台现为 $%s（提交 $%s）→ %s"
        % (read_back, d["new_price"], "一致" if ok else "不一致"))

    try:
        clear_cache(cli, log=log)
    except Exception as e:
        log("  [缓存] 清理失败（不影响已写入的标价）：%r" % e)

    fp = front_price(cfg)
    d["front_after"] = fp
    log("  [前台] 改价后挂牌 $%s（目标 $%s）→ %s"
        % ("-" if fp is None else "%.5f" % fp, d["new_price"],
           "已生效" if (fp and abs(fp - d["new_price"]) / d["new_price"] < 0.01)
           else "尚未生效（正常，5~15 分钟）"))

    d["ok"] = bool(ok)
    if not ok:
        d["msg"] = (d.get("msg") or "") + " | 读回不一致"
    record(conn, d)
    record_display(conn, key, d, d["new_price"], cfg)
    conn.close()
    return d
