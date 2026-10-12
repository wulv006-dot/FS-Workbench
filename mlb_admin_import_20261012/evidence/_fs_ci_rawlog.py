# -*- coding: utf-8 -*-
"""只读：手动跟随 302 到 Azure Blob 取 CI 日志（重定向目标不再带 Authorization）。

GitHub 的 /actions/jobs/{id}/logs 会 302 到一个带签名的 Azure URL。
urllib 默认会跟随并把 Authorization 头一起带过去，导致 Azure 报
InvalidAuthenticationInfo。这里手动取 Location，再裸请求。
"""
import importlib.util, sys, json, ssl, urllib.request, urllib.error
from pathlib import Path

EVID = Path(__file__).parent
spec = importlib.util.spec_from_file_location("fs_push", EVID / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
TOK, REPO = m.TOK, m.REPO
RUN = sys.argv[1] if len(sys.argv) > 1 else "38203106640"

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))

# 1) 取 job id
c, jj = m.req("GET", f"/repos/{REPO}/actions/runs/{RUN}/jobs")
jid = jj["jobs"][0]["id"]
print("job id:", jid)

# 2) 请求 logs，禁止自动跟随
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None

op2 = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
url = f"https://api.github.com/repos/{REPO}/actions/jobs/{jid}/logs"
r = urllib.request.Request(url, headers={
    "Authorization": "Bearer " + TOK,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "fs-workbench-push",
    "Connection": "close",
})
loc = None
try:
    with op2.open(r, timeout=60) as resp:
        print("直接 200, len", len(resp.read()))
except urllib.error.HTTPError as e:
    loc = e.headers.get("Location")
    print("status", e.code, "| Location:", (loc or "")[:120])

if loc:
    r2 = urllib.request.Request(loc, headers={"User-Agent": "curl/8", "Connection": "close"})
    try:
        with op.open(r2, timeout=120) as resp:
            body = resp.read()
        print("日志字节:", len(body))
        txt = body.decode("utf-8", "replace")
        (EVID / "_ci_job.log").write_text(txt, encoding="utf-8")
        print("=" * 66)
        keys = ("UNMAPPED", "Traceback", "RuntimeError", "Error:", "error:",
                "FAIL", "html_tag", "required_tests", "ModuleNotFound",
                "assert", "raise", "not ok", "✗", "❌", "##[error]")
        seen = []
        for i, ln in enumerate(txt.splitlines()):
            if any(k in ln for k in keys):
                seen.append("%5d| %s" % (i, ln[:210]))
        print("\n".join(seen[-60:]) if seen else "（未匹配到关键字）")
    except Exception as e:
        print("下载日志失败:", repr(e))
