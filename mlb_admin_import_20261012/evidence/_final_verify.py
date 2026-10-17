# -*- coding: utf-8 -*-
"""最终校验：4 张卡在后台的完整状态（只读）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient  # noqa: E402

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

GID, CID = 927, 8233
TARGETS = [
    "Dennis Eckersley/99/CP/Athletics/Awards",
    "Ivan Rodriguez/99/C/Marlins/Awards",
    "George Springer/99/CF/Astros/The Show Classics",
    "Andy Pettitte/99/SP/Yankees/Awards",
]

# MLB 总数
d = c.list_models(gid=GID, cid=CID, page=1, limit=1)
print("MLB26 模型总数:", d.get("total"), flush=True)

# 全量抓一遍找 4 条
found = {}
page = 1
while page <= 10:
    dd = c.list_models(gid=GID, cid=CID, page=page, limit=200)
    for row in dd.get("list") or []:
        t = (row.get("title") or "").strip()
        if t in TARGETS:
            found[t] = row
    if page * 200 >= int(dd.get("total") or 0):
        break
    page += 1

print("\n%-52s %-10s %-8s %-8s %s" % ("title", "mid", "price", "is_put", "产品数"), flush=True)
print("-" * 92, flush=True)
summary = []
for t in TARGETS:
    row = found.get(t)
    if not row:
        print("%-52s ❌ 未找到" % t[:50], flush=True)
        summary.append({"title": t, "found": False})
        continue
    mid = row.get("id")
    pd = c._json("GET", "/admin/goods.Goods/index",
                 params={"page": 1, "limit": 1,
                         "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
    pt = (pd.get("data") or {}).get("total")
    print("%-52s %-10s %-8s %-8s %s" % (t[:50], mid, row.get("price"), row.get("is_put"), pt), flush=True)
    summary.append({"title": t, "found": True, "mid": mid, "price": row.get("price"),
                    "is_put": row.get("is_put"), "products": pt})

(HERE / "_final_verify.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写入 _final_verify.json", flush=True)
