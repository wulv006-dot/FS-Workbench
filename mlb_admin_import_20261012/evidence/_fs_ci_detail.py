# -*- coding: utf-8 -*-
"""只读：用多种端点尝试取 CI 失败详情（annotations / raw log via different accept）。"""
import importlib.util, sys, json
from pathlib import Path

spec = importlib.util.spec_from_file_location("fs_push", Path(__file__).parent / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO = m.req, m.REPO
RUN = sys.argv[1] if len(sys.argv) > 1 else "38203106640"

c, jj = req("GET", f"/repos/{REPO}/actions/runs/{RUN}/jobs")
job = jj["jobs"][0]
jid = job["id"]
print("job id:", jid)

for path in (f"/repos/{REPO}/actions/jobs/{jid}/logs",
             f"/repos/{REPO}/check-runs/{jid}/annotations"):
    c, j = req("GET", path, raw=True)
    body = j if isinstance(j, (bytes, bytearray)) else json.dumps(j).encode()
    print("-" * 60)
    print(path, "->", c, "len", len(body))
    if c == 200:
        txt = body.decode("utf-8", "replace")
        Path("mlb_admin_import_20261012/evidence/_ci_job.log").write_text(txt, encoding="utf-8")
        keys = ("UNMAPPED", "error", "Error", "Traceback", "FAIL", "RuntimeError",
                "NotModuleFound", "ModuleNotFound", "html_tag", "required_tests",
                "raise ", "assert", "❌", "✗")
        for ln in txt.splitlines():
            if any(k in ln for k in keys):
                print("  |", ln[:200])
    else:
        print("  body:", body[:250])
