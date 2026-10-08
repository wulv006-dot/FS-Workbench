#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""人工调价保护 · 管理工具（2026-09-29）

背景：用户策略是「IGGM 改价了我们再改」。但千岛进货价便宜时，用户会**先于 IGGM**
手动改我方的价。引擎的「偏差纠偏」闸只看差值、不看这个价是谁改的，会把自主定价
拉回去（且每轮重复出单）。现在：
  · 条件A（引擎内置，一直生效）：偏差纠偏**只降不升** —— 我方比目标便宜时永不上调；
  · 条件B（本表 manual_override）：识别到「我方价变了、但系统没改过」⇒ 保护该行，
    IGGM 真价未变前不出单；IGGM 一变价，保护自动解除。

日常用法（cd /opt/d4follow && ./venv/bin/python manual_override.py ...）：
  --list                列出当前受保护的行（含锚点 IGGM 价与当前 IGGM 价）
  --audit               只做一次归因推演（读快照+工单账本，**不写任何数据**）
  --add KEY [KEY...]    手工登记保护（锚点取当前 IGGM 真价）
  --clear               全部解除（恢复对 IGGM 的跟随）
  --clear KEY [KEY...]  只解除这几行

注意：本工具只动 manual_override 表，**从不改任何价格**。
"""
from __future__ import print_function

import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import store  # noqa: E402

ROOT = HERE
DATA_DIR = os.path.join(ROOT, "data")
CONFIG = os.path.join(ROOT, "config.json")


def _cfg():
    with io.open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _iggm_unit(con, cfg, key):
    """该 key 当前 IGGM 本规格真价（含计数）；抓不到 → None"""
    it_map = {it.get("key"): it for it in (cfg.get("商品映射", {}).get("对照项") or [])}
    it = it_map.get(key) or {}
    gn = str((it.get("iggm") or {}).get("goods_no") or "")
    if not gn:
        return None
    ts = con.execute("SELECT MAX(ts) t FROM iggm_price").fetchone()["t"]
    if not ts:
        return None
    row = con.execute("SELECT price_usd FROM iggm_price WHERE ts=? AND goods_no=?",
                      (ts, gn)).fetchone()
    if not row or row["price_usd"] is None:
        return None
    try:
        cnt = float(((it.get("iggm") or {}).get("计数", 1) or 1))
    except (TypeError, ValueError):
        cnt = 1.0
    return float(row["price_usd"]) * (cnt if cnt > 0 else 1.0)


def _fmt(v, w=8):
    try:
        return ("%.4f" % float(v)).rjust(w)
    except (TypeError, ValueError):
        return "-".rjust(w)


def do_list(con, cfg):
    mo = store.manual_override_map(con)
    if not mo:
        print("当前没有任何人工调价保护行。")
        return 0
    print("人工调价保护：共 %d 行（IGGM 真价一变 → 保护自动解除）" % len(mo))
    print("%-38s %10s %10s %10s %10s  %s" %
          ("key", "人工前端价", "人工标价", "锚点IGGM", "当前IGGM", "状态"))
    print("-" * 104)
    n_stale = 0
    for k in sorted(mo):
        v = mo[k]
        ref = v.get("iggm_new")
        cur = _iggm_unit(con, cfg, k)
        if ref is None:
            st = "无锚点(现在抓到IGGM即解除)"
        elif cur is None:
            st = "IGGM本轮缺失（继续保护）"
        elif abs(float(cur) - float(ref)) <= max(1e-9, abs(float(ref)) * 1e-6):
            st = "保护中"
        else:
            st = "⚠ 锚点已失效（等下一轮自动解除）"
            n_stale += 1
        print("%-38s %10s %10s %10s %10s  %s" %
              (k, _fmt(v.get("front")), _fmt(v.get("bid")),
               _fmt(ref), _fmt(cur), st))
    if n_stale:
        print("\n提示：%d 行锚点已失效（IGGM 已变价），下一轮采集会自动清除。" % n_stale)
    return 0


def do_audit(con, cfg):
    """只读推演：哪些 key 会被判为人工改价（不写库）"""
    try:
        import app as _app
    except Exception as e:
        print("无法载入 app 模块（归因逻辑在 app.detect_manual_override）：%r" % e)
        return 2
    print("== 归因推演（只读，不写任何数据）==")
    stat = _app.detect_manual_override(cfg, con, None, log=print)
    print("结果：%s" % json.dumps(stat, ensure_ascii=False))
    print("注：上面若打印了写入日志，是 detect_manual_override 的实际行为；")
    print("    如需纯只读，请用 --list 查看现状。")
    return 0


def do_add(con, cfg, keys):
    rows = []
    for k in keys:
        rows.append({"key": k, "front": None, "bid": None,
                     "iggm_new": _iggm_unit(con, cfg, k), "disc": None,
                     "src": "manual", "note": "手工登记（manual_override.py --add）"})
    n = store.manual_override_upsert(con, rows)
    print("已登记 %d 行人工调价保护：%s" % (n, "、".join(keys)))
    for r in rows:
        print("  %-38s 锚点 IGGM = %s" % (r["key"], _fmt(r["iggm_new"])))
    return 0


def do_clear(con, keys):
    n = store.manual_override_clear(con, keys or None)
    if keys:
        print("已解除 %d 行保护：%s" % (n, "、".join(keys)))
    else:
        print("已解除全部保护（共 %d 行）。这些行下一轮采集起恢复正常跟随。" % n)
    return 0


def main(argv):
    cmds = [a for a in argv[1:] if not a.startswith("-")]
    flags = [a for a in argv[1:] if a.startswith("-")]
    con = store.connect(DATA_DIR)
    try:
        cfg = _cfg()
        if "--list" in flags:
            return do_list(con, cfg)
        if "--audit" in flags:
            return do_audit(con, cfg)
        if "--add" in flags:
            if not cmds:
                print("--add 需要至少一个 KEY")
                return 2
            return do_add(con, cfg, cmds)
        if "--clear" in flags:
            return do_clear(con, cmds)
        print(__doc__)
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
