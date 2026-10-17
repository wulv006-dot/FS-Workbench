# -*- coding: utf-8 -*-
"""探测 POST /upload/network —— 第三方 URL 图片转内部附件。

前端源码（index-5755c73c.js）：
  Y({url: B + "/upload/network", method:"post", params:{pic_list: n.value}})
    B = siteApiUrl = "https://b2c-api.p2pah.cn"
  响应: a.upload.network.file.full_url / .id
  ⇒ icon = file.id

本探针用 1 张真实卡图 URL 试 1 次。
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
BASE = "https://b2c-api.p2pah.cn"

opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    urllib.request.ProxyHandler({}))

IMG = "https://cards.theshow.com/mlb26/985af223b191066c61bc3c765085bd87-baked-sm.webp"

out = {}

# ---- 方式A：GET/params ----
for method in ("GET", "POST"):
    url = BASE + "/upload/network?" + urllib.parse.urlencode({"pic_list": IMG})
    req = urllib.request.Request(url, method=method, headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Origin": "https://admin.p2pah.cn", "Referer": "https://admin.p2pah.cn/"})
    try:
        with opener.open(req, timeout=60) as r:
            raw = r.read().decode("utf-8", "replace")
        print("[%-4s] HTTP %s\n      %s" % (method, r.status, raw[:700]), flush=True)
        out[method] = {"status": r.status, "body": raw[:1500]}
        try:
            j = json.loads(raw)
            net = ((j.get("upload") or {}).get("network")
                   or (j.get("data") or {}).get("upload", {}).get("network"))
            if net and net.get("file"):
                print("      ★ 命中 file =", json.dumps(net["file"], ensure_ascii=False)[:300], flush=True)
        except Exception:
            pass
    except urllib.error.HTTPError as e:
        print("[%-4s] HTTPError %s  %s" % (method, e.code, e.read()[:400]), flush=True)
        out[method] = {"status": e.code, "body": str(e.read()[:600])}
    except Exception as e:
        print("[%-4s] ERR %r" % (method, e), flush=True)
        out[method] = {"error": repr(e)}

(HERE / "_probe_upload_network.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\n已写入 _probe_upload_network.json", flush=True)
