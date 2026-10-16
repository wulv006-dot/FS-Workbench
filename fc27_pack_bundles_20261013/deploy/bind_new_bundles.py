#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 4 个新建包的产品绑定写入 config（走正常 API + revision 校验）。

绑定值来自 discover-products 的实测结果（已核对三平台齐全）。
"""
import json
import urllib.error
import urllib.request

API = "http://127.0.0.1:8904"
BIND = {
    "premier-league-player-bundle": {"ps": 185753157, "xbox": 185753193, "pc": 185753229},
    "barcelona-player-bundle": {"ps": 185753049, "xbox": 185753085, "pc": 185753121},
    "lyon-women-player-bundle": {"ps": 185752941, "xbox": 185752977, "pc": 185753013},
    "laliga-ea-sports-player-bundle": {"ps": 185752833, "xbox": 185752869, "pc": 185752905},
}


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "X-Forwarded-Proto": "https"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


st, state = call("GET", "/api/state")
print("GET state:", st, "revision:", state.get("revision"))
bundles = []
for b in state["bundles"]:
    pid = b.get("products") or {}
    fresh = BIND.get(b["id"])
    products = dict(pid) if pid else (fresh or {})
    bundles.append({
        "id": b["id"], "title": b["title"],
        "players": [{"futbin_id": p["futbin_id"], "position": p["position"]}
                    for p in b["players"]],
        "products": products,
    })
changed = [b["id"] for b in bundles if BIND.get(b["id"]) and b["products"] == BIND[b["id"]]]
print("将写入绑定的包:", changed)
st2, r2 = call("POST", "/api/config", {
    "expected_revision": state["revision"],
    "settings": state["settings"],
    "bundles": bundles,
})
print("POST config:", st2, r2)
st3, s3 = call("GET", "/api/state")
for b in s3["bundles"]:
    print(" ", b["id"], "->", b.get("products"))
