# -*- coding: utf-8 -*-
"""跟价系统主流程

  抓 IGGM 竞品价 ─┐
  抓 千岛进货成本 ─┼─► 算毛利率 ─► 跟价引擎(开关 OFF/AUTO) ─► 决策台账 ─► 看板
  读 我方前端价  ─┘

用法：
  python tracker.py                     # 正常跑一轮（千岛命中缓存则秒级完成）
  python tracker.py --refresh-qd        # 强制重抓千岛
  python tracker.py --no-p2pah          # 不连改价后台（只跑 IGGM + 千岛）
  python tracker.py --rebuild-only      # 不联网，只按库里已有数据重出看板
  python tracker.py --set-mode AUTO     # 切换跟价开关（只改 config，不执行改价）
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import core_gold
import core_iggm
import core_qd
import engine
import store
from core_p2pah import P2PAHClient

LOG = []


def log(msg):
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), msg)
    LOG.append(line)
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("gbk", "replace").decode("gbk"))


def load_cfg():
    return json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))


def save_cfg(cfg):
    json.dump(cfg, open(os.path.join(ROOT, "config.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def set_mode(cfg, mode):
    mode = str(mode).upper()
    if mode not in ("OFF", "AUTO"):
        raise SystemExit("模式只能是 OFF 或 AUTO")
    cfg["跟价"]["模式"] = mode
    cfg["跟价"]["开关状态"] = mode
    save_cfg(cfg)
    log("跟价开关已设为 %s%s" % (mode, "（只监控不改价）" if mode == "OFF" else "（⚠ 满足条件会自动改价）"))
    return cfg


def read_our_prices(cfg, con, log, skip_backend=False):
    """读我方前端价。

    两个来源，按优先级：
      ① www.mmoexp.com 公开道具页（order.p2pah.cn 的前端展示价，同源）——零风险、随时可读
      ② order.p2pah.cn 后台列表（需要账号密码，且需逆向接口）——作为校验/补充
    任一来源拿到就用，互相不阻断。
    """
    rows, by_key = [], {}
    if cfg.get("前端", {}).get("pages"):
        try:
            import core_front
            items = core_front.fetch_all(cfg, log=log)
            frows, unmatched = core_front.to_our_rows(cfg, items)
            for r in frows:
                if not r.get("_装量匹配"):
                    log("  [前端] ⚠ %s 装量降级匹配到 %s（config 里可能缺该规格）"
                        % (r["title"], r["key"]))
            rows += frows
            if unmatched:
                log("  [前端] 未匹配到对照项：%s" % ("、".join(unmatched[:8])))
            log("  [前端] 匹配到 %d 条我方前端价" % len(frows))
        except Exception as e:
            log("  [前端] 抓取失败: %r" % e)

    # 后台来源（可选）
    if skip_backend:
        log("  [p2pah] --no-p2pah，跳过后台，仅用前端价")
    elif cfg["p2pah"].get("enabled", True) and (cfg["p2pah"].get("账号") or {}).get("username"):
        try:
            cli = P2PAHClient(cfg, log=log)
            if cli.login():
                for p in [cfg["p2pah"].get("产品价格管理", {}).get("路径"),
                          cfg["p2pah"].get("金币价格管理", {}).get("路径")]:
                    if not p:
                        continue
                    r = cli.fetch_list(p, log_page=True)
                    for row in r["rows"]:
                        nm, price, cost = _pick_fields(row)
                        if nm is None:
                            continue
                        key = _match_key(cfg, nm)
                        if not key:
                            continue
                        by_key[key] = {"key": key, "title": nm, "price_usd": price,
                                       "cost_cny": cost, "game": "D4", "server_zone": "",
                                       "cate": "", "source": "p2pah-backend"}
                log("  [p2pah] 后台读到 %d 条" % len(by_key))
            else:
                log("  [p2pah] 登录未成功，仅用前端价")
        except Exception as e:
            log("  [p2pah] 后台读取失败: %r" % e)
    else:
        log("  [p2pah] 未配置后台账号，仅用前端价")

    # 后台价覆盖前端价（后台是权威源），同时合并两边独有的
    merged = {r["key"]: r for r in rows}
    merged.update(by_key)
    return list(merged.values()), merged


NAME_KEYS = ["商品名", "商品名称", "产品名称", "名称", "标题", "name", "title", "goods_name"]
PRICE_KEYS = ["前端价", "售价", "价格", "美元", "price", "usd", "$"]
COST_KEYS = ["采购成本", "成本", "采购价", "cost"]


def _pick_fields(row):
    nm = price = cost = None
    for k, v in row.items():
        kl = k.lower()
        if nm is None and any(x in k or x in kl for x in NAME_KEYS):
            nm = v
        if price is None and any(x in k or x in kl for x in PRICE_KEYS):
            price = _num(v)
        if cost is None and any(x in k or x in kl for x in COST_KEYS):
            cost = _num(v)
    if nm and price is None:
        # 兜底：取行内第一个像数字的单元格
        for v in row.values():
            n = _num(v)
            if n is not None:
                price = n
                break
    return nm, price, cost


def _num(v):
    if v is None:
        return None
    m = __import__("re").search(r"-?\d+(?:\.\d+)?", str(v).replace(",", ""))
    return float(m.group(0)) if m else None


def _match_key(cfg, name, pack=1):
    """后台商品名 → config 对照项 key（装量感知，逻辑与 core_front 保持一致）"""
    try:
        import core_front
        k, _ = core_front.match_key(cfg, name, pack)
        return k
    except Exception:
        return None


def build_qd_map(cfg, con, qd_ts):
    """从库里取千岛成本 → {对照项key: qd_row}"""
    rows = [dict(r) for r in con.execute("SELECT * FROM qd_cost WHERE ts=?", (qd_ts,))]
    spec = cfg["千岛"]["对标区服"]
    ref = cfg["千岛"].get("参考区服") or []
    out = {}
    for it in cfg["商品映射"]["对照项"]:
        kw = (it.get("千岛") or {}).get("商品")
        if not kw:
            continue
        got = core_qd.pick_from_db(rows, spec, [kw])
        if got:
            got["_区服"] = spec
        elif ref:
            # 对标区服没报价时，退到参考区服（并在看板上标出来，别当默认）
            for alt in ref:
                got = core_qd.pick_from_db(rows, alt, [kw])
                if got:
                    got["_区服"] = alt
                    got["_降级区服"] = True
                    log("  [千岛] %s 在对标区服 %s 无报价，已降级用 %s"
                        % (kw, spec, alt))
                    break
        if got:
            out[it["key"]] = got
        else:
            log("  [千岛] ⚠ 找不到进货成本：%s（区服 %s）" % (kw, spec))
    return out


def run(args):
    t0 = time.time()
    cfg = load_cfg()
    if args.set_mode:
        cfg = set_mode(cfg, args.set_mode)
        if args.set_mode_only:
            return
    mode = str(cfg["跟价"].get("模式", "OFF")).upper()
    log("=== RPG 游戏改价系统 —— 开关=%s ===" % mode)

    data_dir = os.path.join(ROOT, cfg["运行"]["数据目录"])
    con = store.connect(data_dir)
    ts = dt.datetime.now().isoformat(timespec="seconds")

    iggm_now, qd_rows, our_rows = {}, [], []
    gold_plan = None      # 本轮金币抓取结果（core_gold.build_plan 的返回）

    if args.rebuild_only:
        log("[rebuild-only] 不联网，直接用库里数据重出看板")
    else:
        # ---------- 1) IGGM ----------
        log("[1/4] 抓 IGGM 竞品价…")
        try:
            ig_rows = core_iggm.scrape_all(cfg, log=log)
        except Exception:
            log("  [IGGM] 整轮失败:\n" + traceback.format_exc()[-800:])
            ig_rows = []
        if ig_rows:
            n = store.save_iggm(con, ts, ig_rows)
            log("  [IGGM] 入库 %d 条" % n)
        else:
            log("  [IGGM] ⚠ 本轮 0 条 → 复用上一份快照")
        ig_ts = ts if ig_rows else store.prev_ts(con, "iggm_price", ts)
        iggm_now = {r["goods_no"]: r for r in (store.iggm_rows(con, ig_ts) if ig_ts else [])}
        prev_t = store.prev_ts(con, "iggm_price", ig_ts) if ig_ts else None
        iggm_prev = {r["goods_no"]: r for r in (store.iggm_rows(con, prev_t) if prev_t else [])}
        log("  当前快照 %d 条 | 上轮基线 %d 条" % (len(iggm_now), len(iggm_prev)))

        # ---------- 2) 千岛 ----------
        log("[2/4] 取千岛进货成本…")
        try:
            qd_rows, qd_ts, cached = core_qd.fetch(cfg, log=log, force=args.refresh_qd)
        except Exception:
            log("  [千岛] 失败:\n" + traceback.format_exc()[-600:])
            qd_ts = store.prev_ts(con, "qd_cost", ts)
        if qd_rows and not cached:
            store.save_qd(con, ts, qd_rows)
            qd_ts = ts
        elif qd_rows:
            # 缓存也要落库，保证快照链连续
            store.save_qd(con, qd_ts, qd_rows)
        if not qd_ts:
            qd_ts = store.prev_ts(con, "qd_cost", ts)
        log("  千岛快照 ts=%s (%d 条)" % (qd_ts, len(qd_rows)))

        # ---------- 3) 我方价格 ----------
        log("[3/4] 读我方前端价…")
        try:
            our_rows, _ = read_our_prices(cfg, con, log, skip_backend=args.no_p2pah)
            if our_rows:
                store.save_our(con, ts, our_rows)
        except Exception:
            log("  [前端] 失败:\n" + traceback.format_exc()[-600:])

        # ---------- 3.5) 金币（Gold）----------
        # 金币与物品是两套机制，单独一条支线（core_gold）：
        #   竞品价比「每 M 单价」，我方可改量是「采购成本」，没有成本地板。
        if core_gold.enabled(cfg):
            log("[3.5/4] 金币跟价（Gold）…")
            try:
                gold_plan = core_gold.build_plan(cfg, log=log)
                store.save_gold(con, ts, gold_plan)
                for it in gold_plan["items"]:
                    log("  [金币] %-22s 利润率 %s ｜ 我方每M %s ｜ IGGM每M %s ｜ 目标采购成本 %s ｜ %s"
                        % (it.get("中文名"), it.get("利润率"),
                           ("%.6g" % it["我方前端每M"]) if it.get("我方前端每M") is not None else "-",
                           ("%.6g" % it["IGGM每M_跟价用"]) if it.get("IGGM每M_跟价用") is not None else "-",
                           it.get("采购成本_新") if it.get("采购成本_新") is not None else "-",
                           it.get("动作") or "-"))
                    if it.get("错误"):
                        log("      ⚠ %s" % it["错误"])
            except Exception:
                log("  [金币] 失败:\n" + traceback.format_exc()[-600:])

    # 回退：本轮没读到就用库里最近一次
    if not our_rows:
        our_rows_map, our_ts = store.our_latest(con)
        our_rows = list(our_rows_map.values())
        if our_ts:
            log("  [p2pah] 复用库中最近一次我方价格 ts=%s (%d 条)" % (our_ts, len(our_rows)))
    ours_now = {r["key"]: r for r in our_rows}

    # ---------- 4) 引擎 ----------
    log("[4/4] 跟价引擎评估…")
    qd_map = build_qd_map(cfg, con, qd_ts) if qd_ts else {}
    decisions = engine.evaluate(cfg, cfg["商品映射"]["对照项"], iggm_now, iggm_prev,
                               ours_now, qd_map, ts, log=log)
    for d in decisions:
        store.add_decision(con, ts, d, applied=0)
    s = engine.summarize(decisions)
    log("  决策：可执行 %d（涨 %d / 降 %d）| 被拦 %d | 仅观察 %d"
        % (s["actionable"], s["follow_up"], s["follow_down"], s["blocked"], s["hold"]))

    elapsed = time.time() - t0
    store.record_run(con, ts, iggm_count=len(iggm_now), qd_count=len(qd_rows),
                     our_count=len(our_rows), follows=s["actionable"], blocked=s["blocked"],
                     elapsed_s=round(elapsed, 1), mode=mode,
                     note="; ".join(LOG[-4:]))
    store.purge(con, int(cfg["运行"].get("保留天数", 365)))

    # ---------- 看板 ----------
    import build_dashboard
    outdir = os.path.join(ROOT, cfg["运行"]["输出目录"])
    os.makedirs(outdir, exist_ok=True)
    html_path = os.path.join(outdir, "自动改价看板.html")
    # 金币计划另存一份 JSON（给人看 / 给本机执行器当工单原型）
    if gold_plan and gold_plan.get("items"):
        gj = os.path.join(outdir, "金币计划_%s.json"
                          % dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
        with open(gj, "w", encoding="utf-8") as f:
            json.dump(gold_plan, f, ensure_ascii=False, indent=1)
        log("金币计划：%s" % gj)
    gold_now, gold_ts = store.gold_latest(con)
    build_dashboard.build(cfg, con, ts, decisions, iggm_now, iggm_prev, ours_now, qd_map,
                          log=log, out_path=html_path, gold=gold_now, gold_ts=gold_ts)
    log("看板：%s" % html_path)
    log("用时 %.1fs" % elapsed)

    lp = os.path.join(ROOT, cfg["运行"]["日志目录"])
    os.makedirs(lp, exist_ok=True)
    with open(os.path.join(lp, "run.log"), "a", encoding="utf-8") as f:
        f.write("\n".join(LOG) + "\n" + "-" * 60 + "\n")

    if args.open:
        import webbrowser
        webbrowser.open("file:///" + html_path.replace("\\", "/"))
    return html_path


def main():
    ap = argparse.ArgumentParser(description="RPG 游戏改价系统")
    ap.add_argument("--refresh-qd", action="store_true", help="强制重抓千岛（忽略缓存）")
    ap.add_argument("--no-p2pah", action="store_true", help="不连改价后台")
    ap.add_argument("--rebuild-only", action="store_true", help="不联网，只重出看板")
    ap.add_argument("--set-mode", choices=["OFF", "AUTO"], help="切换跟价开关")
    ap.add_argument("--set-mode-only", action="store_true", help="只改开关不出看板")
    ap.add_argument("--open", action="store_true", help="跑完自动打开看板")
    run(ap.parse_args())


if __name__ == "__main__":
    main()
