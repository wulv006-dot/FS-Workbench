"""One-file adapter of the existing monitor publisher; no service/config changes."""
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import sys

STAGE = Path(__file__).resolve().parent
BASE = Path("/opt/fc-ops-monitor-stage-noncore-20261009/publishers/monitor-publisher.py")
BASE_SHA = "58226101f76dfdf4539c7ec147ae3b3ee2b7754969add2a9b88d2217026515eb"
TARGET = Path("/opt/fc-ops-readonly-monitor/hooks.py")
DATA = Path("/var/lib/fc-ops-readonly-monitor")
BEFORE = "b326c54808bacdda43d0f5b29e065d503256502d7765a0e75eee35b674223f0d"
AFTER = "792b84ee67f0441ba7da6e591d8029ef25eb3c41c6085d195c2dc1cf2856d753"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify():
    for path, wanted in ((TARGET, BEFORE), (STAGE / "source/hooks.py", AFTER), (BASE, BASE_SHA)):
        if any(p.is_symlink() for p in (path, *path.parents)) or digest(path) != wanted:
            raise ValueError("baseline_or_payload_changed:" + str(path))
    compile((STAGE / "source/hooks.py").read_text(), "hooks.py", "exec")


def publish(apply=False):
    if os.geteuid() != 0:
        raise ValueError("root_required")
    verify()
    spec = importlib.util.spec_from_file_location("existing_monitor_publisher", BASE)
    base = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(base)
    before = base.baseline()
    receipt = {"applied": False, "target": str(TARGET), "before": BEFORE, "after": AFTER}
    if not apply:
        return receipt
    lock_path = DATA / ".collector.lock"
    if any(p.is_symlink() for p in (lock_path, *lock_path.parents)):
        raise ValueError("linked_collector_lock")
    fd = os.open(lock_path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        meta = os.fstat(fd)
        if (not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid != 0
                or stat.S_IMODE(meta.st_mode) != 0o600):
            raise ValueError("collector_lock_metadata")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verify()
        if base.baseline() != before:
            raise ValueError("protected_changed_before_swap")
        backup = DATA / "code-backups" / ("health-contract-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
        backup.mkdir(mode=0o700)
        shutil.copy2(TARGET, backup / "hooks.py")
        original_meta = TARGET.stat()
        installed = False
        try:
            base.noncore_swap(STAGE / "source/hooks.py", TARGET)
            installed = True
            current_meta = TARGET.stat()
            if (digest(TARGET) != AFTER or base.baseline() != before or
                    (original_meta.st_uid, original_meta.st_gid, stat.S_IMODE(original_meta.st_mode)) !=
                    (current_meta.st_uid, current_meta.st_gid, stat.S_IMODE(current_meta.st_mode))):
                raise RuntimeError("post_swap_verification_failed")
            receipt.update(applied=True, backup=str(backup), protected_unchanged=True,
                           services_restarted=False, deployed_at=datetime.now(timezone.utc).isoformat())
            (backup / "receipt.json").write_text(json.dumps(receipt, indent=2))
        except Exception:
            observed = digest(TARGET)
            if observed == AFTER:
                base.noncore_swap(backup / "hooks.py", TARGET)
                if digest(TARGET) != BEFORE:
                    raise RuntimeError("rollback_readback_failed")
            elif observed != BEFORE:
                raise RuntimeError("rollback_blocked_by_concurrent_change")
            raise
    finally:
        os.close(fd)
    (STAGE / "receipt.json").write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish("--apply" in sys.argv)))
