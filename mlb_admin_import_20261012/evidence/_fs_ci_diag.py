# -*- coding: utf-8 -*-
"""拉取 CI 运行详情 + 失败日志（诊断 pr-fast）。"""
from __future__ import annotations
import json, sys, urllib.error, urllib.request
from pathlib import Path

REPO = "wulv006-dot/FS-Workbench"
API = "https://api.github.com"


def token():
    d = json.loads((Path.home() / ".workbuddy" / "mcp.json").read_text("utf-8"))
    return d["mcpServers"]["github-fs"]["headers"]["Authorization"].replace("Bearer ", "").strip()


TOK = token()


def req(method, path, body=None, raw=False):
    url = path if path.startswith("http") else API + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Authorization": "Bearer " + TOK, "Accept": "application/vnd.github+json",
         "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "fs-diag",
         "Connection": "close"}
    if data:
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with op.open(r, timeout=60) as resp:
            b = resp.read()
            return resp.status, (b if raw else json.loads(b.decode("utf-8") or "{}"))
    except urllib.error.HTTPError as e:
        b = e.read()
        try:
            j = json.loads(b.decode("utf-8"))
        except Exception:
            j = {"_raw": b[:600].decode("utf-8", "replace")}
        return e.code, j


def main():
    sha = sys.argv[1]
    c, j = req("GET", f"/repos/{REPO}/actions/runs?head_sha={sha}&per_page=20")
    print("runs:", c)
    for run in j.get("workflow_runs", []):
        print("=" * 70)
        print("run:", run["id"], run["name"], run["status"], run.get("conclusion"))
        print("  url:", run["html_url"])
        # 取 jobs
        c2, j2 = req("GET", f"/repos/{REPO}/actions/runs/{run['id']}/jobs")
        print("  jobs:", c2)
        for job in j2.get("jobs", []):
            print("   - job", job["id"], job["name"], job["status"], job.get("conclusion"))
            for st in job.get("steps", []):
                print("       step: %-38s %-10s %s" % (
                    st.get("name"), st.get("status"), st.get("conclusion")))
        # 试取日志（可能 401，签名 URL）
        c3, j3 = req("GET", f"/repos/{REPO}/actions/jobs/{j2['jobs'][0]['id']}/logs", raw=True) \
            if j2.get("jobs") else (0, b"")
        print("  log:", c3, (j3[:200] if isinstance(j3, bytes) else j3) if c3 != 200 else "(ok)")


if __name__ == "__main__":
    main()
