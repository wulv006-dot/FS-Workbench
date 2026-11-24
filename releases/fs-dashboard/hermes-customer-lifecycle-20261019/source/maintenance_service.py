"""Customer-stage refresh, case attachment, and program review."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
import logging
from pathlib import Path
import re
import sqlite3
import subprocess
from threading import Lock

from customer_segments import ConfigCommitUnknown, load_config, thresholds, write_config
from maintenance_dispatch import Bridge, Dispatcher, checked_template
from maintenance_effects import effects
from maintenance_ledger import (AWAITING, Ledger, SHANGHAI, active_customer, enqueue_entry, fetch_rule,
                                marks, record_dispatch_identity, stamp, transition)
from maintenance_review import (CouponIndex, canonical, coupon_time, digest, email_key,
                                manual_evidence, member_id, review_evidence, valid_email)
from maintenance_sources import AdminFacts, UserProjection
from maintenance_stages import FOLLOW_UP, GID, RANK, cohort, day_end, matches_rule, new_event, payment
from vip_maintenance import events_for


LOGGER = logging.getLogger(__name__)
CONFIG_PATH = Path('/var/lib/fs-customer-segments/segments.json')
ACTOR = 'system-maintenance-stage'
ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}')
ACCOUNT = re.compile(r'[A-Za-z0-9_.-]{1,64}')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS maintenance_runs (
    day TEXT PRIMARY KEY, config_version INTEGER NOT NULL, publication TEXT NOT NULL, completed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_customers (
    customer_id TEXT PRIMARY KEY, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_events (
    id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, last_order_key TEXT NOT NULL,
    event_at TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL, alert INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS maintenance_customer_events ON maintenance_events(customer_id,event_at);
CREATE TABLE IF NOT EXISTS maintenance_cases (
    customer_id TEXT PRIMARY KEY, case_id TEXT UNIQUE, status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_overrides (
    customer_id TEXT PRIMARY KEY, tier TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_changes (
    request_id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL,
    before_json TEXT NOT NULL, after_json TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance_outcomes (
    days INTEGER PRIMARY KEY, observed_at TEXT NOT NULL, body TEXT NOT NULL
);
'''


class PendingIdentity(LookupError):
    pass


def strict_id(value):
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise ValueError('maintenance_id')
    return value


def account(value):
    if not isinstance(value, str) or ACCOUNT.fullmatch(value) is None:
        raise ValueError('maintenance_account')
    return value


def keys(body, fields):
    if set(body) != set(fields.split()):
        raise ValueError('maintenance_request_fields')


def matching_cases(db, customer):
    ident, email = customer['customer_id'], email_key(customer['email'])
    exact, conflicts = [], []
    uid_conflict = False
    uid = member_id(customer.get('uid'))
    query = '''SELECT common.id,common.baseline,
                      preferred.baseline AS preferred, known.customer_id AS customer_id
               FROM vip_cases AS common
               LEFT JOIN vip_preferred_cases AS preferred ON preferred.id=common.id
               LEFT JOIN maintenance_cases AS known ON known.case_id=common.id
               WHERE NOT EXISTS(SELECT 1 FROM vip_events AS audit WHERE audit.case_id=common.id
                                AND json_extract(audit.payload,'$.event')='close')'''
    for case in db.execute(query):
        bodies = [json.loads(body) for body in (case['baseline'], case['preferred']) if body]
        identities = [body.get('identity') or {} for body in bodies]
        emails = {email_key(value) for item in identities for value in item.get('emails', ())
                  if isinstance(value, str)}
        uids = {member_id(value) for item in identities for value in item.get('uids', ())}
        if emails == {email} and case['customer_id'] in (None, ident):
            exact.append(case['id'])
        elif email in emails or (uid and uid in uids):
            conflicts.append(case['id'])
            uid_conflict |= bool(email not in emails and uid and uid in uids)
    return sorted(exact), sorted(conflicts), uid_conflict


def create_case(db, customer, at):
    ident, email = customer['customer_id'], customer['email']
    case_id = digest([ident, stamp(at)])[:32]
    body = dict(buyerId=ident, siteId='266',
                identity=dict(emails=[email], uids=[], esBuyerIds=[], customerIds=[ident]))
    db.execute('INSERT INTO vip_cases(id,week,opened_at,baseline) VALUES(?,?,?,?)',
               (case_id, '', stamp(at), canonical(body)))
    return case_id


def store_case_link(db, customer, case_id, status):
    db.execute('INSERT INTO maintenance_cases VALUES(?,?,?) ON CONFLICT(customer_id) DO UPDATE '
               'SET case_id=excluded.case_id,status=excluded.status', (customer, case_id, status))


def case_binding(db, customer, *, entering_stage=False):
    ident = customer['customer_id']
    prior = db.execute("""SELECT c.case_id,c.status,EXISTS(
                           SELECT 1 FROM vip_events e WHERE e.case_id=c.case_id
                           AND json_extract(e.payload,'$.event')='close') AS closed
                           FROM maintenance_cases c WHERE c.customer_id=?""", (ident,)).fetchone()
    if customer.get('email_conflict'):
        return None, 'pending_identity', [], [], 'email_conflict'
    if not valid_email(customer['email']):
        return None, 'pending_identity', [], [], 'invalid_email'
    exact, conflicts, uid_conflict = matching_cases(db, customer)
    reason = 'case_binding_pending'
    if uid_conflict:
        reason = 'uid_case_conflict'
    elif conflicts:
        reason = 'email_case_conflict'
    elif len(exact) > 1:
        reason = 'multiple_open_cases'
    if prior and prior['status'] == 'pending_identity':
        return None, 'pending_identity', exact, conflicts, reason
    ambiguous = bool(conflicts or len(exact) > 1)
    if prior and prior['case_id'] in exact:
        if not ambiguous:
            return prior['case_id'], 'linked', exact, conflicts, None
        resolution = db.execute("SELECT after_json FROM maintenance_changes WHERE action='case_link' "
                                'AND subject=? ORDER BY rowid DESC LIMIT 1', (ident,)).fetchone()
        if resolution:
            selected = json.loads(resolution['after_json'])
            if (selected.get('case_id'), selected.get('candidates')) == (prior['case_id'], [exact, conflicts]):
                return prior['case_id'], 'linked', exact, conflicts, None
    if ambiguous or (prior and not (entering_stage and prior['closed'])):
        return None, 'pending_identity', exact, conflicts, reason
    return None, 'unlinked', exact, conflicts, reason


def case_link(db, customer, at):
    case_id, status, exact, _, _ = case_binding(db, customer, entering_stage=True)
    if status == 'unlinked':
        case_id, status = (exact[0] if exact else create_case(db, customer, at)), 'linked'
        store_case_link(db, customer['customer_id'], case_id, status)
    elif status == 'pending_identity':
        # Keep a prior assignment reserved until it is explicitly resolved.
        db.execute("INSERT INTO maintenance_cases VALUES(?,NULL,'pending_identity') "
                   "ON CONFLICT(customer_id) DO NOTHING", (customer['customer_id'],))
    return case_id, status


def case_feedback(db, customer):
    case_id, status, _, _, reason = case_binding(db, customer)
    if status != 'linked':
        raise PendingIdentity(reason)
    return events_for(db, case_id)


def event_order_valid(facts, event, customer):
    if not event or event['status'] != 'active' or event['customer_id'] != customer:
        return False
    order = facts.by_order.get(event['last_order_key'])
    return bool(order and order['valid'] and order['customer_id'] == customer and str(order['gid']) == GID)


def dispatch_event(db, row):
    return db.execute('SELECT customer_id,last_order_key,status FROM maintenance_events WHERE id=?',
                      (row['event_id'],)).fetchone()


def assign_empty(db, case_id, owner, event, rule, at):
    if not case_id or owner is None:
        return
    updated = db.execute('UPDATE vip_cases SET owner=? WHERE id=? AND owner IS NULL', (owner, case_id)).rowcount
    request_id = 'ma_' + digest([event, rule])[:32]
    db.execute('INSERT INTO maintenance_changes VALUES(?,?,?,?,?,?,?)',
               (request_id, ACTOR, 'rule_assign' if updated else 'rule_assign_skipped', case_id,
                'null', canonical(owner), stamp(at)))


class Maintenance:
    def __init__(self, store, *, source=None, admin=None, bridge=None, config_path=CONFIG_PATH, clock=None):
        self.ledger = Ledger(store.db)
        self.source = source or UserProjection()
        self.admin = admin or AdminFacts()
        self.bridge = bridge or Bridge()
        self.config_path = config_path
        self.clock = clock or (lambda: datetime.now(SHANGHAI))
        self.cache_lock = Lock()
        self._facts_cache = {}
        self._usage = None
        self._review_offset = 0
        self.dispatcher = Dispatcher(self.ledger, self.bridge, self.prepare_recheck, self.clock)
        with self.ledger.db() as db:
            db.executescript(SCHEMA)

    def facts(self, latest=False):
        with self.cache_lock:
            facts = self._facts_cache.get(latest)
            if facts is None or facts.token != self.source.token():
                facts = self.source.read(self.clock(), latest=latest)
                self._facts_cache[latest] = facts
            return facts

    def advance(self, facts, config):
        at = self.clock()
        with self.ledger.db() as db:
            last = db.execute('SELECT max(day) FROM maintenance_runs').fetchone()[0]
        if last and date.fromisoformat(last) > facts.day:
            raise ValueError('maintenance_publication_regressed')
        day = date.fromisoformat(last) + timedelta(days=1) if last else facts.day
        while day <= facts.day:
            if not facts.covered(day_end(day) - timedelta(days=1), day_end(day)):
                break
            self._day(facts, day, config, at)
            day += timedelta(days=1)
        self._void_corrected(facts, at)

    def _void_corrected(self, facts, at):
        with self.ledger.db(write=True) as db:
            active = db.execute("SELECT * FROM maintenance_events WHERE status='active'").fetchall()
            for row in active:
                if event_order_valid(facts, row, row['customer_id']):
                    continue
                last = coupon_time(json.loads(row['body'])['last_paid_at']).astimezone(SHANGHAI).date()
                if not facts.covered(day_end(last)-timedelta(days=1), day_end(last)):
                    continue
                db.execute("UPDATE maintenance_events SET status='void' WHERE id=?", (row['id'],))
                self.ledger.void(db, at, ACTOR, event_id=row['id'])

    def _day(self, facts, day, config, at):
        current = cohort(facts.orders, day, config, facts.covered)
        for cid, customer in current.items():
            customer['email_conflict'] = facts.email_conflict(cid, customer['email'])
        with self.ledger.db(write=True) as db:
            if db.execute('SELECT 1 FROM maintenance_runs WHERE day=?', (day.isoformat(),)).fetchone():
                return
            previous = {row['customer_id']: json.loads(row['body']) for row in db.execute(
                'SELECT * FROM maintenance_customers')}
            rules = [fetch_rule(db, row['id']) for row in db.execute('SELECT id FROM maintenance_rules')]
            rules = sorted((rule for rule in rules if rule['enabled']), key=lambda rule: (rule['priority'], rule['id']))
            db.execute('DELETE FROM maintenance_customers')
            db.executemany('INSERT INTO maintenance_customers VALUES(?,?)',
                           [(cid, canonical(value)) for cid, value in current.items()])
            for cid, customer in sorted(current.items()):
                event = new_event(previous.get(cid), customer)
                if event is None:
                    continue
                selected = [rule for rule in rules if matches_rule(rule, customer)
                            and coupon_time(rule['enabled_at']) <= coupon_time(event['event_at'])]
                inserted = db.execute("INSERT INTO maintenance_events VALUES(?,?,?,?,?,'active',?) "
                                      'ON CONFLICT(id) DO NOTHING',
                                      (event['id'], cid, event['last_order_key'], event['event_at'], canonical(event),
                                       int(any(rule['alert'] for rule in selected)))).rowcount
                if inserted:
                    case_id, _ = case_link(db, customer, at)
                    for rule in selected:
                        assign_empty(db, case_id, rule['owner'], event['id'], rule['id'], at)
                        if rule['template'] and valid_email(customer['email']):
                            enqueue_entry(db, event['id'], cid, customer['email'], rule, at)
            db.execute('INSERT INTO maintenance_runs VALUES(?,?,?,?)',
                       (day.isoformat(), config['version'], facts.publication['publication_id'], stamp(at)))

    def usage(self, facts, at, *, refresh=False):
        if not refresh and self._usage and self._usage[2] == facts.token and at - self._usage[0] < timedelta(minutes=10):
            return self._usage[1]
        try:
            logs = []
            start = at - timedelta(days=30)
            while start < at:
                end = min(start + timedelta(days=7), at)
                logs.extend(self.admin.logs(start, end))
                start = end
            numbers = {str(log['order_no']) for log in logs if log.get('order_no')}
            owners = self.source.coupon_orders(numbers, facts.token)
            index = CouponIndex(owners, logs, facts.uid_customers)
        except (LookupError, OSError, ValueError, TypeError, sqlite3.Error) as error:
            LOGGER.warning('Maintenance coupon usage unavailable: %s', type(error).__name__)
            return None
        self._usage = (at, index, facts.token)
        return index

    def _evidence(self, entry, facts, at, logs):
        with self.ledger.db() as db:
            event = db.execute('SELECT * FROM maintenance_events WHERE id=?', (entry['event_id'],)).fetchone()
        if not event or event['status'] != 'active':
            raise LookupError('maintenance_event_not_available')
        customer = entry['customer_id']
        if facts.email_conflict(customer, entry['email']):
            raise LookupError('maintenance_email_identity_conflict')
        orders = facts.customers.get(customer, [])
        if not orders or not facts.covered(coupon_time(event['event_at']), facts.cutoff):
            raise LookupError('maintenance_order_coverage')
        if logs is None:
            raise LookupError('maintenance_coupon_usage_unavailable')
        used = logs.for_customer(customer)
        # Automatic batches are already covered by the local ledger.
        used['matched'] = [row for row in used['matched'] if not str(
            (row.get('memberCoupon') or {}).get('grant_batch_no') or '').startswith('FCSM_')]
        relevant = [dict(uid=uid, customer_id=cid) for uid in facts.customer_uids.get(customer, ())
                    for cid in facts.uid_customers[uid]]
        coupons = manual_evidence(relevant, customer, at, self.admin.grants, used)
        cutoff = coupon_time(event['event_at'])
        return dict(coupons=coupons, payments=[
            dict(order_key=row['order_key'], paid_at=row['paid_at'])
            for row in orders if row['valid'] and payment(row) >= cutoff],
            exceptions=self.admin.exceptions(orders))

    @staticmethod
    def _review_identity(entry, facts):
        customer = entry['customer_id']
        orders = (row for row in facts.customers.get(customer, ())
                  if row['valid'] and str(row['gid']) == GID)
        last = max(orders, key=lambda row: (payment(row), row['order_key']), default=None)
        if last is None:
            raise LookupError('maintenance_contact_evidence_missing')
        email = last.get('email')
        return dict(customer_id=customer, email=email, uid=last.get('uid'),
                    email_conflict=facts.email_conflict(customer, email))

    @staticmethod
    def _local_evidence(db, entry, at, evidence, current):
        customer = entry['customer_id']
        feedback = case_feedback(db, current)
        contacts = [dict(at=row['at'], actor=row['actor'], contacted_at=row.get('contacted_at'))
                    for row in feedback if row['event'] == 'contacted']
        return review_evidence(**evidence, automatic=active_customer(db, customer, at), contacts=contacts)

    def review(self, entry, facts, at, logs):
        initial = self._evidence(entry, facts, at, logs)
        identity = self._review_identity(entry, facts)
        with self.ledger.db() as db:
            result = self._local_evidence(db, entry, at, initial, identity)
        second_facts = self.facts(latest=True)
        checked_at = self.clock()
        latest_logs = self.usage(second_facts, checked_at, refresh=True)
        latest = self._evidence(entry, second_facts, checked_at, latest_logs)
        latest_identity = self._review_identity(entry, second_facts)

        def recheck(db, row):
            if self.source.token() != second_facts.token:
                return None
            return self._local_evidence(db, row, self.clock(), latest, latest_identity)['digest']
        return self.ledger.commit_review(entry['id'], result, recheck, self.clock())

    def prepare_recheck(self, row, when):
        facts = self.facts(latest=True)
        with self.ledger.db() as db:
            event = dispatch_event(db, row)
        config, version, _ = load_config(self.config_path)
        customer = row['customer_id']
        current = cohort(facts.customers.get(customer, ()), facts.day, config, facts.covered).get(customer)
        rule = row['rule_body']
        reason = None
        evidence = None
        if not event_order_valid(facts, event, customer):
            reason = 'event_invalid'
        elif current is None or current['tier'] != rule['tier']:
            reason = 'tier_changed'
        elif not valid_email(current['email']) or email_key(current['email']) != email_key(row['email']):
            reason = 'recipient_changed'
        elif facts.email_conflict(customer, current['email']):
            raise PendingIdentity('email_conflict')
        elif rule['customer_type'] is not None and current['customer_type'] != rule['customer_type']:
            reason = 'customer_type_changed'
        elif RANK.get(current['stage'], -1) < RANK[rule['stage']]:
            reason = 'stage_changed'
        else:
            evidence = self._evidence(row, facts, when, self.usage(facts, when, refresh=True))

        def locked(db, fresh):
            if self.source.token() != facts.token or load_config(self.config_path)[1] != version:
                raise LookupError('maintenance_recheck_input_changed')
            latest_event = dispatch_event(db, fresh)
            if not event_order_valid(facts, latest_event, fresh['customer_id']):
                return 'event_invalid'
            if latest_event != event:
                raise LookupError('maintenance_recheck_input_changed')
            if reason:
                return reason
            checked_at = self.clock()
            result = self._local_evidence(db, fresh, checked_at, evidence, current)
            record_dispatch_identity(db, fresh['id'], checked_at)
            return result['reasons'][0] if result['reasons'] else None
        return locked

    def update(self):
        at = self.clock()
        for entry in self.ledger.queue(('ready',), sql_filter='AND ready_at<=?', params=(stamp(at - timedelta(days=3)),)):
            self.ledger.expire(entry['id'], at)
        try:
            facts = self.facts()
        except LookupError:
            return
        config, _, _ = load_config(self.config_path)
        self.advance(facts, config)
        reviewing = self.ledger.queue(('reviewing',), limit=25, offset=self._review_offset)
        if not reviewing and self._review_offset:
            self._review_offset = 0
            reviewing = self.ledger.queue(('reviewing',), limit=25)
        if not reviewing:
            return
        latest = self.facts(latest=True)
        logs = self.usage(latest, at)
        unprocessed = 0
        for entry in reviewing:
            try:
                unprocessed += not self.review(entry, latest, at, logs)
            except (LookupError, OSError, ValueError, KeyError, TypeError) as error:
                unprocessed += 1
                if isinstance(error, PendingIdentity):
                    self.ledger.defer_review_identity(entry['id'], self.clock(), str(error))
                LOGGER.warning('Maintenance review %s pending: %s', entry['id'], type(error).__name__)
        self._review_offset += unprocessed

    def dispatch(self):
        for row in self.ledger.dispatch_queue(self.clock()):
            try:
                self.dispatcher.once(row['id'])
            except (LookupError, OSError, ValueError, TypeError, subprocess.SubprocessError) as error:
                identity_reason = str(error) if isinstance(error, PendingIdentity) else None
                self.ledger.defer_dispatch(row['id'], self.clock(), identity_reason)
                LOGGER.warning('Maintenance dispatch %s deferred: %s', row['id'], type(error).__name__)

    def config_view(self):
        config, version, source = load_config(self.config_path)
        return dict(version=version, source=source, stages=thresholds(GID, config),
                    tiers=config['tiers'].get(GID, {'high': 500, 'ultra': 1000}))

    def save_config(self, body):
        keys(body, 'expected_version stages high ultra')
        config, version, _ = load_config(self.config_path)
        if type(body['expected_version']) is not int or body['expected_version'] != version:
            raise ValueError('maintenance_config_version_conflict')
        candidate = dict(config, version=version + 1,
                         stages=dict(config['stages'], **{GID: body['stages']}),
                         tiers=dict(config['tiers'], **{GID: dict(high=body['high'], ultra=body['ultra'])}))
        try:
            write_config(self.config_path, candidate, version)
        except ConfigCommitUnknown:
            readback, current, _ = load_config(self.config_path)
            if current != candidate['version'] or readback != candidate:
                raise
        return self.config_view()

    def save_rule(self, actor, body):
        keys(body, 'id expected_version tier stage customer_type enabled priority daily_quota coupon_id alert owner')
        ident = strict_id(body['id'])
        if (body['tier'] not in ('high', 'ultra') or body['stage'] not in FOLLOW_UP
                or body['customer_type'] not in (None, 'new', 'old')
                or any(type(body[key]) is not bool for key in ('enabled', 'alert'))
                or any(type(body[key]) is not int for key in ('expected_version', 'priority', 'daily_quota'))
                or not 1 <= body['daily_quota'] <= 10000 or not 0 <= body['priority'] <= 10000):
            raise ValueError('maintenance_rule_fields')
        if body['owner'] is not None:
            account(body['owner'])
        coupon = body['coupon_id']
        if coupon is not None and (type(coupon) is not int or coupon < 1):
            raise ValueError('maintenance_coupon_id')
        template = None
        if coupon and body['enabled']:
            template = checked_template(self.bridge.detail(coupon), coupon, self.clock())
        stored = {field: body[field] for field in (
            'tier', 'stage', 'customer_type', 'enabled', 'priority', 'daily_quota', 'alert', 'owner', 'coupon_id')}
        return self.ledger.save_rule(ident, body['expected_version'], dict(stored, template=template), actor, self.clock())

    def group_view(self, offset=0):
        expected = self.clock().astimezone(SHANGHAI).date() - timedelta(days=1)
        with self.ledger.db() as db:
            last = db.execute('SELECT * FROM maintenance_runs ORDER BY day DESC LIMIT 1').fetchone()
            rows = db.execute('''SELECT s.body,c.case_id,c.status,v.owner,o.tier,
                        (SELECT max(alert) FROM maintenance_events e WHERE e.customer_id=s.customer_id AND e.status='active'
                         AND e.last_order_key=json_extract(s.body,'$.last_order_key')) AS alert
                        FROM maintenance_customers s LEFT JOIN maintenance_cases c USING(customer_id)
                        LEFT JOIN vip_cases v ON v.id=c.case_id LEFT JOIN maintenance_overrides o USING(customer_id)
                        ORDER BY s.customer_id''').fetchall()
        items = []
        for row in rows:
            customer = json.loads(row['body'])
            conflict = customer.get('email_conflict')
            items.append(dict(customer, case_id=None if conflict else row['case_id'],
                              case_status='pending_identity' if conflict else row['status'],
                              owner=None if conflict else row['owner'], override_tier=row['tier'],
                              alert=bool(row['alert'])))
        counts = Counter((r['override_tier'] or r['tier'], r['stage'], r['customer_type']) for r in items)
        items = [row for row in items if row['stage'] in FOLLOW_UP]
        return dict(status='ready' if last and last['day'] == expected.isoformat() else 'waiting',
                    waiting_for=expected.isoformat(), last_run=dict(last) if last else None,
                    groups=[dict(tier=t, stage=s, customer_type=c, count=n) for (t, s, c), n in sorted(counts.items())],
                    items=items[offset:offset+20], next_offset=offset+20 if len(items) > offset+20 else None)

    def customer_view(self, ident):
        strict_id(ident)
        with self.ledger.db() as db:
            row = db.execute('SELECT body FROM maintenance_customers WHERE customer_id=?', (ident,)).fetchone()
            if not row:
                raise LookupError('maintenance_customer_missing')
            customer = json.loads(row['body'])
            case_id, status, exact, _, _ = case_binding(db, customer)
            owner = db.execute('SELECT owner FROM vip_cases WHERE id=?', (case_id,)).fetchone() if case_id else None
            link = dict(customer_id=ident, case_id=case_id, status=status, owner=owner['owner'] if owner else None)
            override = db.execute('SELECT tier FROM maintenance_overrides WHERE customer_id=?', (ident,)).fetchone()
            events = db.execute('SELECT id,event_at,status,alert,body FROM maintenance_events '
                                'WHERE customer_id=? ORDER BY event_at DESC LIMIT 100', (ident,))
            timeline = []
            for event in events:
                body = json.loads(event['body'])
                timeline.append(dict(id=event['id'], at=event['event_at'], stage=body['stage'],
                                     config_version=body['config_version'], status=event['status'],
                                     alert=bool(event['alert'])))
            contacts = events_for(db, case_id) if status == 'linked' else []
            return dict(customer=customer, case=link, matching_cases=exact if status == 'pending_identity' else [],
                        display_tier=override['tier'] if override else None, timeline=timeline, contacts=contacts)

    def resolve_case(self, actor, body):
        keys(body, 'customer_id case_id request_id')
        customer_id = strict_id(body['customer_id'])
        request_id = strict_id(body['request_id'])
        value = body['case_id']
        if value is not None:
            strict_id(value)
        with self.ledger.db(write=True) as db:
            prior = db.execute('SELECT * FROM maintenance_changes WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior['actor'] != actor or prior['action'] != 'case_link' or prior['subject'] != customer_id:
                    raise ValueError('maintenance_request_conflict')
                after = json.loads(prior['after_json'])
                if after['selected'] != value:
                    raise ValueError('maintenance_request_conflict')
                return {key: after[key] for key in ('selected', 'case_id')}
            row = db.execute('SELECT body FROM maintenance_customers WHERE customer_id=?', (customer_id,)).fetchone()
            if not row:
                raise ValueError('maintenance_case_already_resolved')
            customer = json.loads(row['body'])
            _, status, exact, conflicts, _ = case_binding(db, customer)
            if status != 'pending_identity':
                raise ValueError('maintenance_case_already_resolved')
            if customer.get('email_conflict'):
                raise ValueError('maintenance_email_identity_conflict')
            if not valid_email(customer['email']):
                raise ValueError('maintenance_case_email_required')
            if (value is None and exact) or (value is not None and value not in exact):
                raise ValueError('maintenance_case_email_mismatch')
            at = self.clock()
            ident = value or create_case(db, customer, at)
            store_case_link(db, customer_id, ident, 'linked')
            after = {'selected': value, 'case_id': ident}
            resolution = dict(after, candidates=[exact if value else [ident], conflicts])
            db.execute('INSERT INTO maintenance_changes VALUES(?,?,?,?,?,?,?)',
                       (request_id, actor, 'case_link', customer_id, 'null', canonical(resolution), stamp(at)))
            return after

    def queue_view(self, view, offset=0):
        state_sets = {
            'review': ('reviewing', 'held'),
            'ready': ('ready',),
            'delivery': AWAITING + ('dispatching', 'issued', 'limited', 'rejected', 'unknown', 'pending_register',
                                    'manually_closed', 'recheck_failed', 'void', 'removed', 'expired'),
        }
        rows = self.ledger.queue(state_sets[view], limit=21, offset=offset)
        items = []
        customer_ids = list({row['customer_id'] for row in rows[:20]})
        conflicts, identities = set(), {}
        if customer_ids:
            with self.ledger.db() as db:
                entry_ids = [row['id'] for row in rows[:20]]
                identities = {row['entry_id']: row for row in db.execute(
                    'SELECT entry_id,identity_checked_at,identity_reason FROM maintenance_dispatch_checks '
                    f'WHERE identity_checked_at IS NOT NULL AND entry_id IN ({marks(entry_ids)})', entry_ids)}
                conflicts = {row[0] for row in db.execute(
                    f"SELECT customer_id FROM maintenance_customers WHERE customer_id IN ({marks(customer_ids)}) "
                    "AND json_extract(body,'$.email_conflict')=1", customer_ids)}
        for row in rows[:20]:
            reviews = self.ledger.reviews(row['id'])
            item = {key: value for key, value in row.items() if key != 'rule_body'}
            item['review'] = reviews[-1] if reviews else None
            identity = identities.get(row['id'])
            review_check = row['result'] or {}
            if row['state'] == 'reviewing' and review_check.get('identity_reason'):
                item.update(identity_status='pending_identity', identity_reason=review_check['identity_reason'],
                            identity_checked_at=review_check['identity_checked_at'])
            elif identity and row['state'] in AWAITING:
                reason = identity['identity_reason']
                item.update(identity_status='pending_identity' if reason else 'verified',
                            identity_reason=reason, identity_checked_at=identity['identity_checked_at'])
            elif row['customer_id'] in conflicts and row['state'] in ('reviewing', 'ready', *AWAITING):
                item.update(identity_status='pending_identity', identity_reason='email_conflict')
            items.append(item)
        return dict(status='ready', items=items, next_offset=offset+20 if len(rows) > 20 else None)

    def decide_entries(self, actor, body):
        keys(body, 'ids decision')
        ids, decision = body['ids'], body['decision']
        if decision not in ('confirmed', 'removed'):
            raise ValueError('maintenance_decision')
        with self.ledger.db(write=True) as db:
            if ids == 'all' and decision == 'confirmed':
                rows = db.execute("SELECT * FROM maintenance_entries WHERE state='ready'").fetchall()
            elif type(ids) is list and 1 <= len(ids) <= 100 and len(set(map(strict_id, ids))) == len(ids):
                rows = db.execute(f"SELECT * FROM maintenance_entries WHERE state='ready' AND id IN ({marks(ids)})",
                                  ids).fetchall()
            else:
                raise ValueError('maintenance_decision_ids')
            at = self.clock()
            changed = [row['id'] for row in rows if transition(db, row, decision, actor, at)]
        return dict(changed=changed, skipped=0 if ids == 'all' else len(ids)-len(changed))

    def modify(self, actor, action, body):
        if not actor:
            raise PermissionError('maintenance_actor_required')
        account(actor)
        keys(body, 'request_id customer_id expected value')
        request_id, customer_id = strict_id(body['request_id']), strict_id(body['customer_id'])
        expected, value = body['expected'], body['value']
        with self.ledger.db(write=True) as db:
            prior = db.execute('SELECT * FROM maintenance_changes WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if (prior['actor'], prior['action'], prior['subject'], prior['before_json'], prior['after_json']) != (
                        actor, action, customer_id, canonical(expected), canonical(value)):
                    raise ValueError('maintenance_request_conflict')
                return dict(changed=True, reused=True, request_id=request_id)
            row = db.execute('SELECT body FROM maintenance_customers WHERE customer_id=?', (customer_id,)).fetchone()
            if not row:
                raise LookupError('maintenance_customer_missing')
            if action == 'owner':
                if value is not None:
                    account(value)
                case_id, status, _, _, _ = case_binding(db, json.loads(row['body']))
                case = (db.execute('SELECT id,owner FROM vip_cases WHERE id=?', (case_id,)).fetchone()
                        if status == 'linked' else None)
                if not case or case['owner'] != expected:
                    raise ValueError('maintenance_owner_conflict')
                db.execute('UPDATE vip_cases SET owner=? WHERE id=? AND owner IS ?', (value, case['id'], expected))
            elif action == 'tier':
                if value not in (None, 'high', 'ultra'):
                    raise ValueError('maintenance_tier_invalid')
                prior_value = db.execute('SELECT tier FROM maintenance_overrides WHERE customer_id=?',
                                         (customer_id,)).fetchone()
                if (prior_value['tier'] if prior_value else None) != expected:
                    raise ValueError('maintenance_tier_conflict')
                if value is None:
                    db.execute('DELETE FROM maintenance_overrides WHERE customer_id=?', (customer_id,))
                else:
                    db.execute('INSERT INTO maintenance_overrides VALUES(?,?) ON CONFLICT(customer_id) '
                               'DO UPDATE SET tier=excluded.tier', (customer_id, value))
            else:
                raise ValueError('maintenance_action')
            db.execute('INSERT INTO maintenance_changes VALUES(?,?,?,?,?,?,?)',
                       (request_id, actor, action, customer_id, canonical(expected), canonical(value), stamp(self.clock())))
        return dict(changed=True, reused=False, request_id=request_id)

    def effect_view(self, days):
        if days not in (7, 30, 60):
            raise ValueError('maintenance_effect_window')
        with self.ledger.db() as db:
            result = db.execute('SELECT * FROM maintenance_outcomes WHERE days=?', (days,)).fetchone()
        return json.loads(result['body']) if result else dict(status='waiting', items=[], days=days)

    def _baselines(self, entries, facts, days):
        rules = {(e['rule_id'], e['rule_version'], e['config_version']): e for e in entries}
        result = defaultdict(lambda: {'events': 0, 'returned': 0})
        horizon = timedelta(days=days)
        for (rule_id, _, version), entry in rules.items():
            rule = entry['rule_body']
            if version == 0:
                config = json.loads((self.config_path.parent / 'history' / '0.json').read_text('utf-8')) if self.config_path.exists() else load_config(self.config_path)[0]
            else:
                config = load_config(self.config_path)[0]
                if config['version'] != version:
                    config = load_config(self.config_path.parent / 'history' / (str(version) + '.json'))[0]
            if config['version'] != version:
                continue
            enabled_at = coupon_time(rule['enabled_at']).astimezone(SHANGHAI)
            baseline_end = enabled_at - horizon
            candidate_days = defaultdict(set)
            for customer, orders in facts.customers.items():
                for row in orders:
                    if row['valid'] and str(row['gid']) == GID:
                        gap = thresholds(GID, config)[RANK[rule['stage']]-1]
                        day = payment(row).date() + timedelta(days=gap)
                        at = day_end(day)
                        if baseline_end - timedelta(days=60) < at <= baseline_end and at + horizon <= facts.cutoff:
                            candidate_days[customer].add(day)
            for customer, dates in candidate_days.items():
                orders = facts.customers[customer]
                for day in sorted(dates):
                    previous = cohort(orders, day-timedelta(days=1), config, facts.covered).get(customer)
                    current = cohort(orders, day, config, facts.covered).get(customer)
                    event = new_event(previous, current) if current else None
                    at = day_end(day)
                    if not event or not matches_rule(rule, event) or not facts.covered(at, at+horizon):
                        continue
                    value = result[rule_id]
                    value['events'] += 1
                    value['returned'] += any(row['valid'] and str(row['gid']) == GID and
                                             at <= payment(row) < at+horizon for row in orders)
        for value in result.values():
            value['rate'] = value['returned']/value['events']
        return dict(result)

    def update_effects(self):
        at = self.clock()
        facts = self.facts()
        with self.ledger.db() as db:
            entries = []
            rows = db.execute("""SELECT c.*,e.event_at,e.body FROM maintenance_entries c
                                 JOIN maintenance_events e ON c.event_id=e.id
                                 WHERE e.status='active' OR c.dispatch_at IS NOT NULL""")
            for row in rows:
                entry = dict(row)
                entry['config_version'] = json.loads(entry.pop('body'))['config_version']
                entry['rule_body'] = json.loads(entry['rule_body'])
                entries.append(entry)
        start = min((coupon_time(row['event_at']) for row in entries if row['state'] == 'issued'), default=facts.cutoff)
        logs = []
        try:
            end = min(at, facts.cutoff)
            while start < end:
                next_stop = min(start + timedelta(days=7), end)
                logs.extend(self.admin.logs(start, next_stop))
                start = next_stop
        except (OSError, ValueError, KeyError, TypeError) as error:
            LOGGER.warning('Maintenance effect usage unavailable: %s', type(error).__name__)
            logs = None
        outcomes = []
        for days in (7, 30, 60):
            baseline = self._baselines(entries, facts, days)
            items = effects(entries, facts.orders, logs, days, facts.day, facts.covered, baseline)
            value = dict(status='ready' if logs is not None else 'partial', days=days, items=items,
                         observation_date=facts.day.isoformat(), season='FC27 赛季中',
                         season_note='赛季开启可能抬高同期回购率', baseline_days=60)
            outcomes.append((days, stamp(at), canonical(value)))
        with self.ledger.db(write=True) as db:
            db.executemany('INSERT INTO maintenance_outcomes VALUES(?,?,?) ON CONFLICT(days) DO UPDATE '
                           'SET observed_at=excluded.observed_at,body=excluded.body', outcomes)
