# -*- coding: utf-8 -*-
"""把「首次对齐」工单派给本机执行器（写 local_job 队列，worker 抢单执行）。

- 每个游戏一张单；过大的游戏（ARC Raiders ~583 件）按 --chunk 切批，
  避免单次超时（worker 执行超时 1800s）与一次性打后台太多写请求。
- 清缓存只在**每个游戏的最后一批**打开（大游戏切批时中间批次不清）。
- 默认只列单不写（--dry），加 --go 才真正入队。

用法：
    python3 dispatch_align.py --dry
    python3 dispatch_align.py --go
    python3 dispatch_align.py --go --games "暗黑破坏神4,流放之路2" --chunk 200
    python3 dispatch_align.py --go --exclude-key BP_TACTICAL_MK3_HEALING
"""
import argparse
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import store  # noqa: E402

OUT_DIR = os.path.join(HERE, "out_align")
DATA_DIR = os.path.join(HERE, "data")


def load_tickets(d, games=None):
    """取每个游戏最新的一张工单（按 mtime）。"""
    best = {}
    for f in os.listdir(d):
        m = re.match(r"^首次对齐_(.+)_工单_(\d{8}_\d{6})\.json$", f)
        if not m:
            continue
        g, ts = m.group(1), m.group(2)
        fp = os.path.join(d, f)
        if g not in best or ts > best[g][0]:
            best[g] = (ts, fp)
    out = []
    for g, (ts, fp) in best.items():
        if games and g not in games:
            continue
        t = json.load(io.open(fp, encoding="utf-8"))
        t["_file"] = fp
        t["_ts"] = ts
        out.append(t)
    out.sort(key=lambda t: -len(t.get("items") or []))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=OUT_DIR)
    ap.add_argument("--games", default="", help="逗号分隔；空=全部")
    ap.add_argument("--chunk", type=int, default=150,
                    help="单张工单最多多少件（超过就切批）")
    ap.add_argument("--exclude-outliers", action="store_true",
                    help="剔除 |幅度|>=50%% 的项（离群项）")
    ap.add_argument("--exclude-key", action="append", default=[],
                    help="按 key 剔除（可重复）")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--go", action="store_true")
    a = ap.parse_args()
    if not a.dry and not a.go:
        raise SystemExit("要么 --dry（只看）要么 --go（真派单）")

    games = [x.strip() for x in (a.games or "").split(",") if x.strip()]
    tickets = load_tickets(a.dir, games or None)
    if not tickets:
        raise SystemExit("没找到工单（%s）" % a.dir)

    con = None if a.dry else store.connect(DATA_DIR)
    n_job = n_item = 0
    for t in tickets:
        g = t.get("游戏")
        items = list(t.get("items") or [])
        dropped = []
        for it in list(items):
            if it.get("key") in a.exclude_key:
                items.remove(it); dropped.append(it["title"] + "（指定剔除）")
        if a.exclude_outliers:
            keep = []
            for it in items:
                old, new = it.get("old"), it.get("new")
                pct = (abs(new / old - 1) * 100.0) if (old and new) else 0.0
                if pct >= 50:
                    dropped.append("%s（离群 %+.0f%%）" % (it["title"], pct))
                else:
                    keep.append(it)
            items = keep
        if not items:
            print("  %-14s 无待派项，跳过" % g)
            continue
        chunks = [items[i:i + a.chunk] for i in range(0, len(items), a.chunk)]
        for ci, ch in enumerate(chunks, 1):
            last = (ci == len(chunks))
            plan = dict(t)
            plan.pop("_file", None); plan.pop("_ts", None)
            plan["items"] = ch
            # 清缓存只在本游戏最后一批打开
            plan["clearcache"] = bool(t.get("clearcache")) and last
            title = ("首次对齐 %s%s（%d 件）"
                     % (g, (" 第%d/%d批" % (ci, len(chunks))) if len(chunks) > 1 else "",
                        len(ch)))
            tag = "首对:%s" % g
            if a.dry:
                print("  [dry] %-46s clearcache=%s  plan=%s"
                      % (title, plan["clearcache"], os.path.basename(t["_file"])))
            else:
                jid = store.local_job_add(
                    con, "write", title, t["_file"], plan,
                    summary="首次对齐（让价 5%%）· %s · %d 件" % (g, len(ch)),
                    actor=tag)
                print("  ✔ 已派单 %-10s %s" % (jid, title))
            n_job += 1
            n_item += len(ch)
        if dropped:
            print("     剔除 %d 件：%s" % (len(dropped), "；".join(dropped)))
    print("\n%s：%d 张单 / %d 件" % ("预演" if a.dry else "已入队", n_job, n_item))
    if not a.dry:
        open_jobs = con.execute(
            "SELECT id,kind,title,status FROM local_job WHERE status IN"
            " ('pending','dispatched') ORDER BY ts").fetchall()
        print("\n当前未完成队列 %d 张：" % len(open_jobs))
        for r in open_jobs:
            print("   %s [%s] %s" % (r["id"], r["status"], r["title"]))


if __name__ == "__main__":
    main()
