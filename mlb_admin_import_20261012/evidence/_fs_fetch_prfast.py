# -*- coding: utf-8 -*-
"""读远端 main 的 pr_fast.py 映射规则（只读）。"""
from __future__ import annotations
import base64, json, urllib.error, urllib.request
from pathlib import Path

REPO = "wulv006-dot/FS-Workbench"
API = "https://api.github.com"


def token():
    d = json.loads((Path.home() / ".workbuddy" / "mcp.json").read_text("utf-8"))
    return d["mcpServers"]["github-fs"]["headers"]["Authorization"].replace("Bearer ", "").strip()


TOK = token()


def get(path):
    url = API + path
    h = {"Authorization": "Bearer " + TOK, "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "fs", "Connection": "close"}
    r = urllib.request.Request(url, headers=h)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def fetch_file(p, ref="main"):
    c, j = get(f"/repos/{REPO}/contents/{p}?ref={ref}")
    if c != 200:
        return c, None
    return 200, base64.b64decode(j["content"]).decode("utf-8")


# 找 pr_fast.py
for cand in ["tools/pr_fast.py", ".github/workflows/pr-fast.yml"]:
    c, t = fetch_file(cand)
    print("=" * 70)
    print(cand, "->", c, "| size:", len(t) if t else 0)
    if c == 200:
        outp = Path(r"E:\WorkBuddy\大超服务器\mlb_admin_import_20261012\evidence") / \
               ("_remote_" + cand.replace("/", "_"))
        outp.write_text(t, encoding="utf-8")
        print("   已存:", outp)
