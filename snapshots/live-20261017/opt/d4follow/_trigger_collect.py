# -*- coding: utf-8 -*-
"""手动触发一轮采集（kind=collect），并打印 taskId。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8900"
body = json.dumps({"kind": "collect"}).encode("utf-8")
req = urllib.request.Request(BASE + "/api/task", data=body,
                             headers={"Content-Type": "application/json"},
                             method="POST")
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("HTTP", r.status)
        print(r.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("HTTPError", e.code)
    print(e.read().decode("utf-8"))
