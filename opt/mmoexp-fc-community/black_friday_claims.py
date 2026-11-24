"""The FC27 Black Friday claim ledger and Admin coupon delivery."""
import hashlib
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from decimal import Decimal

from black_friday import BONUS_PERCENT
from match_rewards_delivery import EMAIL


class ClaimConflict(ValueError):
    pass


@dataclass(frozen=True)
class Receipt:
    tier: str
    receipts: tuple
    complete: bool
    replay: bool
    rejected: bool = False
    pending_registration: bool = False


def validate_coupon(bridge, label, coupon):
    mode, value = {'one': (1, 1), 'two': (1, 2), 'bonus': (2, 100 - BONUS_PERCENT)}[label]
    required = dict(id=coupon, type=1, status=1, site_id=266, game_id=1327, mode_type=mode,
                    fetch_scene=4, time_effect=2, days=7, is_open=0, repeat_qty=1,
                    goods_id=0, product_type=0, attain=0, max_reduce=0, reduce=value)
    row = bridge.detail(coupon)
    try:
        valid = (all(Decimal(str(row[key])) == expected for key, expected in required.items())
                 and row.get('scope_bindings') in ('', None, []))
    except (KeyError, ArithmeticError, TypeError):
        valid = False
    if not valid:
        raise ValueError('Black Friday coupon terms do not match the campaign.')


class Campaign:
    def __init__(self, state, coupons, lookup, bridge, *, ledger='campaign.sqlite3', legacy=None):
        if (set(coupons) != {'one', 'two', 'bonus'} or len(set(coupons.values())) != 3
                or any(type(value) is not int or value <= 0 for value in coupons.values())):
            raise ValueError('Black Friday coupon configuration is invalid.')
        self.path = state / ledger
        self.coupons, self.lookup, self.bridge = coupons, lookup, bridge
        with self.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS claims (
                discord_id INTEGER PRIMARY KEY, member_id INTEGER UNIQUE,
                email_hash TEXT NOT NULL UNIQUE, tier TEXT NOT NULL)''')
            if any(field[1] == 'member_id' and field[3] for field in db.execute('PRAGMA table_info(claims)')):
                db.execute('''CREATE TABLE claims_next (
                    discord_id INTEGER PRIMARY KEY, member_id INTEGER UNIQUE,
                    email_hash TEXT NOT NULL UNIQUE, tier TEXT NOT NULL)''')
                db.execute('INSERT INTO claims_next SELECT discord_id,member_id,email_hash,tier FROM claims')
                db.execute('DROP TABLE claims')
                db.execute('ALTER TABLE claims_next RENAME TO claims')
            db.execute('''CREATE TABLE IF NOT EXISTS delivery (
                discord_id INTEGER NOT NULL REFERENCES claims(discord_id), slot INTEGER NOT NULL,
                coupon_id INTEGER NOT NULL, batch TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL, job TEXT, receipt TEXT, PRIMARY KEY(discord_id, slot))''')
            if legacy:
                self.import_prior_claim(db, state, legacy)

    @contextmanager
    def transaction(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            yield db

    @staticmethod
    def import_prior_claim(db, state, cfg):
        digest = cfg['recipient_sha256']
        suffix = hashlib.sha256(('BF26-D4-single:' + digest).encode()).hexdigest()[:32].upper()
        batch = 'FC27R_' + suffix
        source = (state / 'real-grant.sqlite3').resolve()
        if not source.is_file():
            return
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old:
            row = old.execute('SELECT coupon,status,job,receipt FROM grants WHERE batch=?', (batch,)).fetchone()
        if row is None:
            return
        coupon, status, job, receipt = row
        if coupon != cfg['coupon_id']:
            raise ValueError('Existing test receipt does not match the reviewed coupon.')
        discord_id, member_id = cfg['discord_id'], cfg['member_id']
        prior = db.execute('SELECT member_id,email_hash FROM claims WHERE discord_id=?', (discord_id,)).fetchone()
        if prior is not None:
            if prior != (member_id, digest):
                raise ValueError('Existing test receipt does not match the campaign ledger.')
            return
        db.execute('INSERT INTO claims VALUES (?,?,?,?)', (discord_id, member_id, digest, 'two'))
        db.execute('INSERT INTO delivery VALUES (?,0,?,?,?,?,?)', (discord_id, coupon, batch, status, job, receipt))

    def find_claim(self, db, discord_id, digest, member_id=None):
        rows = db.execute('''SELECT discord_id,email_hash,tier FROM claims
            WHERE discord_id=? OR email_hash=? OR member_id=?''', (discord_id, digest, member_id)).fetchall()
        if rows:
            if len(rows) != 1 or rows[0][:2] != (discord_id, digest):
                raise ClaimConflict('One drop per Discord account and MMOEXP member.')
            return rows[0][2]
        return None

    def reserve(self, discord_id, digest, email, resume_only):
        with self.transaction() as db:
            tier = self.find_claim(db, discord_id, digest)
        if tier is not None:
            return tier, True
        if resume_only:
            raise ClaimConflict('No earlier claim was found for this account and email.')
        history = self.lookup(email)
        if ((history.member_id is not None and (type(history.member_id) is not int or history.member_id <= 0))
                or type(history.paid) is not int or type(history.completed) is not int
                or not 0 <= history.completed <= history.paid):
            raise ValueError('Incomplete order history.')
        tier = 'bonus' if history.completed >= 5 else 'two' if history.paid else 'one'
        labels = ('two', 'bonus') if tier == 'bonus' else (tier,)
        for label in labels:
            validate_coupon(self.bridge, label, self.coupons[label])
        with self.transaction() as db:
            previous = self.find_claim(db, discord_id, digest, history.member_id)
            if previous is not None:
                return previous, True
            db.execute('INSERT INTO claims VALUES (?,?,?,?)', (discord_id, history.member_id, digest, tier))
            identity = history.member_id if history.member_id is not None else 'email:' + digest
            for slot, label in enumerate(labels):
                suffix = hashlib.sha256(f'BF26:{identity}:{label}'.encode()).hexdigest()[:32].upper()
                db.execute('INSERT INTO delivery VALUES (?,?,?,?,\'ready\',NULL,NULL)',
                           (discord_id, slot, self.coupons[label], 'FC27R_' + suffix))
        return tier, False

    def deliver(self, discord_id, slot, email, label):
        with self.transaction() as db:
            coupon, batch, status, job, receipt = db.execute('''SELECT coupon_id,batch,status,job,receipt
                FROM delivery WHERE discord_id=? AND slot=?''', (discord_id, slot)).fetchone()
        if status == 'confirmed':
            return status, receipt
        if status == 'pending':
            try:
                result = self.bridge.reconcile(job, email, batch)
            except Exception:
                return status, None
        elif status == 'ready':
            validate_coupon(self.bridge, label, coupon)
            with self.transaction() as db:
                taken = db.execute('''UPDATE delivery SET status='submitted'
                    WHERE discord_id=? AND slot=? AND status='ready' ''', (discord_id, slot)).rowcount
            if not taken:
                return 'submitted', None
            try:
                result = self.bridge.grant(coupon, email, batch)
            except Exception:
                result = {}
        else:
            return status, None
        receipt = str(result.get('member_coupon_id') or '')
        newer_job = result.get('job_id') or job
        if result.get('state') == 'confirmed' and receipt.isascii() and receipt.isdigit() and int(receipt) > 0:
            new_status = 'confirmed'
        elif result.get('state') == 'pending_register':
            new_status = 'pending_register'
        elif result.get('state') in ('rejected', 'limit'):
            new_status = 'rejected'
        elif newer_job and (result.get('state') == 'pending' or status == 'pending'):
            new_status = 'pending'
        else:
            new_status = 'unknown'
        with self.transaction() as db:
            db.execute('''UPDATE delivery SET status=?,job=?,receipt=?
                WHERE discord_id=? AND slot=? AND status IN ('submitted','pending')''',
                (new_status, newer_job, receipt if new_status == 'confirmed' else None, discord_id, slot))
        return new_status, receipt if new_status == 'confirmed' else None

    def claim(self, discord_id, email, *, resume_only=False):
        email = email.strip().lower()
        if (type(discord_id) is not int or discord_id <= 0 or len(email) > 254
                or any(separator in email for separator in ('，', '；')) or not EMAIL.fullmatch(email)):
            raise ValueError('Enter a valid MMOEXP email.')
        digest = hashlib.sha256(email.encode()).hexdigest()
        tier, replay = self.reserve(discord_id, digest, email, resume_only)
        labels = ('two', 'bonus') if tier == 'bonus' else (tier,)
        receipts = []
        status = None
        for slot, label in enumerate(labels):
            status, receipt = self.deliver(discord_id, slot, email, label)
            if not receipt:
                break
            receipts.append(receipt)
        return Receipt(tier, tuple(receipts), len(receipts) == len(labels), replay,
                       rejected=status == 'rejected', pending_registration=status == 'pending_register')
