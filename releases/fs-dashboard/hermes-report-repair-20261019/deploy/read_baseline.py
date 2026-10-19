"""Read-only Linux inventory for the exact 371-path tracking follow-up scope."""

import datetime
import hashlib
import json
import stat
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLAN_SHA = 'e0c438f3a969713b9bd00713b2c83a4d8ff0229a102e45746406c68ec4f1fd4c'
UI_READY_SHA = "c159d268efa7a1ba38dbd3c0f47906150ffb86cf50c769629b3abe7b29e9703e"


def read(plan_path=None):
    path = Path(plan_path) if plan_path else HERE / "baseline-paths.json"
    if path.is_symlink():
        raise ValueError("inventory_plan_link")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PLAN_SHA:
        raise ValueError("inventory_plan_sha_drift")
    plan = json.loads(raw)
    names = plan.get("paths")
    expected = plan.get("expectedSha256")
    if plan.get("contract") != "fs-hermes-report-repair-inventory-v1" or \
       plan.get("productionWrites") != 0 or \
       not isinstance(names, list) or len(names) != 371 or len(set(names)) != 371 or \
       set(expected) != set(names) or names != sorted(names):
        raise ValueError("fixed_371_path_contract_required")
    rows = []
    for name in names:
        target = Path(name)
        if any(node.is_symlink() for node in (target, *target.parents)):
            raise ValueError("linked_target:" + name)
        if not target.exists():
            if expected[name] is not None:raise ValueError('required_target_missing:'+name)
            rows.append({'path':name,'exists':False,'sha256':None});continue
        info = target.stat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("regular_file_required:" + name)
        rows.append({"path": name, "exists": True,
                     "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                     "uid": info.st_uid, "gid": info.st_gid,
                     "mode": oct(stat.S_IMODE(info.st_mode)), "links": info.st_nlink})
    actual={r['path']:r['sha256'] for r in rows}
    if actual!=expected:raise ValueError('baseline_drift:'+str([p for p in expected if expected[p]!=actual[p]]))
    units = {}
    for unit in ("fs-business-range.service", "fs-hermes-fc.service", "fc27-p2pah-session.service"):
        result = subprocess.run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "User"],
                                check=True, capture_output=True, text=True, timeout=15)
        units[unit] = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    container = subprocess.run(["docker", "inspect", "-f", "{{.Image}}|{{.Config.Image}}|{{.Config.User}}",
                                "fc27-p2pah-session"], check=True, capture_output=True,
                               text=True, timeout=15).stdout.strip().split("|")
    if len(container) != 3:
        raise ValueError("session_container_identity_invalid")
    uid = subprocess.run(["docker", "exec", "fc27-p2pah-session", "id", "-u"],
                         check=True, capture_output=True, text=True, timeout=15).stdout.strip()
    return {"contract": "fs-hermes-report-repair-baseline-v1",
            "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "inventoryPlanSha256": PLAN_SHA, "production_writes": 0,
            "files": rows, "units": {k:{"ActiveState":v["ActiveState"]} for k,v in units.items() if k!="fc27-p2pah-session.service"},"all_units":units,
            "session": {"imageId": container[0], "tag": container[1], "user": container[2], "uid": uid}}


if __name__ == "__main__":
    print(json.dumps(read(), ensure_ascii=True))
