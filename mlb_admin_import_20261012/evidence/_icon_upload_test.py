# -*- coding: utf-8 -*-
"""端到端验证：给模型写 icon（主图）。

链路：
  ① POST https://b2c-api.p2pah.cn/upload/file  → 拿 file.id
  ② POST /admin/goods.GoodsMould/edit          → 写 icon + _format.icon_format
  ③ GET  /admin/goods.GoodsMould/edit?id=      → 回读确认

⛔ 写操作只发一次，绝不自动重试。
"""
import hashlib
import json
import mimetypes
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient, AdminUnknownResult  # noqa: E402

UPLOAD_BASE = "https://b2c-api.p2pah.cn"
SECRET = "DFSAF[WFKWEFL;SDFJKSDLF;JF"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    urllib.request.ProxyHandler({}))


def upload_image(path):
    """上传图片 → 返回 file 字典（含 id / full_url）。"""
    p = Path(path)
    content = p.read_bytes()
    ms = int(time.time() * 1000)
    fields = {
        "token": hashlib.md5(("%d%s" % (ms, SECRET)).encode()).hexdigest(),
        "timestamp": ms, "id": 0, "view": 1, "type": 0, "watermark": 0,
    }
    b = "----wbimg" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts += [f"--{b}\r\n".encode(),
                  f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode(),
                  str(v).encode(), b"\r\n"]
    ct = mimetypes.guess_type(p.name)[0] or "image/png"
    parts += [f"--{b}\r\n".encode(),
              f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'.encode(),
              f"Content-Type: {ct}\r\n\r\n".encode(),
              content, b"\r\n", f"--{b}--\r\n".encode()]
    body = b"".join(parts)
    req = urllib.request.Request(
        UPLOAD_BASE + "/upload/file", data=body, method="POST",
        headers={"User-Agent": UA, "Content-Type": f"multipart/form-data; boundary={b}",
                 "Origin": "https://admin.p2pah.cn", "Referer": "https://admin.p2pah.cn/",
                 "Accept": "application/json, text/plain, */*"})
    with _opener.open(req, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    pic = (j.get("upload") or {}).get("picture") or {}
    if pic.get("code") != 200:
        raise RuntimeError("上传失败: %s" % json.dumps(pic, ensure_ascii=False)[:300])
    return pic["file"]


cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

MID = 44638327   # Dennis Eckersley
IMG = HERE / "capture_20261012" / "captcha.png"   # 先用探针图做链路验证
log = []

print("=== 1. 上传图片 ===", flush=True)
f = upload_image(IMG)
print("  file.id =", f["id"], flush=True)
print("  full_url =", f["full_url"], flush=True)
log.append({"step": "upload", "file_id": f["id"], "full_url": f["full_url"]})

print("\n=== 2. GET /edit 取当前完整字段 ===", flush=True)
ed = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": MID})
edata = ed.get("data") or {}
row = edata.get("row") or {}
print("  当前 icon =", row.get("icon"), flush=True)
print("  当前 icon_format =", (row.get("_format") or {}).get("icon_format"), flush=True)

# ---- 3. 构造 edit body：全量字段 + 改 icon ----
body = dict(row)
body["icon"] = f["id"]
fmt = dict(row.get("_format") or {})
fmt["icon_format"] = f["full_url"]
body["_format"] = fmt
# 保持 _extend 里的勾选范围（sync_goods 会一并同步产品）
ext = dict(row.get("_extend") or {})
ext["gold_save_mode"] = "sync_goods"
ext["confirm_mould_trigger"] = 0
body["_extend"] = ext

print("\n=== 3. POST /edit 写 icon（仅一次）===", flush=True)
print("  提交 icon =", body["icon"], " _extend.gold_save_mode =", ext.get("gold_save_mode"), flush=True)
try:
    res = c._json("POST", "/admin/goods.GoodsMould/edit", json_body=body)
    print("  返回:", json.dumps(res, ensure_ascii=False)[:300], flush=True)
    log.append({"step": "edit", "result": res})
except AdminUnknownResult as e:
    print("  [X] 结果未知，停止:", e, flush=True)
    log.append({"step": "edit", "unknown": str(e)})
    (HERE / "_icon_test_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(2)
except Exception as e:
    print("  [X] 被拒:", repr(e), flush=True)
    log.append({"step": "edit", "error": repr(e)})
    (HERE / "_icon_test_result.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(1)

time.sleep(3)
print("\n=== 4. 回读确认 ===", flush=True)
ed2 = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": MID})
r2 = (ed2.get("data") or {}).get("row") or {}
icon2 = r2.get("icon")
fmt2 = (r2.get("_format") or {}).get("icon_format")
print("  icon      =", icon2, flush=True)
print("  icon_format =", fmt2, flush=True)
ok = str(icon2) == str(f["id"])
print("\n  结论:", "✅ icon 写入成功" if ok else "⚠️ icon 未变更", flush=True)
log.append({"step": "verify", "icon": icon2, "icon_format": fmt2, "ok": ok})

# 顺带看产品行 icon 是否同步
pd = c._json("GET", "/admin/goods.Goods/index",
             params={"page": 1, "limit": 3,
                     "search": [{"field": "mid", "operator": "=", "val": str(MID)}]})
prows = (pd.get("data") or {}).get("list") or []
print("  关联产品样例 icon:", [p.get("icon") for p in prows], flush=True)
log.append({"step": "products_icon", "icons": [p.get("icon") for p in prows]})

(HERE / "_icon_test_result.json").write_text(
    json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写入 _icon_test_result.json", flush=True)
