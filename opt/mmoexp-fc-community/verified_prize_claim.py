"""Offline ledger for operator-approved FC27 weekly coupon claims.

The issuer must validate winner evidence outside Discord API data before calling
``issue``. This module has no Discord listener, Admin writer or live scheduler.
"""

import hashlib
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path

from match_rewards import RewardError, coupon_snapshot_fingerprint
from match_rewards_delivery import email_fingerprint, normalized_email


WEEK = re.compile(r"20[0-9]{2}-W(?:0[1-9]|[1-4][0-9]|5[0-3])\Z")
EVIDENCE = re.compile(r"[A-Za-z0-9:_-]{8,128}\Z")
FINGERPRINT = re.compile(r"[0-9a-f]{64}\Z")
COUPON_STOCK_CAP = 30
WINNER_CAP = 20
DISCOUNT_PERCENT = 8
VALID_DAYS_AFTER_CLAIM = 7
SITE_ID = 266
GAME_ID = 1327


def validate_campaign_coupon(row):
    """Lock an Admin coupon to the approved 8% FC27 weekly reward terms."""
    if not isinstance(row, dict):
        raise RewardError("FC27 weekly coupon terms are unavailable")
    expected = {"type": 1, "fetch_scene": 4, "status": 1,
                "mode_type": 2, "time_effect": 2, "days": VALID_DAYS_AFTER_CLAIM,
                "site_id": SITE_ID, "game_id": GAME_ID,
                "limit_qty": COUPON_STOCK_CAP, "repeat_qty": 1, "is_open": 0}
    try:
        exact = all(int(row[key]) == value for key, value in expected.items())
        ratio = Decimal(str(row["reduce"])) == Decimal(100 - DISCOUNT_PERCENT)
        uncapped = Decimal(str(row["max_reduce"])) == 0
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise RewardError("FC27 weekly coupon terms are unavailable") from None
    if not (exact and ratio and uncapped):
        raise RewardError("FC27 weekly coupon terms do not match the approved rules")
    try:
        no_minimum = Decimal(str(row["attain"])) == 0
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise RewardError("FC27 weekly coupon terms are unavailable") from None
    if not no_minimum:
        raise RewardError("FC27 weekly coupon terms do not match the approved rules")
    return coupon_snapshot_fingerprint(row)


class VerifiedPrizeClaims:
    """One player-bound ticket per approved event; 20 winners per week."""

    def __init__(self, path):
        self.path = str(Path(path))
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS verified_prize_claims (
                    claim_id TEXT PRIMARY KEY,
                    ticket_hash TEXT NOT NULL UNIQUE,
                    week_key TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    coupon_id INTEGER NOT NULL,
                    coupon_fingerprint TEXT NOT NULL,
                    member_id INTEGER,
                    batch_no TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    recipient_email_hash TEXT,
                    job_id TEXT,
                    member_coupon_id TEXT,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(week_key, evidence_id),
                    UNIQUE(week_key, subject_hash)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS verified_prize_one_member_week
                    ON verified_prize_claims(week_key, member_id)
                    WHERE member_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS verified_prize_one_email_week
                    ON verified_prize_claims(week_key, recipient_email_hash)
                    WHERE recipient_email_hash IS NOT NULL;
            """)

    @staticmethod
    def _claim_view(row):
        """Return only fields needed by the private claim flow and grant adapter."""
        if row is None:
            return None
        return {key: row[key] for key in
                ("claim_id", "week_key", "coupon_id", "member_id", "batch_no",
                 "status", "recipient_email_hash", "job_id", "member_coupon_id")}

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

    def issue(self, week_key, evidence_id, subject_ref, coupon_row,
              expires_at, now=None):
        """Operator-only: return a new bearer ticket once; never persist raw token."""
        ts = int(time.time() if now is None else now)
        if not isinstance(week_key, str) or not WEEK.fullmatch(week_key):
            raise RewardError("Invalid reward week")
        if not isinstance(evidence_id, str) or not EVIDENCE.fullmatch(evidence_id):
            raise RewardError("Verified external evidence ID is required")
        if not isinstance(subject_ref, str) or not EVIDENCE.fullmatch(subject_ref):
            raise RewardError("Verified external player reference is required")
        if (not isinstance(coupon_row, dict) or
                type(coupon_row.get("id")) is not int or coupon_row["id"] <= 0):
            raise RewardError("A locked FC27 coupon is required")
        coupon_fingerprint = validate_campaign_coupon(coupon_row)
        if type(expires_at) is not int or expires_at <= ts:
            raise RewardError("Ticket expiry must be in the future")
        token = secrets.token_urlsafe(32)
        claim_id = secrets.token_hex(16)
        subject_hash = hashlib.sha256(subject_ref.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("""SELECT 1 FROM verified_prize_claims WHERE week_key=?
                          AND (evidence_id=? OR subject_hash=?)""",
                          (week_key, evidence_id, subject_hash)).fetchone():
                raise RewardError("Player already has a ticket this week")
            count = db.execute("SELECT COUNT(*) FROM verified_prize_claims WHERE week_key=?",
                               (week_key,)).fetchone()[0]
            if count >= WINNER_CAP:
                raise RewardError("Weekly ticket cap reached")
            db.execute("""INSERT INTO verified_prize_claims
                       (claim_id,ticket_hash,week_key,evidence_id,subject_hash,coupon_id,
                        coupon_fingerprint,batch_no,status,created_at,expires_at,updated_at)
                       VALUES (?,?,?,?,?,?,?,?,'issued',?,?,?)""",
                       (claim_id, hashlib.sha256(token.encode()).hexdigest(), week_key,
                        evidence_id, subject_hash, coupon_row["id"], coupon_fingerprint,
                        "FC27W_" + claim_id.upper(), ts, expires_at, ts))
        return {"claim_id": claim_id, "ticket": token}

    def redeem(self, ticket, claimant_ref, site_member_id, now=None):
        """Bind the named winner's ticket to one verified MMOEXP account."""
        ts = int(time.time() if now is None else now)
        if not isinstance(ticket, str) or len(ticket) < 32 or len(ticket) > 128:
            raise RewardError("Invalid ticket")
        if not isinstance(claimant_ref, str) or not EVIDENCE.fullmatch(claimant_ref):
            raise RewardError("Verified player reference is required")
        if type(site_member_id) is not int or site_member_id <= 0:
            raise RewardError("Verified MMOEXP member is required")
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        claimant_hash = hashlib.sha256(claimant_ref.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM verified_prize_claims WHERE ticket_hash=?",
                             (digest,)).fetchone()
            if not row:
                raise RewardError("Invalid ticket")
            if row["subject_hash"] != claimant_hash:
                raise RewardError("Ticket belongs to another player")
            return self._reserve(db, row, site_member_id, ts)

    def redeem_for_player(self, week_key, claimant_ref, site_member_id, now=None):
        """Legacy member-ID path; the email-only path is redeem_email_for_player."""
        if not isinstance(week_key, str) or not WEEK.fullmatch(week_key):
            raise RewardError("Invalid reward week")
        if not isinstance(claimant_ref, str) or not EVIDENCE.fullmatch(claimant_ref):
            raise RewardError("Verified player reference is required")
        if type(site_member_id) is not int or site_member_id <= 0:
            raise RewardError("Verified MMOEXP member is required")
        claimant_hash = hashlib.sha256(claimant_ref.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM verified_prize_claims
                          WHERE week_key=? AND subject_hash=?""",
                             (week_key, claimant_hash)).fetchone()
            if not row:
                raise RewardError("No verified reward for this player and week")
            return self._reserve(db, row, site_member_id,
                                 int(time.time() if now is None else now))

    def redeem_email_for_player(self, week_key, claimant_ref, email, now=None):
        """Reserve one weekly reward using the winner's private email input."""
        if not isinstance(week_key, str) or not WEEK.fullmatch(week_key):
            raise RewardError("Invalid reward week")
        if not isinstance(claimant_ref, str) or not EVIDENCE.fullmatch(claimant_ref):
            raise RewardError("Verified player reference is required")
        recipient_hash = email_fingerprint(normalized_email(email))
        claimant_hash = hashlib.sha256(claimant_ref.encode()).hexdigest()
        ts = int(time.time() if now is None else now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""SELECT * FROM verified_prize_claims
                          WHERE week_key=? AND subject_hash=?""",
                             (week_key, claimant_hash)).fetchone()
            if not row:
                raise RewardError("No verified reward for this player and week")
            if row["recipient_email_hash"] == recipient_hash:
                return self._claim_view(row)
            if row["status"] != "issued" or row["expires_at"] <= ts:
                raise RewardError("Ticket unavailable or expired")
            try:
                db.execute("""UPDATE verified_prize_claims SET recipient_email_hash=?,
                              status='reserved',updated_at=? WHERE claim_id=? AND status='issued'""",
                           (recipient_hash, ts, row["claim_id"]))
            except sqlite3.IntegrityError:
                raise RewardError("Account already claimed this week") from None
            return self._claim_view(db.execute(
                "SELECT * FROM verified_prize_claims WHERE claim_id=?",
                (row["claim_id"],)).fetchone())

    def open_week_for_player(self, claimant_ref, now=None):
        """Find the latest unexpired approved week for one authenticated player."""
        if not isinstance(claimant_ref, str) or not EVIDENCE.fullmatch(claimant_ref):
            raise RewardError("Verified player reference is required")
        with self._db() as db:
            row = db.execute("""SELECT week_key FROM verified_prize_claims
                          WHERE subject_hash=? AND expires_at>? ORDER BY week_key DESC LIMIT 1""",
                             (hashlib.sha256(claimant_ref.encode()).hexdigest(),
                              int(time.time() if now is None else now))).fetchone()
            return row["week_key"] if row else None

    def _reserve(self, db, row, site_member_id, ts):
        if row["member_id"] == site_member_id:
            return self._claim_view(row)
        if row["status"] != "issued" or row["expires_at"] <= ts:
            raise RewardError("Ticket unavailable or expired")
        try:
            db.execute("""UPDATE verified_prize_claims
                          SET member_id=?,status='reserved',updated_at=?
                          WHERE claim_id=? AND status='issued'""",
                       (site_member_id, ts, row["claim_id"]))
        except sqlite3.IntegrityError:
            raise RewardError("Account already claimed this week") from None
        return self._claim_view(db.execute(
            "SELECT * FROM verified_prize_claims WHERE claim_id=?",
            (row["claim_id"],)).fetchone())

    def grant_target(self, claim_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM verified_prize_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if not row:
                return None
            target = self._claim_view(row)
            target["site_member_id"] = target["member_id"]
            target["enabled"] = 1
            return target

    def begin_grant(self, claim_id, current_coupon_fingerprint,
                    recipient_email_hash, now=None):
        if not isinstance(recipient_email_hash, str) or not FINGERPRINT.fullmatch(recipient_email_hash):
            raise RewardError("Verified recipient fingerprint is required")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM verified_prize_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if not row or row["status"] != "reserved":
                raise RewardError("Claim is not ready for a first grant")
            if row["coupon_fingerprint"] != current_coupon_fingerprint:
                raise RewardError("Coupon terms changed; grant is paused")
            if row["recipient_email_hash"] and row["recipient_email_hash"] != recipient_email_hash:
                raise RewardError("Reward email changed after reservation")
            db.execute("""UPDATE verified_prize_claims SET status='sending',
                          recipient_email_hash=?,updated_at=? WHERE claim_id=?""",
                       (recipient_email_hash, int(time.time() if now is None else now), claim_id))
            return {"coupon_id": row["coupon_id"], "batch_no": row["batch_no"],
                    "site_member_id": row["member_id"]}

    def record_grant_result(self, claim_id, status, job_id=None,
                            member_coupon_id=None, now=None):
        if status not in ("pending", "confirmed", "unknown"):
            raise RewardError("Invalid grant result")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,job_id FROM verified_prize_claims WHERE claim_id=?",
                             (claim_id,)).fetchone()
            if not row or row["status"] not in ("sending", "pending", "unknown"):
                raise RewardError("Claim has no unresolved grant")
            if row["job_id"] and job_id and row["job_id"] != job_id:
                raise RewardError("Grant job ID changed")
            if status == "pending" and not (job_id or row["job_id"]):
                raise RewardError("Pending grant requires original job ID")
            if status == "confirmed" and not member_coupon_id:
                raise RewardError("Confirmed grant requires member coupon ID")
            db.execute("""UPDATE verified_prize_claims SET status=?,job_id=?,
                          member_coupon_id=?,updated_at=? WHERE claim_id=?""",
                       (status, job_id or row["job_id"], member_coupon_id,
                        int(time.time() if now is None else now), claim_id))
