# -*- coding: utf-8 -*-
"""只读：查看 PR#68 在新推送后的状态 + 最新 CI run。"""
import importlib.util, json, time
from pathlib import Path

spec = importlib.util.spec_from_file_location("fs_push", Path(__file__).parent / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO, BRANCH = m.req, m.REPO, m.BRANCH

c, j = req("GET", f"/repos/{REPO}/git/ref/heads/{BRANCH}")
tip = j["object"]["sha"]
print("branch tip =", tip)

c, j = req("GET", f"/repos/{REPO}/git/ref/heads/main")
print("main       =", j["object"]["sha"])

c, jc = req("GET", f"/repos/{REPO}/git/commits/{tip}")
print("parents    =", [p["sha"] for p in jc["parents"]])

print("-" * 70)
c, jp = req("GET", f"/repos/{REPO}/pulls/68")
print("PR#68:", jp.get("title"))
print("  head.sha      =", jp["head"]["sha"])
print("  base.sha      =", jp["base"]["sha"], "(%s)" % jp["base"]["ref"])
print("  mergeable     =", jp.get("mergeable"), "| state =", jp.get("mergeable_state"))
print("  commits       =", jp.get("commits"), "| changed_files =", jp.get("changed_files"))

print("-" * 70)
for _ in range(3):
    c, jr = req("GET", f"/repos/{REPO}/actions/runs?head_sha={tip}&per_page=5")
    runs = jr.get("workflow_runs", [])
    if runs:
        break
    time.sleep(4)
if not runs:
    print("（暂无 CI run，可能还没触发）")
for r in runs:
    print("run %s | %s | %s | %s" % (r["id"], r["name"], r["status"], r["conclusion"]))
    print("   sha=%s  created=%s" % (r["head_sha"][:12], r["created_at"]))
    print("   url=%s" % r["html_url"])
