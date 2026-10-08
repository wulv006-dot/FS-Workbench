# -*- coding: utf-8 -*-
"""把某个 key 移出跟价监控范围（幂等 · 通用版）。

用途：某规格 IGGM 与我方都没上架 / 用户已下架该行 ⇒ 从 `商品映射.对照项`
与 `p2pah.商品ID映射` 中摘出，并在 `_变更记录` 留痕（只摘行，不删历史）。

⚠️ config 是「活的」（用户会在界面上手动开关跟价），
   所以本脚本**必须在服务器上就地执行**，不要用本地 config 覆盖后再上传。

用法：
    python drop_monitor_item.py --config config.json --key POE2_FR_E1000 \
        --reason "IGGM 未上架该规格；清缓存后我方前端亦读不到，用户下架该行"

    # 先看会改什么，不落盘：
    python drop_monitor_item.py --config config.json --key POE2_FR_E1000 --dry-run
"""
import argparse
import datetime as dt
import io
import json
import shutil
import sys


def find(cfg, key):
    mp = cfg.get("商品映射") or {}
    hit = next((x for x in (mp.get("对照项") or []) if x.get("key") == key), None)
    mid = ((cfg.get("p2pah") or {}).get("商品ID映射") or {})
    return hit, mid.get(key)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--key", required=True, help="要摘出的对照项 key，例如 POE2_FR_E1000")
    ap.add_argument("--reason", default="", help="写进 _变更记录 的原因")
    ap.add_argument("--version", default="", help="新的 config 版本号，留空则不动")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    cfg = json.load(io.open(a.config, encoding="utf-8"))
    mp = cfg.get("商品映射") or {}
    p = cfg.get("p2pah") or {}

    hit, backend_id = find(cfg, a.key)
    if hit is None and backend_id is None:
        print("✅ 已经不在监控范围里了（对照项/商品ID映射 都没有 %s），无需改动。" % a.key)
        return 0

    title = (hit or {}).get("中文名")
    game = (hit or {}).get("游戏")
    print("将移除：key=%s ｜ %s ｜ 游戏=%s ｜ 原后台商品ID=%s" % (a.key, title, game, backend_id))
    print("对照项 %d → %d 条；商品ID映射 %d → %d 条"
          % (len(mp.get("对照项") or []),
             len([x for x in (mp.get("对照项") or []) if x.get("key") != a.key]),
             len((p.get("商品ID映射") or {})),
             len([k for k in (p.get("商品ID映射") or {}) if k != a.key])))
    if a.dry_run:
        print("（dry-run，未落盘）")
        return 0

    bak = a.config + ".bak_" + dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(a.config, bak)

    mp["对照项"] = [x for x in (mp.get("对照项") or []) if x.get("key") != a.key]
    (p.get("商品ID映射") or {}).pop(a.key, None)

    rec = cfg.setdefault("_变更记录", {})
    ver = a.version or cfg.get("版本") or ""
    rec[ver + "_摘出_" + a.key] = {
        "时间": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "动作": "移出跟价范围",
        "key": a.key,
        "中文名": title,
        "原后台商品ID": backend_id,
        "原因": a.reason or "（未填写）",
    }
    if a.version:
        cfg["版本"] = a.version

    io.open(a.config, "w", encoding="utf-8").write(
        json.dumps(cfg, ensure_ascii=False, indent=1))
    print("备份：%s" % bak)
    print("✅ 已移除对照项 %s（%s），原后台ID %s" % (a.key, title, backend_id))
    print("对照项剩余 %d 条（其中 %s %d 条）"
          % (len(mp["对照项"]), game or "-",
             len([x for x in mp["对照项"] if x.get("游戏") == game])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
