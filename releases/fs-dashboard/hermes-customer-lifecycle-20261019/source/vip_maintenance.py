"""Private, weekly FC27 VIP maintenance and verified payment outcomes."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
import json
import logging
import os
import re
import sqlite3
import tempfile
import uuid

from customer_tracking import ID, SHANGHAI, payment_moment


TRACKING_DB = Path('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db')
REPORT_ROOT = Path('/var/lib/fs-hermes-fc/native')
UK_US = 'uk_us'
PREFERRED = 'global_preferred'
SCOPE_TABLES = {
    UK_US: ('vip_weeks', 'vip_week_cases', 'vip_cases', 'vip_refresh'),
    PREFERRED: ('vip_preferred_weeks', 'vip_preferred_week_cases', 'vip_preferred_cases', 'vip_preferred_refresh'),
}
EVENTS = {'claim', 'contacted', 'feedback', 'close'}
BULK_CLAIM = 'vip_bulk_claim'
MAX_BULK_CLAIMS = 100
RETRY_DELAY = timedelta(minutes=30)
OBSERVATION = timedelta(days=7)
SCHEMA = """
CREATE TABLE IF NOT EXISTS vip_weeks (
    week TEXT PRIMARY KEY, frozen_at TEXT, coverage TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vip_cases (
    id TEXT PRIMARY KEY, week TEXT NOT NULL, opened_at TEXT NOT NULL,
    baseline TEXT NOT NULL, observation TEXT, observed_at TEXT, owner TEXT
);
CREATE TABLE IF NOT EXISTS vip_week_cases (
    week TEXT NOT NULL, case_id TEXT NOT NULL, PRIMARY KEY(week, case_id)
);
CREATE TABLE IF NOT EXISTS vip_events (
    request_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, actor TEXT NOT NULL,
    payload TEXT NOT NULL, at TEXT NOT NULL, receipt TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS vip_case_events ON vip_events(case_id);
CREATE TABLE IF NOT EXISTS vip_refresh (
    id INTEGER PRIMARY KEY CHECK(id=1), attempted_at TEXT NOT NULL, status TEXT NOT NULL,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS vip_preferred_weeks (
    week TEXT PRIMARY KEY, frozen_at TEXT, coverage TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vip_preferred_week_cases (
    week TEXT NOT NULL, case_id TEXT NOT NULL, baseline TEXT, PRIMARY KEY(week, case_id)
);
CREATE TABLE IF NOT EXISTS vip_preferred_cases (
    id TEXT PRIMARY KEY, week TEXT NOT NULL, opened_at TEXT NOT NULL,
    baseline TEXT NOT NULL, observation TEXT, observed_at TEXT
);
CREATE TABLE IF NOT EXISTS vip_preferred_refresh (
    id INTEGER PRIMARY KEY CHECK(id=1), attempted_at TEXT NOT NULL, status TEXT NOT NULL,
    updated_at TEXT
);
"""


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def local(value):
    value = payment_moment(value)
    return value.astimezone(SHANGHAI) if value else None


def start_of(day):
    return datetime.combine(day, time.min, tzinfo=SHANGHAI)


def week_for(value):
    return value - timedelta(days=value.weekday())


def checked_week(value):
    try:
        week = date.fromisoformat(value) if isinstance(value, str) else value
    except ValueError:
        raise ValueError('vip_week') from None
    if type(week) is not date or week.weekday() or isinstance(value, str) and week.isoformat() != value:
        raise ValueError('vip_week')
    return week


def checked_scope(scope):
    if not isinstance(scope, str) or scope not in SCOPE_TABLES:
        raise ValueError('vip_scope')
    return scope


def scoped_rows(db, scope, week=None):
    _, memberships, cases, _ = SCOPE_TABLES[scope]
    owner_join = ' JOIN vip_cases AS common ON common.id=c.id' if scope == PREFERRED else ''
    owner = ',common.owner' if owner_join else ''
    if week is not None:
        baseline = ',w.baseline AS week_baseline' if scope == PREFERRED else ''
        return db.execute(f'SELECT c.*{owner}{baseline} FROM {cases} AS c{owner_join} '
                          f'JOIN {memberships} AS w ON w.case_id=c.id WHERE w.week=? ORDER BY c.opened_at,c.id',
                          (week,)).fetchall()
    current_scope = (' WHERE c.id NOT IN (SELECT id FROM vip_preferred_cases) '
                     'OR c.id IN (SELECT case_id FROM vip_week_cases)') if scope == UK_US else ''
    return db.execute(f'SELECT c.*{owner} FROM {cases} AS c{owner_join}{current_scope} ORDER BY c.opened_at,c.id').fetchall()


def events_for(db, case_id, cutoff=None):
    events = [dict(json.loads(row['payload']), actor=row['actor'], at=row['at'])
              for row in db.execute('SELECT actor,payload,at FROM vip_events WHERE case_id=? ORDER BY rowid', (case_id,))]
    return [event for event in events if local(event['at']) < cutoff] if cutoff else events


def aliases(buyer):
    identity = buyer['identity']
    return {(buyer['siteId'], kind, str(value))
            for kind in ('uids', 'emails', 'esBuyerIds', 'customerIds') for value in identity.get(kind, [])}


def same_buyer(left, right):
    if left['siteId'] != right['siteId']:
        return False
    left_uids, right_uids = (set(map(str, record['identity']['uids'])) for record in (left, right))
    if left_uids and right_uids:
        return not left_uids.isdisjoint(right_uids)
    return left['buyerId'] == right['buyerId'] or bool(aliases(left) & aliases(right))


def refund_or_exception(order):
    return (order.get('refundStatus') in {'full_observed', 'marked_amount_unknown', 'unknown'}
            or order.get('afterSales') in {'fraud', 'dispute'}
            or order.get('refundReadback', {}).get('status') in {'missing', 'unavailable'})


def disposition(buyer, order):
    if buyer.get('scope') == PREFERRED:
        from vip_followup import preferred_disposition
        if order.get('refundReadback', {}).get('status') in {'missing', 'unavailable'}:
            return 'unknown'
        return preferred_disposition(order)
    if refund_or_exception(order):
        return ('problem' if order.get('refundStatus') == 'full_observed'
                and order.get('refundReadback', {}).get('status') not in {'missing', 'unavailable'} else 'unknown')
    if str(order.get('payStatus')) == '1' or order.get('refundStatus') == 'partial_observed':
        return 'effective'
    return 'problem'


def returned_orders(buyer, opened, through):
    result, unresolved = [], False
    for order in buyer['history']:
        paid_at = local(order.get('paidAtShanghai'))
        if not paid_at or not opened <= paid_at < through or order['siteId'] != buyer['siteId']:
            continue
        result_kind = disposition(buyer, order)
        if result_kind == 'unknown':
            unresolved = True
        elif result_kind == 'effective':
            result.append((paid_at, order))
    return sorted(result, key=lambda row: row[0]), unresolved


def paid_usd(orders):
    amount = Decimal(0)
    for _, order in orders:
        value, refund = order.get('amountUsd'), order.get('knownSettledRefundUsd')
        if value is None or order.get('refundStatus') == 'partial_observed' and refund is None:
            return None
        amount += Decimal(value) - Decimal(refund or '0')
    return str(amount.quantize(Decimal('.01')))


def outcome_for(case, buyer, events, cutoff=None):
    opened = local(case['opened_at'])
    observed = local(case['observed_at'])
    first_contact = min((local(event['contacted_at']) for event in events if event['event'] == 'contacted'), default=None)
    closed = next((local(event['at']) for event in events if event['event'] == 'close'), None)
    through = min(observed, cutoff) if observed and cutoff else observed
    matures = first_contact + OBSERVATION if first_contact else opened + OBSERVATION
    if through:
        relevant_through = min(through, matures) if first_contact else min(through, closed) if closed else through
        orders, unresolved = returned_orders(buyer, opened, relevant_through)
    else:
        orders, unresolved = [], False
    natural = [(when, order) for when, order in orders if (first_contact is None or when < first_contact)
               and (closed is None or when < closed)]
    contacted = [(when, order) for when, order in orders if first_contact and first_contact < when < matures]
    unresolved = unresolved or any(when == first_contact for when, order in orders)
    complete = bool(through and through >= opened and buyer.get('paymentCoverage', {}).get('complete') is True and not unresolved)
    kind, matching, first_paid = 'unknown', [], None
    if natural or contacted:
        kind, matching = ('natural', natural) if natural else ('post_contact', contacted)
        first_paid = matching[0][0].isoformat()
    elif complete and through >= matures:
        kind = 'no_return'
    status = 'partial' if not complete else 'mature' if through >= matures else 'immature'
    return dict(status=status, kind=kind, paid_usd=paid_usd(matching) if matching else None,
                first_paid_at=first_paid, observed_through=through.isoformat() if through else None,
                matures_at=matures.isoformat())


def case_view(case, events, week, actor=None, cutoff=None):
    base = json.loads(case['baseline'])
    buyer = json.loads(case['observation']) if case['observation'] else base
    week_baseline = json.loads(case['week_baseline']) if 'week_baseline' in case.keys() and case['week_baseline'] else None
    frozen = week_baseline or base
    outcome = outcome_for(case, buyer, events, cutoff)
    preferred = base.get('scope') == PREFERRED
    recent = buyer.get('lastObservedOrder') or buyer.get('lastOrder') or base.get('lastOrder') or {}
    effective = [order for order in buyer['history'] if disposition(buyer, order) == 'effective']
    latest_valid = max(effective, key=lambda order: local(order['paidAtShanghai']), default={})
    last_paid = local(latest_valid.get('paidAtShanghai'))
    observed = local(case['observed_at']) or local(case['opened_at'])
    days_since_paid = (observed.date() - last_paid.date()).days if last_paid else None
    updates = {key: next((event[key] for event in reversed(events) if key in event), None)
               for key in ('reason', 'notes', 'next_review_day')}
    contacted = any(event['event'] == 'contacted' for event in events)
    closed = any(event['event'] == 'close' for event in events)
    owner = case['owner']
    status = ('closed' if closed else 'contacted' if contacted else 'returned' if outcome['kind'] == 'natural'
              else 'assigned' if owner else 'queued')
    after_sales = {'problem': '问题订单', 'fraud': '欺诈标记', 'dispute': '争议', 'after_sales': '售后标记'}
    issue = after_sales.get(recent.get('afterSales'))
    refund = {'full_observed': '全额退款', 'partial_observed': '部分退款',
              'marked_amount_unknown': '已标记退款，金额待核'}.get(recent.get('refundStatus'))
    may_be_due = (days_since_paid is not None and days_since_paid >= 15
                  and buyer.get('paymentCoverage', {}).get('complete') is True
                  and (preferred or recent.get('refundStatus') not in {'marked_amount_unknown', 'unknown'}))
    purchase_days = sorted({local(order['paidAtShanghai']).date() for order in effective})
    gaps = [(right - left).days for left, right in zip(purchase_days, purchase_days[1:])]
    cadence = median(gaps) if gaps else None
    windows = frozen['windows']
    first = Decimal(windows['firstHalf']['salesUsd'])
    second = Decimal(windows['secondHalf']['salesUsd'])
    month = Decimal(windows['month']['salesUsd'])
    evidence = [f'入组30日实付 ${month:.2f}，前15日 ${first:.2f}，后15日 ${second:.2f}']
    if days_since_paid is not None:
        evidence.append(f'距末次有效付款 {days_since_paid} 天')
    if cadence is not None:
        evidence.append(f'观察到 {len(purchase_days)} 个购买日，中位间隔 {cadence:g} 天')
    elif purchase_days:
        evidence.append('目前仅观察到 1 个购买日')
    detail = ' '.join(str(recent[key]) + ('K' if key == 'purchaseK' else '')
                      for key in ('platform', 'purchaseK') if recent.get(key))
    if detail:
        evidence.append(f'最近一单 {detail}')
    if issue or refund:
        evidence.append('最近一单有' + '、'.join(value for value in (issue, refund) if value))
    if issue or refund:
        priority, ask = 'after_sales', '先核处理进展。上单之后还有哪一步需要协助？'
    elif outcome['kind'] == 'natural':
        priority, ask = 'review', '联系前已观察到回购，退出本次召回'
    elif outcome['kind'] == 'post_contact':
        priority, ask = 'review', '联系后七天内已观察到付款，回看上次反馈和需求'
    elif may_be_due and cadence is not None and len(purchase_days) >= 3 and days_since_paid > cadence:
        priority, ask = 'due', '近期仍在同一平台玩吗？这次间隔较长，购买时有没有遇到困难？'
    elif may_be_due and len(purchase_days) == 1 and recent.get('purchaseK'):
        priority, ask = 'due', '上次购买的 Coins 还够用吗？那次是提前备量，还是近期需求变化？'
    elif may_be_due:
        priority, ask = 'due', '联系前复核当日付款。最近游戏需求或购买方式有变化吗？'
    else:
        priority, ask = 'review', '复核当天付款、身份和退款情况；确认到期再联系'
    cycle = 'normal' if days_since_paid is not None and days_since_paid <= 14 else 'due' if may_be_due else 'unknown'
    band = 'P1' if cycle == 'due' and days_since_paid >= 22 else 'P2' if cycle == 'due' else 'watch'
    review_day = (last_paid.date() + timedelta(days=15)).isoformat() if last_paid else None
    if preferred and cycle == 'normal':
        ask = '仍在正常复购周期，观察后续付款'
    quality = frozen.get('quality')
    checks = sorted(set((quality or {}).get('checksBeforeContact', ())) | set(buyer.get('checksBeforeContact', ())))
    if preferred and cycle == 'due' and 'latest_payment_or_after_sales_needs_review' in checks:
        ask = '先核最近一单付款与售后，再决定是否联系'
    reason = '。'.join(evidence) + '。' + ask
    return dict(case_id=case['id'], week=case['week'], site_id=buyer['siteId'], email=buyer.get('email'),
                uid=buyer.get('uid'), country=buyer.get('country'),
                last_paid_at=last_paid.isoformat() if last_paid else None,
                days_since_last_paid=days_since_paid,
                first_review_day=review_day, cycle={'status': cycle, 'review_day': review_day},
                owner=owner, status=status,
                can_update=bool(actor and not closed and owner in (None, actor) and (not preferred or cycle == 'due' or owner == actor)),
                carried_over=case['week'] != week and (not preferred or week_baseline is None or owner is not None),
                windows=windows, quality=quality,
                checks_before_contact=checks,
                guidance={'priority': priority, 'reason': reason, 'purchase_days': len(purchase_days),
                          'median_gap_days': cadence, 'band': band, 'headline': evidence[1] if days_since_paid is not None else '末次有效付款待核',
                          'evidence': evidence, 'detail': reason, 'question': ask},
                events=events, outcome=outcome, **updates)


def claim_blocker(view, actor, scope, *, ready_only):
    if view['status'] == 'closed':
        return 'closed'
    if ready_only and view['status'] == 'returned':
        return 'returned'
    owner = view['owner']
    if owner is not None:
        return 'already_claimed' if owner == actor else 'assigned_to_other'
    if not ready_only:
        return None
    if view['status'] == 'contacted':
        return 'already_claimed'
    cycle = view['cycle']['status']
    if cycle == 'due' or scope == UK_US and view['guidance']['priority'] == 'after_sales':
        return None
    return 'not_due' if cycle == 'normal' else 'payment_unverified'


def record_event(db, request_id, case_id, actor, payload, stamp):
    event = payload['event']
    if event == 'claim':
        updated = db.execute('UPDATE vip_cases SET owner=? WHERE id=? AND owner IS NULL', (actor, case_id))
        if updated.rowcount != 1:
            raise ValueError('vip_already_assigned')
    receipt = dict(status='recorded', case_id=case_id, event=event, owner=actor,
                   request_id=request_id, recorded_at=stamp, reused=False)
    db.execute('INSERT INTO vip_events VALUES(?,?,?,?,?,?)',
               (request_id, case_id, actor, encoded(payload), stamp, encoded(receipt)))
    return receipt


def summarize(items):
    outcomes = [item['outcome'] for item in items]
    natural = [row for row in outcomes if row['kind'] == 'natural']
    after = [row for row in outcomes if row['kind'] == 'post_contact']
    contacted = [item for item in items if any(event['event'] == 'contacted' for event in item['events'])]
    reasons = {}
    for item in items:
        if item['reason'] in {'early_stock', 'game_demand', 'platform_change', 'price', 'payment',
                              'fulfillment', 'no_reply', 'resolved', 'no_contact'}:
            reasons[item['reason']] = reasons.get(item['reason'], 0) + 1

    def amount(rows):
        if any(row['paid_usd'] is None for row in rows):
            return None
        return format(sum((Decimal(row['paid_usd']) for row in rows), Decimal('0.00')), 'f')

    return dict(people=len(items), new_people=sum(not item['carried_over'] for item in items),
                carried_people=sum(item['carried_over'] for item in items), contacted_people=len(contacted),
                natural_people=len(natural), post_contact_people=len(after),
                immature_people=sum(row['status'] == 'immature' for row in outcomes),
                unknown_people=sum(row['status'] == 'partial' for row in outcomes),
                mature_contacted_people=sum(item['outcome']['status'] == 'mature'
                                            and item['outcome']['kind'] != 'natural' for item in contacted),
                mature_post_contact_people=sum(row['status'] == 'mature' for row in after),
                closed_people=sum(item['status'] == 'closed' for item in items), feedback_reasons=reasons,
                due_people=sum(item['cycle']['status'] == 'due' for item in items),
                normal_cycle_people=sum(item['cycle']['status'] == 'normal' for item in items),
                unknown_cycle_people=sum(item['cycle']['status'] == 'unknown' for item in items),
                p1_people=sum(item['guidance']['band'] == 'P1' for item in items),
                p2_people=sum(item['guidance']['band'] == 'P2' for item in items),
                natural_usd=amount(natural), post_contact_usd=amount(after))


def queue_view(db, week, actor=None, cutoff=None, scope=UK_US):
    weeks, _, _, _ = SCOPE_TABLES[scope]
    frozen = db.execute(f'SELECT frozen_at,coverage FROM {weeks} WHERE week=?', (week,)).fetchone()
    coverage = json.loads(frozen['coverage']) if frozen else None
    items = [case_view(row, events_for(db, row['id'], cutoff), week, actor, cutoff)
             for row in scoped_rows(db, scope, week)]
    order = {'after_sales': 0, 'due': 1, 'review': 2}
    def rank(item):
        windows, guidance = item['windows'], item['guidance']
        gap = (item['days_since_last_paid'] or 0) - (guidance['median_gap_days'] or 14)
        decline = Decimal(windows['firstHalf']['salesUsd']) - Decimal(windows['secondHalf']['salesUsd'])
        band = {'P1': 0, 'P2': 1, 'watch': 2}[guidance['band']] if scope == PREFERRED else 0
        return (item['status'] in {'closed', 'returned'}, band, order[guidance['priority']],
                -gap, -decline, -Decimal(windows['month']['salesUsd']), -guidance['purchase_days'])

    items.sort(key=rank)
    return dict(scope=scope, week=week, frozen_at=frozen['frozen_at'] if frozen else None, coverage=coverage,
                status='ready' if frozen and frozen['frozen_at'] and coverage['complete'] is True
                else 'partial' if frozen else 'pending',
                items=items, summary=summarize(items) if frozen and frozen['frozen_at'] else None)


def vip_weekly_report(path, week, cutoff, scope=UK_US):
    """Read the frozen report cohort without touching customer history or contacting its source."""
    connection = None
    try:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN')
        view = queue_view(connection, checked_week(week).isoformat(), cutoff=cutoff, scope=checked_scope(scope))
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError):
        return dict(status='unavailable', week=week, reason='vip_week_evidence_unavailable')
    finally:
        if connection is not None:
            connection.close()
    through = [local(item['outcome']['observed_through']) for item in view['items']]
    earliest = min((moment for moment in through if moment), default=None)
    payment_complete = all(moment is not None and moment >= cutoff for moment in through)
    payment_complete = payment_complete and all(item['outcome']['status'] != 'partial' for item in view['items'])
    reason = None
    if view['frozen_at'] is None:
        reason = 'vip_week_not_frozen'
    elif view['status'] == 'partial' or not payment_complete:
        reason = 'vip_week_partial_coverage'
    return dict(status=view['status'] if not view['frozen_at'] or not reason else 'partial',
                week=week, frozen_at=view['frozen_at'], summary=view['summary'],
                earliest_observed_through=earliest.isoformat() if earliest else None,
                cutoff=cutoff.isoformat(), payment_complete=payment_complete if view['frozen_at'] else None,
                reason=reason,
                method='按同站会员去重。联系前付款计自然回流。联系后七天付款只表示时间顺序；七天未满及来源不全另列，未知金额不补零。')


def weekly_artifact(root, week):
    return root / ('vip-maintenance-' + checked_week(week).isoformat() + '.json')


def read_weekly_report(root, week, cutoff):
    try:
        value = json.loads(weekly_artifact(root, week).read_bytes())
        if value['week'] != week or value['cutoff'] != cutoff.isoformat():
            raise ValueError('vip_weekly_cutoff')
        return value
    except (OSError, ValueError, TypeError, KeyError):
        return dict(status='unavailable', week=week, cutoff=cutoff.isoformat(), reason='vip_week_evidence_unavailable')


def write_weekly_report(root, week, value):
    path = weekly_artifact(root, week)
    uid, gid = None, None
    if os.name == 'posix':
        info = root.stat()
        uid, gid = info.st_uid, info.st_gid
    fd, name = tempfile.mkstemp(prefix='.vip-maintenance-', dir=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if uid is not None:
                os.fchown(stream.fileno(), uid, gid)
            stream.write(encoded(value).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class VipMaintenance:
    def __init__(self, store, source=None, clock=lambda: datetime.now(SHANGHAI), *, report_root=None):
        self.store = store
        self.source = source
        self.clock = clock
        self.report_root = report_root if report_root is not None else REPORT_ROOT if store.path == TRACKING_DB else None
        self.report_revision = None
        with store.db() as db:
            db.executescript(SCHEMA)

    def queue(self, week=None, *, actor=None, scope=UK_US):
        current = week_for(self.clock().astimezone(SHANGHAI).date())
        week = checked_week(week) if week is not None else current
        scope = checked_scope(scope)
        with self.store.db() as db:
            db.execute('BEGIN')
            result = queue_view(db, week.isoformat(), actor, scope=scope)
        result['viewer'] = actor
        for item in result['items']:
            item['can_bulk_claim'] = bool(actor and week == current and
                                          claim_blocker(item, actor, scope, ready_only=True) is None)
        return result

    def weekly_summary(self, week, cutoff, scope=UK_US):
        return vip_weekly_report(self.store.path, week, cutoff, scope)

    def lookup_receipt(self, actor, request_id):
        if not isinstance(request_id, str) or not ID.fullmatch(request_id):
            raise ValueError('vip_feedback_fields')
        with self.store.db() as db:
            record = db.execute('SELECT case_id,actor,receipt FROM vip_events WHERE request_id=?', (request_id,)).fetchone()
        if record is None:
            return None
        if record['actor'] != actor:
            raise PermissionError('vip_owner_required')
        return dict(status='available', action='vip_feedback' if record['case_id'] else BULK_CLAIM,
                    result=json.loads(record['receipt']))

    def bulk_claim(self, actor, body):
        if not isinstance(actor, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', actor):
            raise PermissionError('vip_owner_required')
        if type(body) is not dict or set(body) != {'week', 'scope', 'request_id', 'case_ids'}:
            raise ValueError('vip_bulk_claim_fields')
        request_id, case_ids = body['request_id'], body['case_ids']
        if (not isinstance(request_id, str) or not ID.fullmatch(request_id)
                or type(case_ids) is not list or not 1 <= len(case_ids) <= MAX_BULK_CLAIMS
                or not all(isinstance(value, str) and ID.fullmatch(value) for value in case_ids)
                or len(case_ids) != len(set(case_ids)) or not isinstance(body['week'], str)):
            raise ValueError('vip_bulk_claim_fields')
        week, scope = checked_week(body['week']).isoformat(), checked_scope(body['scope'])
        payload = dict(week=week, scope=scope, case_ids=case_ids)
        now = self.clock().astimezone(SHANGHAI)
        stamp = now.isoformat()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM vip_events WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior['actor'] != actor:
                    raise PermissionError('vip_owner_required')
                if prior['case_id'] or json.loads(prior['payload']) != payload:
                    raise ValueError('vip_bulk_claim_conflict')
                return dict(json.loads(prior['receipt']), reused=True)
            if db.execute('SELECT 1 FROM requests WHERE request_id=?', (request_id,)).fetchone():
                raise ValueError('vip_bulk_claim_conflict')
            if week != week_for(now.date()).isoformat():
                raise ValueError('vip_bulk_claim_current_week')
            members = {row['id']: row for row in scoped_rows(db, scope, week)}
            items = []
            claimed = 0
            for case_id in case_ids:
                case = members.get(case_id)
                reason = 'not_member'
                if case is not None:
                    view = case_view(case, events_for(db, case_id), week, actor)
                    reason = claim_blocker(view, actor, scope, ready_only=True)
                if reason is None:
                    record_event(db, f'{request_id}:{case_id}', case_id, actor,
                                 dict(event='claim', scope=scope), stamp)
                    claimed += 1
                items.append(dict(case_id=case_id, status='skipped' if reason else 'claimed',
                                  reason_code=reason or 'claimed'))
            receipt = dict(status='recorded', action=BULK_CLAIM, request_id=request_id, week=week, scope=scope,
                           claimed=claimed, skipped=len(items) - claimed, items=items, reused=False)
            # Reserve the original ID in the legacy namespace. Its public record contains no case data.
            db.execute('INSERT INTO requests VALUES(?,?,?,?)', (request_id, BULK_CLAIM, '',
                                                              encoded({'status':'private_receipt'})))
            db.execute('INSERT INTO vip_events VALUES(?,?,?,?,?,?)',
                       (request_id, '', actor, encoded(payload), stamp, encoded(receipt)))
            return receipt

    def feedback(self, actor, body):
        now = self.clock().astimezone(SHANGHAI)
        if not isinstance(actor, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', actor):
            raise PermissionError('vip_owner_required')
        common = {'case_id', 'request_id', 'event'}
        fields = {'claim': set(), 'contacted': {'contacted_at', 'reason', 'notes', 'next_review_day'},
                  'feedback': {'reason', 'notes', 'next_review_day'}, 'close': {'reason', 'notes'}}
        if (type(body) is not dict or not common <= set(body) or not isinstance(body['event'], str)
                or body['event'] not in EVENTS or set(body) - common - fields[body['event']] - {'scope'}
                or not all(isinstance(body[key], str) and ID.fullmatch(body[key]) for key in ('case_id', 'request_id'))):
            raise ValueError('vip_feedback_fields')
        event, case_id, request_id = body['event'], body['case_id'], body['request_id']
        scope = checked_scope(body.get('scope', UK_US))
        if event == 'feedback' and set(body) - {'scope'} == common:
            raise ValueError('vip_feedback_fields')
        for key, limit in (('reason', 100), ('notes', 1000)):
            if key in body and (not isinstance(body[key], str) or not body[key].strip() or len(body[key]) > limit
                                or any(ord(char) < 32 and char not in '\n\t' for char in body[key])):
                raise ValueError('vip_feedback_fields')
        if 'next_review_day' in body:
            day = body['next_review_day']
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError('vip_feedback_fields')
            except (ValueError, TypeError):
                raise ValueError('vip_feedback_fields') from None
        contacted_at = None
        payload = {key: value for key, value in body.items() if key not in ('request_id', 'case_id')}
        if event == 'contacted':
            try:
                contacted_at = datetime.fromisoformat(body.get('contacted_at', '').replace('Z', '+00:00'))
                if contacted_at.utcoffset() is None:
                    raise ValueError('vip_feedback_fields')
                payload['contacted_at'] = contacted_at.astimezone(SHANGHAI).isoformat()
            except (ValueError, TypeError, AttributeError):
                raise ValueError('vip_feedback_fields') from None
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM vip_events WHERE request_id=?', (request_id,)).fetchone()
            if prior:
                if prior['actor'] != actor:
                    raise PermissionError('vip_owner_required')
                if prior['case_id'] != case_id or json.loads(prior['payload']) != payload:
                    raise ValueError('vip_feedback_conflict')
                return dict(json.loads(prior['receipt']), reused=True)
            if db.execute('SELECT 1 FROM requests WHERE request_id=?', (request_id,)).fetchone():
                raise ValueError('vip_feedback_conflict')
            case = db.execute('SELECT * FROM vip_cases WHERE id=?', (case_id,)).fetchone()
            if case is None:
                raise LookupError('vip_case_not_found')
            if case['owner'] not in (None, actor) or case['owner'] is None and event != 'claim':
                raise PermissionError('vip_owner_required')
            events = events_for(db, case_id)
            preferred = db.execute('SELECT * FROM vip_preferred_cases WHERE id=?', (case_id,)).fetchone()
            has_uk = db.execute('SELECT 1 FROM vip_week_cases WHERE case_id=?', (case_id,)).fetchone()
            if scope == PREFERRED and not preferred:
                raise LookupError('vip_case_not_found')
            if any(item['event'] == 'close' for item in events):
                raise ValueError('vip_case_closed')
            if event == 'claim':
                ready_only = bool(preferred and (scope == PREFERRED or not has_uk))
                if ready_only:
                    view = case_view(dict(preferred, owner=case['owner']), events, preferred['week'], actor)
                else:
                    view = {'owner':case['owner'], 'status':'queued'}
                reason = claim_blocker(view, actor, PREFERRED if ready_only else scope, ready_only=ready_only)
                if reason:
                    raise ValueError('vip_already_assigned' if reason == 'already_claimed' else 'vip_not_due')
            if contacted_at and not local(case['opened_at']) <= contacted_at <= now:
                raise ValueError('vip_feedback_fields')
            return record_event(db, request_id, case_id, actor, payload, now.isoformat())

    def refresh(self, week=None):
        now = self.clock().astimezone(SHANGHAI)
        current = week_for(now.date())
        week = checked_week(week) if week is not None else current
        if week != current:
            raise ValueError('vip_refresh_current_week')
        results = {scope: self._run_scope(scope, week.isoformat(), now) for scope in SCOPE_TABLES}
        self._publish_weekly(current)
        return dict(results[UK_US], scope_status={scope: value['status'] for scope, value in results.items()})

    def _run_scope(self, scope, week, now):
        _, _, _, refresh = SCOPE_TABLES[scope]
        stamp = now.isoformat()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute(f'SELECT * FROM {refresh} WHERE id=1').fetchone()
            reused = bool(prior and (prior['status'] == 'ready' and local(prior['updated_at']).date() == now.date()
                                    or now - local(prior['attempted_at']) < RETRY_DELAY))
            if reused:
                return dict(status=prior['status'], week=week, reused=True)
            db.execute(f"INSERT OR REPLACE INTO {refresh} VALUES(1,?,'pending',NULL)", (stamp,))
        try:
            if self.source is None:
                import vip_followup
                self.source = vip_followup
            status = self._refresh(week, now, scope)
        except Exception as error:
            logging.getLogger(__name__).error('VIP %s refresh failed: %s', scope, type(error).__name__)
            status = 'failed'
        with self.store.db() as db:
            db.execute(f'UPDATE {refresh} SET status=?,updated_at=? WHERE attempted_at=?', (status, stamp, stamp))
        return dict(status=status, week=week, reused=False)

    def _publish_weekly(self, current):
        if self.report_root is None:
            return
        with self.store.db() as db:
            latest = tuple(db.execute(f'SELECT updated_at FROM {tables[3]} WHERE id=1').fetchone()['updated_at']
                           for tables in SCOPE_TABLES.values())
            event_revision = db.execute('SELECT max(rowid) FROM vip_events').fetchone()[0]
        revision = (current, latest, event_revision)
        if revision == self.report_revision:
            return
        for week in (current - OBSERVATION, current):
            cutoff = start_of(week + OBSERVATION)
            week_text = week.isoformat()
            value = self.weekly_summary(week_text, cutoff)
            value['scopes'] = {UK_US: dict(value), PREFERRED: self.weekly_summary(week_text, cutoff, PREFERRED)}
            value['scope_overlap'] = '同一客户可能同时属于两个范围，人数和金额按范围分别展示。'
            write_weekly_report(self.report_root, week, value)
        self.report_revision = revision

    def _refresh(self, week, now, scope):
        weeks, _, cases_table, _ = SCOPE_TABLES[scope]
        with self.store.db() as db:
            frozen = db.execute(f'SELECT frozen_at FROM {weeks} WHERE week=?', (week,)).fetchone()
            cases = scoped_rows(db, scope)
        if not frozen or not frozen['frozen_at']:
            reader = self.source.read_preferred_cohort if scope == PREFERRED else self.source.read_cohort
            cohort = reader(anchor=checked_week(week), now=now)
            self._freeze(week, now, cohort, scope)
            with self.store.db() as db:
                cases = scoped_rows(db, scope)
        # Previously closed cases remain eligible for refund corrections within the source window.
        source_start = now - timedelta(days=365)
        active = [row for row in cases if local(row['opened_at']) >= source_start]
        if not active:
            with self.store.db() as db:
                frozen = db.execute(f'SELECT frozen_at FROM {weeks} WHERE week=?', (week,)).fetchone()
            return 'ready' if frozen and frozen['frozen_at'] else 'partial'
        buyers_by_id, cutoffs, recheck_orders = {}, [], {}
        with self.store.db() as db:
            for case in active:
                buyer = json.loads(case['observation'] or case['baseline'])
                opened = local(case['opened_at'])
                continuity = local(buyer['paymentCoverage'].get('through'))
                cutoffs.append(max(opened, continuity) if continuity else opened)
                events = events_for(db, case['id'])
                contact = min((local(event['contacted_at']) for event in events if event['event'] == 'contacted'), default=None)
                closed = next((local(event['at']) for event in events if event['event'] == 'close'), None)
                endpoint = contact + OBSERVATION if contact else closed or now
                last_order = (buyer.get('lastOrder') or {}).get('orderNo') if case['observed_at'] else None
                for order in buyer['history']:
                    at = local(order['paidAtShanghai'])
                    if at >= source_start and (opened <= at < endpoint or not closed and order['orderNo'] == last_order):
                        recheck_orders[order['orderNo']] = order
                previous = buyers_by_id.get(buyer['buyerId'])
                if previous:
                    orders = {order['orderNo']: order for order in previous['history'] + buyer['history']}
                    buyer = dict(buyer, history=list(orders.values()))
                buyers_by_id[buyer['buyerId']] = buyer
        since = max(source_start, min(cutoffs))
        refreshed = self.source.refresh_buyers(
            list(buyers_by_id.values()), since=since, now=now,
            recheck_orders=[order for order in recheck_orders.values() if local(order['paidAtShanghai']) < since])
        by_buyer = {buyer['buyerId']: buyer for buyer in refreshed['buyers']}
        source_as_of = local(refreshed['asOfShanghai'])
        if source_as_of is None or source_as_of > now:
            raise ValueError('vip_observation_time')
        complete = refreshed['coverage']['complete'] is True and by_buyer.keys() == buyers_by_id.keys()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for case in active:
                base = json.loads(case['observation'] or case['baseline'])
                buyer = by_buyer.get(base['buyerId'])
                if buyer is None or buyer['siteId'] != base['siteId']:
                    buyer = dict(base, paymentCoverage=dict(base['paymentCoverage'], complete=False, observedThrough=None))
                    complete = False
                observed = local(buyer['paymentCoverage'].get('observedThrough'))
                if observed and observed > source_as_of:
                    raise ValueError('vip_observation_time')
                db.execute(f'UPDATE {cases_table} SET observation=?,observed_at=? WHERE id=?',
                           (encoded(buyer), observed.isoformat() if observed else case['observed_at'], case['id']))
            frozen = db.execute(f'SELECT frozen_at FROM {weeks} WHERE week=?', (week,)).fetchone()
            return 'ready' if complete and frozen and frozen['frozen_at'] else 'partial'

    def _freeze(self, week, now, cohort, scope):
        weeks, memberships, _, _ = SCOPE_TABLES[scope]
        other_scope = PREFERRED if scope == UK_US else UK_US
        coverage = cohort['coverage']
        frozen = coverage.get('datesComplete', coverage['complete']) is True
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute(f'SELECT frozen_at FROM {weeks} WHERE week=?', (week,)).fetchone()
            if existing and existing['frozen_at']:
                return
            db.execute(f'INSERT OR REPLACE INTO {weeks} VALUES(?,?,?)',
                       (week, now.isoformat() if frozen else None, encoded(coverage)))
            previous, other = [], []
            other_current = {row['id'] for row in scoped_rows(db, other_scope, week)}
            for target_scope, rows in ((scope, previous), (other_scope, other)):
                for case in scoped_rows(db, target_scope):
                    buyer = json.loads(case['observation'] or case['baseline'])
                    view = case_view(case, events_for(db, case['id']), week)
                    active = view['status'] not in {'closed', 'returned'} and view['outcome']['kind'] not in {'natural', 'post_contact'}
                    rows.append((case, buyer, view, active))
                    if target_scope == scope and active and (scope == UK_US or view['owner']):
                        db.execute(f'INSERT OR IGNORE INTO {memberships}(week,case_id) VALUES(?,?)', (week, case['id']))
            if not frozen:
                return
            opened = start_of(checked_week(week))
            for buyer in cohort['buyers']:
                last_order = buyer.get('lastOrder') or {}
                last_paid = local(last_order.get('paidAtShanghai'))
                if (scope == UK_US and last_paid and (opened.date() - last_paid.date()).days < 9
                        and buyer.get('followUpStatus') == 'recent'
                        and last_order.get('afterSales') not in {'problem', 'fraud', 'dispute', 'after_sales'}
                        and last_order.get('refundStatus') in {'none_observed', 'partial_observed'}):
                    continue
                matching = [entry for entry in previous if same_buyer(buyer, entry[1])]
                cross_scope = [entry for entry in other if same_buyer(buyer, entry[1])]
                if any(view['reason'] == 'no_contact' and view['status'] == 'closed'
                       for _, _, view, _ in matching + cross_scope):
                    continue
                same_cycle = next((case for case, _, _, active in reversed(matching)
                                   if active or (json.loads(case['baseline']).get('lastOrder') or {}).get('orderNo') == last_order.get('orderNo')), None)
                if same_cycle:
                    if scope == PREFERRED:
                        db.execute(f'INSERT OR REPLACE INTO {memberships}(week,case_id,baseline) VALUES(?,?,?)',
                                   (week, same_cycle['id'], encoded(buyer)))
                    continue
                shared = next((case for case, prior_buyer, _, active in reversed(cross_scope)
                               if active or case['id'] in other_current
                               or (prior_buyer.get('lastOrder') or {}).get('orderNo') == last_order.get('orderNo')), None)
                prior = matching or cross_scope
                if prior:
                    identity = prior[-1][1]
                    buyer = dict(buyer, buyerId=identity['buyerId'], identity={
                        key: sorted(set(buyer['identity'][key]) | set(identity['identity'][key]))
                        for key in buyer['identity']})
                ident = shared['id'] if shared else uuid.uuid4().hex
                if shared is None:
                    db.execute('INSERT INTO vip_cases VALUES(?,?,?,?,NULL,NULL,NULL)',
                               (ident, week, opened.isoformat(), encoded(buyer)))
                if scope == PREFERRED:
                    db.execute('INSERT INTO vip_preferred_cases VALUES(?,?,?,?,NULL,NULL)',
                               (ident, week, opened.isoformat(), encoded(buyer)))
                if scope == UK_US and shared:
                    db.execute('UPDATE vip_cases SET week=?,opened_at=?,baseline=?,observation=NULL,observed_at=NULL WHERE id=?',
                               (week, min(local(shared['opened_at']), opened).isoformat(), encoded(buyer), ident))
                if scope == PREFERRED:
                    db.execute(f'INSERT INTO {memberships}(week,case_id,baseline) VALUES(?,?,?)', (week, ident, encoded(buyer)))
                else:
                    db.execute(f'INSERT INTO {memberships}(week,case_id) VALUES(?,?)', (week, ident))
