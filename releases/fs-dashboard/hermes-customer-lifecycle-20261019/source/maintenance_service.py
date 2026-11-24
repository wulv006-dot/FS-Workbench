"""Customer-stage refresh, case attachment, and program review."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
import logging
from pathlib import Path
import re
from threading import Lock

from customer_segments import ConfigCommitUnknown, load_config, thresholds, write_config
from maintenance_dispatch import Bridge, Dispatcher, checked_template, valid_email
from maintenance_effects import effects
from maintenance_ledger import (AWAITING, Ledger, SHANGHAI, active_customer, enqueue_entry, fetch_rule,
                                marks, stamp, transition)
from maintenance_reconcile import reconcile
from maintenance_review import BATCH, CouponIndex, canonical, coupon_time, digest, manual_evidence, member_id, review_evidence
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
    ident, email = customer['customer_id'], customer['email']
    exact, conflicts = [], []
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
        emails = {value.strip().lower() for item in identities for value in item.get('emails', ())
                  if isinstance(value, str)}
        uids = {member_id(value) for item in identities for value in item.get('uids', ())}
        if emails == {email} and case['customer_id'] in (None, ident):
            exact.append(case['id'])
        elif email in emails or (uid and uid in uids):
            conflicts.append(case['id'])
    return sorted(exact), sorted(conflicts)


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


def case_link(db, customer, at):
    ident, email = customer['customer_id'], customer['email']
    if not valid_email(email):
        store_case_link(db, ident, None, 'pending_identity')
        return None, 'pending_identity'
    prior = db.execute('SELECT case_id,status FROM maintenance_cases WHERE customer_id=?', (ident,)).fetchone()
    exact, conflicts = matching_cases(db, customer)
    if prior and prior['status'] == 'linked' and prior['case_id'] in exact:
        return prior['case_id'], prior['status']
    if conflicts or len(exact) > 1:
        status, case_id = 'pending_identity', None
    elif exact:
        status, case_id = 'linked', exact[0]
    else:
        status, case_id = 'linked', create_case(db, customer, at)
    store_case_link(db, ident, case_id, status)
    return case_id, status


def case_feedback(db, customer_id):
    row = db.execute('SELECT case_id,status FROM maintenance_cases WHERE customer_id=?', (customer_id,)).fetchone()
    if not row or row['status'] == 'pending_identity':
        return []
    return events_for(db, row['case_id'])


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
                order = facts.by_order.get(row['last_order_key'])
                if order and order['valid'] and order['customer_id'] == row['customer_id']:
                    continue
                last = coupon_time(json.loads(row['body'])['last_paid_at']).astimezone(SHANGHAI).date()
                if not facts.covered(day_end(last)-timedelta(days=1), day_end(last)):
                    continue
                db.execute("UPDATE maintenance_events SET status='void' WHERE id=?", (row['id'],))
                self.ledger.void(db, at, ACTOR, event_id=row['id'])

    def _day(self, facts, day, config, at):
        current = cohort(facts.orders, day, config, facts.covered)
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
        except (OSError, ValueError, KeyError, TypeError) as error:
            LOGGER.warning('Maintenance coupon usage unavailable: %s', type(error).__name__)
            return None
        index = CouponIndex(facts.orders, logs, facts.uid_customers)
        self._usage = (at, index, facts.token)
        return index

    def _evidence(self, entry, facts, at, logs):
        with self.ledger.db() as db:
            event = db.execute('SELECT * FROM maintenance_events WHERE id=?', (entry['event_id'],)).fetchone()
        if not event or event['status'] != 'active':
            raise LookupError('maintenance_event_not_available')
        customer = entry['customer_id']
        orders = facts.customers.get(customer, [])
        if not orders or not facts.covered(coupon_time(event['event_at']), facts.cutoff):
            raise LookupError('maintenance_order_coverage')
        used = logs.for_customer(customer) if logs is not None else None
        # A fallback use hit needs a defensible customer. Keep our automatic batches in the local ledger.
        if used:
            used['matched'] = [row for row in used['matched'] if not str(
                (row.get('memberCoupon') or {}).get('grant_batch_no') or '').startswith('FCSM_')]
        relevant = [dict(uid=uid, customer_id=cid) for uid in facts.customer_uids.get(customer, ())
                    for cid in facts.uid_customers[uid]]
        coupons = manual_evidence(relevant, customer, at, self.admin.grants, used)
        if logs is None:
            coupons['notice'] += '；用券记录暂不可用，未归属条数待核'
            coupons['unattributed'] = None
        cutoff = coupon_time(event['event_at'])
        return dict(coupons=coupons, payments=[
            dict(order_key=row['order_key'], paid_at=row['paid_at'])
            for row in orders if row['valid'] and payment(row) >= cutoff],
            exceptions=self.admin.exceptions(orders))

    @staticmethod
    def _local_evidence(db, entry, at, evidence):
        customer = entry['customer_id']
        contacts = [dict(at=row['at'], actor=row['actor'], contacted_at=row.get('contacted_at'))
                    for row in case_feedback(db, customer) if row['event'] == 'contacted']
        return review_evidence(**evidence, automatic=active_customer(db, customer, at), contacts=contacts)

    def review(self, entry, facts, at, logs, latest_logs):
        initial = self._evidence(entry, facts, at, logs)
        with self.ledger.db() as db:
            result = self._local_evidence(db, entry, at, initial)
        second_facts = self.facts(latest=True)
        latest = self._evidence(entry, second_facts, self.clock(), latest_logs)
        def recheck(db, row):
            if self.source.token() != second_facts.token:
                return None
            return self._local_evidence(db, row, self.clock(), latest)['digest']
        return self.ledger.commit_review(entry['id'], result, recheck, self.clock())

    def prepare_recheck(self, row, when):
        facts = self.facts(latest=True)
        config, _, _ = load_config(self.config_path)
        current = cohort(facts.customers.get(row['customer_id'], ()), facts.day, config, facts.covered).get(row['customer_id'])
        rule = row['rule_body']
        if current is None or current['tier'] != rule['tier']:
            return lambda db, fresh: 'tier_changed'
        if current['email'] != row['email']:
            return lambda db, fresh: 'recipient_changed'
        if rule['customer_type'] is not None and current['customer_type'] != rule['customer_type']:
            return lambda db, fresh: 'customer_type_changed'
        if RANK.get(current['stage'], -1) < RANK[rule['stage']]:
            return lambda db, fresh: 'stage_changed'
        evidence = self._evidence(row, facts, when, self.usage(facts, when, refresh=True))

        def locked(db, fresh):
            if self.source.token() != facts.token or load_config(self.config_path)[1] != config['version']:
                raise LookupError('maintenance_recheck_input_changed')
            result = self._local_evidence(db, fresh, self.clock(), evidence)
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
        latest_logs = self.usage(latest, self.clock(), refresh=True)
        unprocessed = 0
        for entry in reviewing:
            try:
                unprocessed += not self.review(entry, latest, at, logs, latest_logs)
            except (LookupError, OSError, ValueError, KeyError, TypeError) as error:
                unprocessed += 1
                LOGGER.warning('Maintenance review %s pending: %s', entry['id'], type(error).__name__)
        self._review_offset += unprocessed

    def dispatch(self):
        for row in self.ledger.dispatch_queue(self.clock()):
            try:
                self.dispatcher.once(row['id'])
            except (LookupError, OSError, ValueError, KeyError, TypeError) as error:
                LOGGER.warning('Maintenance dispatch %s deferred: %s', row['id'], type(error).__name__)

    def reconcile(self):
        reconcile(self.ledger, self.clock)

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
        items = [dict(json.loads(row['body']), case_id=row['case_id'], case_status=row['status'],
                      owner=row['owner'], override_tier=row['tier'], alert=bool(row['alert'])) for row in rows]
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
            link = db.execute('SELECT c.*,v.owner FROM maintenance_cases c LEFT JOIN vip_cases v ON v.id=c.case_id '
                              'WHERE c.customer_id=?', (ident,)).fetchone()
            override = db.execute('SELECT tier FROM maintenance_overrides WHERE customer_id=?', (ident,)).fetchone()
            events = db.execute('SELECT id,event_at,status,alert,body FROM maintenance_events '
                                'WHERE customer_id=? ORDER BY event_at DESC LIMIT 100', (ident,))
            timeline = []
            for event in events:
                body = json.loads(event['body'])
                timeline.append(dict(id=event['id'], at=event['event_at'], stage=body['stage'],
                                     config_version=body['config_version'], status=event['status'],
                                     alert=bool(event['alert'])))
            contacts = case_feedback(db, ident)
            customer = json.loads(row['body'])
            exact, _ = matching_cases(db, customer) if link and link['status'] == 'pending_identity' else ([], [])
            return dict(customer=customer, case=dict(link) if link else None, matching_cases=exact,
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
                return after
            link = db.execute('SELECT status FROM maintenance_cases WHERE customer_id=?', (customer_id,)).fetchone()
            row = db.execute('SELECT body FROM maintenance_customers WHERE customer_id=?', (customer_id,)).fetchone()
            if not row or not link or link['status'] != 'pending_identity':
                raise ValueError('maintenance_case_already_resolved')
            customer = json.loads(row['body'])
            if not valid_email(customer['email']):
                raise ValueError('maintenance_case_email_required')
            exact, _ = matching_cases(db, customer)
            if (value is None and exact) or (value is not None and value not in exact):
                raise ValueError('maintenance_case_email_mismatch')
            at = self.clock()
            ident = value or create_case(db, customer, at)
            store_case_link(db, customer_id, ident, 'linked')
            after = {'selected': value, 'case_id': ident}
            db.execute('INSERT INTO maintenance_changes VALUES(?,?,?,?,?,?,?)',
                       (request_id, actor, 'case_link', customer_id, 'null', canonical(after), stamp(at)))
            return after

    def queue_view(self, view, offset=0):
        state_sets = {
            'review': ('reviewing', 'held'),
            'ready': ('ready',),
            'delivery': AWAITING + ('dispatching', 'issued', 'limited', 'rejected', 'unknown', 'pending_register',
                                    'manually_closed', 'recheck_failed', 'void', 'removed', 'expired'),
            'manual': ('pending_register', 'unknown'),
        }
        filter_sql = 'AND job_id IS NULL' if view == 'manual' else ''
        rows = self.ledger.queue(state_sets[view], limit=21, offset=offset, sql_filter=filter_sql)
        items = []
        for row in rows[:20]:
            reviews = self.ledger.reviews(row['id'])
            items.append({key: value for key, value in row.items() if key != 'rule_body'})
            items[-1]['review'] = reviews[-1] if reviews else None
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

    def manual_result(self, actor, body):
        keys(body, 'id batch state evidence')
        ident = strict_id(body['id'])
        proof = body['evidence']
        row = self.ledger.entry(ident)
        if (not isinstance(body['batch'], str) or BATCH.fullmatch(body['batch']) is None
                or not row or body['batch'] != row['batch'] or not isinstance(proof, str)
                or not 1 <= len(proof.strip()) <= 300 or any(ord(char) < 32 for char in proof)):
            raise ValueError('maintenance_manual_evidence')
        return dict(changed=self.ledger.manual_result(ident, body['state'], actor, self.clock(), proof.strip()))

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
            row = db.execute('SELECT 1 FROM maintenance_customers WHERE customer_id=?', (customer_id,)).fetchone()
            if not row:
                raise LookupError('maintenance_customer_missing')
            if action == 'owner':
                if value is not None:
                    account(value)
                case = db.execute('SELECT v.id,v.owner FROM maintenance_cases c JOIN vip_cases v ON c.case_id=v.id '
                                  "WHERE c.customer_id=? AND c.status='linked' AND NOT EXISTS(SELECT 1 FROM vip_events e "
                                  "WHERE e.case_id=v.id AND json_extract(e.payload,'$.event')='close')",
                                  (customer_id,)).fetchone()
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
