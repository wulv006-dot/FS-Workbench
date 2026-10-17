# -*- coding: utf-8 -*-
"""只读：抓 CI job 日志（多种端点尝试）并打印关键错误行。"""
import importlib.util, sys, json, re
from pathlib import Path

spec = importlib.util.spec_from_file_location("fs_push", Path(__file__).parent / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO = m.req, m.REPO

RUN = sys.argv[1] if len(sys.argv) > 1 else "38202767135"

c, jj = req("GET", f"/repos/{REPO}/actions/runs/{RUN}/jobs")
job = jj["jobs"][0]
jid = job["id"]
print("job id =", jid, "| url =", job["html_url"])

# 尝试 logs 端点
c, raw = req("GET", f"/repos/{REPO}/actions/jobs/{jid}/logs", raw=True)
print("logs 端点状态:", c)
if c == 200:
    txt = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    print("日志长度:", len(txt))
    Path("mlb_admin_import_20261012/evidence/_ci_job.log").write_text(txt, encoding="utf-8")
    lines = txt.splitlines()
    keys = ("UNMAPPED", "Error", "error", "Traceback", "FAIL", "FAILED",
            "required_tests", "html_tag", "RuntimeError", "✗", "❌", "raise")
    print("-" * 70)
    for i, ln in enumerate(lines):
        if any(k in ln for k in keys):
            print("%5d| %s" % (i, ln[:200]))
else:
    print("body:", str(raw)[:400])
