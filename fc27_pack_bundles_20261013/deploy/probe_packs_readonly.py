#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只读侦察：FC27 Packs 捆绑包产品的后台字段结构（零写入）。

- 登录 admin-api.p2pah.cn（复用 /opt/mlb-admin-write 已部署的 admin_api_client + _cred.json）
- GET /admin/goods.Goods/edit?id=<gid> 拉三个捆绑包产品详情
- 只打印结构字段，绝不打印凭据/完整表单
"""
import json
import sys

sys.path.insert(0, "/opt/mlb-admin-write/src")
from admin_api_client import AdminApiClient  # noqa: E402

IDS = [185327265, 185327726, 185327193]
KEEP = ("id", "gid", "cid", "mid", "title", "price", "unit_price", "num",
        "discount", "status", "site_id", "site_ids", "aid", "aids",
        "type", "category_id", "min", "is_del", "update_time")


def cred():
    with open("/opt/mlb-admin-write/_cred.json", "r", encoding="utf-8") as fh:
        data = json.load(fh)
    user = data.get("P2PAH_USERNAME") or data.get("username")
    pwd = data.get("P2PAH_PASSWORD") or data.get("password")
    if user and pwd:
        return str(user), str(pwd)
    raise SystemExit("cred json keys unknown: %s" % list(data))


def slim(row):
    if not isinstance(row, dict):
        return row
    out = {}
    for k, v in row.items():
        if k in KEEP:
            out[k] = v
        elif isinstance(v, (str, int, float)) and len(str(v)) < 60:
            out[k] = v
    return out


def main():
    user, pwd = cred()
    cli = AdminApiClient()
    cli.login_with_ocr(user, pwd)
    print("LOGIN_OK")
    for pid in IDS:
        try:
            env = cli._json("GET", "/admin/goods.Goods/edit", params={"id": pid})
            row = (env.get("data") or {}).get("row") if isinstance(env.get("data"), dict) else None
            if row is None:
                print(json.dumps({"id": pid, "result": "no_row",
                                  "env_keys": list(env.keys()),
                                  "msg": env.get("msg")}, ensure_ascii=False))
                continue
            print(json.dumps({"id": pid, "row": slim(row)}, ensure_ascii=False)[:1800])
        except Exception as exc:
            print(json.dumps({"id": pid, "error": repr(exc)[:200]}, ensure_ascii=False))
    # 顺带按 gid=1327 搜 Bundle 关键词（axios 括号格式），确认列表可按标题过滤
    try:
        env = cli._json("GET", "/admin/goods.Goods/index", params={
            "page": 1, "limit": 20,
            "search": [{"field": "gid", "operator": "=", "val": "1327"},
                       {"field": "title", "operator": "LIKE", "val": "Bundle"}],
        })
        data = env.get("data") or {}
        rows = data.get("list") or []
        print(json.dumps({"search_bundle": {"total": data.get("total"),
              "rows": [{k: r.get(k) for k in ("id", "title", "cid", "price", "site_id")
                        if k in r} for r in rows[:10]]}}, ensure_ascii=False)[:1800])
    except Exception as exc:
        print(json.dumps({"search_error": repr(exc)[:200]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
