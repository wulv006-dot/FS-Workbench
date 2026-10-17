# -*- coding: utf-8 -*-
"""取证 4：拉实时竞品/前台数据，判定 3 处 X1000 错位是「配置缓存过期」还是「IGGM 真的是 100 装」。只读。"""
import glob
import io
import json
import os

CFG = "/opt/d4follow/config.json"
D4 = "暗黑破坏神4"


def main():
    cfg = json.load(io.open(CFG, encoding="utf-8"))
    for k in ("iggm", "千岛", "运行", "前端", "同族联动", "引擎"):
        print("=" * 70)
        print("### %s" % k)
        print(json.dumps(cfg.get(k), ensure_ascii=False, indent=1)[:3500])
        print()

    print("=" * 70)
    print("### 数据目录内容")
    ddir = (cfg.get("运行") or {}).get("数据目录") or "data"
    for base in (ddir, os.path.join("/opt/d4follow", ddir), "/opt/d4follow/data"):
        if os.path.isdir(base):
            print("--- %s ---" % base)
            for root, dirs, files in os.walk(base):
                if root.count(os.sep) - base.count(os.sep) > 2:
                    continue
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    try:
                        sz = os.path.getsize(fp)
                    except OSError:
                        sz = -1
                    if sz > 200:
                        print("   %-70s %8d" % (fp, sz))
            break

    print()
    print("=" * 70)
    print("### 商品映射.对照项 里的 LAIR_KEY_X1000 全字段")
    for it in (cfg.get("商品映射") or {}).get("对照项") or []:
        if it.get("key") in ("LAIR_KEY_X1000", "GREATER_LAIR_KEY_X1000",
                             "SUPERIOR_LAIR_KEY_X1000",
                             "LAIR_KEY_X100", "LAIR_KEY_X10"):
            print("-" * 60)
            print(json.dumps(it, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
