# -*- coding: utf-8 -*-
"""只读：轮询指定 CI run 的状态与步骤结论。用法: _fs_watch.py <run_id>"""
import importlib.util, sys, time
from pathlib import Path

spec = importlib.util.spec_from_file_location("fs_push", Path(__file__).parent / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO = m.req, m.REPO

RUN = sys.argv[1] if len(sys.argv) > 1 else "38202767135"

for i in range(60):
    c, j = req("GET", f"/repos/{REPO}/actions/runs/{RUN}")
    st, concl = j.get("status"), j.get("conclusion")
    print("[%02d] status=%s conclusion=%s" % (i, st, concl))
    if st == "completed":
        break
    time.sleep(10)

print("=" * 70)
c, jj = req("GET", f"/repos/{REPO}/actions/runs/{RUN}/jobs")
for job in jj.get("jobs", []):
    print("JOB:", job["name"], "|", job["status"], "|", job["conclusion"])
    for s in job.get("steps", []):
        mark = {"success": "✅", "failure": "❌", "skipped": "⏭",
                "cancelled": "🚫"}.get(s["conclusion"], "·")
        print("   %s %-44s %s" % (mark, s["name"], s.get("conclusion")))
