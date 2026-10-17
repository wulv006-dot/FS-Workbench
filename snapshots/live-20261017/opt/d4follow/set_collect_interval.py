#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把指定游戏的采集周期改成 N 小时（用户 2026-10-02：AION2 → 0.5h = 30 分钟）。

为什么不直接调 /api/schedule：
  那个接口的 SCHED_CHOICES 当时还没 0.5 档（本次一并加了），
  且它是 web 层；这里走文件层，行为可控、可离线演练。

用法：
    python3 set_collect_interval.py AION2 0.5
    python3 set_collect_interval.py --show
"""
import io, json, os, shutil, sys, time

CFG = os.environ.get("D4_CFG", "/opt/d4follow/config.json")
BACKUP_DIR = "/opt/d4follow/_rollback_20261002_1830_隐藏金币监控"


def show(c):
    d = ((c.get("运行") or {}).get("采集周期小时")) or {}
    print("-" * 56)
    for k, v in d.items():
        h = float(v)
        print("  %-16s %sh（%s）" % (
            k, v, ("%d 分钟" % round(h * 60)) if (h * 60) < 60 else ("%g 小时" % h)))
    print("-" * 56)


def main():
    if "--show" in sys.argv:
        show(json.load(open(CFG, encoding="utf-8")))
        return 0
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    game = sys.argv[1].strip()
    try:
        hours = float(sys.argv[2])
    except ValueError:
        print("周期必须是数字小时，收到 %r" % sys.argv[2])
        return 2
    if not (0.25 <= hours <= 24):
        print("周期需在 0.25h（15 分钟）~ 24h 之间，收到 %r" % hours)
        return 2

    c = json.load(open(CFG, encoding="utf-8"))
    run = c.setdefault("运行", {})
    d = run.setdefault("采集周期小时", {})
    old = d.get(game)
    if old is not None and float(old) == hours:
        print("%s 已经是 %sh，无需改动。" % (game, hours))
        show(c)
        return 0

    bdir = BACKUP_DIR.rstrip("/\\").replace("\\", "/")
    os.makedirs(bdir, exist_ok=True)
    bak = "%s/config.before_interval_%s.json" % (bdir, time.strftime("%Y%m%d_%H%M%S"))
    shutil.copy2(CFG, bak)
    print("已备份 -> %s" % bak)

    d[game] = hours
    run["采集间隔分钟"] = min(int(run.get("采集间隔分钟", 60) or 60),
                              max(15, int(hours * 60)))
    c.setdefault("_变更记录", {})["2.12.0_AION2改30分钟"] = {
        "时间": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "改动": {game: hours},
        "说明": "用户 2026-10-02 要求 AION2 金币采集+监控自动采集改为每 30 分钟一轮。"
                "心跳 d4follow-collect.timer 已是 15min，能等到 0.5h 档。",
    }
    io.open(CFG, "w", encoding="utf-8", newline="").write(
        json.dumps(c, ensure_ascii=False, indent=2))

    chk = json.load(open(CFG, encoding="utf-8"))
    got = ((chk.get("运行") or {}).get("采集周期小时") or {}).get(game)
    if got is None or float(got) != hours:
        shutil.copy2(bak, CFG)
        print("写入校验失败，已用备份还原。")
        return 1

    print("%s 采集周期：%s -> %sh（%d 分钟）"
          % (game, old, hours, round(hours * 60)))
    print("提示：需 systemctl restart d4follow 才生效。")
    show(chk)
    return 0


if __name__ == "__main__":
    sys.exit(main())
