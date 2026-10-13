#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读侦察②：gid=1327 + cid=10255(Packs) + site_id=0(ALL) 的捆绑包产品全矩阵。"""
import json
import sys

sys.path.insert(0, "/opt/mlb-admin-write/src")
from admin_api_client import AdminApiClient  # noqa: E402


def cred():
    with open("/opt/mlb-admin-write/_cred.json", "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return str(data["P2PAH_USERNAME"]), str(data["P2PAH_PASSWORD"])


def main():
    user, pwd = cred()
    cli = AdminApiClient()
    cli.login_with_ocr(user, pwd)
    print("LOGIN_OK")
    rows_all = []
    page = 1
    while page <= 10:
        env = cli._json("GET", "/admin/goods.Goods/index", params={
            "page": page, "limit": 100,
            "search": [{"field": "gid", "operator": "=", "val": "1327"},
                       {"field": "cid", "operator": "=", "val": "10255"},
                       {"field": "site_id", "operator": "=", "val": "0"}],
        })
        data = env.get("data") or {}
        rows = data.get("list") or []
        rows_all.extend(rows)
        total = int(data.get("total") or 0)
        if len(rows_all) >= total or not rows:
            break
        page += 1
    out = [{"id": r.get("id"), "title": r.get("title"), "aid": r.get("aid"),
            "uuid": r.get("uuid"), "unit_price": r.get("unit_price"),
            "price": r.get("price"), "discount": r.get("discount"),
            "status": r.get("status"), "mid": r.get("mid")}
           for r in rows_all]
    print(json.dumps({"total": len(rows_all), "rows": out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
