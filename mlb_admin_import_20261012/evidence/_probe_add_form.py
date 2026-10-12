# -*- coding: utf-8 -*-
"""拉取「新增模型」表单的完整契约（只读 GET /add）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from admin_api_client import AdminApiClient

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: None)
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

r = c._json("GET", "/admin/goods.GoodsMould/add")
(HERE / "add_form_contract.json").write_text(
    json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
print("=== GET /admin/goods.GoodsMould/add 返回结构 ===")
print(json.dumps(r, ensure_ascii=False, indent=2)[:3000])

# 顺便：编辑态表单（拿一条 MLB 已有模型的 edit 结构做对照）
print("\n=== GET /admin/goods.GoodsMould/edit?id=44234597 （MLB 已有模型，只读）===")
try:
    r2 = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": 44234597})
    (HERE / "edit_form_contract_mlb.json").write_text(
        json.dumps(r2, ensure_ascii=False, indent=2), encoding="utf-8")
    row = (r2.get("data") or {}).get("row") or {}
    print("  字段:", sorted(row.keys()))
    print("  抽样:", json.dumps({k: row.get(k) for k in
          ("id", "gid", "cid", "title", "price", "discount", "is_put", "status", "min_qty", "sort")},
          ensure_ascii=False))
    print("  more.extend:", json.dumps((row.get("more") or {}).get("extend"), ensure_ascii=False)[:300])
except Exception as e:
    print("  异常:", repr(e))
