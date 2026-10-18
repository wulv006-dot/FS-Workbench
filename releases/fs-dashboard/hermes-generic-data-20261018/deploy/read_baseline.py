"""Linux read-only inventory. The output contains hashes and metadata, never file bodies."""

import datetime
import hashlib
import json
import stat
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
plan = json.loads((HERE / "baseline-paths.json").read_text("utf-8"))
if plan.get("contract") != "fs-hermes-generic-data-baseline-paths-v1" or plan.get("productionWrites") != 0:
    raise ValueError("fixed_inventory_plan_required")
allowed = set(plan["newAllowed"])
rows = []
for name in plan["paths"]:
    path = Path(name)
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlink_rejected:" + name)
    if not path.exists():
        if name not in allowed:
            raise ValueError("protected_file_missing:" + name)
        rows.append({"path": name, "exists": False, "sha256": None})
        continue
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("regular_file_required:" + name)
    rows.append({"path": name, "exists": True,
                 "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "uid": info.st_uid, "gid": info.st_gid,
                 "mode": oct(stat.S_IMODE(info.st_mode)), "links": info.st_nlink})
units = {}
for unit in ("fs-business-range.service", "fs-hermes-fc.service", "fc27-p2pah-session.service"):
    result = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState"],
                            check=True, capture_output=True, text=True, timeout=15)
    units[unit] = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
print(json.dumps({"contract": "fs-hermes-generic-data-live-baseline-v1",
                  "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "inventoryPlanSha256": hashlib.sha256((HERE / "baseline-paths.json").read_bytes()).hexdigest(),
                  "production_writes": 0, "files": rows, "units": units}, ensure_ascii=False))
