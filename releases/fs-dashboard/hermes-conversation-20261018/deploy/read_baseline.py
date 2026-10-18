"""Read-only on-server inventory for this exact release; output contains no file bodies."""

import datetime
import hashlib
import json
import stat
import subprocess
from pathlib import Path


HERE = Path(__file__).resolve().parent
config = json.loads((HERE / "baseline-paths.json").read_text("utf-8"))
rows = []
for name in config["paths"]:
    path = Path(name)
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise ValueError("symlink_rejected: " + name)
    if not path.exists():
        if name not in config["new_allowed"]:
            raise ValueError("required_file_missing: " + name)
        rows.append({"path": name, "exists": False, "sha256": None})
        continue
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("regular_file_required: " + name)
    rows.append({"path": name, "exists": True, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                 "uid": info.st_uid, "gid": info.st_gid, "mode": oct(stat.S_IMODE(info.st_mode)), "links": info.st_nlink})
units = {}
for unit in ("fs-business-range.service", "fs-hermes-fc.service"):
    result = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState"], check=True, capture_output=True, text=True)
    units[unit] = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
print(json.dumps({"contract": "fs-hermes-conversation-baseline-v1", "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "production_writes": 0, "files": rows, "units": units}, ensure_ascii=False))
