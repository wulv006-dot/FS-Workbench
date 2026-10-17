# -*- coding: utf-8 -*-
"""重建探针树：按 PR#68 的真实 diff 清单铺开文件，然后跑 pr_fast.py。
用法: _fs_probe_rebuild.py
"""
import importlib.util, json, shutil, subprocess, sys, os
from pathlib import Path

EVID = Path(__file__).parent
SRC = EVID.parent.parent
PROBE = SRC / "._prfast_probe"

spec = importlib.util.spec_from_file_location("fs_push", EVID / "_fs_push.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
req, REPO, BRANCH = m.req, m.REPO, m.BRANCH

# 1) 取 PR#68 的真实变更文件清单
c, jp = req("GET", f"/repos/{REPO}/pulls/68")
base, head = jp["base"]["sha"], jp["head"]["sha"]
print("base =", base[:12], " head =", head[:12], " files =", jp["changed_files"])

changed = []
page = 1
while True:
    c, jf = req("GET", f"/repos/{REPO}/pulls/68/files?per_page=100&page={page}")
    if c != 200 or not jf:
        break
    changed += [f["filename"] for f in jf]
    if len(jf) < 100:
        break
    page += 1
print("拿到 changed 文件:", len(changed))

# 2) 重建探针树
if PROBE.exists():
    shutil.rmtree(PROBE, ignore_errors=True)
(PROBE / ".github/workflows").mkdir(parents=True)
(PROBE / "tools").mkdir(parents=True)

# workflow + pr_fast.py
shutil.copy2(SRC / "mlb_admin_import_20261012/evidence/_remote_.github_workflows_pr-fast.yml",
             PROBE / ".github/workflows/pr-fast.yml")
shutil.copy2(SRC / "tools/pr_fast.py", PROBE / "tools/pr_fast.py")
shutil.copy2(SRC / "mlb_admin_import_20261012/evidence/_remote_tools_pr_fast.py",
             PROBE / "tools/pr_fast_orig.py")

# 3) 铺开每个 changed 文件（从本地 SRC 拷，不存在则从远端 blob 拉）
missing = []
for rel in changed:
    s = SRC / rel
    d = PROBE / rel
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.exists():
        shutil.copy2(s, d)
    else:
        missing.append(rel)

print("本地缺失（需从远端拉）:", len(missing))
for rel in missing:
    print("   -", rel)
