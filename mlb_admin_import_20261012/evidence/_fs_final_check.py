# -*- coding: utf-8 -*-
"""只读：合并后终态核验（main 前进 / PR 关闭 / 关键文件已入 main）。"""
import base64, importlib.util
from pathlib import Path

EVID = Path(__file__).parent
spec = importlib.util.spec_from_file_location("fs_push", EVID / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO, SRC = m.req, m.REPO, m.SRC

c, j = req("GET", f"/repos/{REPO}/git/ref/heads/main")
main_sha = j["object"]["sha"]
print("main       =", main_sha)
print("  上一次 main = d64a859002589e000e0e5d8fb3b265455123e5d5")
print("  前进?      ", main_sha != "d64a859002589e000e0e5d8fb3b265455123e5d5")

c, jp = req("GET", f"/repos/{REPO}/pulls/68")
print("-" * 66)
print("PR#68  state =", jp.get("state"), "| merged =", jp.get("merged"))
print("  merged_at =", jp.get("merged_at"))
print("  merge_sha =", jp.get("merge_commit_sha"))
print("  merged_by =", (jp.get("merged_by") or {}).get("login"))

# main 上关键交付物是否存在 + 内容校验
c, jc = req("GET", f"/repos/{REPO}/git/commits/{main_sha}")
c, jt = req("GET", f"/repos/{REPO}/git/trees/{jc['tree']['sha']}?recursive=1")
blobs = {e["path"]: e["sha"] for e in jt["tree"] if e["type"] == "blob"}

print("-" * 66)
checks = [
    "tools/pr_fast.py",
    "mlb_admin_import_20261012/src/mlb_write_cards.py",
    "mlb_admin_import_20261012/tests/test_admin_write_channel.py",
    "共享资源/MLB新卡上架/client/启动执行器.bat",
    "共享资源/MLB新卡上架/tests/test_shelf_tool_offline.py",
    "共享资源/MLB新卡上架/web/index.html",
    ".gitignore",
]
for p in checks:
    print("  %-62s %s" % (p, "✅ 在 main" if p in blobs else "❌ 缺失"))

# 关键字节保真复核：bat 的 CRLF、pr_fast 的分组
c, jb = req("GET", f"/repos/{REPO}/git/blobs/{blobs['共享资源/MLB新卡上架/client/启动执行器.bat']}")
bat = base64.b64decode(jb["content"])
print("-" * 66)
print("main 上 启动执行器.bat: %d B | CRLF=%d 裸LF=%d" % (
    len(bat), bat.count(b"\r\n"), bat.count(b"\n") - bat.count(b"\r\n")))

c, jb = req("GET", f"/repos/{REPO}/git/blobs/{blobs['tools/pr_fast.py']}")
pf = base64.b64decode(jb["content"])
print("main 上 tools/pr_fast.py: %d B | 含 mlb-admin=%s 含 mlb-shelf-tool=%s" % (
    len(pf), b"mlb-admin" in pf, b"mlb-shelf-tool" in pf))

# 本地与 main 一致性
for rel in ("tools/pr_fast.py", "共享资源/MLB新卡上架/client/启动执行器.bat",
            "mlb_admin_import_20261012/tests/test_admin_write_channel.py"):
    c, jb = req("GET", f"/repos/{REPO}/git/blobs/{blobs[rel]}")
    remote = base64.b64decode(jb["content"])
    local = (SRC / rel).read_bytes()
    print("  本地 == main ? %-58s %s" % (rel, local == remote))
