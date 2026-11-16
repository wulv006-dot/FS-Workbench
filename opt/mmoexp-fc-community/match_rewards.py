"""First-party FC27 match rewards ledger; no Discord data or network calls.

Only a trusted MMOEXP site settlement worker may call ``credit_site_points``.
The public Discord bot must never use UnifyFootball points, roles, messages, or
leaderboard rows as coupon eligibility evidence.
"""

import hashlib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path


SITE_EVIDENCE = re.compile(r"site:[A-Za-z0-9_-]{1,96}\Z")
OFFER_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
COUPON_FIELDS = ("id", "title", "type", "fetch_scene", "status", "mode_type",
                 "attain", "reduce", "max_reduce", "limit_qty", "repeat_qty",
                 "time_effect", "start_time", "end_time", "days", "site_id",
                 "game_id", "product_type", "goods_id", "scope_bindings", "is_open")
REQUIRED_COUPON_FIELDS = ("id", "fetch_scene", "status", "mode_type", "attain",
                          "reduce", "limit_qty", "repeat_qty", "site_id", "game_id")


class RewardError(ValueError):
    pass


def coupon_snapshot_fingerprint(row):
    """Hash the same coupon terms the existing Lucky Loot adapter reads."""
    if not isinstance(row, dict) or any(key not in row for key in REQUIRED_COUPON_FIELDS):
        raise RewardError("Coupon detail is incomplete")
    terms = {key: row[key] for key in COUPON_FIELDS if key in row}
    raw = json.dumps(terms, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class RewardStore:
    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS reward_points (
                    evidence_id TEXT PRIMARY KEY,
                    site_member_id INTEGER NOT NULL,
                    points INTEGER NOT NULL CHECK(points > 0),
                    created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reward_offers (
                    offer_id TEXT PRIMARY KEY,
                    coupon_id INTEGER NOT NULL,
                    coupon_fingerprint TEXT NOT NULL,
                    cost_points INTEGER NOT NULL CHECK(cost_points > 0),
                    max_claims INTEGER NOT NULL CHECK(max_claims > 0),
                    enabled INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS reward_claims (
                    claim_id TEXT PRIMARY KEY,
                    offer_id TEXT NOT NULL,
                    site_member_id INTEGER NOT NULL,
                    batch_no TEXT NOT NULL UNIQUE,
                    cost_points INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    job_id TEXT,
                    member_coupon_id TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(offer_id, site_member_id)
                );
            """)

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _member(site_member_id):
        if type(site_member_id) is not int or site_member_id <= 0:
            raise RewardError("A verified MMOEXP member ID is required")
        return site_member_id

    def credit_site_points(self, site_member_id, evidence_id, points, now=None):
        """Record one final, verified MMOEXP-site settlement exactly once.

        The source event must come from the site settlement worker. This method
        is deliberately not exposed as an HTTP or Discord command.
        """
        self._member(site_member_id)
        if not isinstance(evidence_id, str) or not SITE_EVIDENCE.fullmatch(evidence_id):
            raise RewardError("A first-party settlement evidence ID is required")
        if type(points) is not int or points <= 0 or points > 100:
            raise RewardError("Invalid settlement points")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT site_member_id,points FROM reward_points WHERE evidence_id=?",
                             (evidence_id,)).fetchone()
            if old:
                if old["site_member_id"] != site_member_id or old["points"] != points:
                    raise RewardError("Settlement evidence changed")
                return False
            db.execute("INSERT INTO reward_points VALUES (?,?,?,?)",
                       (evidence_id, site_member_id, points, int(now or time.time())))
            return True

    def configure_offer(self, offer_id, coupon_id, coupon_fingerprint,
                        cost_points, max_claims, enabled=False):
        if not isinstance(offer_id, str) or not OFFER_ID.fullmatch(offer_id):
            raise RewardError("Invalid offer ID")
        if (type(coupon_id) is not int or coupon_id <= 0 or
                not isinstance(coupon_fingerprint, str) or
                not FINGERPRINT.fullmatch(coupon_fingerprint) or
                type(cost_points) is not int or cost_points <= 0 or
                type(max_claims) is not int or max_claims <= 0):
            raise RewardError("Invalid coupon offer")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM reward_offers WHERE offer_id=?",
                                  (offer_id,)).fetchone()
            values = (coupon_id, coupon_fingerprint, cost_points, max_claims)
            if existing:
                if values != tuple(existing[k] for k in
                                   ("coupon_id", "coupon_fingerprint", "cost_points", "max_claims")):
                    raise RewardError("An existing offer cannot change its coupon or terms")
                db.execute("UPDATE reward_offers SET enabled=? WHERE offer_id=?",
                           (int(bool(enabled)), offer_id))
            else:
                db.execute("INSERT INTO reward_offers VALUES (?,?,?,?,?,?)",
                           (offer_id, *values, int(bool(enabled))))

    @staticmethod
    def _claim_id(offer_id, site_member_id):
        return hashlib.sha256("{}:{}".format(offer_id, site_member_id).encode()).hexdigest()[:32]

    def balance(self, site_member_id):
        self._member(site_member_id)
        with self._db() as db:
            earned = db.execute("SELECT COALESCE(SUM(points),0) FROM reward_points WHERE site_member_id=?",
                                (site_member_id,)).fetchone()[0]
            spent = db.execute("""SELECT COALESCE(SUM(cost_points),0) FROM reward_claims
                                  WHERE site_member_id=? AND status!='void'""",
                               (site_member_id,)).fetchone()[0]
            return earned - spent

    def claim_status(self, offer_id, site_member_id):
        """Read an earlier claim even after the offer has been paused."""
        self._member(site_member_id)
        with self._db() as db:
            row = db.execute("SELECT * FROM reward_claims WHERE offer_id=? AND site_member_id=?",
                             (offer_id, site_member_id)).fetchone()
            return dict(row) if row else None

    def claim(self, offer_id, site_member_id, now=None):
        """Atomically reserve points and one coupon slot for a site member."""
        self._member(site_member_id)
        if not isinstance(offer_id, str) or not OFFER_ID.fullmatch(offer_id):
            raise RewardError("Invalid offer ID")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            offer = db.execute("SELECT * FROM reward_offers WHERE offer_id=? AND enabled=1",
                               (offer_id,)).fetchone()
            if not offer:
                raise RewardError("Offer is unavailable")
            old = db.execute("SELECT * FROM reward_claims WHERE offer_id=? AND site_member_id=?",
                             (offer_id, site_member_id)).fetchone()
            if old and old["status"] != "void":
                return dict(old)
            used = db.execute("""SELECT COUNT(*) FROM reward_claims
                                 WHERE offer_id=? AND status!='void'""", (offer_id,)).fetchone()[0]
            if used >= offer["max_claims"]:
                raise RewardError("Offer is fully claimed")
            earned = db.execute("SELECT COALESCE(SUM(points),0) FROM reward_points WHERE site_member_id=?",
                                (site_member_id,)).fetchone()[0]
            spent = db.execute("""SELECT COALESCE(SUM(cost_points),0) FROM reward_claims
                                  WHERE site_member_id=? AND status!='void'""",
                               (site_member_id,)).fetchone()[0]
            if earned - spent < offer["cost_points"]:
                raise RewardError("Not enough MMOEXP Match Points")
            claim_id = self._claim_id(offer_id, site_member_id)
            batch_no = "FC27R_" + claim_id.upper()
            ts = int(now or time.time())
            if old:
                db.execute("""UPDATE reward_claims SET status='reserved',updated_at=?
                              WHERE claim_id=? AND status='void'""", (ts, claim_id))
            else:
                db.execute("INSERT INTO reward_claims VALUES (?,?,?,?,?,'reserved',NULL,NULL,?,?)",
                           (claim_id, offer_id, site_member_id, batch_no, offer["cost_points"], ts, ts))
            return dict(db.execute("SELECT * FROM reward_claims WHERE claim_id=?",
                                   (claim_id,)).fetchone())

    def begin_grant(self, claim_id, current_coupon_fingerprint, now=None):
        """Return the stable Admin batch once; caller must verify site member email."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT c.*,o.coupon_id,o.coupon_fingerprint FROM reward_claims c
                                JOIN reward_offers o ON c.offer_id=o.offer_id
                                WHERE c.claim_id=? AND o.enabled=1""", (claim_id,)).fetchone()
            if not row or row["status"] != "reserved":
                raise RewardError("Claim is not ready for a first grant")
            if row["coupon_fingerprint"] != current_coupon_fingerprint:
                raise RewardError("Coupon terms changed; grant is paused")
            db.execute("UPDATE reward_claims SET status='sending',updated_at=? WHERE claim_id=?",
                       (int(now or time.time()), claim_id))
            return {"coupon_id": row["coupon_id"], "batch_no": row["batch_no"],
                    "site_member_id": row["site_member_id"]}

    def record_grant_result(self, claim_id, status, job_id=None,
                            member_coupon_id=None, now=None):
        if status not in ("pending", "confirmed", "unknown"):
            raise RewardError("Grant result must be pending, confirmed or unknown")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,job_id FROM reward_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if not row or row["status"] not in ("sending", "pending", "unknown"):
                raise RewardError("Claim has no unresolved grant")
            if row["job_id"] and job_id and row["job_id"] != job_id:
                raise RewardError("Grant job ID changed")
            if status == "pending" and not (job_id or row["job_id"]):
                raise RewardError("Pending grant requires the original job ID")
            if status == "confirmed" and not member_coupon_id:
                raise RewardError("Confirmed grant requires a member coupon ID")
            db.execute("""UPDATE reward_claims SET status=?,job_id=?,member_coupon_id=?,updated_at=?
                          WHERE claim_id=?""", (status, job_id or row["job_id"],
                                                member_coupon_id, int(now or time.time()), claim_id))

    def void_before_grant(self, claim_id, now=None):
        """Release a reservation only before any Admin request may have started."""
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM reward_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if not row or row["status"] != "reserved":
                raise RewardError("Only an unsubmitted reservation can be voided")
            db.execute("UPDATE reward_claims SET status='void',updated_at=? WHERE claim_id=?",
                       (int(now or time.time()), claim_id))
