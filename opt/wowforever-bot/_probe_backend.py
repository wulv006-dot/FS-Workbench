# -*- coding: utf-8 -*-
"""只读验证：从后台 gid=1364 价表读出 40 行 b2c 价（玩家价）。"""
import json
import re
import sys

sys.path.insert(0, "/opt/d4follow")
sys.path.insert(0, "/opt/fs-order-session")

from core_p2pah import P2PAHClient  # noqa: E402

CFG = json.load(open("/opt/d4follow/config.json", encoding="utf-8"))
GID = "1364"
QUIET = lambda *a, **k: None


def parse_name(s):
    region = ("US" if re.search(r"美服|US", s, re.I)
              else "EU" if re.search(r"欧服|EU", s, re.I)
              else "KR" if re.search(r"韩服|KR", s, re.I)
              else "ASIA" if re.search(r"亚服|ASIA|TW", s, re.I)
              else "?")
    fac = ("H" if re.search(r"Horde", s, re.I) else
           "A" if re.search(r"Alliance", s, re.I) else "?")
    low = s.lower()
    if re.search(r"roleplay\s*[- ]?\s*pvp|rp\s*[- ]?pvp", low):
        t = "RP_PVP"
    elif re.search(r"roleplay|(?<![a-z])rp(?![a-z])", low):
        t = "RP"
    elif "hardcore" in low:
        t = "HC"
    elif "normal" in low or "pve" in low:
        t = "NORMAL"
    elif "pvp" in low:
        t = "PVP"
    else:
        t = "?"
    return region, t, fac


client = P2PAHClient(CFG, log=QUIET)
html = client.request("/game/admin_game_price/index.html?gid=%s" % GID,
                      headers={"Accept": "text/html"})
print("HTML len =", len(html))

rows = []
for t in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html)[1:]:
    m = re.search(r"<td>(\d+)</td>", t)
    if not m:
        continue
    rid = m.group(1)
    nm = re.search(r'<span><i class="fa fa-edit text-info"></i>\s*([^<]*)</span>', t)
    cost = re.search(r'jq_showprice_costprice_%s"><i[^>]*></i>\s*([\d.]+)' % rid, t)
    lr = re.search(r'jq_showprice_lirunlv_%s"><i[^>]*></i>\s*([\d.]+)' % rid, t)
    b2c = re.search(r'jq_showprice_b2c_%s"><i[^>]*></i>\s*([\d.]+)' % rid, t)
    name = nm.group(1).strip() if nm else ""
    r, tk, f = parse_name(name)
    rows.append({
        "id": rid, "name": name, "region": r, "type": tk, "faction": f,
        "cost": float(cost.group(1)) if cost else None,
        "margin": float(lr.group(1)) if lr else None,
        "b2c": float(b2c.group(1)) if b2c else None,
    })

print("rows =", len(rows))
print("有 b2c 的 =", sum(1 for r in rows if r["b2c"] is not None))
print()
print(f"{'id':<7}{'区服':<30}{'region':<7}{'type':<7}{'fac':<4}{'cost':>9}{'margin':>8}{'b2c':>10}")
for r in rows[:12]:
    print(f"{r['id']:<7}{r['name'][:28]:<30}{r['region']:<7}{r['type']:<7}{r['faction']:<4}"
          f"{str(r['cost']):>9}{str(r['margin']):>8}{str(r['b2c']):>10}")

fx = float((CFG.get("汇率") or {}).get("USDCNY") or 6.65)
print("\n汇率 USDCNY =", fx)
bad = [r for r in rows if r["cost"] and r["b2c"] and r["margin"]]
if bad:
    ratios = [r["b2c"] / r["cost"] for r in bad]
    print("b2c/cost 比值: min=%.4f max=%.4f" % (min(ratios), max(ratios)))
    r0 = bad[0]
    print("样例 %s: cost=%.4f b2c=%.4f margin=%.3f -> 若按 1/(1-margin)=%.4f"
          % (r0["name"], r0["cost"], r0["b2c"], r0["margin"], 1 / (1 - r0["margin"])))
    print("       b2c/汇率 = %.4f (%s 每金)" % (r0["b2c"] / fx, "USD" if True else ""))

with open("/tmp/wowf_backend_rows.json", "w", encoding="utf-8") as f:
    json.dump({"rows": rows, "fx": fx}, f, ensure_ascii=False, indent=1)
print("\n写出 /tmp/wowf_backend_rows.json")
