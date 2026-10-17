# -*- coding: utf-8 -*-
"""跟价模拟器 —— 不碰任何真实数据，把「如果 IGGM 这样变，我们会怎么跟」跑给你看。

用途：
  1. 验收跟价逻辑（AUTO 模式到底会不会跟、跟到多少、会不会被闸拦下）
  2. 演练开关 OFF/AUTO 的差异
  3. 上线前自查，避免真开 AUTO 才发现规则不对

原理：读库里最新快照 → 在内存里把指定商品的 IGGM 价改掉 → 拿内存里的 cfg
（模式强制 AUTO）跑一遍 engine.evaluate → 打印决策。全程不写数据库、不发改价请求。

用法：
  python simulate.py                          # 默认：全部 IGGM 商品 -10% / +10% 各跑一遍
  python simulate.py --pct -10                # 只看降价 10%
  python simulate.py --goods 1971094355=0.015 # 指定某个 goods_no 改成指定价
  python simulate.py --pct 15 --mode OFF      # 看关闭状态下会说什么
"""
import argparse
import copy
import datetime as dt
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import engine
import store


def load_cfg():
    return json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))


def latest(con, table):
    ts = con.execute("SELECT MAX(ts) t FROM %s" % table).fetchone()["t"]
    return ts


def run(cfg, con, changes, mode, log=print):
    """changes: {goods_no: new_price}

    iggm_prev = 真实当前快照（基线）
    iggm_now  = 把指定商品改成变化后的价（模拟未来）
    """
    ig_ts = latest(con, "iggm_price")
    qd_ts = latest(con, "qd_cost")
    real = {r["goods_no"]: r for r in store.iggm_rows(con, ig_ts)}
    iggm_prev = real
    iggm_now = copy.deepcopy(real)
    for gn, p in (changes or {}).items():
        if gn in iggm_now:
            iggm_now[gn]["price_usd"] = p
    our_map, _ = store.our_latest(con)
    ours_now = our_map or {}

    import tracker
    qd_map = tracker.build_qd_map(cfg, con, qd_ts)

    c2 = copy.deepcopy(cfg)
    c2["跟价"]["模式"] = mode
    dec = engine.evaluate(c2, c2["商品映射"]["对照项"], iggm_now, iggm_prev,
                          ours_now, qd_map, dt.datetime.now().isoformat(timespec="seconds"),
                          log=lambda *a: None)
    return dec


def show(dec, title, log=print):
    s = engine.summarize(dec)
    log("")
    log("── %s ──" % title)
    log("   可执行 %d（涨 %d / 降 %d）｜ 被拦 %d ｜ 仅观察 %d"
        % (s["actionable"], s["follow_up"], s["follow_down"], s["blocked"], s["hold"]))
    act = [d for d in dec if d["action"] in ("follow_up", "follow_down", "blocked")]
    if not act:
        log("   （没有商品被触发跟价）")
    for d in act:
        old, new = d.get("iggm_old"), d.get("iggm_new")
        ig = ("$%.4f→$%.4f" % (old, new)) if (old and new) else "（IGGM 无对应规格）"
        # 口径与引擎一致：比的是「我方标价」（后台 $每个价格），不是客户端看到的前端价。
        # 被拦下的行显示它本该去的目标标价，比显示「—」有用。
        cur = d.get("ours_bid") or 0
        newv = d.get("ours_new")
        if newv is None:
            newv = d.get("target_usd")
        arrow = "↑" if (newv or 0) >= cur else "↓"
        log("   [%s] %-22s %s  我方标价 $%.4f %s $%s"
            % ({"follow_up": "跟涨", "follow_down": "跟降", "blocked": "拦截"}[d["action"]],
               d["title"], ig,
               cur, arrow,
               ("%.4f" % newv) if newv is not None else "—"))
        log("        %s" % d["reason"])
    return s


def main():
    ap = argparse.ArgumentParser(description="IGGM 跟价模拟器（不碰真实数据）")
    ap.add_argument("--pct", type=float, help="所有 IGGM 商品统一涨跌百分比，如 -10")
    ap.add_argument("--goods", nargs="*", help="指定 goods_no=新价，可多个")
    ap.add_argument("--mode", default="AUTO", choices=["OFF", "AUTO"])
    ap.add_argument("--save-plan", nargs="?", const="__auto__",
                    help="把模拟出的改价计划存成 JSON，供 apply_price.py --plan 演练 dry-run")
    a = ap.parse_args()

    cfg = load_cfg()
    con = store.connect(os.path.join(ROOT, cfg["运行"]["数据目录"]))
    ig_ts = latest(con, "iggm_price")
    base = {r["goods_no"]: r["price_usd"] for r in store.iggm_rows(con, ig_ts)}
    if not base:
        print("库里还没有 IGGM 快照，请先跑 python tracker.py")
        return

    lines = []
    def L(m=""):
        print(m)
        lines.append(m)

    L("IGGM 跟价模拟器（基线快照 %s，共 %d 个商品）" % (ig_ts, len(base)))
    L("★ 本次为纯模拟：不改 config、不写数据库、不发任何改价请求")

    scenarios = []
    if a.goods:
        ch = {}
        for kv in a.goods:
            k, v = kv.split("=")
            ch[k] = float(v)
        scenarios.append(("指定价：%s" % ", ".join("%s→$%s" % (k, v) for k, v in ch.items()), ch))
    elif a.pct is not None:
        ch = {k: round(v * (1 + a.pct / 100.0), 6) for k, v in base.items()}
        scenarios.append(("IGGM 全部 %+.0f%%" % a.pct, ch))
    else:
        scenarios.append(("IGGM 全部降价 10%", {k: round(v * 0.9, 6) for k, v in base.items()}))
        scenarios.append(("IGGM 全部涨价 10%", {k: round(v * 1.1, 6) for k, v in base.items()}))

    last_dec, last_name, last_mode = None, None, None
    for name, ch in scenarios:
        for mode in ([a.mode] if a.goods else [a.mode]):
            dec = run(cfg, con, ch, mode)
            show(dec, "%s ｜ 开关=%s" % (name, mode), log=L)
            last_dec, last_name, last_mode = dec, name, mode
            if mode == "OFF":
                dec2 = run(cfg, con, ch, "AUTO")
                show(dec2, "%s ｜ 开关=AUTO（同一变化的对照）" % name, log=L)

    out = os.path.join(ROOT, cfg["运行"]["输出目录"])
    os.makedirs(out, exist_ok=True)
    fp = os.path.join(out, "模拟跟价_%s.md" % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    open(fp, "w", encoding="utf-8").write("\n".join(lines))
    print("\n报告已存：%s" % fp)

    if a.save_plan and last_dec is not None:
        plan = [{"key": d["key"], "title": d["title"],
                 "ours_old": d.get("ours_old"), "ours_new": d.get("ours_new"),
                 "ours_bid": d.get("ours_bid"), "target_front_usd": d.get("target_front_usd"),
                 "iggm_old": d.get("iggm_old"), "iggm_new": d.get("iggm_new"),
                 "target_usd": d.get("target_usd"), "cost_usd": d.get("cost_usd"),
                 "margin_old": d.get("margin_old"), "margin_new": d.get("margin_new"),
                 "action": d.get("action"), "reason": d.get("reason"),
                 "mode": last_mode, "装量": d.get("装量"),
                 "_来源": "模拟：%s（非真实 IGGM 变化，勿据此改价）" % last_name}
                for d in last_dec if d.get("action") in ("follow_up", "follow_down")]
        pf = a.save_plan if a.save_plan != "__auto__" else os.path.join(out, "改价计划_模拟.json")
        json.dump({"generatedAt": dt.datetime.now().isoformat(timespec="seconds"),
                   "simulated": True, "scenario": last_name, "mode": last_mode,
                   "plan": plan}, open(pf, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print("改价计划已存：%s（%d 件）" % (pf, len(plan)))
        print("可演练 dry-run：python apply_price.py --plan \"%s\"" % pf)


if __name__ == "__main__":
    main()
