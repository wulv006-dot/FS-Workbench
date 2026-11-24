"""SQLite state machine for maintenance coupon entries and reservations."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3

from maintenance_review import REVIEW_ACTOR, canonical, digest


SHANGHAI = timezone(timedelta(hours=8))
AWAITING = ('confirmed', 'auto_confirmed', 'deferred')
REVOCABLE = ('reviewing', 'ready') + AWAITING
RESERVED = ('dispatching', 'issued', 'pending_register', 'unknown')
IN_FLIGHT = ('dispatching', 'pending_register', 'unknown')
ALLOWED = {
    'reviewing': {'ready', 'held', 'void'},
    'ready': {'confirmed', 'removed', 'expired', 'auto_confirmed', 'void'},
    **{state: {'dispatching', 'deferred', 'recheck_failed', 'void'} for state in AWAITING},
    'dispatching': {'dispatching', 'issued', 'pending_register', 'limited', 'rejected', 'unknown'},
    'pending_register': {'issued', 'limited', 'rejected', 'manually_closed'},
    'unknown': {'issued', 'limited', 'rejected', 'manually_closed'},
}
for terminal in ('held', 'removed', 'expired', 'void', 'recheck_failed', 'issued',
                 'limited', 'rejected', 'manually_closed'):
    ALLOWED[terminal] = frozenset()
ALLOWED = {state: frozenset(targets) for state, targets in ALLOWED.items()}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS maintenance_rules (
    id TEXT PRIMARY KEY, version INTEGER NOT NULL, body TEXT NOT NULL, enabled_at TEXT
);
CREATE TABLE IF NOT EXISTS maintenance_auto_history (
    revision INTEGER PRIMARY KEY, rule_id TEXT NOT NULL, at TEXT NOT NULL,
    actor TEXT NOT NULL, enabled INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS maintenance_auto_asof ON maintenance_auto_history(rule_id,at,revision);
CREATE TABLE IF NOT EXISTS maintenance_entries (
    id TEXT PRIMARY KEY, event_id TEXT NOT NULL, customer_id TEXT NOT NULL, email TEXT NOT NULL,
    rule_id TEXT NOT NULL, rule_version INTEGER NOT NULL, rule_body TEXT NOT NULL, state TEXT NOT NULL,
    created_at TEXT NOT NULL, ready_at TEXT, deferred_day TEXT, dispatch_at TEXT, dispatch_day TEXT,
    batch TEXT UNIQUE, job_id TEXT, result TEXT, UNIQUE(customer_id,rule_id,event_id)
);
CREATE INDEX IF NOT EXISTS maintenance_customer_quota ON maintenance_entries(customer_id,dispatch_at,state);
CREATE INDEX IF NOT EXISTS maintenance_rule_quota ON maintenance_entries(rule_id,dispatch_day,state);
CREATE INDEX IF NOT EXISTS maintenance_entry_state ON maintenance_entries(state,created_at);
CREATE TABLE IF NOT EXISTS maintenance_reconcile_checks (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_reviews (
    entry_id TEXT NOT NULL, digest TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, result TEXT NOT NULL,
    PRIMARY KEY(entry_id,digest)
);
CREATE TABLE IF NOT EXISTS maintenance_transitions (
    entry_id TEXT NOT NULL, prior TEXT NOT NULL, next TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL,
    details TEXT NOT NULL
);
'''


def stamp(at):
    if at.utcoffset() is None:
        raise ValueError('maintenance_timezone_required')
    return at.astimezone(timezone.utc).isoformat(timespec='microseconds')


def marks(values):
    return ','.join('?' for _ in values)


def batch_for(customer, rule, event):
    return 'FCSM_' + digest([customer, rule, event])[:32].upper()


def entry_view(row):
    result = dict(row)
    for name in ('rule_body', 'result'):
        result[name] = json.loads(result[name]) if result[name] else None
    return result


def rule_view(row):
    if row is None:
        return None
    return dict(id=row['id'], version=row['version'], enabled_at=row['enabled_at'], **json.loads(row['body']))


def fetch_entry(db, ident):
    row = db.execute('SELECT * FROM maintenance_entries WHERE id=?', (ident,)).fetchone()
    return entry_view(row) if row else None


def fetch_rule(db, rule_id):
    return rule_view(db.execute('SELECT * FROM maintenance_rules WHERE id=?', (rule_id,)).fetchone())


def transition(db, row, state, actor, at, details=None, **fields):
    prior, ident = row['state'], row['id']
    if state not in ALLOWED[prior]:
        return False
    fields.update(state=state, result=canonical(details or {}))
    updated = db.execute(
        'UPDATE maintenance_entries SET ' + ','.join(name + '=?' for name in fields)
        + ' WHERE id=? AND state=?', (*fields.values(), ident, prior)).rowcount
    if updated:
        db.execute('INSERT INTO maintenance_transitions VALUES(?,?,?,?,?,?)',
                   (ident, prior, state, actor, stamp(at), fields['result']))
    return bool(updated)


def enqueue_entry(db, event, customer, email, rule, at):
    ident = 'm_' + digest([customer, rule['id'], event])
    db.execute('''INSERT INTO maintenance_entries
                  (id,event_id,customer_id,email,rule_id,rule_version,rule_body,state,created_at)
                  VALUES(?,?,?,?,?,?,?,'reviewing',?) ON CONFLICT(customer_id,rule_id,event_id) DO NOTHING''',
               (ident, event, customer, email, rule['id'], rule['version'], canonical(rule), stamp(at)))
    return ident


def active_customer(db, customer, at):
    occupied = db.execute(
        f'SELECT id,batch,dispatch_at FROM maintenance_entries WHERE customer_id=? AND state IN ({marks(RESERVED)}) '
        'AND dispatch_at>? ORDER BY dispatch_at,id',
        (customer, *RESERVED, stamp(at - timedelta(days=30))))
    return [dict(row) for row in occupied]


class Ledger:
    def __init__(self, connection):
        self.connection = connection
        with self.db() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def db(self, write=False):
        with self.connection() as db:
            db.row_factory = sqlite3.Row
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db

    def save_rule(self, ident, expected_version, body, actor, at):
        with self.db(write=True) as db:
            previous = fetch_rule(db, ident)
            version = previous['version'] if previous else 0
            if version != expected_version:
                raise ValueError('maintenance_rule_version_conflict')
            enabled_at = previous['enabled_at'] if previous and previous['enabled'] else None
            if body['enabled'] and not enabled_at:
                enabled_at = stamp(at)
            db.execute('INSERT INTO maintenance_rules VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                       'version=excluded.version, body=excluded.body, enabled_at=excluded.enabled_at',
                       (ident, version + 1, canonical(body), enabled_at))
            if not previous:
                db.execute('INSERT INTO maintenance_auto_history(rule_id,at,actor,enabled) VALUES(?,?,?,0)',
                           (ident, stamp(at), actor))
            if not body['enabled']:
                self.void(db, at, actor, rule_id=ident)
            return fetch_rule(db, ident)

    def set_auto(self, ident, enabled, actor, at):
        with self.db(write=True) as db:
            at = at() if callable(at) else at
            latest = db.execute('SELECT * FROM maintenance_auto_history WHERE rule_id=? '
                                'ORDER BY at DESC,revision DESC LIMIT 1', (ident,)).fetchone()
            if latest is None:
                raise LookupError('maintenance_rule_missing')
            if latest['at'] > stamp(at):
                raise ValueError('maintenance_auto_clock_regressed')
            if bool(latest['enabled']) == enabled:
                return latest['revision']
            return db.execute('INSERT INTO maintenance_auto_history(rule_id,at,actor,enabled) VALUES(?,?,?,?)',
                              (ident, stamp(at), actor, int(enabled))).lastrowid

    def rules(self):
        with self.db() as db:
            result = []
            for row in db.execute('SELECT * FROM maintenance_rules ORDER BY id'):
                rule = rule_view(row)
                history = db.execute('SELECT * FROM maintenance_auto_history WHERE rule_id=? '
                                     'ORDER BY at DESC,revision DESC LIMIT 1', (rule['id'],)).fetchone()
                rule.update(auto_enabled=bool(history['enabled']), auto_revision=history['revision'])
                result.append(rule)
            return sorted(result, key=lambda rule: (rule['priority'], rule['id']))

    def enqueue(self, event, customer, email, rule_id, at):
        with self.db(write=True) as db:
            rule = fetch_rule(db, rule_id)
            if not rule or not rule['enabled'] or not rule['template']:
                raise ValueError('maintenance_rule_cannot_enqueue')
            return enqueue_entry(db, event, customer, email, rule, at)

    def entry(self, ident):
        with self.db() as db:
            return fetch_entry(db, ident)

    def reviews(self, ident):
        with self.db() as db:
            return [json.loads(row['result']) for row in db.execute(
                'SELECT result FROM maintenance_reviews WHERE entry_id=? ORDER BY at', (ident,))]

    def commit_review(self, ident, result, checked_digest, at):
        state = {'pass': 'ready', 'hold': 'held'}[result['decision']]
        with self.db(write=True) as db:
            row = fetch_entry(db, ident)
            if not row or row['state'] != 'reviewing':
                return False
            if callable(checked_digest):
                checked_digest = checked_digest(db, row)
            if result['digest'] != checked_digest:
                return False
            if not db.execute('INSERT INTO maintenance_reviews VALUES(?,?,?,?,?) '
                              'ON CONFLICT(entry_id,digest) DO NOTHING',
                              (ident, result['digest'], REVIEW_ACTOR, stamp(at), canonical(result))).rowcount:
                return False
            return transition(db, row, state, REVIEW_ACTOR, at, result,
                              ready_at=stamp(at) if state == 'ready' else None)

    def decide(self, ident, decision, actor, at):
        if decision not in ('confirmed', 'removed'):
            raise ValueError('maintenance_decision_invalid')
        with self.db(write=True) as db:
            row = fetch_entry(db, ident)
            return bool(row and row['state'] == 'ready' and transition(db, row, decision, actor, at))

    def expire(self, ident, at):
        with self.db(write=True) as db:
            row = fetch_entry(db, ident)
            if not row or row['state'] != 'ready':
                return False
            due = datetime.fromisoformat(row['ready_at']) + timedelta(hours=72)
            if at < due:
                return False
            switch = db.execute('SELECT * FROM maintenance_auto_history WHERE rule_id=? AND at<=? '
                                'ORDER BY at DESC,revision DESC LIMIT 1', (row['rule_id'], stamp(due))).fetchone()
            details = {'due_at': stamp(due)}
            state = 'expired'
            if switch and switch['enabled']:
                state = 'auto_confirmed'
                details.update(action='超时自动发放', revision=switch['revision'],
                               enabled_by=switch['actor'], enabled_at=switch['at'])
            return transition(db, row, state, 'system-maintenance-timeout', at, details)

    def void(self, db, at, actor, **where):
        if set(where) not in ({'rule_id'}, {'event_id'}, set()):
            raise ValueError('maintenance_void_filter')
        filters = ''.join(f' AND {field}=?' for field in where)
        rows = db.execute(f'SELECT * FROM maintenance_entries WHERE state IN ({marks(REVOCABLE)})' + filters,
                          (*REVOCABLE, *where.values())).fetchall()
        for row in rows:
            transition(db, row, 'void', actor, at, where)
        return len(rows)

    def stop_dispatch(self, at):
        actor = 'system-maintenance-rollback'
        with self.db(write=True) as db:
            for raw in db.execute('SELECT * FROM maintenance_rules').fetchall():
                body = json.loads(raw['body'])
                if body['enabled']:
                    body['enabled'] = False
                    db.execute('UPDATE maintenance_rules SET version=version+1,body=?,enabled_at=NULL WHERE id=?',
                               (canonical(body), raw['id']))
                last = db.execute('SELECT at,enabled FROM maintenance_auto_history WHERE rule_id=? '
                                  'ORDER BY at DESC,revision DESC LIMIT 1', (raw['id'],)).fetchone()
                if last and last['enabled']:
                    db.execute('INSERT INTO maintenance_auto_history(rule_id,at,actor,enabled) VALUES(?,?,?,0)',
                               (raw['id'], max(last['at'], stamp(at)), actor))
            self.void(db, at, actor)

    def active_customer(self, customer, at):
        with self.db() as db:
            return active_customer(db, customer, at)

    def claim(self, ident, at, recheck=None, *, validate=None):
        """Recheck local facts under the claim lock and validate at the recorded dispatch time."""
        actor = 'system-maintenance-dispatch'
        with self.db(write=True) as db:
            row = fetch_entry(db, ident)
            if not row or row['state'] not in AWAITING:
                return None
            rule = fetch_rule(db, row['rule_id'])
            reason = None
            if not rule or not rule['enabled'] or rule['version'] != row['rule_version']:
                reason = 'rule_changed'
            elif recheck is not None:
                reason = recheck(db, row)
            at = at() if callable(at) else at
            day = at.astimezone(SHANGHAI).date().isoformat()
            if row['deferred_day'] and row['deferred_day'] >= day:
                return None
            if not reason and validate is not None:
                reason = validate(row, at)
            if reason:
                transition(db, row, 'recheck_failed', actor, at, {'reason': reason})
                return None
            occupied = db.execute(
                f'SELECT count(*) FROM maintenance_entries WHERE rule_id=? AND dispatch_day=? '
                f'AND state IN ({marks(RESERVED)})', (row['rule_id'], day, *RESERVED)).fetchone()[0]
            if occupied >= rule['daily_quota']:
                transition(db, row, 'deferred', actor, at, {'reason': 'daily_quota'}, deferred_day=day)
                return None
            if active_customer(db, row['customer_id'], at):
                transition(db, row, 'recheck_failed', actor, at, {'reason': 'customer_quota'})
                return None
            batch = batch_for(row['customer_id'], row['rule_id'], row['event_id'])
            if transition(db, row, 'dispatching', actor, at, dispatch_at=stamp(at), dispatch_day=day, batch=batch):
                return fetch_entry(db, ident)
        return None

    def result(self, ident, expected, receipt, at, source='system-maintenance-dispatch', *, reconciled=False):
        if expected not in IN_FLIGHT:
            raise ValueError('maintenance_result_state')
        receipt_state = receipt.get('state')
        job = receipt.get('job_id')
        job = job if isinstance(job, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,128}', job) else None
        coupon_id = str(receipt.get('member_coupon_id') or '')
        with self.db(write=True) as db:
            row = fetch_entry(db, ident)
            if not row or row['state'] != expected:
                return False
            if reconciled and row['job_id']:
                db.execute('INSERT OR REPLACE INTO maintenance_reconcile_checks(entry_id) VALUES(?)', (ident,))
            if row['job_id'] and job and row['job_id'] != job:
                return False
            job = row['job_id'] or job
            state = {
                'confirmed': 'issued' if re.fullmatch(r'[1-9][0-9]*', coupon_id) else 'unknown',
                'pending': 'dispatching' if job else 'unknown',
                'pending_register': 'pending_register',
                'limit': 'limited',
                'rejected': 'rejected',
            }.get(receipt_state, 'unknown')
            if expected != 'dispatching' and state in ('dispatching', 'unknown', 'pending_register'):
                return False
            details = {'bridge_state': receipt_state if isinstance(receipt_state, str) else 'unknown'}
            if receipt.get('error_code'):
                details['error_code'] = receipt['error_code']
            if state == 'issued':
                details['member_coupon_id'] = coupon_id
            if state == 'dispatching' and row['job_id'] == job:
                return False
            return transition(db, row, state, source, at, details, job_id=job)

    def manual_result(self, ident, state, actor, at, proof):
        if state not in ('issued', 'rejected', 'manually_closed') or not proof:
            raise ValueError('maintenance_manual_result')
        with self.db(write=True) as db:
            row = fetch_entry(db, ident)
            return bool(row and not row['job_id'] and row['state'] in ('unknown', 'pending_register')
                        and transition(db, row, state, actor, at, {'admin_batch_evidence': proof}))

    def queue(self, states, *, limit=100, offset=0, sql_filter='', params=()):
        with self.db() as db:
            rows = db.execute(f'SELECT * FROM maintenance_entries WHERE state IN ({marks(states)}) '
                              + sql_filter + ' ORDER BY created_at,id LIMIT ? OFFSET ?',
                              (*states, *params, limit, offset))
            return [entry_view(row) for row in rows]

    def dispatch_queue(self, at):
        day = at.astimezone(SHANGHAI).date().isoformat()
        with self.db() as db:
            rows = db.execute(
                f'SELECT * FROM maintenance_entries WHERE state IN ({marks(AWAITING)}) '
                "AND (deferred_day IS NULL OR deferred_day<?) ORDER BY created_at,json_extract(rule_body,'$.priority'),id LIMIT 100",
                (*AWAITING, day))
            return [entry_view(row) for row in rows]

    def manual_queue(self, *, limit=100, offset=0):
        return self.queue(('pending_register', 'unknown'), limit=limit, offset=offset,
                          sql_filter='AND job_id IS NULL')

    def reconcile_queue(self):
        with self.db() as db:
            rows = db.execute(f'SELECT e.* FROM maintenance_entries e '
                              'LEFT JOIN maintenance_reconcile_checks c ON c.entry_id=e.id '
                              f'WHERE e.state IN ({marks(IN_FLIGHT)}) AND e.job_id IS NOT NULL '
                              'ORDER BY c.sequence,e.created_at,e.id LIMIT 100', IN_FLIGHT)
            return [entry_view(row) for row in rows]

    def recover_dispatches(self, at, maximum_age):
        rows = self.queue(('dispatching',), sql_filter='AND job_id IS NULL AND dispatch_at<=?',
                          params=(stamp(at - maximum_age),))
        for row in rows:
            self.result(row['id'], 'dispatching', {}, at, 'system-maintenance-reconcile')