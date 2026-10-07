"""Independent switch for FC27 Coins -> Players price synchronization."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile

from automation_policy import ROOT


POLICY_FILE = Path(os.environ.get("FC27_PLAYER_SYNC_POLICY", str(ROOT / "config/player-sync.json")))


def initial_policy():
    return {"enabled": False, "revision": 0, "updated_at": None, "updated_by": None}


def load_policy():
    if not POLICY_FILE.exists():
        return initial_policy()
    value = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    if (not isinstance(value, dict) or set(value) != set(initial_policy())
            or type(value["enabled"]) is not bool
            or type(value["revision"]) is not int or value["revision"] < 0
            or (value["updated_at"] is not None and not isinstance(value["updated_at"], str))
            or (value["updated_by"] is not None and not isinstance(value["updated_by"], str))):
        raise ValueError("player_sync_policy_invalid")
    return value


def save_policy(enabled, actor, expected_revision):
    if type(enabled) is not bool or type(expected_revision) is not int or expected_revision < 0:
        raise ValueError("player_sync_request_invalid")
    if not isinstance(actor, str) or not actor or len(actor) > 60:
        raise ValueError("player_sync_actor_invalid")
    import fcntl
    POLICY_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock = POLICY_FILE.with_suffix(".lock")
    with lock.open("a+b") as stream:
        os.chmod(lock, 0o660)
        fcntl.flock(stream, fcntl.LOCK_EX)
        before = load_policy()
        if before["revision"] != expected_revision:
            raise ValueError("player_sync_revision_changed")
        result = {"enabled": enabled, "revision": expected_revision + 1,
                  "updated_at": datetime.now(timezone.utc).isoformat(), "updated_by": actor}
        audit_path = POLICY_FILE.parent / "player-sync-events.jsonl"
        with audit_path.open("a", encoding="utf-8") as audit:
            os.chmod(audit_path, 0o660)
            fd, temp = tempfile.mkstemp(dir=POLICY_FILE.parent, prefix=".player-sync-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(result, output, ensure_ascii=False, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temp, 0o640)
                os.replace(temp, POLICY_FILE)
                audit.write(json.dumps({"at": result["updated_at"], "actor": actor,
                                        "before": before, "after": result}, ensure_ascii=False) + "\n")
                audit.flush()
                os.fsync(audit.fileno())
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
    return result
