# -*- coding: utf-8 -*-
"""图片上传接口契约探测（b2c-api.p2pah.cn/upload/file）。

已知（前端源码逆向）：
  端点   POST https://b2c-api.p2pah.cn/upload/file
  鉴权   multipart 字段 token = md5(str(ms) + "DFSAF[WFKWEFL;SDFJKSDLF;JF")
         字段 timestamp = 毫秒时间戳
  附加   id=0, view=1, type=0, watermark=0, site_id(可选)
  返回   { code:200, file:{ id, name|title, full_url, suffix } }
         ⇒ icon = file.id

本探针目标：确认
  ① 文件表单字段名（file? image? filename?）
  ② 是否还需要 batoken / 其它头
  ③ 返回结构

⛔ 探针只用 1 张真实 PNG 试 1 次；若上传成功会真实产生一个附件（无害，可弃用）。
"""
import hashlib
import json
import mimetypes
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

UPLOAD_BASE = "https://b2c-api.p2pah.cn"
SECRET = "DFSAF[WFKWEFL;SDFJKSDLF;JF"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    urllib.request.ProxyHandler({}))


def build_auth_fields(extra=None):
    ms = int(time.time() * 1000)
    f = {"token": hashlib.md5(("%d%s" % (ms, SECRET)).encode()).hexdigest(),
         "timestamp": ms}
    if extra:
        f.update(extra)
    return f


def multipart(fields, file_field, filename, content):
    b = "----wbupl" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out += [f"--{b}\r\n".encode(),
                f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode(),
                str(v).encode(), b"\r\n"]
    ct = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    out += [f"--{b}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {ct}\r\n\r\n".encode(),
            content, b"\r\n", f"--{b}--\r\n".encode()]
    return b"".join(out), f"multipart/form-data; boundary={b}"


# 用一张真实 PNG（就用之前抓的验证码图，尺寸小）
png_path = HERE / "capture_20261012" / "captcha.png"
if png_path.is_file():
    img = png_path.read_bytes()
else:
    # 兜底：1x1 透明 PNG
    import base64
    img = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
print("测试图字节数:", len(img), flush=True)

results = {}

# ---- 探测不同文件字段名 ----
for field in ["file", "image", "img", "picture", "upload"]:
    fields = build_auth_fields({"id": 0, "view": 1, "type": 0, "watermark": 0})
    body, ctype = multipart(fields, field, "probe_test.png", img)
    req = urllib.request.Request(UPLOAD_BASE + "/upload/file", data=body,
                                 method="POST",
                                 headers={"User-Agent": UA, "Content-Type": ctype,
                                          "Origin": "https://admin.p2pah.cn",
                                          "Referer": "https://admin.p2pah.cn/",
                                          "Accept": "application/json, text/plain, */*"})
    try:
        with opener.open(req, timeout=40) as r:
            raw = r.read().decode("utf-8", "replace")
        print("[%-8s] HTTP %s  %s" % (field, r.status, raw[:280]), flush=True)
        results[field] = {"status": r.status, "body": raw[:600]}
        try:
            j = json.loads(raw)
            if j.get("code") in (200, 1) and j.get("file"):
                print("      ★ 命中！file =", json.dumps(j["file"], ensure_ascii=False)[:300], flush=True)
                break
        except Exception:
            pass
    except urllib.error.HTTPError as e:
        print("[%-8s] HTTPError %s  %s" % (field, e.code, e.read()[:280]), flush=True)
        results[field] = {"status": e.code, "body": str(e.read()[:300])}
    except Exception as e:
        print("[%-8s] ERR %r" % (field, e), flush=True)
        results[field] = {"error": repr(e)}

(HERE / "_probe_upload_contract.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写入 _probe_upload_contract.json", flush=True)
