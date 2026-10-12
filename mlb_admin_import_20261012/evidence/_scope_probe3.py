# -*- coding: utf-8 -*-
"""修复 axios 括号编码后，重新核验 scope。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from admin_api_client import (AdminApiClient, SCOPE_FC27_PLAYERS,
                              SCOPE_MLB26_PLAYERS, build_query)

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
user = cred["P2PAH_USERNAME"]
pwd = cred["P2PAH_PASSWORD"]

c = AdminApiClient(log=lambda *a: print(*a, flush=True))
st = c.login_with_ocr(user, pwd)
print("token_len =", len(st.token))
print("identity ok:", c.verify_identity())

for label, scope in (("FC27已知", SCOPE_FC27_PLAYERS), ("MLB猜测", SCOPE_MLB26_PLAYERS)):
    try:
        data = c.list_models(gid=scope["gid"], cid=scope["cid"], page=1, limit=5)
        rows = data.get("list") or []
        print("=== %s(%s/%s) -> total=%s 返回%d行"
              % (label, scope["gid"], scope["cid"], data.get("total"), len(rows)))
        for r in rows[:5]:
            keys = ("id", "name", "pname", "title", "gid", "cid", "sort")
            print("    ", {k: r.get(k) for k in keys if k in r})
    except Exception as e:
        print("=== %s 失败: %r" % (label, e))

# 无筛选，看看全量到底有没有数据
try:
    raw = c._json("GET", "/admin/goods.GoodsMould/index",
                  params={"page": 1, "limit": 3, "order": "sort,desc"})
    print("RAW(no filter):", json.dumps(raw, ensure_ascii=False)[:400])
except Exception as e:
    print("RAW(no filter) 失败:", repr(e))
