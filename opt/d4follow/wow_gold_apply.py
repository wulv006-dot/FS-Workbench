# -*- coding: utf-8 -*-
"""魔兽世界：无限（1364）金币改价 —— 命令行入口（默认只试算，不写后台）。

用法
----
  python wow_gold_apply.py                  # 试算：抓 DD373 → 算价 → 出台账/工单，不写
  python wow_gold_apply.py --apply --confirm  # 真写：还需 wow_gold_config.json 的「启用」= true
                                             # 且环境变量 WOW_GOLD_APPLY=1

安全闸（三道，缺一不写）
 ① config 启用=true  ② 命令行 --apply --confirm  ③ 环境变量 WOW_GOLD_APPLY=1
写了什么：只对「动作 != hold」且「建议采购成本 非空」的行，POST itemEdit 改采购成本；
Hardcore 与 DD373 无对应区的行不动（见 config 的「无对应区处理」）。
"""
import datetime as dt
import json
import os
import sys
import time
import fcntl

sys.path.insert(0, "/opt/fs-order-session")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core_wow_gold as W                                    # noqa: E402
import core_wow_sources as WS                                # noqa: E402
from core_p2pah import P2PAHClient                           # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(ROOT, "output")
EDIT_URL = "/game/admin_game_price/itemEdit"


def log(*a):
    print(*a, flush=True)


def fx_of(cfg_main):
    try:
        return float((cfg_main.get("汇率") or {}).get("USDCNY") or 6.65)
    except (TypeError, ValueError):
        return 6.65


def write_cost(client, row_id, value):
    body = "data_type=costprice&data_val=%s" % value
    r = client.request(EDIT_URL + "?ids=" + str(row_id), data=body.encode(),
                       method="POST",
                       headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                                "X-Requested-With": "XMLHttpRequest",
                                "Accept": "application/json, text/javascript, */*; q=0.01"})
    try:
        j = json.loads(r)
        return int(j.get("code") or 0) == 1, (j.get("msg") or "")[:120]
    except Exception:                                        # noqa: BLE001
        return False, (r or "")[:120]


IGGMSID = {("美服","NORMAL","A"):29411,("美服","NORMAL","H"):29413,
           ("美服","PVP","A"):29415,("美服","PVP","H"):29417,
           ("美服","RP","A"):29419,("美服","RP","H"):29421,
           ("美服","RP_PVP","A"):29423,("美服","RP_PVP","H"):29425,
           ("欧服","NORMAL","A"):29427,("欧服","NORMAL","H"):29429,
           ("欧服","PVP","A"):29431,("欧服","PVP","H"):29433,
           ("欧服","RP","A"):29435,("欧服","RP","H"):29437,
           ("欧服","RP_PVP","A"):29439,("欧服","RP_PVP","H"):29441}


def publish_console(plan):
    """把本轮算价结果写进 RPG 看板的 gold_price（沿用最新一轮的 ts，和 AION2 同快照）"""
    import sqlite3
    con = sqlite3.connect(os.path.join(ROOT, "data", "iggm_follow.db"), timeout=10)
    try:
        ts = con.execute("SELECT MAX(ts) FROM gold_price").fetchone()[0]
        if not ts:
            return 0
        n = 0
        for p in plan:
            con.execute(
                "INSERT OR REPLACE INTO gold_price(ts,key,title,row_id,aid,iggm_sid,"
                "iggm_raw,iggm_per_m,our_per_m,our_tier,our_tiers,margin_rate,"
                "cost_old,cost_target,ratio,action,reason,divisor,ok,price_mode,price_tier,"
                "src_base,src_base_v,comp_min,comp_min_src,gap_comp,gap_comp_pct,"
                "dd_ref_usd,dd_ref_cny,dd_items) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, p["key"], p["后台名"], p["后台行ID"], None,
                 IGGMSID.get((p["区"], p["类型"], p["阵营"])),
                 None, p.get("IGGM"), p.get("目标b2c"), 1, None,
                 p.get("利润率"), p.get("现采购成本"), p.get("建议采购成本"),
                 (round(p["目标b2c"] / p["IGGM"], 6) if p.get("IGGM") and p.get("目标b2c") else None),
                 p.get("动作"), "%s｜%s" % (p.get("规则"), p.get("备注") or ""),
                 5.32, 0,
                 ("igmm_anchor" if p.get("IGGM") else "dd373_only"), 1,
                 p.get("规则"), p.get("成本价USD"),
                 p.get("IGGM"), ("IGGM" if p.get("IGGM") else "DD373"),
                 (round(p["目标b2c"] - p["IGGM"], 6) if p.get("IGGM") and p.get("目标b2c") else None),
                 (round((p["目标b2c"] / p["IGGM"] - 1) * 100, 3) if p.get("IGGM") and p.get("目标b2c") else None),
                 p.get("成本价USD"), p.get("均价元每金"), p.get("挂单数")))
            n += 1
        con.commit()
        return n
    finally:
        con.close()


def main(argv):
    do_apply = "--apply" in argv
    do_confirm = "--confirm" in argv
    only = set()
    for i, a in enumerate(argv):
        if a == "--only" and i + 1 < len(argv):
            only = {x for x in argv[i + 1].split(",") if x}
    cfg = W.load_cfg()
    p = cfg["参数"]
    main_cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    fx = fx_of(main_cfg)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")

    client = P2PAHClient(main_cfg, log=log)
    if not client.login():
        log("✗ 后台会话不可用（order.p2pah.cn 未登录）")
        return 2
    rows = W.read_backend_rows(client, cfg, log=log)
    if not rows:
        log("✗ 没解析到后台行")
        return 2

    log("同轮采集 DD373 与比价器出货（不读取收货需求）…")
    pages, bjq_pages, collected_at = WS.collect_pair(W.dd_crawl, log=log)
    iggm, iggm_ts = W.load_iggm(path=os.path.join(ROOT, p.get("IGGM数据文件") or "data/wow_iggm.json"),
                                max_age_h=float(p.get("IGGM最长时效小时") or 12), log=log)
    plan = W.build_plan(rows, pages, cfg, fx, iggm=iggm, log=log, bjq_pages=bjq_pages)

    os.makedirs(OUT_DIR, exist_ok=True)
    led = os.path.join(OUT_DIR, "魔兽金币台账_%s.json" % ts)
    json.dump({"ts": dt.datetime.now().isoformat(timespec="seconds"),
               "gid": cfg.get("gid"), "汇率": fx, "参数": p,
               "启用": bool(cfg.get("启用")), "IGGM采集时间": iggm_ts,
               "IGGM锚定": {"倍数": p.get("IGGM锚定倍数"), "上限": p.get("IGGM上限倍数")},
               "策略版本": WS.VERSION, "双源轮次开始": collected_at,
               "plan": plan},
              open(led, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    todo = [r for r in plan if r["动作"] != "hold" and r["建议采购成本"] is not None]
    if only:
        todo = [r for r in todo if r["key"] in only or r["后台行ID"] in only]
    ticket = {"kind": "p2pah-gold-apply-ticket", "游戏": ["WoW Forever"],
              "gid": cfg.get("gid"), "ts": dt.datetime.now().isoformat(timespec="seconds"),
              "汇率": fx, "count": len(todo),
              "系统总开关": bool(cfg.get("启用")), "clearcache": True,
              "口径": "同轮DD373/比价器出货；同价位库存>20G；有货才跟IGGM×1.03；毛利率15%-40%",
              "策略版本": WS.VERSION,
              "items": [{"key": r["key"], "中文名": r["后台名"], "游戏": "WoW Forever",
                         "后台行ID": r["后台行ID"],
                         "采购成本_旧": r["现采购成本"], "采购成本_新": r["建议采购成本"],
                         "利润率": r["利润率"], "目标b2c": r["目标b2c"],
                         "DD373区": r["DD373"], "均价元每金": r["均价元每金"],
                         "用金": r["用金"], "成本来源": r["成本来源"],
                         "规则": r["规则"], "动作": r["动作"]}
                        for r in todo]}
    try:
        _np = publish_console(plan)
        log("  控制台台账已刷新：%d 行写入 gold_price" % _np)
    except Exception as _e:
        log("  ⚠ 控制台台账写入失败（不影响改价）：%r" % _e)

    tk = os.path.join(OUT_DIR, "魔兽金币工单_%s.json" % ts)
    json.dump(ticket, open(tk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    log("\n==== 试算结果 ====")
    for r in plan:
        log("%-6s %-28s %-20s %2d/%-2d 金%-6.0f 用%-5.0f 均%-9s %-14s b2c %8.4f → %8.4f  %s"
            % (r["后台行ID"], r["后台名"], r["DD373"] or "—",
               r["挂单数"], r["用单数"], r["可买金"] or 0, r["用金"] or 0,
               ("%.4f" % r["均价元每金"]) if r["均价元每金"] else "—",
               r["规则"], r["现b2c"] or 0, r["目标b2c"] or 0, r["动作"]))
    log("\n台账 %s\n工单 %s（%d 条待改）" % (led, tk, len(todo)))

    if not do_apply:
        log("（试算模式，未写后台。真写需 --apply --confirm 且 config 启用=true）")
        return 0
    if not (cfg.get("启用") and do_confirm and os.environ.get("WOW_GOLD_APPLY") == "1"):
        log("✗ 闸未开：启用=%s / --confirm=%s / WOW_GOLD_APPLY=%s"
            % (cfg.get("启用"), do_confirm, os.environ.get("WOW_GOLD_APPLY")))
        return 3

    if not todo:
        log("本轮无需改价（全部 hold / 与后台一致），不派单")
        return 0

    import store as S
    if not todo:
        log("无待改行，不创建空工单")
        return 0
    con = S.connect(os.path.join(ROOT, "data"))
    _dup = con.execute(
        "SELECT id,status FROM local_job WHERE kind='writegold' AND title LIKE '%WoW Forever%'"
        " AND status IN ('pending','dispatched') ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if _dup:
        log("已有在途魔兽金币工单 %s（%s），本轮不重复派单" % (_dup["id"], _dup["status"]))
        return 0
    jid = S.local_job_add(
        con, kind="writegold",
        title="金币改价 WoW Forever · %d 个服务区" % len(todo),
        plan_path=tk, plan=ticket,
        summary="、".join("%s %s" % (i["后台名"], i["建议采购成本"]) for i in todo[:6])
                + ("…" if len(todo) > 6 else ""),
        actor="wow_gold_apply", exec_mode="server")
    log("\n▶ 已派给服务器执行器：任务 %s（%d 行）" % (jid, len(todo)))
    log("  执行器会：写采购成本 → 点「更新b2c网站」(getweb=1) → 清缓存 → 读回核对")
    log("  进度看：journalctl -u p2pah-srv-exec -f   或 output/local_job 看板")
    return 0


if __name__ == "__main__":
    with open(os.path.join(ROOT, 'data', 'wow_dual_follow.lock'), 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('已有魔兽轮次运行，本次不重叠执行')
            sys.exit(0)
        sys.exit(main(sys.argv[1:]))
