"""Internal FC27 coupon delivery; requires a verified MMOEXP site-member provider.

This module deliberately has no HTTP or Discord entry point. A site service
must authenticate the current member before it invokes the reward ledger.
"""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from match_rewards import RewardError, coupon_snapshot_fingerprint


EMAIL = re.compile(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+\Z")


def normalized_email(value):
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value.strip()):
        raise RewardError("Valid MMOEXP account email is required")
    return value.strip().lower()


def verified_email(site_member, expected_member_id):
    """Accept only an identity assertion supplied by the MMOEXP site backend."""
    if (not isinstance(site_member, dict) or
            type(site_member.get("site_id")) is not int or site_member["site_id"] != 266 or
            type(site_member.get("member_id")) is not int or
            site_member["member_id"] != expected_member_id or
            site_member.get("email_verified") is not True or
            site_member.get("account_active") is not True):
        raise RewardError("Verified MMOEXP member is required")
    try:
        return normalized_email(site_member.get("email"))
    except RewardError:
        raise RewardError("Verified MMOEXP member is required") from None


def email_fingerprint(email):
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


class CouponBridge:
    """Call the existing Lucky Loot coupon adapter over stdin, never argv."""

    def __init__(self, node=None, script=None):
        self.node = node or shutil.which("node")
        self.script = Path(script or Path(__file__).with_name("reward_coupon_bridge.cjs"))
        if not self.node or not self.script.is_file():
            raise RewardError("Coupon adapter is unavailable")

    def _call(self, payload):
        try:
            done = subprocess.run([self.node, str(self.script)],
                                  input=json.dumps(payload, separators=(",", ":")),
                                  text=True, capture_output=True, timeout=105,
                                  check=False)
            if done.returncode or len(done.stdout) > 200000 or not done.stdout:
                raise RewardError("Coupon adapter is unavailable")
            result = json.loads(done.stdout)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise RewardError("Coupon adapter is unavailable")
            return result["result"]
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
            raise RewardError("Coupon adapter is unavailable") from None

    def detail(self, coupon_id):
        return self._call({"action": "detail", "coupon_id": coupon_id})

    def grant(self, coupon_id, email, batch_no):
        return self._call({"action": "grant", "coupon_id": coupon_id,
                           "email": email, "batch_no": batch_no})

    def reconcile(self, job_id, email, batch_no):
        return self._call({"action": "reconcile", "job_id": job_id,
                           "email": email, "batch_no": batch_no})


class RewardDelivery:
    def __init__(self, store, member_provider, coupon_adapter):
        self.store = store
        self.member_provider = member_provider
        self.coupon_adapter = coupon_adapter

    def _member_email(self, member_id):
        return verified_email(self.member_provider(member_id), member_id)

    @staticmethod
    def _coupon_detail(row, coupon_id):
        if (not isinstance(row, dict) or
                type(row.get("id")) not in (int, str) or str(row["id"]) != str(coupon_id) or
                int(row.get("site_id") or 0) != 266 or
                int(row.get("game_id") or 0) != 1327 or
                int(row.get("fetch_scene") or 0) != 4 or
                int(row.get("status") or 0) != 1):
            raise RewardError("FC27 coupon is unavailable")
        return coupon_snapshot_fingerprint(row)

    def deliver(self, claim_id):
        """Submit at most one Admin grant for a reserved, verified member."""
        target = self.store.grant_target(claim_id)
        if not target:
            raise RewardError("Claim not found")
        if target["status"] != "reserved":
            return self.store.grant_target(claim_id)
        if not target["enabled"]:
            raise RewardError("Offer is unavailable")
        email = self._member_email(target["site_member_id"])
        return self._deliver_email(claim_id, target, email)

    def _deliver_email(self, claim_id, target, email):
        row = self.coupon_adapter.detail(target["coupon_id"])
        fingerprint = self._coupon_detail(row, target["coupon_id"])
        dispatch = self.store.begin_grant(claim_id, fingerprint,
                                          email_fingerprint(email))
        try:
            result = self.coupon_adapter.grant(dispatch["coupon_id"],
                                               email, dispatch["batch_no"])
        except Exception:
            self.store.record_grant_result(claim_id, "unknown")
            return self.store.grant_target(claim_id)
        if not isinstance(result, dict):
            result = {}
        if result.get("state") == "confirmed" and result.get("member_coupon_id"):
            self.store.record_grant_result(claim_id, "confirmed",
                                           member_coupon_id=str(result["member_coupon_id"]))
        elif result.get("state") == "pending" and result.get("job_id"):
            self.store.record_grant_result(claim_id, "pending",
                                           job_id=str(result["job_id"]))
        else:
            self.store.record_grant_result(claim_id, "unknown")
        return self.store.grant_target(claim_id)

    def reconcile(self, claim_id):
        """Only query the original Admin job; a second grant POST is impossible here."""
        target = self.store.grant_target(claim_id)
        if not target or target["status"] != "pending" or not target["job_id"]:
            raise RewardError("No pending grant job")
        email = self._member_email(target["site_member_id"])
        if email_fingerprint(email) != target["recipient_email_hash"]:
            self.store.record_grant_result(claim_id, "unknown", job_id=target["job_id"])
            return self.store.grant_target(claim_id)
        return self._reconcile_email(claim_id, target, email)

    def _reconcile_email(self, claim_id, target, email):
        try:
            result = self.coupon_adapter.reconcile(target["job_id"], email,
                                                   target["batch_no"])
        except Exception:
            return target  # A read-only job check may safely be retried.
        if not isinstance(result, dict):
            return target
        if result.get("state") == "confirmed" and result.get("member_coupon_id"):
            self.store.record_grant_result(claim_id, "confirmed",
                                           job_id=target["job_id"],
                                           member_coupon_id=str(result["member_coupon_id"]))
        return self.store.grant_target(claim_id)


class WeeklyEmailDelivery(RewardDelivery):
    """Send a verified weekly prize to the email privately entered by its winner."""

    def __init__(self, store, coupon_adapter):
        super().__init__(store, None, coupon_adapter)

    def deliver(self, claim_id, email):
        target = self.store.grant_target(claim_id)
        if not target:
            raise RewardError("Claim not found")
        address = normalized_email(email)
        if email_fingerprint(address) != target["recipient_email_hash"]:
            raise RewardError("Reward email changed after reservation")
        if target["status"] != "reserved":
            return target
        return self._deliver_email(claim_id, target, address)

    def reconcile(self, claim_id, email):
        target = self.store.grant_target(claim_id)
        if not target or target["status"] != "pending" or not target["job_id"]:
            raise RewardError("No pending grant job")
        address = normalized_email(email)
        if email_fingerprint(address) != target["recipient_email_hash"]:
            raise RewardError("Reward email changed after reservation")
        return self._reconcile_email(claim_id, target, address)
