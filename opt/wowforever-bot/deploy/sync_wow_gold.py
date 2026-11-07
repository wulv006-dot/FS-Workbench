# -*- coding: utf-8 -*-
"""【跑在 187】从 183 的 RPG 改价系统拉最新台账 → 写成看板快照。

数据链路（单向，只读，不碰改价逻辑）
-----------------------------------
183 /opt/d4follow  ── wow-gold-follow.timer（10 分钟一轮）
        │  产出 output/魔兽金币台账_<YYYYMMDD_HHMMSS>.json
        ↓  ssh（内网 172.18.108.183，用既有 transfer_key）
187 sync_wow_gold.py ── 归一化 → state/gold_prices.json
        ↓
bot priceboard 检测文件 mtime 变化 → 原位刷新看板

口径
----
展示 **目标b2c**（改价系统算出来的目标价），不是我自己去后台页面解析。
单位：USD / 每 1 金（台账里「均价元每金」是元/金，×IGGM倍数÷汇率 = 目标b2c，可自证）。
"""
import json
import os
import subprocess
import sys
import tempfile
import time

KEY = "/opt/rpg-migration-20261102/transfer_key"
HOST = "root@172.18.108.183"
REMOTE = "/opt/d4follow/_wow_ledger_dump.py"
OUT = "/opt/wowforever-bot/state/gold_prices.json"

REGION = {"美服": "US", "欧服": "EU", "韩服": "KR", "亚服": "ASIA",
          "台服": "TW"}


def fetch_ledger():
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
           "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
           HOST, "python3", REMOTE]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=90)
    if p.returncode != 0:
        raise RuntimeError("ssh/py failed (%d): %s"
                           % (p.returncode, p.stderr.decode("utf-8", "replace")[:200]))
    raw = p.stdout.decode("utf-8", "replace").strip()
    if not raw:
        raise RuntimeError("empty stdout from 183")
    return json.loads(raw)


def to_epoch(ts):
    """台账 ts 形如 2026-11-07T17:51:14（无时区，按本机时区理解）。"""
    if not ts:
        return int(time.time())
    try:
        return int(time.mktime(time.strptime(ts.replace("T", " "), "%Y-%m-%d %H:%M:%S")))
    except (ValueError, TypeError):
        return int(time.time())


def main():
    try:
        d = fetch_ledger()
    except Exception as e:                                    # noqa: BLE001
        print("[sync] 拉取失败：%s" % e, file=sys.stderr)
        return 1

    plan = d.get("plan") or []
    rows = []
    for r in plan:
        b2c = r.get("目标b2c")
        if b2c is None:
            b2c = r.get("现b2c")
        rows.append({
            "id": str(r.get("后台行ID") or ""),
            "name": r.get("后台名") or "",
            "key": r.get("key") or "",
            "region": REGION.get(r.get("区") or "", "UNKNOWN"),
            "type": r.get("类型") or "UNKNOWN",
            "faction": r.get("阵营") or "?",
            "b2c": round(float(b2c), 6) if b2c is not None else None,
            "current_b2c": r.get("现b2c"),
            "cost": r.get("建议采购成本"),
            "avg_cny_per_g": r.get("均价元每金"),
            "action": r.get("动作"),
        })

    if not rows:
        print("[sync] 台账里没有 plan 行，放弃覆盖", file=sys.stderr)
        return 2

    payload = {
        "rows": rows,
        "fetched_at": to_epoch(d.get("ts")),
        "ledger_ts": d.get("ts"),
        "ledger": d.get("ledger"),
        "gid": d.get("gid"),
        "fx": d.get("fx"),
        "source": "183-ledger",
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(OUT), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, OUT)

    priced = sum(1 for r in rows if r["b2c"])
    print("[sync] OK %d 行（有价 %d） ledger=%s ts=%s"
          % (len(rows), priced, d.get("ledger"), d.get("ts")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
