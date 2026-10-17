# -*- coding: utf-8 -*-
"""只读：比对本地 vs 远端分支 blob 的行尾（定位 CRLF 被吃掉的环节）。"""
import base64, importlib.util
from pathlib import Path

EVID = Path(__file__).parent
spec = importlib.util.spec_from_file_location("fs_push", EVID / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO, BRANCH, SRC = m.req, m.REPO, m.BRANCH, m.SRC

REL = "共享资源/MLB新卡上架/client/启动执行器.bat"

c, jb = req("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
tip = jb["object"]["sha"]
c, jc = req("GET", f"/repos/{REPO}/git/commits/{tip}")
c, jt = req("GET", f"/repos/{REPO}/git/trees/{jc['tree']['sha']}?recursive=1")
blobs = {e["path"]: e["sha"] for e in jt["tree"] if e["type"] == "blob"}

print("远端 blob sha =", blobs.get(REL))
c, j = req("GET", f"/repos/{REPO}/git/blobs/{blobs[REL]}")
remote = base64.b64decode(j["content"])

local = (SRC / REL).read_bytes()


def stat(b, tag):
    print("%-8s 大小=%-6d CRLF=%-4d 裸LF=%-4d BOM=%s" % (
        tag, len(b), b.count(b"\r\n"), b.count(b"\n") - b.count(b"\r\n"),
        b[:3] == b"\xef\xbb\xbf"))


stat(local, "本地")
stat(remote, "远端")
print("-" * 60)
print("内容一致 ?", local == remote)
if local != remote:
    # 找第一处差异
    for i in range(min(len(local), len(remote))):
        if local[i] != remote[i]:
            print("首个差异 @ byte", i)
            print("  本地:", local[max(0, i - 30):i + 30])
            print("  远端:", remote[max(0, i - 30):i + 30])
            break
