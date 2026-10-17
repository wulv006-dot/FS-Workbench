# -*- coding: utf-8 -*-
"""POE2 首次对齐（DRY-RUN）：按 IGGM 真价一次性对齐我方后台标价。

为什么需要单独一条通道：
  引擎只在「IGGM 本轮相对上一轮变价」时评估；首次接入时没有上一轮基线，
  所有行都会落成 hold（"IGGM 本轮新增 / 首次抓到该规格…先建立基线"）。
  这里是**一次性对齐工具**：直接比对「IGGM 真价 × 计数」与「我方前端现价」，
  产出 diff 与工单；不写任何数据（真写由本机执行器 --confirm 执行）。

用法：
    python poe2_align.py                 # 只看 diff（默认）
    python poe2_align.py --game 流放之路2
"""
import argparse
import datetime as dt
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core_front          # noqa: E402
import core_iggm           # noqa: E402
import engine              # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "对齐工单")
RECON = os.path.join(HERE, "..", "侦察")
os.makedirs(OUT, exist_ok=True)
os.makedirs(RECON, exist_ok=True)


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--game", default="流放之路2")
    a = ap.parse_args()
    cfg = json.load(io.open(a.config, encoding="utf-8"))
    game = a.game
    # 让价系数（我方前端价 = IGGM 真价 × 该系数）。与引擎共用同一字段，
    # 别在这里自己算 —— 否则首批对齐与后续跟价会差一个百分点还不报错。
    allow = engine.allowance(cfg)

    # ---- 1) IGGM 一侧 ----
    ig = []
    ig += core_iggm.scrape_zones(cfg, log=lambda *x: None)
    ig += core_iggm.scrape_golds(cfg, log=lambda *x: None)
    iggm_by_no = {str(r["goods_no"]): r for r in ig}

    # ---- 2) 我方前端一侧 ----
    items = core_front.fetch_multi_game(cfg, log=lambda *x: None)
    ours_by_key = {}
    idx = {}
    for it in cfg["商品映射"]["对照项"]:
        if it.get("前台商品名"):
            idx[(str(it["前台服务区"]), core_front.norm_name(it["前台商品名"]),
                 it.get("前台类目") or "items")] = it["key"]
    for x in items:
        k = idx.get((str(x.get("zone_key")), core_front.norm_name(x.get("name")), x.get("kind")))
        if k:
            ours_by_key[k] = x

    # ---- 3) 逐项比对 ----
    rows, skipped = [], []
    for it in cfg["商品映射"]["对照项"]:
        if it.get("游戏") != game:
            continue
        key = it["key"]
        cname = it.get("中文名")
        gn = str((it.get("iggm") or {}).get("goods_no") or "")
        cnt = engine.units_of(it)
        disc = engine.disc_of(cfg, it)
        follow = it.get("跟价", True) is not False
        cur = iggm_by_no.get(gn)
        ig_raw = fnum((cur or {}).get("unit_price_usd"))
        ig_use = ig_raw * cnt if ig_raw is not None else None
        our = ours_by_key.get(key)
        our_front = fnum((our or {}).get("unit_price"))
        rec = {
            "key": key, "中文名": cname, "计数": cnt, "折扣": disc * 100,
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
        tgt_bid = round(ig_use * allow / disc, 5)   # 后台写的是 "%.5f"，比对也按 5 位
        cur_bid = round(our_front / disc, 5)
        rec["目标标价(后台$)"] = tgt_bid
        rec["差额"] = tgt_bid - cur_bid
        rec["幅度%"] = ((tgt_bid / cur_bid) - 1.0) * 100.0 if cur_bid else None
        rec["动作"] = "hold" if abs(rec["差额"]) < 1e-9 else \
            ("follow_up" if rec["差额"] > 0 else "follow_down")
        rows.append(rec)

    rows.sort(key=lambda r: abs(r.get("幅度%") or 0), reverse=True)

    # ---- 4) 报告 ----
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    lines = []
    lines.append("# 首次对齐 · %s · 差异清单（%s）"
                 % (game, dt.datetime.now().strftime("%Y-%m-%d %H:%M")))
    lines.append("")
    lines.append("口径：**我方前端价 = IGGM 真价 × 计数 × 让价系数 %.4f**"
                 "（让价 %.1f%%；IGGM 真价 = 机房价 ÷ 折算系数）；"
                 "后台标价 = 前端价 ÷ 后台折扣。"
                 % (allow, (1.0 - allow) * 100.0))
    lines.append("")
    lines.append("## 需要改的（%d 件）" % len([r for r in rows if r["动作"] != "hold"]))
    lines.append("")
    lines.append("| 商品 | 计数 | 我方现价 | IGGM真价×计数 | 目标标价 | 差额 | 幅度 | 方向 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        if r["动作"] == "hold":
            continue
        lines.append("| %s | %s | %s | %s | %s | %+.6g | %+.2f%% | %s |"
                     % (r["中文名"], ("%g" % r["计数"]),
                        _money(r["我方标价(后台$)"]), _money(r["IGGM真价×计数"]),
                        _money(r["目标标价(后台$)"]), r["差额"], r["幅度%"],
                        {"follow_up": "涨", "follow_down": "降", "hold": "不动"}[r["动作"]]))
    lines.append("")
    lines.append("## 不动的（%d 件）" % len([r for r in rows if r["动作"] == "hold"]))
    lines.append("")
    lines.append("| 商品 | 我方现价 | IGGM真价×计数 | 说明 |")
    lines.append("|---|---|---|---|")
    for r in rows:
        if r["动作"] == "hold":
            lines.append("| %s | %s | %s | 已经一致 |"
                         % (r["中文名"], _money(r["我方标价(后台$)"]),
                            _money(r["IGGM真价×计数"])))
    lines.append("")
    lines.append("## 跳过（%d 件）" % len(skipped))
    lines.append("")
    lines.append("| 商品 | 我方前端现价 | IGGM商品号 | 原因 |")
    lines.append("|---|---|---|---|")
    for r in skipped:
        lines.append("| %s | %s | %s | %s |"
                     % (r["中文名"], _money(r["我方前端现价"]), r["iggm_no"], r.get("跳过原因", "")))

    md = os.path.join(RECON, "首次对齐_%s_差异清单.md" % game)
    io.open(md, "w", encoding="utf-8").write("\n".join(lines))

    # ---- 5) 工单（写给本机执行器） ----
    plan = [r for r in rows if r["动作"] != "hold"]
    ticket = {
        "kind": "poe2-align-ticket",
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "游戏": game,
        "口径": "old/new 都是后台「$每个价格」；front 是客户看到的前端价",
        "count": len(plan),
        "clearcache": True,
        "items": [{"key": r["key"], "title": r["中文名"],
                   "old": r["我方标价(后台$)"], "new": r["目标标价(后台$)"],
                   "gid": _gid(cfg, r["key"]),
                   "后台折扣": r["折扣"],
                   "front_old": r["我方前端现价"], "front_new": r["目标前端价"],
                   "IGGM真价×计数": r["IGGM真价×计数"],
                   "方向": "涨" if r["动作"] == "follow_up" else "降"} for r in plan],
        "skipped": [{"key": r["key"], "why": r.get("跳过原因")} for r in skipped],
        "执行方式": "python p2pah_local.py write --plan <本文件> --config <新config> --confirm",
    }
    fp = os.path.join(OUT, "首次对齐_%s_工单_%s.json" % (game, ts))
    io.open(fp, "w", encoding="utf-8").write(
        json.dumps(ticket, ensure_ascii=False, indent=1))
    io.open(os.path.join(OUT, "首次对齐_%s_明细_%s.json" % (game, ts)), "w",
            encoding="utf-8").write(json.dumps(rows + skipped, ensure_ascii=False, indent=1))

    # ---- 6) 控制台摘要 ----
    print("══ 首次对齐 · %s ══ 待改 %d 件 ｜ 一致 %d 件 ｜ 跳过 %d 件"
          % (len(plan), len([r for r in rows if r["动作"] == "hold"]), len(skipped)))
    for r in rows:
        if r["动作"] != "hold":
            print("  %-30s %-10s → %-10s (%+8.2f%%) %s"
                  % (r["中文名"][:30], _money(r["我方标价(后台$)"]),
                     _money(r["目标标价(后台$)"]), r["幅度%"],
                     "涨" if r["动作"] == "follow_up" else "降"))
    print("  ── 跳过 ──")
    for r in skipped:
        print("  %-30s %s" % (r["中文名"][:30], r.get("跳过原因")))
    print("\n差异清单：%s" % md)
    print("工单：%s" % fp)


def _money(v):
    if v is None:
        return "-"
    if abs(v) >= 1:
        return "$%.4g" % v
    return "$%s" % ("%.8f" % v).rstrip("0")


def _gid(cfg, key):
    """后台 gid（POE2=552）。统一走 engine.game_gid —— 别在这里自己查
    `p2pah.游戏[中文名]`，那是 2026-09-25 把 POE2 工单写成 gid=456 的根因。"""
    return engine.game_gid(cfg, key)


if __name__ == "__main__":
    main()
