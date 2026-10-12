"""Clear the P2PAH admin cache after a confirmed FC27 Coins write.

Runs in the existing private FC27 session container. Credentials and tokens stay
inside that process; only a small success/failure marker reaches the worker.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import re
import sys
import time
import uuid

sys.path.insert(0, "/usr/local/bin")
from p2pah_session_service import SessionManager, read_private_config


AUDIT = Path("/run/coin-execution.json")
CACHE_PATH = "/admin/tools.Caches/clear?server=1"


class CacheClearError(ValueError):
    def __init__(self, reason, responses):
        super().__init__(reason)
        self.responses = responses


def response_details(status, raw):
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    message = payload.get("msg")
    safe = (isinstance(message, str) and 0 < len(message) <= 160 and
            (message in {"Please login first", "You have no permission", "ok"} or
             (re.fullmatch(r"[\u4e00-\u9fff\s，。！？、：；（）【】]+", message) and
              not any(word in message for word in ("密码", "口令", "密钥", "验证码")))))
    data = payload.get("data")
    return {"http_status": status,
            "api_code": payload.get("code") if type(payload.get("code")) is int else None,
            "message": message if safe else "redacted_or_nontext",
            "login_route": isinstance(data, dict) and data.get("routePath") == "/admin/login",
            "body_sha256": hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()}


def login_required(details):
    # Production /admin/index/index returns this exact contract when unauthenticated.
    return details["http_status"] == 200 and details["api_code"] == 302 and details["login_route"]


def identity(manager):
    status, raw = manager.request("/admin/index/index", token=manager.token)
    details = response_details(status, raw)
    try:
        payload = json.loads(raw)
        username = (payload.get("data") or {}).get("adminInfo", {}).get("username")
    except (ValueError, UnicodeError, AttributeError):
        username = None
    return status == 200 and details["api_code"] == 1 and username == "chenchao", details


def clear_once(manager):
    status, raw = manager.request(CACHE_PATH, data={"type": "all", "file": ""},
                                  token=manager.token)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        return False, "cache_response_invalid", response_details(status, raw)
    if not isinstance(payload, dict):
        return False, "cache_response_invalid", response_details(status, raw)
    details = response_details(status, raw)
    if status == 200 and type(payload.get("code")) is int and payload.get("code") == 1:
        return True, "cleared", details
    message = str(payload.get("msg") or "")
    if status == 200 and payload.get("code") == 0 and "操作过于频繁" in message:
        return False, "cache_rate_limited", details
    if login_required(details):
        return False, "cache_session_expired", details
    if status in (401, 403) or payload.get("code") in (401, 403):
        return False, "cache_permission_denied", details
    return False, "cache_clear_rejected", details


def clear_confirmed_write(execution_id, audit, manager):
    if (str(uuid.UUID(execution_id)) != execution_id or
            audit.get("execution_id") != execution_id or
            audit.get("status") != "CONFIRMED" or
            audit.get("sync_confirmed") is not True or
            not audit.get("changed")):
        raise ValueError("confirmed_write_required")
    if not manager.ensure():
        raise ValueError("chenchao_session_unavailable")
    authorized, _ = identity(manager)
    if not authorized:
        raise ValueError("chenchao_identity_unconfirmed")
    responses, recovered = [], []
    for _ in range(3):
        ok, reason, details = clear_once(manager)
        responses.append({"action": "clear", "reason": reason, **details})
        if ok:
            return {"status": "cleared", "scope": "all", "attempts": sum(
                    row["action"] == "clear" for row in responses), "recovered": recovered,
                    "responses": responses, "checked_at": datetime.now(timezone.utc).isoformat()}
        if reason == "cache_permission_denied" or len(recovered) == 2:
            break
        if reason == "cache_rate_limited" and reason not in recovered:
            time.sleep(31)
            recovered.append(reason)
            authorized, identity_details = identity(manager)
            responses.append({"action": "identity", **identity_details})
            if authorized:
                continue
            if not login_required(identity_details):
                raise CacheClearError("chenchao_identity_unconfirmed", responses)
        elif reason not in {"cache_session_expired", "cache_clear_rejected"}:
            break
        else:
            authorized, identity_details = identity(manager)
            responses.append({"action": "identity", **identity_details})
        if not login_required(identity_details) or "cache_session_expired" in recovered:
            break
        if not manager.ensure():
            raise CacheClearError("chenchao_session_unavailable", responses)
        authorized, identity_details = identity(manager)
        responses.append({"action": "identity_after_renewal", **identity_details})
        if not authorized:
            raise CacheClearError("chenchao_identity_unconfirmed", responses)
        recovered.append("cache_session_expired")
    raise CacheClearError(reason, responses)


def main():
    try:
        execution_id = sys.argv[1]
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        result = clear_confirmed_write(execution_id, audit,
                                       SessionManager(read_private_config()))
    except (IndexError, OSError, ValueError, TypeError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "cache_clear_unavailable"
        result = {"status": "unconfirmed", "reason": reason[:80]}
        if isinstance(exc, CacheClearError):
            result["responses"] = exc.responses
        print(json.dumps(result))
        raise SystemExit(2)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
