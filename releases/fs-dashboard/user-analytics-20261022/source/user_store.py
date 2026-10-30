"""Private durable purchase facts and frozen snapshots, independent of short-lived caches."""
import hmac
import hashlib
import json
import os
import re
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from pathlib import Path

from user_contract import canonical, digest, stamp, money


def safe(path):
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('private_store_symlink')


def _public_targeted_attempt(value):
    status = value['status']
    if status not in ('complete', 'partial', 'failed', 'deferred'):
        raise ValueError('targeted_refresh_status')
    public = dict(status=status, at=stamp(value['at']).isoformat())
    counts = ('requested_rows', 'returned_rows', 'missing_rows', 'changed_rows')
    for key in counts:
        if key in value:
            number = value[key]
            if type(number) is not int or not 0 <= number <= 400:
                raise ValueError('targeted_refresh_counts')
            public[key] = number
    if status in ('complete', 'partial'):
        if (any(key not in public for key in counts)
                or public['requested_rows'] != public['returned_rows'] + public['missing_rows']
                or public['changed_rows'] > public['returned_rows']
                or (status == 'complete') != (public['missing_rows'] == 0)):
            raise ValueError('targeted_refresh_counts')
    if 'error' in value:
        error = value['error']
        public['error'] = error if isinstance(error, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', error) else 'source_error'
    if 'retryable' in value:
        if type(value['retryable']) is not bool:
            raise ValueError('targeted_refresh_retryable')
        public['retryable'] = value['retryable']
    return public


def _validate_targeted_cursors(value, sites):
    if not isinstance(value, dict) or set(value) - set(sites):
        raise ValueError('targeted_refresh_cursors')
    for cursors in value.values():
        if (not isinstance(cursors, dict) or set(cursors) - {'fast', 'watch'}
                or any(type(cursor) is not int or not 0 <= cursor < 2**63 for cursor in cursors.values())):
            raise ValueError('targeted_refresh_cursors')


class Store:
    def __init__(self, root, key, config, read_only=False):
        self.root, self.key, self.config = Path(root), key, config
        self.read_only = read_only
        if not isinstance(key, bytes) or len(key) < 32:
            raise ValueError('identity_key_required')
        safe(self.root)
        if read_only and not self.root.is_dir():
            raise ValueError('existing_restore_directory_required')
        if not read_only:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.stat().st_mode & 0o077:
            raise ValueError('private_directory_permissions')
        self.path = self.root / 'customers.sqlite3'
        safe(self.path)
        if not self.path.exists():
            if read_only:
                raise ValueError('existing_restore_database_required')
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        if self.path.stat().st_mode & 0o077:
            raise ValueError('private_database_permissions')
        with self.db() as db:
            if not read_only:
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
              CREATE TABLE IF NOT EXISTS job_attempts(id INTEGER PRIMARY KEY,job_id TEXT NOT NULL,state TEXT NOT NULL,body TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS revisions(id INTEGER PRIMARY KEY,reason TEXT,body TEXT);
              CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,query TEXT,body TEXT,members TEXT);
              CREATE TABLE IF NOT EXISTS snapshot_members(id TEXT PRIMARY KEY,body TEXT NOT NULL);
                ''')
            fingerprint = hmac.new(key, b'fs-user-identity-v1', 'sha256').hexdigest()
            mapping = digest({k: config[k] for k in ('sites', 'identity_version', 'scope_version', 'projects')})
            for name, value in (('key_fingerprint', fingerprint), ('mapping_fingerprint', mapping)):
                old = db.execute('SELECT value FROM meta WHERE key=?', (name,)).fetchone()
                if old and old[0] != value:
                    raise ValueError('identity_or_mapping_migration_required')
                if read_only and not old:
                    raise ValueError('restore_identity_metadata_missing')
                if not read_only:
                    db.execute('INSERT OR IGNORE INTO meta VALUES(?,?)', (name, value))

    @contextmanager
    def db(self):
        safe(self.path)
        db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=15) if self.read_only else sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        if self.read_only:
            db.execute('PRAGMA query_only=ON')
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

    def _normalize_orders(self, site, rows, period=None):
        """The same purpose-specific projection, with no database or identity writes."""
        normalized, keys = [], set()
        for raw in rows:
            if str(raw.get('site_id')) != site:
                raise ValueError('order_site_mismatch')
            paid = stamp(raw.get('paytime')).isoformat()
            if period is not None and not period[0] <= paid < period[1]:
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
            if str(raw.get('status')) not in self.config['known_order_statuses']:
                raise ValueError('unmapped_order_status')
            valid = str(raw['pay_status']) == '1'
            if str(raw.get('status')) in self.config.get('excluded_order_statuses', []):
                valid = False
            test = self.config.get('verified_test_rules', {}).get(number)
            if test:
                if str(test['gid']) != gid or money(test['salesUsd']) != money(raw.get('amount_usd_format')):
                    raise ValueError('test_order_identity_mismatch')
                valid = False
            # Do not retain arbitrary source fields in this purpose-specific private projection.
            body = {k: raw.get(k) for k in ('id', 'order_no', 'email', 'uid', 'pay_status', 'status', 'status_format', 'currency_code', 'payback')}
            body.update(amount_usd=money(raw.get('amount_usd_format')), amount_rmb=money(raw.get('amount_rmb_format')),
                        source_refund_amount=money(raw.get('return_money')), test_order=bool(test))
            normalized.append((key, gid, paid, valid, body))
        return normalized, keys

    def replace_window(self, site, start, end, rows, capture, reason='window_sync'):
        site = str(site)
        if site not in self.config['sites'] or not stamp(start) < stamp(end):
            raise ValueError('window_scope')
        start, end, capture = stamp(start).isoformat(), stamp(end).isoformat(), stamp(capture).isoformat()
        normalized, keys = self._normalize_orders(site, rows, (start, end))
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
            payload = dict(captured_at=capture, source_rows=len(rows), identified_rows=sum(bool(self.identity(db, site, r[4].get('email'))) for r in normalized),
                           source_status_rule_sha256=self.config.get('source_status_rule_sha256'),
                           effective_rows=sum(r[3] for r in normalized), excluded_test_rows=sum(bool(r[4]['test_order']) for r in normalized),
                           status_counts={s: sum(str(r[4]['pay_status']) == s for r in normalized) for s in ('0', '1', '2')},
                           correction_coverage='complete_reenumeration_of_payment_window_only')
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?,?,?)', (job, site, start, end, 'complete', canonical(payload), rev + 1))
            db.execute('INSERT INTO job_attempts(job_id,state,body) VALUES(?,?,?)', (job, 'complete', canonical(dict(site=site, start=start, end_exclusive=end, captured_at=capture))))
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (rev + 1, reason, canonical(changes)))
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(rev + 1),))
        return dict(job_id=job, state='complete', data_version=str(rev + 1), **payload)

    def correct_orders(self, site, requested, rows, capture):
        """Correct selected existing orders; absent IDs never erase other facts.

        This is not payment-window enumeration and cannot establish coverage.
        Customer reassignment requires a separate verified migration contract.
        """
        site = str(site)
        if (site not in self.config['sites'] or not isinstance(requested, dict) or not 1 <= len(requested) <= 400
                or any(not isinstance(ident, str) or not ident.isascii() or not ident.isdigit()
                       or len(ident) > 32 or int(ident) <= 0 or str(int(ident)) != ident
                       or not isinstance(key, str) or not key.startswith('admin:' + site + ':')
                       or not 0 < len(key) - len('admin:' + site + ':') <= 160
                       for ident, key in requested.items())
                or len(set(requested.values())) != len(requested)):
            raise ValueError('targeted_scope')
        if not isinstance(rows, list) or len(rows) > len(requested):
            raise ValueError('targeted_rows')
        capture_at = stamp(capture)
        capture = capture_at.isoformat()
        normalized, _ = self._normalize_orders(site, rows)
        returned = {}
        for row in normalized:
            if stamp(row[2]) > capture_at:
                raise ValueError('targeted_order_time_after_capture')
            ident = str(row[4].get('id') or '')
            if ident not in requested or requested[ident] != row[0]:
                raise ValueError('targeted_order_identity_mismatch')
            if ident in returned:
                raise ValueError('targeted_duplicate_source_id')
            returned[ident] = row
        job = 't_' + digest([site, sorted(requested.items())])[:24]
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rev = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            previous = {}
            for ident, key in requested.items():
                old = db.execute('SELECT * FROM orders WHERE order_key=?', (key,)).fetchone()
                if old is None or old['site'] != site or str(json.loads(old['body']).get('id') or '') != ident:
                    raise ValueError('targeted_existing_order_required')
                previous[ident] = dict(old)
            updates, changes = [], []
            for ident, (key, gid, paid, valid, body) in returned.items():
                old = previous[ident]
                if str(body.get('email') or '').strip() != str(json.loads(old['body']).get('email') or '').strip():
                    raise ValueError('targeted_customer_identity_mismatch')
                values = (site, gid, old['customer_id'], paid, int(valid), canonical(body))
                if tuple(old[k] for k in ('site', 'gid', 'customer_id', 'paid_at', 'valid', 'body')) != values:
                    changes.append(old)
                    updates.append((key, *values, rev + 1))
            if updates:
                db.executemany('INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?)', updates)
                rev += 1
                db.execute('INSERT INTO revisions VALUES(?,?,?)', (rev, 'targeted_order_correction', canonical(changes)))
                db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(rev),))
            missing = len(requested) - len(returned)
            payload = dict(mode='targeted', captured_at=capture, requested_rows=len(requested),
                           returned_rows=len(returned), missing_rows=missing, changed_rows=len(updates),
                           data_version=str(rev), correction_coverage='selected_existing_orders_only',
                           source_status_rule_sha256=self.config.get('source_status_rule_sha256'))
            state = 'partial' if missing else 'complete'
            db.execute('INSERT INTO job_attempts(job_id,state,body) VALUES(?,?,?)', (job, state, canonical(payload)))
        return dict(job_id=job, state=state, **payload)

    def failed_window(self, site, start, end, error):
        # Failed attempts never erase a previously complete coverage record.
        job = 'j_' + digest([str(site), stamp(start).isoformat(), stamp(end).isoformat()])[:24]
        with self.db() as db:
            from datetime import datetime
            from user_contract import TZ
            db.execute('INSERT INTO job_attempts(job_id,state,body) VALUES(?,?,?)',
                       (job, 'failed', canonical(dict(site=str(site), start=start, end_exclusive=end, error=error, at=datetime.now(TZ).isoformat()))))
            db.execute('INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?)',
                       (job, str(site), stamp(start).isoformat(), stamp(end).isoformat(), 'failed', canonical({'error': error}), None))
        return job

    def read(self, analytics=False, start=None, end=None):
        if (start is None) != (end is None) or start is not None and (not analytics or not stamp(start) < stamp(end)):
            raise ValueError('analytics_period_required')
        with self.db() as db:
            db.execute('BEGIN')
            revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            orders = []
            where = ' WHERE valid=1' if analytics else ''
            if start is not None:
                where += ' AND paid_at>=? AND paid_at<?'
            for row in db.execute('SELECT * FROM orders' + where + ' ORDER BY paid_at,order_key', (stamp(start).isoformat(),stamp(end).isoformat()) if start is not None else ()):
                row = dict(row)
                if analytics:
                    row = self.analytics_row_v1(row)
                orders.append(row)
            jobs = [dict(r) for r in db.execute('SELECT * FROM jobs')]
        return revision, orders, jobs

    @staticmethod
    def analytics_row_v1(row):
        """Versioned projection also used by persisted v1 replay inputs."""
        row = dict(row)
        body = json.loads(row['body'])
        row['source_id'] = str(body.get('id') or '')
        row['body'] = canonical({'amount_usd': body.get('amount_usd'), 'order_no_hash': hashlib.sha256(str(body.get('order_no') or '').encode()).hexdigest()})
        return row

    def read_at(self, version, start=None, end=None):
        """One batch replay; validity and payment dates are filtered after revision selection."""
        if not isinstance(version, str) or not version.isdecimal() or str(int(version)) != version or (start is None) != (end is None):
            raise ValueError('snapshot_replay_version')
        target = int(version)
        result = {}
        def include(raw):
            if raw['revision'] <= target:
                old = result.get(raw['order_key'])
                if old is None or raw['revision'] > old['revision']:
                    result[raw['order_key']] = self.analytics_row_v1(raw)
        with self.db() as db:
            db.execute('BEGIN')
            current = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            if target > current:
                raise ValueError('snapshot_replay_future_version')
            for row in db.execute('SELECT * FROM orders WHERE revision<=?', (target,)):
                include(dict(row))
            for row in db.execute('SELECT body FROM revisions WHERE id>? ORDER BY id', (target,)):
                for old in json.loads(row[0]):
                    include(old)
        if start is not None:
            start, end = stamp(start).isoformat(), stamp(end).isoformat()
            if not start < end:
                raise ValueError('analytics_period_required')
        return sorted((r for r in result.values() if r['valid'] and (start is None or start <= r['paid_at'] < end)),
                      key=lambda r: (r['paid_at'], r['order_key']))

    @staticmethod
    def decorate_private_v1(private, orders, query, config, global_allowed):
        """Keep the v1 record fields stable for old recipes."""
        if global_allowed:
            by_customer = {}
            cutoff = stamp(query['as_of'])
            for row in orders:
                cid = row['customer_id']
                if cid and cid in private['records'] and row['site'] in config['sites'] and stamp(row['paid_at']) < cutoff and row['valid']:
                    by_customer.setdefault(cid, []).append(row)
            for cid, record in private['records'].items():
                whole = by_customer.get(cid, [])
                record.update(global_earliest_observed_at=min((r['paid_at'] for r in whole), default=None),
                              global_last_paid_at=max((r['paid_at'] for r in whole), default=None))
        private['scope_projects'] = config['projects']
        return private

    def replay_snapshot_v1(self, query, public, recipe):
        """The v1 algorithm and record layout remain readable when future versions are added."""
        if (set(recipe) != {'contract', 'query', 'data_version', 'config', 'jobs', 'global_allowed', 'private_sha256'}
                or recipe['query'] != query or recipe['data_version'] != public['data_version']
                or recipe['config']['scope_version'] != public['scope_version']
                or recipe['config']['identity_version'] != public['identity_version']
                or type(recipe['global_allowed']) is not bool or recipe['global_allowed'] != public.get('requires_global_scope', False)):
            raise ValueError('snapshot_replay_contract')
        from user_replay_v1 import analyze
        cohort = query.get('state_basis') == 'period_cohort'
        rows = self.read_at(recipe['data_version'], **dict(start=query['start'], end=query['end_exclusive']) if cohort else {})
        _, private = analyze(rows, recipe['jobs'], query, recipe['config'])
        self.decorate_private_v1(private, rows, query, recipe['config'], recipe['global_allowed'])
        private.pop('events', None)
        if digest(private) != recipe['private_sha256']:
            raise ValueError('snapshot_replay_integrity')
        return private

    def revision(self):
        with self.db() as db:
            return db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]

    def coverage(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM jobs')]

    def job_health(self):
        with self.db() as db:
            latest = db.execute('SELECT job_id,state,body FROM job_attempts ORDER BY id DESC LIMIT 1').fetchone()
            failures = db.execute("SELECT count(*) FROM job_attempts WHERE state='failed'").fetchone()[0]
        result = dict(failed_attempts=failures, latest_attempt=dict(latest) if latest else None)
        path = self.root / 'targeted-refresh.json'
        if path.exists() or path.is_symlink():
            try:
                safe(path)
                fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
                with os.fdopen(fd, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                            or info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 65536):
                        raise ValueError('targeted_refresh_permissions')
                    raw = source.read(65537)
                if len(raw) > 65536:
                    raise ValueError('targeted_refresh_size')
                value = json.loads(raw)
                if not isinstance(value, dict) or value.get('contract') != 'fs-users-targeted-refresh-v1':
                    raise ValueError('targeted_refresh_contract')
                if 'cursors' in value:
                    _validate_targeted_cursors(value['cursors'], self.config['sites'])
                if 'latest_attempts' in value:
                    attempts = value['latest_attempts']
                    if not isinstance(attempts, dict) or set(attempts) - set(self.config['sites']):
                        raise ValueError('targeted_refresh_sites')
                    sites = {site: _public_targeted_attempt(attempts[site]) if site in attempts else dict(status='deferred')
                             for site in self.config['sites']}
                    ranks = dict(complete=0, deferred=1, partial=2, failed=3)
                    public = dict(status=max((attempt['status'] for attempt in sites.values()), key=ranks.get), sites=sites)
                else:
                    public = _public_targeted_attempt(value['latest_attempt'])
                result['targeted_reconciliation'] = public
            except (OSError, ValueError, KeyError, TypeError):
                result['targeted_reconciliation'] = dict(status='failed', error='targeted_refresh_metadata_invalid')
        return result

    def remap_projects(self, config):
        if any(config[k] != self.config[k] for k in ('sites', 'identity_version')) or config['scope_version'] == self.config['scope_version']:
            raise ValueError('explicit_identity_migration_required')
        fields = ('sites', 'identity_version', 'scope_version', 'projects')
        before = digest({k: self.config[k] for k in fields})
        after = digest({k: config[k] for k in fields})
        with self.db() as db:
            if db.execute("SELECT value FROM meta WHERE key='mapping_fingerprint'").fetchone()[0] != before:
                raise ValueError('mapping_revision_conflict')
            rev = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]) + 1
            db.execute("UPDATE meta SET value=? WHERE key='mapping_fingerprint'", (after,))
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (rev, 'verified_project_mapping_revision', '[]'))
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(rev),))
        self.config = config
        return dict(data_version=str(rev), before=before, after=after, identities_preserved=True)

    def orders_at(self, version, customer_id):
        version = int(version)
        with self.db() as db:
            candidates = [dict(r) for r in db.execute('SELECT * FROM orders WHERE customer_id=? AND revision<=?', (customer_id, version))]
            for row in db.execute('SELECT body FROM revisions WHERE id>?', (version,)):
                candidates.extend(r for r in json.loads(row[0]) if r['customer_id'] == customer_id and r['revision'] <= version)
        result = {}
        for row in candidates:
            if row['order_key'] not in result or row['revision'] > result[row['order_key']]['revision']:
                result[row['order_key']] = row
        return sorted(result.values(), key=lambda r: (r['paid_at'], r['order_key']))

    def email(self, customer_id):
        with self.db() as db:
            row = db.execute('SELECT email FROM identities WHERE customer_id=? LIMIT 1', (customer_id,)).fetchone()
        if not row:
            raise LookupError('customer_missing')
        return row[0]

    def find_email(self, email, sites):
        # Reuse the identity key without creating an identity for a search miss.
        lookups = [hmac.new(self.key, canonical([self.config['sites'][site].get('verified_identity_group') or ('site:' + site), email]).encode(), 'sha256').hexdigest() for site in sites]
        with self.db() as db:
            return {row[0] for lookup in lookups for row in db.execute('SELECT customer_id FROM identities WHERE lookup=?', (lookup,))}

    def backup(self, destination):
        destination = Path(destination)
        safe(destination)
        if destination.exists():
            raise FileExistsError('backup_already_exists')
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.db() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('backup_integrity')
                revision = target.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
            finally:
                target.close()
        return dict(path=destination.name, revision=revision)

    def save_snapshot(self, query, public, members):
        ident = 'us_' + digest({'query': query, 'data': public})[:32]
        evidence = 'ua_' + ident[3:]
        public = dict(public, snapshot_id=ident, evidence_id=evidence)
        member_id = digest(members)
        reference = canonical(dict(member_ref=member_id, **({'member_kind':'recipe-v1'} if members.get('contract') == 'fs-users-private-replay-v1' else {})))
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT query,body,members FROM snapshots WHERE id=?', (ident,)).fetchone()
            if old is not None and tuple(old[:2]) == (canonical(query), canonical(public)) and old[2] not in (reference, canonical(members)):
                previous = self._snapshot_members(db, old[2])
                incoming_recipe = members.get('contract') == 'fs-users-private-replay-v1'
                previous_recipe = previous.get('contract') == 'fs-users-private-replay-v1'
                if incoming_recipe or previous_recipe:
                    before = previous['private_sha256'] if previous_recipe else digest({k: v for k, v in previous.items() if k != 'events'})
                    after = members['private_sha256'] if incoming_recipe else digest({k: v for k, v in members.items() if k != 'events'})
                    if before == after:
                        return public  # Same immutable public ID keeps its original reference during rollout/rollback.
                raise ValueError('snapshot_integrity')
            db.execute('INSERT OR IGNORE INTO snapshot_members VALUES(?,?)', (member_id, canonical(members)))
            db.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)',
                       (ident, canonical(query), canonical(public), reference))
            row = db.execute('SELECT query,body,members FROM snapshots WHERE id=?', (ident,)).fetchone()
            if tuple(row[:2]) != (canonical(query), canonical(public)) or row[2] not in (reference, canonical(members)):
                raise ValueError('snapshot_integrity')
        return public

    @staticmethod
    def _snapshot_members(db, encoded):
        members = json.loads(encoded)
        if set(members) == {'member_ref'} or set(members) == {'member_ref','member_kind'} and members['member_kind'] == 'recipe-v1':
            record = db.execute('SELECT body FROM snapshot_members WHERE id=?', (members['member_ref'],)).fetchone()
            if not record:
                raise ValueError('snapshot_members_integrity')
            value = json.loads(record[0])
            if digest(value) != members['member_ref']:
                raise ValueError('snapshot_members_integrity')
            return value
        return members

    def snapshot_token(self, ident):
        """Validate the small recipe before a private-cache hit; legacy lists are not cached."""
        with self.db() as db:
            row = db.execute('SELECT CASE WHEN length(CAST(members AS BLOB))<=256 THEN members ELSE NULL END FROM snapshots WHERE id=?', (ident,)).fetchone()
            if not row:
                raise LookupError('snapshot_missing')
            if row[0] is None:
                return None  # Never decode a large legacy inline list just to decide cacheability.
            reference = json.loads(row[0])
            if reference.get('member_kind') != 'recipe-v1':
                return None
            recipe = self._snapshot_members(db, row[0])
            if recipe.get('contract') != 'fs-users-private-replay-v1':
                raise ValueError('snapshot_replay_contract')
            return digest(reference)

    def snapshot_public(self, ident):
        if not isinstance(ident, str) or len(ident) != 35 or not ident.startswith('us_') or any(c not in '0123456789abcdef' for c in ident[3:]):
            raise LookupError('snapshot_missing')
        with self.db() as db:
            row = db.execute('SELECT query,body FROM snapshots WHERE id=?', (ident,)).fetchone()
        if not row:
            raise LookupError('snapshot_missing')
        public, query = json.loads(row['body']), json.loads(row['query'])
        core = {k: v for k, v in public.items() if k not in ('snapshot_id', 'evidence_id')}
        if ident != 'us_' + digest({'query': query, 'data': core})[:32]:
            raise ValueError('snapshot_integrity')
        return query, public

    def snapshot(self, ident):
        query, public = self.snapshot_public(ident)
        with self.db() as db:
            row = db.execute('SELECT members FROM snapshots WHERE id=?', (ident,)).fetchone()
        if not row:
            raise LookupError('snapshot_missing')
        with self.db() as db:
            members = self._snapshot_members(db, row['members'])
        if members.get('contract') == 'fs-users-private-replay-v1':
            members = self.replay_snapshot_v1(query, public, members)
        return query, public, members
