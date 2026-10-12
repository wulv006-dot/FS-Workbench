# -*- coding: utf-8 -*-
"""服务器侧只读取证：4 张目标卡状态（复用生产 Writer 的只读方法，零自造轮子）。

不写任何东西。
"""
import json
import sys
import time

sys.path.insert(0, "/opt/mlb-admin-write/src")

import admin_api_client as C   # noqa: E402
import mlb_write_cards as W    # noqa: E402

RESULT = "/opt/mlb-admin-write/evidence/_result.json"
CRED = "/opt/mlb-admin-write/_cred.json"

cred = json.load(open(CRED, encoding="utf-8"))
data = json.load(open(RESULT, encoding="utf-8"))
cards = [c for c in data.get("cards", []) if c.get("include")]
print("目标卡: %d 张 | GID=%s CID=%s" % (len(cards), W.GID, W.CID))

cl = C.AdminApiClient(log=lambda *a: print(*a, flush=True))
ok = False
for attempt in range(10):
    try:
        cl.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])
        ok = True
        break
    except Exception as e:
        print("  登录尝试 %d 失败: %r" % (attempt + 1, e))
        time.sleep(1)
if not ok:
    sys.exit("[X] 连续登录失败")

w = W.Writer(cl, dry_run=True, log=lambda *a: None)
print("=" * 76)

summary = []
for card in cards:
    title = card["product_name"]
    exp_hash = card.get("hash")
    rec = {"title": title, "expected_zh": exp_hash}
    print("[%s]" % title)
    print("   期望 zh_title: %s" % exp_hash)
    try:
        row = w.find_model(title)
        if row is None:
            print("   ❌ 后台未找到（需新增）")
            rec["verdict"] = "missing"
            summary.append(rec)
            continue
        mid = row.get("id")
        rec["mid"] = mid
        ed = cl._json("GET", "/admin/goods.GoodsMould/edit", params={"id": mid})
        r = (ed.get("data") or {}).get("row") or {}
        icon = r.get("icon")
        zh = next((e.get("value") for e in (r.get("more") or {}).get("extend") or []
                   if isinstance(e, dict) and e.get("key") == "zh_title"), None)
        nprod = w.products_of(mid)
        rec.update({"icon": icon, "zh": zh, "products": nprod})
        zh_ok = (zh == exp_hash)
        icon_ok = bool(icon)
        prod_ok = (nprod is not None and int(nprod) >= W.EXPECTED_PRODUCTS)
        rec["verdict"] = "complete" if (zh_ok and icon_ok and prod_ok) else "incomplete"
        print("   ✅ mid=%s" % mid)
        print("      icon       = %s        %s" % (icon, "OK" if icon_ok else "缺失"))
        print("      zh_title   = %s" % zh)
        print("      zh 匹配    = %s" % zh_ok)
        print("      产品数     = %s / 期望 %s   %s" % (nprod, W.EXPECTED_PRODUCTS,
                                                        "OK" if prod_ok else "不足"))
    except Exception as e:
        print("   取证失败: %r" % e)
        rec["verdict"] = "error:%r" % e
    summary.append(rec)

print("=" * 76)
print("汇总：")
n_complete = 0
for r in summary:
    v = r.get("verdict")
    tag = {"complete": "✅ 已完整（会被幂等跳过）",
           "missing": "➕ 后台缺失（需要新增）",
           "incomplete": "⚠️ 已存在但字段不全（需要补齐）"}.get(
        v, "❌ %s" % v)
    if v == "complete":
        n_complete += 1
    print("  %-56s %s" % (r["title"][:54], tag))
print()
print("完整 %d / %d" % (n_complete, len(summary)))
print("只读取证完成，未做任何写入。")

json.dump(summary, open("/opt/mlb-admin-write/evidence/_live_verify.json", "w",
                        encoding="utf-8"), ensure_ascii=False, indent=2)
