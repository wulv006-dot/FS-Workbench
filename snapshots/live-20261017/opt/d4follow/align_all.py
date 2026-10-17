# -*- coding: utf-8 -*-
"""首次对齐（全游戏 · DRY-RUN）——按「我方前端价 = IGGM 真价 × 计数 × 让价系数」
把 6 个游戏 + 金币一次性对齐到 IGGM 现价低 5%。

为什么要单独一条通道（与 poe2_align.py 同因）：
  引擎只在「IGGM 本轮相对上一轮变价」时评估；首次接入 / 大改口径时没有可比基线，
  所有行都会落成 hold（"先建立基线"）。这里是**一次性对齐工具**：
  直接比对「IGGM 真价 × 计数」与「我方前端现价」，产出差异清单与工单；
  不写任何数据（真写由本机执行器 --confirm 执行）。

与 poe2_align.py 的区别：
  1) **只抓一次 IGGM / 只拉一次我方前端**，然后按游戏分组出多张工单
     （避免 6 次全量抓取把 IGGM 抓出频控）。
  2) 输出带「离群项」专区（默认 |幅度| ≥ 50% 单独列出），执行前必须过目。

用法：
    python align_all.py                      # 全部游戏，出报告+工单（DRY-RUN）
    python align_all.py --games ARC Raiders  # 只算某几个
    python align_all.py --scrape-json /tmp/ig.json   # 复用已抓快照
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import core_front          # noqa: E402
import core_iggm           # noqa: E402
import engine              # noqa: E402

OUT_DIR = os.path.join(HERE, "out_align")
REPORT_DIR = os.path.join(HERE, "out_align")
OUTLIER_PCT = 50.0         # |幅度| ≥ 该值 → 归入「离群项」单独提示


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(v):
    if v is None:
        return "-"
    if abs(v) >= 1:
        return "$%.4g" % v
    return "$%s" % ("%.8f" % v).rstrip("0")


def collect_iggm(cfg, scrape_json=None, log=print):
    """IGGM 一侧：优先复用快照 JSON，否则现场抓一次全量。

    ⚠ 必须用 `scrape_all`：它 = 暗黑4 分类（iggm.目标）+ 扩展分类 + 多游戏服务区
      + 多游戏金币。只用 `scrape_zones` 会漏掉**暗黑4 那 26 条**（2026-09-27 踩过：
      首次对齐里暗黑4 27 件全被标成「IGGM 没抓到」）。
    """
    if scrape_json and os.path.exists(scrape_json):
        rows = json.load(io.open(scrape_json, encoding="utf-8"))
        log("  [IGGM] 复用快照 %s：%d 条" % (scrape_json, len(rows)))
        return rows
    t0 = dt.datetime.now()
    rows = core_iggm.scrape_all(cfg, log=log)
    log("  [IGGM] 现场抓取完成：%d 条（用时 %.1fs）"
        % (len(rows), (dt.datetime.now() - t0).total_seconds()))
    if scrape_json:
        io.open(scrape_json, "w", encoding="utf-8").write(
            json.dumps(rows, ensure_ascii=False))
        log("  [IGGM] 快照已存 %s" % scrape_json)
    return rows


def collect_ours(cfg, log=print):
    """我方前端一侧：**两条通道都要走**（与 app.task_collect 同口径）。

      · 暗黑4（老单游戏通道）：fetch_all + to_our_rows —— 靠「关键词 + 装量」匹配，
        对照项**没有** 前台服务区/前台商品名 字段，只能走这条。
      · 多游戏（POE2 / ARC / DND / WarDogs / WoW）：fetch_multi_game + to_multi_rows
        —— 靠「前台服务区 + 前台商品名 + 类目」精确匹配。

    返回 {key: 行}。行的 `price_usd` = 前端展示价（整包、客户实付）——
    与 engine.evaluate 里 `our.get("price_usd")` 同口径（**不是** unit_price）。
    """
    out = {}
    try:
        items = core_front.fetch_all(cfg, log=lambda *x: None)
        frows, unmatched = core_front.to_our_rows(cfg, items)
        for r in frows:
            out[r["key"]] = r
        log("  [前端/暗黑4] 抓 %d 行 → 匹配 %d，未匹配 %d"
            % (len(items), len(frows), len(unmatched)))
    except Exception as e:
        log("  [前端/暗黑4] 失败：%r" % e)
    if (cfg.get("iggm") or {}).get("多游戏"):
        try:
            mitems = core_front.fetch_multi_game(cfg, log=lambda *x: None)
            mrows, mun = core_front.to_multi_rows(cfg, mitems)
            for r in mrows:
                out.setdefault(r["key"], r)
            log("  [前端/多游戏] 抓 %d 行 → 匹配 %d，未匹配 %d"
                % (len(mitems), len(mrows), len(mun)))
        except Exception as e:
            log("  [前端/多游戏] 失败：%r" % e)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--games", default="", help="逗号分隔；空=全部游戏")
    ap.add_argument("--scrape-json", default="", help="IGGM 快照 JSON（读过/写回）")
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--report", default=REPORT_DIR)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    os.makedirs(a.report, exist_ok=True)

    cfg = json.load(io.open(a.config, encoding="utf-8"))
    allow = engine.allowance(cfg)
    log = print
    log("══ 首次对齐 ══ 让价系数 %.6f（让价 %.2f%%）" % (allow, (1 - allow) * 100))

    # ---- 1) IGGM 一侧 ----
    ig = collect_iggm(cfg, a.scrape_json or None, log=log)
    iggm_by_no = {}
    for r in ig:
        k = str(r.get("goods_no") or "")
        if k:
            iggm_by_no[k] = r

    # ---- 2) 我方前端一侧 ----
    ours_by_key = collect_ours(cfg, log=log)

    # ---- 3) 逐项比对（全游戏）----
    sel = [g.strip() for g in (a.games or "").split(",") if g.strip()]
    rows, skipped = [], []
    for it in cfg["商品映射"]["对照项"]:
        game = it.get("游戏")
        if sel and game not in sel:
            continue
        key = it["key"]
        cname = it.get("中文名") or key
        gn = str((it.get("iggm") or {}).get("goods_no") or "")
        cnt = engine.units_of(it)
        disc = engine.disc_of(cfg, it)
        follow = it.get("跟价", True) is not False
        cur = iggm_by_no.get(gn)
        ig_raw = fnum((cur or {}).get("unit_price_usd"))
        ig_use = ig_raw * cnt if ig_raw is not None else None
        our = ours_by_key.get(key)
        # ⚠ 前端展示价口径 = price_usd（整包、客户实付），**不是** unit_price。
        #   engine.evaluate 里就是 `our.get("price_usd")`；用它才能和
        #   「IGGM 真价 × 计数」同口径。（2026-09-27 踩过：取 unit_price 会把
        #   多游戏整包价错当成单价。）
        our_front = fnum((our or {}).get("price_usd"))
        rec = {
            "游戏": game, "key": key, "中文名": cname, "计数": cnt, "折扣": disc * 100,
            "iggm_no": gn, "iggm_title": (cur or {}).get("title"),
            "IGGM机房价": fnum((cur or {}).get("unit_price_raw_usd")),
            "IGGM真价(单个)": ig_raw, "IGGM真价×计数": ig_use,
            "我方前端现价": our_front,
            "我方标价(后台$)": (our_front / disc) if our_front is not None else None,
            "让价系数": allow,
            "目标前端价": (ig_use * allow) if ig_use else None,
            "目标标价(后台$)": ((ig_use * allow) / disc) if ig_use else None,
            "跟价": follow,
        }
        if ig_use is None:
            rec["跳过原因"] = "IGGM 本轮没抓到该商品号（可能已下架/改号）"
            skipped.append(rec)
            continue
        if our_front is None:
            rec["跳过原因"] = "我方前端没读到该规格（后台有行但前端未上架）"
            skipped.append(rec)
            continue
        if not follow:
            rec["跳过原因"] = "配置里「跟价」= false（占位/无可比价，暂不跟）"
            skipped.append(rec)
            continue
        tgt_bid = round(ig_use * allow / disc, 5)
        cur_bid = round(our_front / disc, 5)
        rec["目标标价(后台$)"] = tgt_bid
        rec["差额"] = tgt_bid - cur_bid
        rec["幅度%"] = ((tgt_bid / cur_bid) - 1.0) * 100.0 if cur_bid else None
        rec["动作"] = ("hold" if abs(rec["差额"]) < 1e-9
                     else ("follow_up" if rec["差额"] > 0 else "follow_down"))
        rows.append(rec)

    # ---- 4) 按游戏分组 ----
    order, by_game = [], {}
    for it in cfg["商品映射"]["对照项"]:
        g = it.get("游戏")
        if g not in by_game:
            by_game[g] = {"rows": [], "skipped": []}
            order.append(g)
    for r in rows:
        by_game[r["游戏"]]["rows"].append(r)
    for r in skipped:
        by_game[r["游戏"]]["skipped"].append(r)
    if sel:
        order = [g for g in order if g in sel]

    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    total_plan = total_hold = total_skip = 0
    tickets, summary_lines = [], []

    for g in order:
        gr = by_game[g]["rows"]
        gs = by_game[g]["skipped"]
        gr.sort(key=lambda r: abs(r.get("幅度%") or 0), reverse=True)
        plan = [r for r in gr if r["动作"] != "hold"]
        hold = [r for r in gr if r["动作"] == "hold"]
        outl = [r for r in plan if abs(r.get("幅度%") or 0) >= OUTLIER_PCT]
        total_plan += len(plan)
        total_hold += len(hold)
        total_skip += len(gs)

        # 差异清单（人看）
        L = []
        L.append("# 首次对齐 · %s · 差异清单（%s）" % (g, stamp))
        L.append("")
        L.append("口径：**我方前端价 = IGGM 真价 × 计数 × 让价系数 %.6f**"
                 "（让价 %.2f%%；IGGM 真价 = 机房价 × 折算系数）；"
                 "后台标价 = 前端价 ÷ 后台折扣。"
                 % (allow, (1 - allow) * 100))
        L.append("")
        L.append("待改 **%d** 件 ｜ 已一致 %d 件 ｜ 跳过 %d 件 ｜ 其中离群"
                 "（|幅度|≥%.0f%%）**%d** 件" % (len(plan), len(hold), len(gs),
                                                OUTLIER_PCT, len(outl)))
        L.append("")
        if outl:
            L.append("## ⚠ 离群项（执行前请重点确认，%d 件）" % len(outl))
            L.append("")
            L.append("| 商品 | 我方现标价 | 目标标价 | 幅度 | IGGM真价×计数 |")
            L.append("|---|---|---|---|---|")
            for r in outl:
                L.append("| %s | %s | %s | %+.1f%% | %s |"
                         % (r["中文名"], money(r["我方标价(后台$)"]),
                            money(r["目标标价(后台$)"]), r["幅度%"],
                            money(r["IGGM真价×计数"])))
            L.append("")
        L.append("## 需要改的（%d 件）" % len(plan))
        L.append("")
        L.append("| 商品 | 计数 | 我方现标价 | IGGM真价×计数 | 目标标价 | 差额 | 幅度 | 方向 |")
        L.append("|---|---|---|---|---|---|---|---|")
        for r in plan:
            L.append("| %s | %s | %s | %s | %s | %+.6g | %+.2f%% | %s |"
                     % (r["中文名"], ("%g" % r["计数"]),
                        money(r["我方标价(后台$)"]), money(r["IGGM真价×计数"]),
                        money(r["目标标价(后台$)"]), r["差额"], r["幅度%"],
                        {"follow_up": "涨", "follow_down": "降"}[r["动作"]]))
        L.append("")
        L.append("## 不动的（%d 件）" % len(hold))
        L.append("")
        L.append("| 商品 | 我方现标价 | IGGM真价×计数 | 说明 |")
        L.append("|---|---|---|---|")
        for r in hold:
            L.append("| %s | %s | %s | 已经一致 |"
                     % (r["中文名"], money(r["我方标价(后台$)"]),
                        money(r["IGGM真价×计数"])))
        L.append("")
        L.append("## 跳过（%d 件）" % len(gs))
        L.append("")
        L.append("| 商品 | 我方前端现价 | IGGM商品号 | 原因 |")
        L.append("|---|---|---|---|")
        for r in gs:
            L.append("| %s | %s | %s | %s |"
                     % (r["中文名"], money(r["我方前端现价"]), r["iggm_no"],
                        r.get("跳过原因", "")))
        md = os.path.join(a.report, "首次对齐_%s_差异清单_%s.md" % (g, ts))
        io.open(md, "w", encoding="utf-8").write("\n".join(L))

        # 工单（给本机执行器）
        gid = engine.game_gid(cfg, plan[0]["key"]) if plan else None
        ticket = {
            "kind": "poe2-align-ticket",
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "游戏": g,
            "gid": gid,
            "口径": "old/new 都是后台「$每个价格」；front 是客户看到的前端价",
            "让价系数": allow,
            "count": len(plan),
            "clearcache": True,
            "items": [{"key": r["key"], "title": r["中文名"],
                       "old": r["我方标价(后台$)"], "new": r["目标标价(后台$)"],
                       "gid": engine.game_gid(cfg, r["key"]),
                       "后台折扣": r["折扣"],
                       "front_old": r["我方前端现价"],
                       "front_new": r["目标前端价"],
                       "IGGM真价×计数": r["IGGM真价×计数"],
                       "方向": "涨" if r["动作"] == "follow_up" else "降"}
                      for r in plan],
            "skipped": [{"key": r["key"], "why": r.get("跳过原因")} for r in gs],
            "执行方式": ("python p2pah_local.py write --plan <本文件> --confirm"),
        }
        fp = os.path.join(a.out, "首次对齐_%s_工单_%s.json" % (g, ts))
        io.open(fp, "w", encoding="utf-8").write(
            json.dumps(ticket, ensure_ascii=False, indent=1))
        io.open(os.path.join(a.out, "首次对齐_%s_明细_%s.json" % (g, ts)), "w",
                encoding="utf-8").write(
            json.dumps(gr + gs, ensure_ascii=False, indent=1))
        tickets.append(fp)
        up = sum(1 for r in plan if r["动作"] == "follow_up")
        summary_lines.append(
            "  %-14s 待改 %4d（涨 %4d / 降 %4d）｜ 一致 %3d ｜ 跳过 %3d ｜ 离群 %d"
            % (g, len(plan), up, len(plan) - up, len(hold), len(gs), len(outl)))
        print(summary_lines[-1])
        if outl:
            print("      ⚠ 离群 %d 件：" % len(outl))
            for r in outl[:8]:
                print("        %-34s %s → %s (%+.1f%%)"
                      % (str(r["中文名"])[:34], money(r["我方标价(后台$)"]),
                         money(r["目标标价(后台$)"]), r["幅度%"]))

    print("\n── 合计 ── 待改 %d 件 ｜ 一致 %d 件 ｜ 跳过 %d 件"
          % (total_plan, total_hold, total_skip))
    print("工单目录：%s" % a.out)
    print("差异清单目录：%s" % a.report)
    io.open(os.path.join(a.out, "首次对齐_汇总_%s.txt" % ts), "w",
            encoding="utf-8").write(
        "首次对齐（让价 %.2f%%）%s\n%s\n合计 待改 %d ｜ 一致 %d ｜ 跳过 %d\n\n工单：\n%s\n"
        % ((1 - allow) * 100, stamp, "\n".join(summary_lines), total_plan,
           total_hold, total_skip, "\n".join(tickets)))


if __name__ == "__main__":
    main()
