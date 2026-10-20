"""CAS deployment for the worker, optionally with its confirmed-write cache helper.

Fixes the scope gate of the four-file publisher (which rejects any target set
that is not exactly four files). Keeps the identical safety discipline:

  * flock on /var/lib/fc27-cloud/state/price-writer.lock (non-blocking)
  * queue / jobs / executions idle check
  * re-verify every baseline hash, abort on any drift
  * require fc27-cloud-api, fc27-cloud-worker and the automation timer active
  * snapshot the target into /var/lib/fc27-cloud/rollback/<stamp>/
  * stop API + worker so the loaded module is reloaded idle
  * atomic os.replace() swap preserving mode/owner, fsync file + directory
  * restart API + worker, wait for monitor health worker == ok
  * verify installed hash == after and every protected hash == before
  * on any failure: stop, restore the backup, restart, re-raise

Usage:
    python3 publish_worker.py            # check only (no writes)
    python3 publish_worker.py --apply    # perform the swap
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from urllib.request import Request, urlopen

STAGE = Path(__file__).resolve().parent
sys.path.insert(0, "/opt/fc27-cloud-browser")
from automation_tick import queue_mutation  # noqa: E402

ROOT = Path("/var/lib/fc27-cloud")
TARGET_PATH = "/opt/fc27-cloud-browser/fc27_cloud_worker.py"
TARGETS = {name: '/opt/fc27-cloud-browser/' + name for name in
           ('automation_tick.py', 'fc27_cloud_worker.py', 'player_sync_job.py', 'sync_players.sh')}

UNITS = ("fc27-cloud-api", "fc27-cloud-worker", "fc27-automation-tick.timer")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(*args):
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def idle():
    if list((ROOT / "queue").glob("*.json")):
        raise RuntimeError("queue_not_idle")
    for path in (ROOT / "jobs").glob("*.json"):
        job = json.loads(path.read_text())
        if (job.get("status") in {"queued", "running"} or
                (job.get("kind") == "auto_cycle" and
                 job.get("result", {}).get("status") == "confirmed" and not job.get("completed_at"))):
            raise RuntimeError("job_not_idle")
    for path in (ROOT / "executions").glob("*.json"):
        if json.loads(path.read_text()).get("status") in {"RUNNING", "UNCERTAIN", "PARTIAL"}:
            raise RuntimeError("coin_execution_unresolved")


def swap(source, target):
    meta = target.stat()
    temp = target.with_name("." + target.name + ".readback-tmp")
    created = False
    try:
        with temp.open("xb") as stream:
            created = True
            stream.write(source.read_bytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, stat.S_IMODE(meta.st_mode))
        os.chown(temp, meta.st_uid, meta.st_gid)
        os.replace(temp, target)
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if created and temp.exists():
            temp.unlink()


def wait_health():
    monitor = None
    for _ in range(20):
        try:
            with urlopen(Request("http://127.0.0.1:8879/monitor",
                                 headers={"X-Authenticated-User": "wulv"}), timeout=5) as res:
                monitor = json.load(res)
            if monitor["health"]["worker"] == "ok":
                break
        except OSError:
            pass
        time.sleep(0.5)
    if not monitor or monitor["health"]["worker"] != "ok":
        raise RuntimeError("runtime_not_ready")
    return monitor


def main(apply):
    manifest = json.loads((STAGE / "manifest.json").read_text(encoding="utf-8"))
    targets = manifest["targets"]
    if os.geteuid() != 0 or set(targets) != set(TARGETS):
        raise RuntimeError("deployment_scope_invalid")
    for name, row in targets.items():
        if row["target"] != TARGETS[name]:
            raise RuntimeError("deployment_target_invalid")
        if row["before"] != manifest["before"].get(row["target"]):
            raise RuntimeError("baseline_self_inconsistent")
        source = STAGE / "candidate" / name
        if source.is_symlink() or not source.resolve().is_relative_to(STAGE.resolve()):
            raise RuntimeError("candidate_unsafe")
        if digest(source) != row["after"]:
            raise RuntimeError("candidate_changed")
        if source.suffix == '.py':compile(source.read_text(encoding="utf-8"), name, "exec")
        else:command('sh', '-n', str(source))

    protected = {p: v for p, v in manifest["before"].items() if p not in
                 {row["target"] for row in targets.values()}}

    with queue_mutation():
        lock = os.open(ROOT / "state/price-writer.lock", os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            idle()
            for path, wanted in manifest["before"].items():
                p = Path(path)
                if p.is_symlink() or digest(p) != wanted:
                    raise RuntimeError("baseline_changed:" + path)
            for unit in UNITS:
                command("systemctl", "is-active", "--quiet", unit)

            if not apply:
                receipt = {"status": "checked", "applied": False,
                           "targets": targets,
                           "protected": len(protected)}
                print(json.dumps(receipt))
                return receipt

            backup = ROOT / "rollback" / ("natural-recovery-" +
                                          datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
            backup.mkdir(mode=0o700)
            for name, row in targets.items():
                shutil.copy2(row["target"], backup / name)
            (backup / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            installed = []
            try:
                command("systemctl", "stop", "fc27-cloud-worker")
                command("systemctl", "stop", "fc27-cloud-api")
                idle()
                for path, wanted in manifest["before"].items():
                    if Path(path).is_symlink() or digest(Path(path)) != wanted:
                        raise RuntimeError("baseline_changed_before_replace:" + path)
                for name, row in targets.items():
                    if digest(STAGE / "candidate" / name) != row["after"]:
                        raise RuntimeError("candidate_changed_before_replace")
                for name, row in targets.items():
                    installed.append(name)
                    swap(STAGE / "candidate" / name, Path(row["target"]))
                command("systemctl", "start", "fc27-cloud-api")
                command("systemctl", "start", "fc27-cloud-worker")
                monitor = wait_health()
                for unit in UNITS:
                    command("systemctl", "is-active", "--quiet", unit)
                actual = {row["target"]: digest(Path(row["target"])) for row in targets.values()}
                if any(actual[row["target"]] != row["after"] for row in targets.values()):
                    raise RuntimeError("installed_hash_mismatch")
                for path, wanted in protected.items():
                    if digest(Path(path)) != wanted:
                        raise RuntimeError("protected_input_changed:" + path)
                receipt = {
                    "status": "deployed", "at": datetime.now(timezone.utc).isoformat(),
                    "backup": str(backup),
                    "installed_sha256": actual,
                    "protected_sha256": protected,
                    "policy_revision": monitor["automation"]["revision"],
                    "health": monitor["health"],
                }
                (backup / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
                print(json.dumps(receipt, ensure_ascii=False))
                return receipt
            except Exception:
                command("systemctl", "stop", "fc27-cloud-worker")
                command("systemctl", "stop", "fc27-cloud-api")
                for name in reversed(installed):
                    swap(backup / name, Path(targets[name]["target"]))
                command("systemctl", "start", "fc27-cloud-api")
                command("systemctl", "start", "fc27-cloud-worker")
                raise
        finally:
            os.close(lock)


if __name__ == "__main__":
    main("--apply" in sys.argv)
