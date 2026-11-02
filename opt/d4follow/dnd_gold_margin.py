# -*- coding: utf-8 -*-
"""Dark and Darker 金币「与 IGGM 真价持平」—— 命令行入口

用法：
    python3.9 dnd_gold_margin.py            # DRY-RUN（只算不写，默认）
    python3.9 dnd_gold_margin.py --apply    # 真写后台（全自动链路用这个）

退出码：0 = 正常（含「已经持平，不需要改」）；1 = 出错
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import core_dnd_gold  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="D&D 金币跟 IGGM 真价持平")
    ap.add_argument("--apply", action="store_true", help="真的写后台（不加则 DRY-RUN）")
    a = ap.parse_args()

    cfg = json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    print("=== D&D 金币跟 IGGM 真价持平 %s ==="
          % ("真写" if a.apply else "DRY-RUN（不动数据）"))

    d = core_dnd_gold.run(cfg, apply=a.apply)
    print("--- 结果 ---")
    print(json.dumps(d, ensure_ascii=False, indent=1))
    if d.get("action") in ("up", "down") and d.get("ok"):
        return 0
    if d.get("action") == "hold":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
