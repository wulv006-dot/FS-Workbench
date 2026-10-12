# -*- coding: utf-8 -*-
"""修复 4 张 MLB 卡：补 icon（主图）+ zh_title（扩展属性）。

背景：早先只用 add/shelves 建了模型和产品，**漏了两个关键字段**：
  ① icon        —— 主图附件 ID（自动改价脚本依赖）
  ② more.extend —— [{"key":"zh_title","value":"<hash>"}]（自动改价脚本依赖）

zh_title 来源：`card_hash` = 卡图 URL 里的 32 位 hex。
  图标地址 = https://cards.theshow.com/mlb26/<hash>-baked-sm.webp
  扩展属性 = zh_title=<hash>
  （执行器 mlb_agent.py:758/767 原文如此）

流程（每卡）：
  ① GET /upload/network?pic_list=<卡图URL>  → file.id + file.full_url
  ② POST /admin/goods.GoodsMould/edit       → icon / _format.icon_format / more.extend
  ③ GET  /edit?id= 回读确认

⛔ 写操作只发一次（每卡一次 edit），绝不自动重试。
"""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from admin_api_client import AdminApiClient, AdminUnknownResult  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
B2C = "https://b2c-api.p2pah.cn"
ICON_BASE = "https://cards.theshow.com/mlb26/"

_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    urllib.request.ProxyHandler({}))


def upload_network(url):
    """外链图 → 内部附件。返回 {id, full_url}。"""
    u = B2C + "/upload/network?" + urllib.parse.urlencode({"pic_list": url})
    req = urllib.request.Request(u, method="POST", headers={
        "User-Agent": UA, "Accept": "application/json, text/plain, */*",
        "Origin": "https://admin.p2pah.cn", "Referer": "https://admin.p2pah.cn/"})
    with _opener.open(req, timeout=60) as r:
        j = json.loads(r.read().decode("utf-8", "replace"))
    net = (j.get("upload") or {}).get("network") or {}
    if net.get("code") != 200 or not net.get("file"):
        raise RuntimeError("upload/network 失败: %s" % json.dumps(net, ensure_ascii=False)[:300])
    return net["file"]


# 4 张卡：mid / hash
CARDS = [
    (44638327, "Dennis Eckersley/99/CP/Athletics/Awards",          "985af223b191066c61bc3c765085bd87"),
    (44638391, "Ivan Rodriguez/99/C/Marlins/Awards",               "258e272e00697025b7c2dff30d851de4"),
    (44638393, "George Springer/99/CF/Astros/The Show Classics",   "d42892e47513d78c3f1f75788b258743"),
    (44638395, "Andy Pettitte/99/SP/Yankees/Awards",               "c303e117d4149111a78106ad02957cb4"),
]

# 支持 --only <mid> 只跑一张（用于灰度验证）
_ONLY = None
for _i, _a in enumerate(sys.argv):
    if _a == "--only" and _i + 1 < len(sys.argv):
        _ONLY = int(sys.argv[_i + 1])
if _ONLY:
    CARDS = [c for c in CARDS if c[0] == _ONLY]
    print("[灰度] 只跑 mid=%s" % _ONLY, flush=True)

cred = json.loads((HERE / "_cred.json").read_text("utf-8"))
c = AdminApiClient(log=lambda *a: print(*a, flush=True))
c.login_with_ocr(cred["P2PAH_USERNAME"], cred["P2PAH_PASSWORD"])

report = []

for idx, (mid, title, h) in enumerate(CARDS, 1):
    print("\n" + "=" * 66, flush=True)
    print("[%d/4] %s  (mid=%s)" % (idx, title, mid), flush=True)
    rec = {"mid": mid, "title": title, "hash": h}
    report.append(rec)

    img_url = ICON_BASE + h + "-baked-sm.webp"

    # ---- ① 外链转内部附件 ----
    print("  → upload/network …", flush=True)
    try:
        f = upload_network(img_url)
        print("     icon(id) = %s" % f.get("id"), flush=True)
        print("     full_url = %s" % f.get("full_url"), flush=True)
        rec["icon"] = f.get("id")
        rec["icon_url"] = f.get("full_url")
    except Exception as e:
        print("     [X] 转附件失败:", repr(e), flush=True)
        rec["verdict"] = "upload-network-failed"
        continue

    # ---- ② 取当前模型全字段 ----
    ed = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": mid})
    row = (ed.get("data") or {}).get("row") or {}

    body = dict(row)
    body["icon"] = f["id"]
    fmt = dict(row.get("_format") or {})
    fmt["icon_format"] = f["full_url"]
    body["_format"] = fmt
    # ★ 关键：more.extend 里的 zh_title
    more = dict(row.get("more") or {})
    more["extend"] = [{"key": "zh_title", "value": h}]
    body["more"] = more
    # 只改模型，不动产品（避免误改价）
    ext = dict(row.get("_extend") or {})
    ext["gold_save_mode"] = "mould_only"
    ext["confirm_mould_trigger"] = 1
    body["_extend"] = ext

    print("  → POST /edit 写 icon + zh_title（仅一次）…", flush=True)
    try:
        res = c._json("POST", "/admin/goods.GoodsMould/edit", json_body=body)
        print("     返回:", json.dumps(res, ensure_ascii=False)[:260], flush=True)
        rec["edit"] = res.get("msg")
    except AdminUnknownResult as e:
        print("     [X] 结果未知，停止:", e, flush=True)
        rec["verdict"] = "edit-unknown(no-retry)"
        break
    except Exception as e:
        print("     [X] 被拒:", repr(e), flush=True)
        rec["verdict"] = "edit-failed: %r" % e
        continue

    time.sleep(2.5)
    # ---- ③ 回读确认 ----
    ed2 = c._json("GET", "/admin/goods.GoodsMould/edit", params={"id": mid})
    r2 = (ed2.get("data") or {}).get("row") or {}
    icon2 = r2.get("icon")
    ext2 = (r2.get("more") or {}).get("extend") or []
    zh = ""
    for e2 in ext2:
        if isinstance(e2, dict) and e2.get("key") == "zh_title":
            zh = e2.get("value")
    fmt2 = (r2.get("_format") or {}).get("icon_format")
    print("  回读: icon=%s  zh_title=%s" % (icon2, zh), flush=True)
    print("        icon_format=%s" % fmt2, flush=True)
    ok = str(icon2) == str(f["id"]) and zh == h
    print("  结论:", "✅ 达标" if ok else "⚠️ 不一致", flush=True)
    rec.update({"icon_readback": icon2, "zh_title": zh, "icon_format": fmt2,
                "verdict": "ok" if ok else "mismatch"})

(HERE / "_fix_icon_zhtitle_result.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

print("\n" + "=" * 66, flush=True)
print("汇总:", flush=True)
for r in report:
    print("  %-50s icon=%-9s zh=%s" % (r["title"][:48], r.get("icon_readback"),
                                        (r.get("zh_title") or "")[:34]), flush=True)
print("\n已写入 _fix_icon_zhtitle_result.json", flush=True)
