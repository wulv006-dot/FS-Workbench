# -*- coding: utf-8 -*-
"""复核 write_log 里「未通过」的行：重读货架，若现价已等于新价则改判为「通过」。

为什么需要它
------------
G2G 的 my_offers 列表有 **6.5~10.3 秒**的索引延迟（2026-10-12 用「零净变化回写」
探针实测）。旧版回读只等 6s，正好落在延迟窗口里，把「已写进去但尚未索引」的
行误判成「未通过」。本工具按**现价事实**改判，并把原判决与改判依据都留在 detail 里。

用法
----
    venv/bin/python3 tools/recheck_writes.py             # 只看，不改（dry）
    venv/bin/python3 tools/recheck_writes.py --apply     # 真改（改前用 sqlite 热备份）
"""
import argparse
import io
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import core_self                                    # noqa: E402
import store                                        # noqa: E402

CFG = json.load(io.open(os.path.join(HERE, "config.json"), encoding="utf-8"))
TOKEN_FILE = os.path.join(HERE, CFG["g2g"]["token_file"])
SELLER_ID = CFG["g2g"]["seller_id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真改；不给只做 dry-run")
    ap.add_argument("--limit", type=int, default=50, help="最多复核多少条未通过行")
    a = ap.parse_args()

    info = core_self.load_token(TOKEN_FILE)
    print("token 可用，剩余 %ss" % info["remaining"])
    now = {}
    for o in core_self.fetch_my_offers(info["token"], seller_id=SELLER_ID):
        now[o.get("offer_id")] = (core_self._f(o.get("converted_unit_price"))
                                  or core_self._f(o.get("unit_price")))
    print("货架读回 %d 条" % len(now))

    c = sqlite3.connect(store.DB, timeout=15)
    c.row_factory = sqlite3.Row
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM write_log WHERE verified=0 ORDER BY ts DESC LIMIT ?", (a.limit,))]
    print("待复核（verified=0）%d 条" % len(rows))
    fixed = []
    for r in rows:
        cur = now.get(r["offer_id"])
        hit = (cur is not None and r["new_price"] is not None
               and abs(cur - float(r["new_price"])) < 0.005)
        t = time.strftime("%m-%d %H:%M", time.localtime(r["ts"]))
        print("  %s %-14s %-8s %-9s 目标 %-6s 现价 %-6s -> %s"
              % (t, r["offer_id"], r["server"], r["side"],
                 r["new_price"], cur, "改判通过" if hit else "仍不符，保持不动"))
        if hit:
            fixed.append((cur, r))

    if not a.apply:
        print("\n[dry] 未改动任何数据；确认无误后加 --apply。")
        return
    if not fixed:
        print("\n没有需要改判的行。")
        return

    # 改前热备份（sqlite backup API，WAL 下也拿到一致快照）
    bak = store.DB + ".bak-recheck-%s" % time.strftime("%Y%m%d_%H%M%S")
    dst = sqlite3.connect(bak)
    c.backup(dst)
    dst.close()
    print("\n改前备份 -> %s" % bak)

    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    for cur, r in fixed:
        note = ("%s | %s 复核：现价已=新价 %.2f，原「未通过」判为 G2G 货架索引延迟误报"
                "（实测延迟 6.5~10.3s，旧版回读只等 6s）" % ((r["detail"] or ""), stamp, cur))
        c.execute("UPDATE write_log SET verified=1, readback=?, operator=?, detail=? "
                  "WHERE ts=? AND offer_id=?",
                  (cur, (r["operator"] or "") + "+recheck", note[:900],
                   r["ts"], r["offer_id"]))
    c.commit()
    print("已改判 %d 条（原判决与依据都写进了 detail）" % len(fixed))


if __name__ == "__main__":
    main()
