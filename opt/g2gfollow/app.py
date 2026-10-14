# -*- coding: utf-8 -*-
"""G2G 金币改价系统（AION2 Kinah）· 独立服务

独立于 d4follow：目录 /opt/g2gfollow、进程 g2gfollow.service、端口 8903、
SQLite data/g2gfollow.db。运行时**不读也不写** d4follow 的任何文件。

铁律（写入侧）
--------------
    ① 采集只出 dry-run 工单，绝不碰价格；
    ② 工单要逐行人工放行（released=1）才可能被执行；
    ③ 执行默认 dry；真写必须显式 confirm=true；
    ④ 每条写完都回读校验，校验不过的进流水标红。

Token：主通道是保活器用 ssh 把 var/token.json 推上来（不开公网写端点）；
      POST /api/token 只是登录后的人工排障入口。
"""
import csv
import io
import json
import os
import sys
import threading
import time

from flask import Flask, Response, jsonify, render_template, request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import core_self                                    # noqa: E402
import pricing                                      # noqa: E402
import store                                        # noqa: E402
from vendor import core_dd373_cost                  # noqa: E402
from vendor import core_g2g                         # noqa: E402

with io.open(os.path.join(HERE, "config.json"), encoding="utf-8") as _f:
    CFG = json.load(_f)

TOKEN_FILE = os.path.join(HERE, CFG["g2g"]["token_file"])
SELLER_ID = CFG["g2g"]["seller_id"]

app = Flask(__name__, template_folder=os.path.join(HERE, "templates"))
app.config["JSON_AS_ASCII"] = False

JOB = {"running": False, "phase": "", "logs": [], "started": 0, "finished": 0,
       "ok": None, "summary": None}
_LOCK = threading.Lock()


def jlog(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    with _LOCK:
        JOB["logs"].append(line)
        JOB["logs"] = JOB["logs"][-400:]


# ─────────────────────────── 采集 ───────────────────────────

def _do_collect():
    try:
        JOB.update({"running": True, "phase": "读 token", "ok": None,
                    "summary": None, "started": time.time(), "logs": []})
        jlog("开始采集（只出建议单，不改任何价）")
        info = core_self.load_token(TOKEN_FILE)
        jlog("token 可用，剩余 %ss" % info["remaining"])

        JOB["phase"] = "抓 DD373 成本"
        _buy_wan = float(CFG["定价"].get("买满量_万基纳", 15000))
        _gate_wan = float(CFG["定价"].get("够量闸门_万基纳", _buy_wan))
        jlog("抓 DD373 成本中（每区回溯买满 %g 万基纳 = %g 亿基纳的订单簿，1~3 分钟）…"
             % (_buy_wan, _buy_wan / 10000.0))
        jlog("  够量闸门 = %g 万基纳（= %g 亿）；不足的区改按条数吃满 %d 条；"
             "挂单 1~%d 条走 $%s/M，0 条走 $%s/M"
             % (_gate_wan, _gate_wan / 10000.0,
                int(CFG["定价"].get("条数下限", 10)),
                int(CFG["定价"].get("条数下限", 10)) - 1,
                CFG["定价"].get("条数不足售价_usd_per_m", 12.99),
                CFG["定价"]["闸门价_usd_per_m"]))
        servers = CFG["服务区"]
        rate = float(CFG["汇率"]["USDCNY"])
        # 只传一个游戏的服务区即可：本系统的 config 里就是 AION2 那 86 区，
        # 不需要（也不该依赖）d4follow 后来加的按游戏分发参数 game=，
        # 保证 vendor 快照与仓库基线版的函数签名严格一致。
        costs = core_dd373_cost.fetch_costs(
            servers, rate, log=jlog, gap=float(CFG["运行"]["DD373请求间隔秒"]),
            target_wan=_buy_wan, gate_wan=_gate_wan)
        store.save_snapshot("cost", {"rate": rate, "costs": costs})
        ok_n = sum(1 for v in costs.values() if v.get("ok"))
        jlog("成本完成：%d 区有报价 / 共 %d 区" % (ok_n, len(servers)))

        # ── 2026-10-13 新增：抓 G2G 竞品（cheapold）────────────────────────
        # 老板口径「两个站都跟踪 cheapold 的价格」⇒ 定价基准从「DD373 成本」换成
        # 「G2G 该子服务器的 cheapold 价」，DD373 成本退为**地板/天花板**的参照。
        # 走的是 d4follow 同一份 core_g2g（纯 urllib、只读公开搜索接口、无需登录），
        # 每区一次请求（86 区 ≈ 1~2 分钟）；抓不到的区不编数，回退「成本÷(1−无cheapold利润率)」。
        JOB["phase"] = "抓 G2G 竞品价"
        _cn = str(CFG["定价"].get("cheapold卖家") or "cheapold")
        jlog("抓 G2G 各子服务器竞品价中（找卖家 %s；每区一次只读搜索请求）…" % _cn)
        cb_map, cb_err = {}, []
        for sv in servers:
            _ds = str(sv.get("g2g_dataset") or "").strip()
            if not _ds:
                continue
            try:
                cb_map[sv["key"]] = core_g2g.cheapold_base(
                    _ds, sv.get("大区") or "", name=_cn, log=None)
            except Exception as e:                  # noqa: BLE001
                cb_map[sv["key"]] = {"base": None, "src": None, "error": repr(e)[:200]}
                cb_err.append(sv.get("中文名") or sv.get("key"))
        store.save_snapshot("cheapold", cb_map)
        _nch = sum(1 for v in cb_map.values()
                   if (v.get("cheapold") is not None))
        _nbase = sum(1 for v in cb_map.values() if (v.get("base") is not None))
        jlog("竞品完成：%d 区抓到报价（其中 %d 区有卖家 %s）/ 共 %d 区"
             % (_nbase, _nch, _cn, len(servers)))
        if cb_err:
            jlog("  ⚠ 以下区抓取失败（本轮回退「成本÷(1−无cheapold利润率)」）：%s"
                 % "、".join(cb_err[:10]))

        JOB["phase"] = "抓 G2G 货架"
        jlog("抓本店 G2G 货架 …")
        raw = core_self.fetch_my_offers(info["token"], seller_id=SELLER_ID, log=jlog)
        store.save_snapshot("offers", raw)
        offers = [r for r in (core_self.parse_offer(o) for o in raw) if r]
        jlog("货架 %d 条，其中 Aion2 金币 %d 条" % (len(raw), len(offers)))

        JOB["phase"] = "算建议单"
        idx = pricing.build_cost_index(costs, servers)
        cb_idx = pricing.build_cheapold_index(cb_map, servers)
        rows = pricing.build_plan(offers, idx, CFG, cheapold_idx=cb_idx)
        ts = store.save_plan(rows)
        s = pricing.summarize(rows)
        store.save_snapshot("summary", s)
        jlog("建议单已生成（ts=%s）：%s" % (time.strftime("%H:%M:%S", time.localtime(ts)), s))
        JOB.update({"phase": "完成", "ok": True, "summary": s, "finished": time.time()})
    except core_self.TokenError as e:
        jlog("× token 不可用：%s" % e)
        jlog("  请确认本机保活器在跑，并把 var/token.json 推到服务器")
        JOB.update({"phase": "失败(token)", "ok": False, "finished": time.time()})
    except Exception as e:                          # noqa: BLE001
        import traceback
        jlog("× 采集失败：%r" % e)
        jlog(traceback.format_exc()[-1200:])
        JOB.update({"phase": "失败", "ok": False, "finished": time.time()})
    finally:
        JOB["running"] = False


# ─────────────────────────── 执行 ───────────────────────────

def _plan_row_to_dict(r):
    return {"offer_id": r["offer_id"], "区服组": r["zone_group"], "服务区": r["server"],
            "阵营": r["side"], "标题": r["title"], "当前价": r["cur_price"],
            "目标价": r["target"], "动作": r["action"], "定价方式": r["mode"]}


def _do_execute(dry=True, operator="dashboard"):
    """对已放行的行执行写入。dry=True 只回放计划；真写逐条 PUT + 回读校验。"""
    rows = [r for r in store.released_rows()
            if r["action"] in ("上调", "下调") and r["target"] is not None]
    if not rows:
        return {"ok": True, "dry": dry, "total": 0, "note": "没有已放行且需变价的行"}

    if dry:
        return {"ok": True, "dry": True, "total": len(rows),
                "plan": [(_plan_row_to_dict(r), ) and {
                    "offer_id": r["offer_id"], "区服组": r["zone_group"],
                    "服务区": r["server"], "阵营": r["side"],
                    "旧价": r["cur_price"], "新价": r["target"]} for r in rows]}

    info = core_self.load_token(TOKEN_FILE)
    tok = info["token"]
    gap = float(CFG["运行"]["写价间隔秒"])
    results = []
    for r in rows:
        old, new = r["cur_price"], r["target"]
        ok, meta = core_self.update_price(tok, r["offer_id"], new,
                                          seller_id=SELLER_ID, log=jlog)
        results.append({"offer_id": r["offer_id"], "区服组": r["zone_group"],
                        "服务区": r["server"], "阵营": r["side"],
                        "旧价": old, "新价": new, "api_ok": ok, "detail": meta.get("detail")})
        jlog("%s %s %s → $%s : %s" % ("✓" if ok else "×", r["zone_group"],
                                      r["server"], new, meta.get("detail", "")[:120]))
        time.sleep(gap)

    # 写后读回：一次性拉货架整体校验（比逐条读省请求）。
    # ⚠ 2026-10-12 实测：G2G 的 offer 列表有**秒级索引延迟** —— 刚写完立刻拉，
    #   末尾几条可能仍是旧价。用「零净变化回写」探针实测（把当前价原样写回，
    #   只看 updated_at 何时刷新）：写入返回后第 6.5s 读仍是旧值、第 10.3s 才见刷新
    #   ⇒ 索引延迟约 6.5~10.3s。
    #   当天旧版「只等 6s 读一次」正好卡在延迟窗口里，把最后写的 3 条误判成
    #   「未通过」（17:24:21 那批：Zikel/Zemurru/Ulgorn，实际价格早已生效）。
    #   故这里改成「按总超时轮询」，别把「还没索引」当成「没写进去」。
    def _readback_prices():
        d = {}
        for o in core_self.fetch_my_offers(tok, seller_id=SELLER_ID, log=jlog):
            d[o.get("offer_id")] = (core_self._f(o.get("converted_unit_price"))
                                    or core_self._f(o.get("unit_price")))
        return d

    def _pending(rb):
        """还没反映新价的条数（读不到也算没反映）。"""
        return [r for r in results
                if not (rb.get(r["offer_id"]) is not None and r["新价"] is not None
                        and abs(rb[r["offer_id"]] - float(r["新价"])) < 0.005)]

    wait = float(CFG["运行"].get("回读等待秒", 6))
    total = float(CFG["运行"].get("回读总超时秒", 40))
    t0 = time.time()
    readback, still, n_try = {}, list(results), 0   # still 先当「全都还没反映」
    while True:
        n_try += 1
        time.sleep(wait if n_try == 1 else wait + 4)
        try:
            readback = _readback_prices()
        except Exception as e:                      # noqa: BLE001
            # 单次读失败**不能**直接判「全部未通过」：那会把一次网络抖动
            # 记成一整批「没写进去」。只记日志，留给总超时内的下一次重试。
            jlog("× 第 %d 次回读货架失败：%r" % (n_try, e))
        else:
            still = _pending(readback)
            if not still:
                break
            jlog("  回读还有 %d 条未反映新价（疑索引延迟），%ds 后重试 …"
                 % (len(still), wait + 4))
        if time.time() - t0 >= total:
            break
    settled = not still
    waited = time.time() - t0
    jlog("  回读收口：等待 %.0fs / %d 次，%s"
         % (waited, n_try, "全部已反映新价" if settled
            else "仍有 %d 条未反映（按未通过记账）" % len(still)))

    n_ok = 0
    for r in results:
        rb = readback.get(r["offer_id"])
        r["readback"] = rb
        r["verified"] = (rb is not None and r["新价"] is not None
                         and abs(rb - float(r["新价"])) < 0.005)
        if r["verified"]:
            n_ok += 1
        note = " | 回读等待=%.0fs%s" % (waited, "" if settled else "（总超时前仍未反映）")
        store.log_write({"offer_id": r["offer_id"], "区服组": r["区服组"],
                         "服务区": r["服务区"], "阵营": r["阵营"],
                         "old_price": r["旧价"], "new_price": r["新价"],
                         "api_ok": r["api_ok"], "readback": rb,
                         "verified": r["verified"], "operator": operator,
                         "detail": ((r.get("detail") or "") + note)[:800]})
    jlog("执行完成：%d 条，回读校验通过 %d 条（回读等待 %.0fs）"
         % (len(results), n_ok, waited))
    return {"ok": True, "dry": False, "total": len(results), "verified": n_ok,
            "readback_waited": round(waited, 1), "results": results}


# ─────────────────────────── 视图 ───────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


def _token_status():
    try:
        info = core_self.load_token(TOKEN_FILE)
        return {"ok": True, "remaining": info["remaining"]}
    except core_self.TokenError as e:
        return {"ok": False, "error": str(e)}


@app.route("/api/state")
def api_state():
    cost_ts, cost = store.latest_snapshot("cost")
    cb_ts, cb_snap = store.latest_snapshot("cheapold")
    offer_ts, _offers = store.latest_snapshot("offers")
    plan_ts, rows = store.latest_plan()
    rows_out = [{
        "offer_id": r["offer_id"], "区服组": r["zone_group"], "服务区": r["server"],
        "阵营": r["side"], "标题": r["title"], "当前价": r["cur_price"],
        "成本": r["cost"], "可买量万": r["qty_wan"], "够量": r["enough"],
        "目标价": r["target"], "差额": r["diff"], "动作": r["action"],
        "定价方式": r["mode"], "说明": r["note"], "放行": bool(r["released"]),
        # 2026-10-13：跟 cheapold 口径 —— 看板「竞品cheapold」列取原始 cheapold 价，
        #   另给「基准价 / 基准来源」说明本轮真正在跟的值（无 cheapold 时退推荐前二）。
        "cheapold价": r.get("cb"),
        "基准价": r.get("base"), "基准来源": r.get("base_src"),
        # 2026-10-12：DD373 区名自带的「天N/魔N」备注，贴在服务区名旁边方便对照
        #   （86 个区全覆盖；取磁盘快照，缺快照留空，绝不编数）。
        "区服备注": core_dd373_cost.zone_note(r["zone_group"], r["server"]),
    } for r in rows]
    # 写入流水同样带上备注（历史记录里的 service 名一样要能对着 DD373 看）。
    writes = store.list_writes(30)
    for w in writes:
        w["区服备注"] = core_dd373_cost.zone_note(w.get("zone_group"), w.get("server"))
    return jsonify({
        "now": time.time(),
        "config": {"seller_id": SELLER_ID, "shop": CFG["g2g"]["shop_name"],
                   "利润率": CFG["定价"]["利润率"],
                   "闸门价": CFG["定价"]["闸门价_usd_per_m"],
                   "保护占位价": CFG["定价"].get("保护占位价"),
                   "服务区数": len(CFG["服务区"]),
                   # 2026-10-12 新增：看板要拿这几个值做人民币换算 + 净利率
                   "汇率USDCNY": float(CFG["汇率"]["USDCNY"]),
                   "综合费率": float(CFG.get("费用", {}).get("G2G综合费率", 0.0) or 0.0),
                   "买满量万": float(CFG["定价"].get("买满量_万基纳", 15000)),
                   "够量闸门万": float(CFG["定价"].get("够量闸门_万基纳", 15000)),
                   # 2026-10-13 新增：跟 cheapold 口径（看板顶栏与文案跟着配置走）
                   "跟cheapold": bool(CFG["定价"].get("跟cheapold", True)),
                   "cheapold卖家": CFG["定价"].get("cheapold卖家") or "cheapold",
                   "下浮比例": float(CFG["定价"].get("下浮比例", 0.01)),
                   "利润率下限": float(CFG["定价"].get("利润率下限", 0.20)),
                   "利润率上限": float(CFG["定价"].get("利润率上限", 0.40)),
                   "无cheapold利润率": float(CFG["定价"].get("无cheapold利润率", 0.30)),
                   "条数下限": int(CFG["定价"].get("条数下限", 10)),
                   "条数不足售价": float(CFG["定价"].get("条数不足售价_usd_per_m", 12.99)),
                   "小数位": int(CFG["定价"].get("小数位", 2))},
        "token": _token_status(),
        "cost_at": cost_ts, "cost_zones": (len(cost.get("costs", {})) if cost else 0),
        "cheapold_at": cb_ts, "cheapold_zones": (len(cb_snap) if cb_snap else 0),
        "offers_at": offer_ts,
        "plan_at": plan_ts,
        "summary": pricing.summarize(rows_out) if rows_out else None,
        "rows": rows_out,
        "job": {k: JOB[k] for k in ("running", "phase", "ok", "summary")},
        "logs": JOB["logs"][-60:],
        "writes": writes,
    })


@app.route("/api/collect", methods=["POST"])
def api_collect():
    if JOB["running"]:
        return jsonify({"ok": False, "error": "已有采集在跑"}), 409
    threading.Thread(target=_do_collect, daemon=True).start()
    return jsonify({"ok": True, "started": time.time()})


@app.route("/api/job")
def api_job():
    return jsonify(JOB)


@app.route("/api/release", methods=["POST"])
def api_release():
    d = request.get_json(force=True, silent=True) or {}
    oid = d.get("offer_id")
    if not oid:
        return jsonify({"ok": False, "error": "缺 offer_id"}), 400
    n = store.set_released(oid, bool(d.get("on", True)))
    return jsonify({"ok": True, "changed": n})


@app.route("/api/release_all", methods=["POST"])
def api_release_all():
    d = request.get_json(force=True, silent=True) or {}
    on = bool(d.get("on", True))
    want = d.get("actions") or ["上调", "下调"]    # 默认只批量放行需要变价的行
    # 2026-10-12 新增：min_pct = 只放行「|目标价−现价| ÷ 现价 ≥ min_pct」的行。
    #   自动轮（tools/auto_cycle.py）用它挡掉「几厘钱的无意义刷新」，避免每 15 分钟
    #   把 74 个区全写一遍。手动点按钮时不传 = 0 = 行为与以前逐字一致。
    min_pct = float(d.get("min_pct") or 0.0)
    # 2026-10-12 新增（老板要求「大区筛选分类」）：areas / sides 可选过滤，
    #   配合看板的「放行本筛选需变价行」按钮 —— 只放行某个大区（或某个阵营）的行。
    #   两个都不传时 = 与以前逐字一致（全量放行），自动轮 auto_cycle.py 走的就是这条。
    areas = set(d.get("areas") or [])
    sides = set(d.get("sides") or [])
    ts, rows = store.latest_plan()
    n = skipped = 0
    for r in rows:
        if r["action"] not in want:
            continue
        if areas and (r.get("zone_group") or "") not in areas:
            continue
        if sides and (r.get("side") or "") not in sides:
            continue
        if on and min_pct > 0:
            cur, tgt = r.get("cur_price"), r.get("target")
            if not cur or tgt is None or abs(float(tgt) - float(cur)) / float(cur) < min_pct:
                skipped += 1
                continue
        store.set_released(r["offer_id"], on)
        n += 1
    return jsonify({"ok": True, "changed": n, "skipped": skipped, "min_pct": min_pct,
                    "areas": sorted(areas), "sides": sorted(sides)})


@app.route("/api/execute", methods=["POST"])
def api_execute():
    d = request.get_json(force=True, silent=True) or {}
    dry = bool(d.get("dry", True))
    if not dry and not d.get("confirm"):
        return jsonify({"ok": False,
                        "error": "真实写入需要 confirm=true（这是防手滑的硬闸）"}), 400
    if not dry and JOB["running"]:
        return jsonify({"ok": False, "error": "采集在跑，先等它结束再写价"}), 409
    try:
        return jsonify(_do_execute(dry=dry, operator=d.get("operator") or "dashboard"))
    except core_self.TokenError as e:
        return jsonify({"ok": False, "error": "token 不可用：%s" % e}), 401
    except Exception as e:                          # noqa: BLE001
        return jsonify({"ok": False, "error": repr(e)[:400]}), 500


@app.route("/api/token", methods=["POST"])
def api_token():
    """保活器/人工更新 token。写 var/token.json（原子替换）。"""
    d = request.get_json(force=True, silent=True) or {}
    tok = d.get("access_token") or d.get("token")
    if not tok:
        return jsonify({"ok": False, "error": "缺 access_token"}), 400
    os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
    tmp = TOKEN_FILE + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps({"access_token": tok, "payload": d.get("payload"),
                            "saved_at": time.time(), "seller_id": SELLER_ID,
                            "remaining": d.get("remaining")}, ensure_ascii=False, indent=1))
    os.replace(tmp, TOKEN_FILE)
    return jsonify({"ok": True})


@app.route("/api/export.csv")
def api_export():
    _, rows = store.latest_plan()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["区服组", "服务区", "阵营", "当前G2G价", "DD373成本$/M", "可买量(万基纳)",
                "够量", "跟价基准$/M", "基准来源", "目标价$/M", "差额", "动作",
                "定价方式", "放行", "offer_id", "说明"])
    for r in rows:
        w.writerow([r["zone_group"], r["server"], r["side"], r["cur_price"], r["cost"],
                    r["qty_wan"], r["enough"], r.get("base"), r.get("base_src"),
                    r["target"], r["diff"], r["action"],
                    r["mode"], "Y" if r["released"] else "", r["offer_id"], r["note"]])
    data = "\ufeff" + buf.getvalue()
    return Response(data, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition":
                             "attachment; filename=g2g_plan_%s.csv"
                             % time.strftime("%Y%m%d_%H%M")})


@app.route("/api/health")
def api_health():
    return jsonify({"ok": True, "service": "g2gfollow",
                    "port": CFG["运行"]["端口"], "seller_id": SELLER_ID,
                    "now": time.strftime("%Y-%m-%d %H:%M:%S")})


store.init()
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(CFG["运行"]["端口"]), debug=False, threaded=True)
