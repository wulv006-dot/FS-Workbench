"""Private durable purchase facts and frozen snapshots, independent of short-lived caches."""
import hmac
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from user_contract import canonical, digest, stamp


def safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('private_store_symlink')


class Store:
    def __init__(self, root, key, config):
        self.root, self.key, self.config = Path(root), key, config
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError('identity_key_required')
        safe(self.root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_mode & 0o077:
            raise ValueError('private_directory_permissions')
        self.path = self.root / 'customers.sqlite3'
        safe(self.path)
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        if self.path.stat().st_mode & 0o077:
            raise ValueError('private_database_permissions')
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
              INSERT OR IGNORE INTO meta VALUES('revision','0');
              CREATE TABLE IF NOT EXISTS identities(lookup TEXT PRIMARY KEY,customer_id TEXT NOT NULL,email TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS orders(order_key TEXT PRIMARY KEY,site TEXT NOT NULL,gid TEXT NOT NULL,
                customer_id TEXT,paid_at TEXT NOT NULL,valid INTEGER NOT NULL,body TEXT NOT NULL,revision INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS purchase_time ON orders(paid_at,valid);
              CREATE INDEX IF NOT EXISTS customer_time ON orders(customer_id,paid_at);
              CREATE TABLE IF NOT EXISTS jobs(job_id TEXT PRIMARY KEY,site TEXT,start TEXT,end TEXT,
                state TEXT,body TEXT,revision INTEGER);
              CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY,reason TEXT,body TEXT);
              CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,query TEXT,body TEXT,members TEXT);
            ''')
            fingerprint = hmac.new(key, b'fs-user-identity-v1', 'sha256').hexdigest()
            mapping = digest({k: config[k] for k in ('sites', 'identity_version', 'scope_version', 'projects')})
            for name, value in (('key_fingerprint', fingerprint), ('mapping_fingerprint', mapping)):
                old = db.execute('SELECT value FROM meta WHERE key=?', (name,)).fetchone()
                if old and old[0] != value:
                    raise ValueError('identity_or_mapping_migration_required')
                db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', (name, value))

    @contextmanager
    def db(self):
        safe(self.path)
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def identity(self, db, site, email):
        email = str(email or '').strip()
        if not email or len(email) > 320 or '@' not in email:
            return None
        # Cross-site grouping requires an explicitly verified shared identity group.
        group = self.config['sites'][site].get('verified_identity_group') or ('site:' + site)
        lookup = hmac.new(self.key, canonical([group, email]).encode(), 'sha256').hexdigest()
        row = db.execute('SELECT customer_id FROM identities WHERE lookup=?', (lookup,)).fetchone()
        if row:
            return row[0]
        cid = 'c_' + uuid.uuid4().hex
        db.execute('INSERT INTO identities VALUES(?,?,?)', (lookup, cid, email))
        return cid

    def replace_window(self, site, start, end, rows, capture, reason='window_sync'):
        site = str(site)
        if site not in self.config['sites'] or not stamp(start) < stamp(end):
            raise ValueError('window_scope')
        start, end, capture = stamp(start).isoformat(), stamp(end).isoformat(), stamp(capture).isoformat()
        normalized, keys = [], set()
        for raw in rows:
            if str(raw.get('site_id')) != site:
                raise ValueError('order_site_mismatch')
            paid = stamp(raw.get('paytime')).isoformat()
            if not start <= paid < end:
                raise ValueError('order_time_mismatch')
            number, gid = str(raw.get('order_no') or ''), str(raw.get('gid') or '')
            if not number or len(number) > 160 or not gid.isdigit():
                raise ValueError('order_identity_invalid')
            key = 'admin:' + site + ':' + number
            if key in keys:
                # Duplicate source order rows need a verified line-item contract before ingestion.
                raise ValueError('duplicate_order')
            keys.add(key)
            if str(raw.get('pay_status')) not in ('0', '1', '2'):
                raise ValueError('unmapped_payment_status')
            valid = str(raw['pay_status']) == '1'
            if str(raw.get('status')) in self.config.get('excluded_order_statuses', []):
                valid = False
            if number in self.config.get('verified_test_orders', []):
                valid = False
            # Do not retain arbitrary source fields in this purpose-specific private projection.
            body = {k: raw.get(k) for k in ('id', 'order_no', 'email', 'uid', 'pay_status', 'status')}
            normalized.append((key, gid, paid, valid, body))
        job = 'j_' + digest([site, start, end])[:24]
        with self.db() as db:
            rev = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            previous = {r['order_key']: dict(r) for r in db.execute(
                'SELECT * FROM orders WHERE site=? AND paid_at>=? AND paid_at<?', (site, start, end))}
            changes = []
            for key, gid, paid, valid, body in normalized:
                cid = self.identity(db, site, body['email'])
                encoded = canonical(body)
                old = db.execute('SELECT * FROM orders WHERE order_key=?', (key,)).fetchone()
                values = (site, gid, cid, paid, int(valid), encoded)
                if old and tuple(old[k] for k in ('site', 'gid', 'customer_id', 'paid_at', 'valid', 'body')) == values:
                    continue
                if old:
                    changes.append(dict(old))
                db.execute('INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?)', (key, *values, rev + 1))
            for key, old in previous.items():
                if key not in keys and old['valid']:
                    changes.append(old)
                    db.execute('UPDATE orders SET valid=0,revision=? WHERE order_key=?', (rev + 1, key))
            # Coverage itself is versioned even when membership is unchanged.
            payload = dict(captured_at=capture, source_rows=len(rows), identified_rows=sum(bool(r[4].get('email')) for r in normalized),
                           status_counts={s: sum(str(r[4]['pay_status']) == s for r in normalized) for s in ('0', '1', '2')},
                           correction_coverage='complete_reenumeration_of_payment_window_only')
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?)', (job, site, start, end, 'complete', canonical(payload), rev + 1))
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (rev + 1, reason, canonical(changes)))
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(rev + 1),))
        return dict(job_id=job, state='complete', data_version=str(rev + 1), **payload)

    def failed_window(self, site, start, end, error):
        # Failed attempts never erase a previously complete coverage record.
        job = 'j_' + digest([str(site), stamp(start).isoformat(), stamp(end).isoformat()])[:24]
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?)',
                       (job, str(site), stamp(start).isoformat(), stamp(end).isoformat(), 'failed', canonical({'error': error}), None))
        return job

    def read(self):
        with self.db() as db:
            db.execute('BEGIN')
            revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            orders = [dict(r) for r in db.execute('SELECT * FROM orders ORDER BY paid_at,order_key')]
            jobs = [dict(r) for r in db.execute('SELECT * FROM jobs')]
        return revision, orders, jobs

    def save_snapshot(self, query, public, members):
        ident = 'us_' + digest({'query': query, 'data': public})[:32]
        evidence = 'ua_' + ident[3:]
        public = dict(public, snapshot_id=ident, evidence_id=evidence)
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)',
                       (ident, canonical(query), canonical(public), canonical(members)))
            row = db.execute('SELECT query,body,members FROM snapshots WHERE id=?', (ident,)).fetchone()
            if tuple(row) != (canonical(query), canonical(public), canonical(members)):
                raise ValueError('snapshot_integrity')
        return public

    def snapshot(self, ident):
        if not isinstance(ident, str) or len(ident) != 35 or not ident.startswith('us_') or any(c not in '0123456789abcdef' for c in ident[3:]):
            raise LookupError('snapshot_missing')
        with self.db() as db:
            row = db.execute('SELECT * FROM snapshots WHERE id=?', (ident,)).fetchone()
        if not row:
            raise LookupError('snapshot_missing')
        public, query = json.loads(row['body']), json.loads(row['query'])
        core = {k: v for k, v in public.items() if k not in ('snapshot_id', 'evidence_id')}
        if ident != 'us_' + digest({'query': query, 'data': core})[:32]:
            raise ValueError('snapshot_integrity')
        return query, public, json.loads(row['members'])
