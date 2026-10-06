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
import math
import os
import subprocess
import sys
import time
import uuid
import tempfile
from write_contract import serialized, execute_bound_plan, validate_envelope, persistence_capability
from pathlib import Path

BASE = "https://admin-api.p2pah.cn"
DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = str(Path(os.environ.get("NBA_DATA_DIR") or (Path.home()/".local"/"state"/"fs-nba-reprice")).resolve())
if Path(DATA_DIR).is_relative_to(Path(DIR).resolve().parent):
    raise RuntimeError("NBA_DATA_DIR_MUST_BE_OUTSIDE_SOURCE")
TOKEN_FILE = os.path.join(DATA_DIR, "_token.txt")
CK_FILE = os.path.join(DATA_DIR, "_ck.txt")

def prepare_runtime():
    os.makedirs(DATA_DIR, mode=0o700, exist_ok=True)

def private_write(path, value):
    prepare_runtime()
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
CRED = {
    "username": os.environ.get("P2PAH_ADMIN_USERNAME", ""),
    "password": os.environ.get("P2PAH_ADMIN_PASSWORD", ""),
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/154.0.0.0 Safari/537.36")

# 目标: gid=1329 NBA 2K27 / mid=42278471 产品模型 VC / site_id=0 ALL
TARGET_MID = "42278471"
TARGET_GID = "1329"
# aid -> 平台
AID_MAP = {"21595": "PlayStation 5", "21591": "Xbox Series X|S", "21597": "PC Platform"}


_runtime_serialized = serialized(DATA_DIR)


@_runtime_serialized
def _curl(method, url, headers=None, data=None, out_file=None, timeout=40,
          cookie_jar=True):
    """返回 (http_code, bytes)。out_file 非空时把响应体写到该文件。"""
    prepare_runtime()
    if out_file:
        dst=out_file
    else:
        fd,dst=tempfile.mkstemp(dir=DATA_DIR,prefix=".api-response-")
        os.close(fd)
    # Precreate outputs privately before curl overwrites them.
    private_write(dst, "")
    if cookie_jar and not os.path.exists(CK_FILE):
        private_write(CK_FILE, "")
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
    try:
        r = subprocess.run(cmd, capture_output=True)
        code = r.stdout.decode("utf-8", "ignore").strip()
        body = open(dst, "rb").read() if os.path.exists(dst) else b""
        return code, body
    finally:
        if not out_file and os.path.exists(dst):
            os.unlink(dst)


def api(method, path, data=None, token=True):
    hdr = {}
    if token:
        tk = open(TOKEN_FILE, encoding="utf-8").read().strip() if os.path.exists(TOKEN_FILE) else ""
        if tk:
            hdr["batoken"] = tk
    code, body = _curl(method, BASE + path, hdr, data)
    try:
        return code, json.loads(body.decode("utf-8", "ignore"))
    except Exception:
        return code, body.decode("utf-8", "ignore")


@_runtime_serialized
def login():
    captcha_id = str(uuid.uuid4())
    png = os.path.join(DATA_DIR, "_adm_cap.png")
    _curl("GET", f"{BASE}/api/common/captcha?server=1&id={captcha_id}",
          {"Accept": "image/avif,image/webp,*/*"}, out_file=png, cookie_jar=True)
    ocr = os.path.join(DIR, "ocr_captcha.py")
    if os.environ.get("PYTHON"):
        env_py = os.environ["PYTHON"]
    elif os.name == "nt":
        env_py = r"C:\Users\Administrator\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
    else:
        env_py = "python3"
    r = subprocess.run([env_py, ocr, png], capture_output=True)
    code = r.stdout.decode("utf-8", "ignore").strip()
    print("[captcha] recognition completed")
    body = {"username": CRED["username"], "password": CRED["password"],
            "captcha": code, "captcha_id": captcha_id, "keep": True, "loading": False}
    status, js = api("POST", "/admin/login", body, token=False)
    print("[login] completed")
    if isinstance(js, dict) and js.get("code") == 1:
        tk = js["data"]["token"]
        private_write(TOKEN_FILE, tk)
        print("[login] session saved")
        return tk
    return None


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
        raise RuntimeError("UPSTREAM_PRODUCT_READ_FAILED")
    return js["data"]["row"]


@_runtime_serialized
def write_one(tid, unit_price):
    """把 unit_price 写回指定产品, 返回 (ok, msg, old)"""
    if os.environ.get("WRITE_READY") != "true":
        raise RuntimeError("WRITE_DISABLED")
    if type(unit_price) not in (int, float) or not math.isfinite(unit_price) or unit_price <= 0:
        raise ValueError("INVALID_PRICE")
    if tid not in {t["id"] for t in TARGETS}:
        raise ValueError("INVALID_PRODUCT")
    row = read_one(tid)
    old = row.get("unit_price")
    row["unit_price"] = unit_price
    for k in ("_format", "_extend"):
        row.pop(k, None)
    code, js = api("POST", "/admin/goods.Goods/edit", row)
    ok = isinstance(js, dict) and js.get("code") == 1
    msg = "UPSTREAM_WRITE_CONFIRMED" if ok else "UPSTREAM_WRITE_FAILED"
    return ok, msg, old


@_runtime_serialized
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
    """探测 token 是否有效, 失效则重新登录"""
    code, js = api("GET", "/admin/goods.Goods/index?page=1&limit=1")
    if isinstance(js, dict) and js.get("code") == 1:
        return True
    print("[ensure_token] token 失效, 重新登录...", file=sys.stderr)
    return login() is not None


def _write_prices(data):
    """从 JSON 文件读价格并写入; 打印一行 JSON 结果"""
    if os.environ.get("WRITE_READY") != "true" or not isinstance(data, dict) or data.get("confirm") != "NBA_PRICE_APPLY":
        return {"ok":False,"error":"WRITE_DISABLED_OR_UNCONFIRMED"}
    prices = data.get("prices") if isinstance(data, dict) else None
    if not prices:
        return {"ok": False, "error": "缺少 prices"}
    area2key = {"PS": "PlayStation 5", "PlayStation 5": "PlayStation 5",
                "Xbox": "Xbox Series X|S", "XBOX": "Xbox Series X|S",
                "Xbox Series X|S": "Xbox Series X|S",
                "PC": "PC Platform", "PC Platform": "PC Platform"}
    pmap = {}
    for k, v in prices.items():
        key = area2key.get(str(k))
        if not key:
            return {"ok": False, "error": f"未知平台 {k}"}
        if type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 9007199254740991:
            return {"ok": False, "error": f"{key} 售价非法: {v}"}
        pmap[key] = round(float(v), 4)

    if not ensure_token():
        return {"ok":False,"error":"UPSTREAM_LOGIN_FAILED"}
    results, verify = [], {}
    for t in TARGETS:
        if t["key"] not in pmap:
            continue
        try:
            ok, msg, old = write_one(t["id"], pmap[t["key"]])
        except Exception as e:
            ok, msg, old = False, "UPSTREAM_WRITE_FAILED", None
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
    return {"ok": allok, "results": results, "verify": verify}



def write_from_file(path_in):
    identity={}
    try:
        if os.environ.get("WRITE_READY") != "true":
            raise RuntimeError("WRITE_DISABLED")
        with open(path_in, encoding="utf-8") as source:
            envelope=json.load(source)
        request_id,plan_hash,plan=validate_envelope(envelope)
        identity={'requestId':request_id,'planSha256':plan_hash,'operator':plan['operator'],
                  'persistence':persistence_capability()}
        result=execute_bound_plan(DATA_DIR,envelope,_write_prices)
    except (ValueError,RuntimeError,OSError):
        # No raw file, credential, upstream response or exception text in output.
        # A lock/read/setup failure may concern an existing in-flight request.
        result={**identity,"ok":False,"error":"BOUND_WRITE_REFUSED","state":"unknown" if identity else "rejected"}
    print(json.dumps(result,ensure_ascii=False))


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

