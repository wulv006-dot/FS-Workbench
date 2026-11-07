# -*- coding: utf-8 -*-
"""取后台价表表头 + 一行原文，确认价格单位口径。"""
import json
import re
import sys

sys.path.insert(0, "/opt/d4follow")
sys.path.insert(0, "/opt/fs-order-session")
from core_p2pah import P2PAHClient  # noqa: E402

CFG = json.load(open("/opt/d4follow/config.json", encoding="utf-8"))
client = P2PAHClient(CFG, log=lambda *a, **k: None)
html = client.request("/game/admin_game_price/index.html?gid=1364",
                      headers={"Accept": "text/html"})
open("/tmp/wowf_pricepage.html", "w", encoding="utf-8").write(html)

ths = re.findall(r"<th[^>]*>([\s\S]*?)</th>", html)
print("== 表头 ==")
for i, t in enumerate(ths):
    txt = re.sub(r"<[^>]+>", " ", t)
    txt = re.sub(r"\s+", " ", txt).strip()
    if txt:
        print(f"  [{i}] {txt[:40]}")

print("\n== 含 22716 的 <tr> 原文（去标签）==")
for t in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", html):
    if "22716" in t:
        txt = re.sub(r"<[^>]+>", "|", t)
        txt = re.sub(r"\|+", "|", txt)
        print(" ", re.sub(r"\s+", " ", txt).strip()[:600])
        break

print("\n== 页面上出现的单位词 ==")
for kw in ["单位", "每金", "千金", "1000", "万金", "Gold", "gold", "1G", "单位:"]:
    n = html.count(kw)
    if n:
        print(f"  {kw!r} x{n}")
