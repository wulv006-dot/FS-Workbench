"""Clear the P2PAH admin cache after a confirmed FC27 Coins write.

Runs in the existing private FC27 session container. Credentials and tokens stay
inside that process; only a small success/failure marker reaches the worker.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, "/usr/local/bin")
from p2pah_session_service import SessionManager, read_private_config


AUDIT = Path("/run/coin-execution.json")
CACHE_PATH = "/admin/tools.Caches/clear?server=1"


def clear_once(manager):
    status, raw = manager.request(CACHE_PATH, data={"type": "all", "file": ""},
                                  token=manager.token)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        return False, "cache_response_invalid"
    if not isinstance(payload, dict):
        return False, "cache_response_invalid"
    if status == 200 and payload.get("code") == 1:
        return True, "cleared"
    message = str(payload.get("msg") or "")
    if status == 200 and payload.get("code") == 0 and "操作过于频繁" in message:
        return False, "cache_rate_limited"
    if status in (401, 403) or payload.get("code") in (401, 403):
        return False, "cache_permission_denied"
    return False, "cache_clear_rejected"


def clear_confirmed_write(execution_id, audit, manager):
    if (str(uuid.UUID(execution_id)) != execution_id or
            audit.get("execution_id") != execution_id or
            audit.get("status") != "CONFIRMED" or
            audit.get("sync_confirmed") is not True or
            not audit.get("changed")):
        raise ValueError("confirmed_write_required")
    if not manager.ensure():
        raise ValueError("chenchao_session_unavailable")
    status, raw = manager.request("/admin/index/index", token=manager.token)
    try:
        identity = json.loads(raw)
        username = (identity.get("data") or {}).get("adminInfo", {}).get("username")
    except (ValueError, UnicodeError, AttributeError):
        username = None
    if status != 200 or username != "chenchao":
        raise ValueError("chenchao_identity_unconfirmed")
    ok, reason = clear_once(manager)
    if reason == "cache_rate_limited":
        time.sleep(31)
        ok, reason = clear_once(manager)
    if not ok:
        raise ValueError(reason)
    return {"status": "cleared", "scope": "all", "checked_at": datetime.now(timezone.utc).isoformat()}


def main():
    try:
        execution_id = sys.argv[1]
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        result = clear_confirmed_write(execution_id, audit,
                                       SessionManager(read_private_config()))
    except (IndexError, OSError, ValueError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "cache_clear_unavailable"
        print(json.dumps({"status": "unconfirmed", "reason": reason[:80]}))
        raise SystemExit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
