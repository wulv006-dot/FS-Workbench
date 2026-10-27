#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
p2pah 新后台 (admin-api.p2pah.cn) API 助手
==========================================
用途: 读取/写入 NBA 2K27 VC 三端售价

关键点(2026-09-30 逆向后确认):
  - WAF: 必须带完整浏览器头(UA/sec-ch-ua/Sec-Fetch-*/server/think-lang), 否则 302
  - 登录: POST /admin/login  body {username,password,captcha,captcha_id,keep}
          验证码 GET /api/common/captcha?server=1&id=<uuid>  (PNG)
          鉴权头: batoken
  - 列表筛选参数是 search[N][field] / search[N][val] / search[N][operator]
    (不是 filter! 这是之前筛选不生效的原因)
  - 产品编辑: GET /admin/goods.Goods/edit?id=<id>  ->  POST /admin/goods.Goods/edit

用法:
  python p2pah_api.py login                 # 登录并保存 token
  python p2pah_api.py find                  # 定位三端 VC 产品(只读)
  python p2pah_api.py edit <id>             # 打印编辑表单(只读)
"""
import json
import os
import subprocess
import sys
import time
import uuid

def _fs_shared_admin_token():
    import importlib.util
    spec = importlib.util.spec_from_file_location('fs_shared_admin', '/opt/fs-shared-session/shared_admin.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    token, _ = module.admin_token_from_service()
    if not token:
        raise RuntimeError('FS_SHARED_SESSION_UNAVAILABLE')
    return token


BASE = "http://127.0.0.1:8911"
DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(DIR, "_token.txt")
CK_FILE = os.path.join(DIR, "_ck.txt")
CRED = {}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")

# 目标: gid=1329 NBA 2K27 / mid=42278471 产品模型 VC / site_id=0 ALL
TARGET_MID = "42278471"
TARGET_GID = "1329"
# aid -> 平台
AID_MAP = {"21595": "PlayStation 5", "21591": "Xbox Series X|S", "21597": "PC Platform"}


_TMP_BODY = os.path.join(DIR, "_api_body.tmp")


def _curl(method, url, headers=None, data=None, out_file=None, timeout=40,
          cookie_jar=True):
    """返回 (http_code, bytes)。out_file 非空时把响应体写到该文件。"""
    dst = out_file or _TMP_BODY
    cmd = ["curl", "-sS", "-g", "-o", dst, "-w", "%{http_code}",
           "--max-time", str(timeout), "-X", method,
           "-H", f"User-Agent: {UA}",
           "-H", "sec-ch-ua: \"Chromium\";v=\"154\", \"Not:A-Brand\";v=\"24\"",
           "-H", "sec-ch-ua-mobile: ?0",
           "-H", "sec-ch-ua-platform: \"Windows\"",
           "-H", "Sec-Fetch-Dest: empty",
           "-H", "Sec-Fetch-Mode: cors",
           "-H", "Sec-Fetch-Site: same-site",
           "-H", "Origin: https://admin.p2pah.cn",
           "-H", "Referer: https://admin.p2pah.cn/",
           "-H", "server: true",
           "-H", "think-lang: zh-cn",
           "-H", "Accept: application/json, text/plain, */*"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", json.dumps(data)]
    if cookie_jar and os.path.exists(CK_FILE):
        cmd += ["-b", CK_FILE, "-c", CK_FILE]
    cmd.append(url)
    r = subprocess.run(cmd, capture_output=True)
    code = r.stdout.decode("utf-8", "ignore").strip()
    body = open(dst, "rb").read() if os.path.exists(dst) else b""
    return code, body


def api(method, path, data=None, token=True):
    if path in ('/admin/index/login', '/api/common/refreshToken'):
        raise RuntimeError('FS_SHARED_AUTH_ONLY')
    hdr = {}
    if token:
        tk = _fs_shared_admin_token()
        if tk:
            hdr["batoken"] = tk
    code, body = _curl(method, BASE + path, hdr, data)
    try:
        return code, json.loads(body.decode("utf-8", "ignore"))
    except Exception:
        return code, body.decode("utf-8", "ignore")


def login():
    return _fs_shared_admin_token()


def find_vc():
    """用 search[] 定位 mid=42278471 & site_id=0 的三端产品"""
    q = ("search[0][field]=mid&search[0][val]=" + TARGET_MID + "&search[0][operator]=%3D"
         "&search[1][field]=site_id&search[1][val]=0&search[1][operator]=%3D")
    status, js = api("GET", f"/admin/goods.Goods/index?page=1&limit=50&{q}")
    print("status:", status)
    if not isinstance(js, dict):
        print(js[:500])
        return
    lst = (js.get("data") or {}).get("list") or []
    print("total:", (js.get("data") or {}).get("total"), " got:", len(lst))
    for r in lst:
        aid = str(r.get("aid"))
        print(f"  id={r.get('id'):<12} aid={aid:<6} {AID_MAP.get(aid, '?'):<18} "
              f"cid={r.get('cid')} site={r.get('site_id')} gid={r.get('gid')} "
              f"price={r.get('price')} unit_price={r.get('unit_price')} "
              f"m_cost={r.get('m_cost')} m_rate={r.get('m_rate')} title={r.get('title')!r}")


def show_edit(gid):
    status, js = api("GET", f"/admin/goods.Goods/edit?id={gid}")
    print("status:", status)
    if isinstance(js, dict):
        row = (js.get("data") or {}).get("row") or {}
        print(json.dumps(row, ensure_ascii=False, indent=1)[:6000])
    else:
        print(js[:500])


# ---------------------------------------------------------------- 写入
TARGETS = [
    {"key": "PlayStation 5", "id": 165466527, "aid": "21595"},
    {"key": "Xbox Series X|S", "id": 165466561, "aid": "21591"},
    {"key": "PC Platform", "id": 165466595, "aid": "21597"},
]


def read_one(tid):
    code, js = api("GET", f"/admin/goods.Goods/edit?id={tid}")
    if not isinstance(js, dict) or js.get("code") != 1:
        raise RuntimeError(f"读取 {tid} 失败: {js}")
    return js["data"]["row"]


def write_one(tid, unit_price):
    """把 unit_price 写回指定产品, 返回 (ok, msg, old)"""
    row = read_one(tid)
    old = row.get("unit_price")
    row["unit_price"] = unit_price
    for k in ("_format", "_extend"):
        row.pop(k, None)
    code, js = api("POST", "/admin/goods.Goods/edit", row)
    ok = isinstance(js, dict) and js.get("code") == 1
    msg = js.get("msg") if isinstance(js, dict) else str(js)[:200]
    return ok, msg, old


def apply_prices(price_map):
    """price_map: {'PlayStation 5':0.1504, 'Xbox Series X|S':0.1504, 'PC Platform':0.0859}"""
    print("=== 写入前 ===")
    for t in TARGETS:
        r = read_one(t["id"])
        print(f"  {t['key']:<18} id={t['id']} aid={t['aid']} unit_price={r.get('unit_price')}")
    print("\n=== 写入 ===")
    results = []
    for t in TARGETS:
        new = price_map[t["key"]]
        ok, msg, old = write_one(t["id"], new)
        print(f"  {t['key']:<18} {old} -> {new}  {'OK' if ok else 'FAIL'} {msg}")
        results.append({"platform": t["key"], "id": t["id"], "aid": t["aid"],
                        "old": old, "new": new, "ok": ok, "msg": msg})
    print("\n=== 写入后复核 ===")
    for t in TARGETS:
        r = read_one(t["id"])
        mark = "✓" if float(r.get("unit_price") or 0) == float(price_map[t["key"]]) else "✗"
        print(f"  {t['key']:<18} unit_price={r.get('unit_price')} {mark}")
    return results


def ensure_token():
    return bool(_fs_shared_admin_token())


def write_from_file(path_in):
    """从 JSON 文件读价格并写入; 打印一行 JSON 结果"""
    data = json.load(open(path_in, encoding="utf-8"))
    prices = data.get("prices") if isinstance(data, dict) else None
    if not prices:
        print(json.dumps({"ok": False, "error": "缺少 prices"}, ensure_ascii=False))
        return
    area2key = {"PS": "PlayStation 5", "PlayStation 5": "PlayStation 5",
                "Xbox": "Xbox Series X|S", "XBOX": "Xbox Series X|S",
                "Xbox Series X|S": "Xbox Series X|S",
                "PC": "PC Platform", "PC Platform": "PC Platform"}
    pmap = {}
    for k, v in prices.items():
        key = area2key.get(str(k))
        if not key:
            print(json.dumps({"ok": False, "error": f"未知平台 {k}"}, ensure_ascii=False))
            return
        if not (float(v) > 0):
            print(json.dumps({"ok": False, "error": f"{key} 售价非法: {v}"}, ensure_ascii=False))
            return
        pmap[key] = round(float(v), 4)

    ensure_token()
    results, verify = [], {}
    for t in TARGETS:
        if t["key"] not in pmap:
            continue
        try:
            ok, msg, old = write_one(t["id"], pmap[t["key"]])
        except Exception as e:
            ok, msg, old = False, str(e), None
        results.append({"platform": t["key"], "area": {"PlayStation 5": "PS", "Xbox Series X|S": "Xbox",
                                                       "PC Platform": "PC"}[t["key"]],
                        "id": t["id"], "aid": t["aid"], "old": old,
                        "new": pmap[t["key"]], "ok": ok, "msg": msg})
    # 复核
    for t in TARGETS:
        if t["key"] not in pmap:
            continue
        try:
            cur = float(read_one(t["id"]).get("unit_price") or 0)
        except Exception:
            cur = None
        verify[t["key"]] = {"current": cur, "expect": pmap[t["key"]],
                            "match": cur is not None and abs(cur - pmap[t["key"]]) < 1e-6}
    allok = all(r["ok"] for r in results) and all(v["match"] for v in verify.values())
    print(json.dumps({"ok": allok, "results": results, "verify": verify}, ensure_ascii=False))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "find"
    if cmd == "login":
        login()
    elif cmd == "find":
        find_vc()
    elif cmd == "edit":
        show_edit(sys.argv[2])
    elif cmd == "write":
        write_from_file(sys.argv[2])
        sys.exit(0)
    elif cmd == "noop":
        # 安全验证: 把当前值原样写回, 不改变任何价格
        cur = {}
        for t in TARGETS:
            cur[t["key"]] = read_one(t["id"]).get("unit_price")
        print("[noop] 当前值原样回写:", cur)
        apply_prices(cur)
    elif cmd == "apply":
        # 从 prices.json 读目标价写入
        pm = json.load(open(os.path.join(DIR, "prices.json"), encoding="utf-8"))
        apply_prices({k: float(v) for k, v in pm.items()})

