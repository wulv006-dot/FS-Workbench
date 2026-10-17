# -*- coding: utf-8 -*-
"""最终验收：4 张卡 vs 已有正常模型 的字段对齐（只读）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient  # noqa: E402

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

# 参照：一条已有正常模型
REF_ID = 44234597  # Rafael Flores

CARDS = [
    (44638327, "Dennis Eckersley/99/CP/Athletics/Awards"),
    (44638391, "Ivan Rodriguez/99/C/Marlins/Awards"),
    (44638393, "George Springer/99/CF/Astros/The Show Classics"),
    (44638395, "Andy Pettitte/99/SP/Yankees/Awards"),
]

FIELDS = ("id", "gid", "cid", "top_cid", "title", "icon", "price", "discount",
          "min_qty", "status", "is_put", "is_rec", "sort")


def snapshot(mid):
    d = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": mid})
    row = (d.get("data") or {}).get("row") or {}
    fmt = row.get("_format") or {}
    ext = (row.get("more") or {}).get("extend") or []
    zh = next((e.get("value") for e in ext
               if isinstance(e, dict) and e.get("key") == "zh_title"), None)
    return row, fmt, zh, ext


print("=" * 78, flush=True)
print("参照模型 id=%s" % REF_ID, flush=True)
rrow, rfmt, rzh, rext = snapshot(REF_ID)
print("  title      =", rrow.get("title"), flush=True)
print("  icon       =", rrow.get("icon"), flush=True)
print("  zh_title   =", rzh, flush=True)
print("  more.extend=", json.dumps(rext, ensure_ascii=False)[:120], flush=True)

print("\n" + "=" * 78, flush=True)
print("4 张新卡逐条核对", flush=True)
allok = True
res = []
for mid, title in CARDS:
    row, fmt, zh, ext = snapshot(mid)
    # 产品数
    pd = c._json("GET", "/admin/goods.Goods/index",
                 params={"page": 1, "limit": 1,
                         "search": [{"field": "mid", "operator": "=", "val": str(mid)}]})
    pt = (pd.get("data") or {}).get("total")
    checks = {
        "icon>0": bool(row.get("icon")),
        "zh_title": bool(zh),
        "icon_format": bool(fmt.get("icon_format")),
        "products=48": int(pt or 0) == 48,
        "title": (row.get("title") or "").strip() == title,
        "gid/cid": row.get("gid") == 927 and row.get("cid") == 8233,
    }
    ok = all(checks.values())
    allok = allok and ok
    print("\n  mid=%s %s" % (mid, "✅" if ok else "⚠️"), flush=True)
    print("    title    = %s" % row.get("title"), flush=True)
    print("    icon     = %s" % row.get("icon"), flush=True)
    print("    zh_title = %s" % zh, flush=True)
    print("    price    = %s   is_put=%s  产品数=%s" % (row.get("price"), row.get("is_put"), pt), flush=True)
    if not ok:
        print("    未过项:", [k for k, v in checks.items() if not v], flush=True)
    res.append({"mid": mid, "title": row.get("title"), "icon": row.get("icon"),
                "zh_title": zh, "icon_format": fmt.get("icon_format"),
                "price": row.get("price"), "is_put": row.get("is_put"),
                "products": pt, "checks": checks, "ok": ok})

print("\n" + "=" * 78, flush=True)
print("总判定:", "✅ 4 张卡全部达标（与已有模型字段对齐）" if allok else "⚠️ 存在未达标项", flush=True)

(HERE / "_acceptance_final.json").write_text(
    json.dumps({"ref": {"title": rrow.get("title"), "icon": rrow.get("icon"), "zh_title": rzh},
                "cards": res, "all_ok": allok}, ensure_ascii=False, indent=2),
    encoding="utf-8")
print("已写入 _acceptance_final.json", flush=True)
