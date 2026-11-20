"""Private, weekly FC27 VIP maintenance and verified payment outcomes."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median
import json
import os
import re
import sqlite3
import tempfile
import uuid

from customer_tracking import ID, SHANGHAI, payment_moment


TRACKING_DB = Path('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db')
REPORT_ROOT = Path('/var/lib/fs-hermes-fc/native')
EVENTS = {'claim', 'contacted', 'feedback', 'close'}
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


def returned_orders(buyer, opened, through):
    result, unresolved = [], False
    for order in buyer['history']:
        paid_at = local(order.get('paidAtShanghai'))
        if not paid_at or not opened <= paid_at < through or order['siteId'] != buyer['siteId']:
            continue
        if refund_or_exception(order):
            unresolved |= (order.get('refundStatus') != 'full_observed'
                           or order.get('refundReadback', {}).get('status') in {'missing', 'unavailable'})
        elif str(order.get('payStatus')) == '1' or order.get('refundStatus') == 'partial_observed':
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
    outcome = outcome_for(case, buyer, events, cutoff)
    recent = buyer.get('lastOrder') or base.get('lastOrder') or {}
    effective = [order for order in buyer['history']
                 if not refund_or_exception(order)
                 and (str(order.get('payStatus')) == '1' or order.get('refundStatus') == 'partial_observed')]
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
                  and recent.get('refundStatus') not in {'marked_amount_unknown', 'unknown'})
    purchase_days = sorted({local(order['paidAtShanghai']).date() for order in effective})
    gaps = [(right - left).days for left, right in zip(purchase_days, purchase_days[1:])]
    cadence = median(gaps) if gaps else None
    windows = base['windows']
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
    reason = '。'.join(evidence) + '。' + ask
    return dict(case_id=case['id'], week=case['week'], site_id=buyer['siteId'], email=buyer.get('email'),
                uid=buyer.get('uid'), country=buyer.get('country'),
                last_paid_at=last_paid.isoformat() if last_paid else None,
                days_since_last_paid=days_since_paid,
                first_review_day=(last_paid.date() + timedelta(days=15)).isoformat() if last_paid else None,
                owner=owner, status=status, can_update=bool(actor and not closed and owner in (None, actor)),
                carried_over=case['week'] != week, windows=windows,
                guidance={'priority': priority, 'reason': reason, 'purchase_days': len(purchase_days),
                          'median_gap_days': cadence}, events=events, outcome=outcome, **updates)


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
                natural_usd=amount(natural), post_contact_usd=amount(after))


def queue_view(db, week, actor=None, cutoff=None):
    frozen = db.execute('SELECT frozen_at,coverage FROM vip_weeks WHERE week=?', (week,)).fetchone()
    coverage = json.loads(frozen['coverage']) if frozen else None
    records = db.execute('''SELECT c.* FROM vip_cases c JOIN vip_week_cases w ON c.id=w.case_id
                            WHERE w.week=? ORDER BY c.opened_at,c.id''', (week,))
    items = [case_view(row, events_for(db, row['id'], cutoff), week, actor, cutoff) for row in records]
    order = {'after_sales': 0, 'due': 1, 'review': 2}
    def rank(item):
        windows, guidance = item['windows'], item['guidance']
        gap = (item['days_since_last_paid'] or 0) - (guidance['median_gap_days'] or 14)
        decline = Decimal(windows['firstHalf']['salesUsd']) - Decimal(windows['secondHalf']['salesUsd'])
        return (item['status'] in {'closed', 'returned'}, order[guidance['priority']],
                -gap, -decline, -Decimal(windows['month']['salesUsd']), -guidance['purchase_days'])

    items.sort(key=rank)
    return dict(week=week, frozen_at=frozen['frozen_at'] if frozen else None, coverage=coverage,
                status='ready' if frozen and frozen['frozen_at'] and coverage['complete'] is True
                else 'partial' if frozen else 'pending',
                items=items, summary=summarize(items) if frozen and frozen['frozen_at'] else None)


def vip_weekly_report(path, week, cutoff):
    """Read the frozen report cohort without touching customer history or contacting its source."""
    connection = None
    try:
        connection = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN')
        view = queue_view(connection, checked_week(week).isoformat(), cutoff=cutoff)
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

    def queue(self, week=None, *, actor=None):
        if week is None:
            week = week_for(self.clock().astimezone(SHANGHAI).date())
        with self.store.db() as db:
            db.execute('BEGIN')
            return queue_view(db, checked_week(week).isoformat(), actor)

    def weekly_summary(self, week, cutoff):
        return vip_weekly_report(self.store.path, week, cutoff)

    def lookup_receipt(self, actor, request_id):
        if not isinstance(request_id, str) or not ID.fullmatch(request_id):
            raise ValueError('vip_feedback_fields')
        with self.store.db() as db:
            record = db.execute('SELECT actor,receipt FROM vip_events WHERE request_id=?', (request_id,)).fetchone()
        if record is None:
            return None
        if record['actor'] != actor:
            raise PermissionError('vip_owner_required')
        return dict(status='available', action='vip_feedback', result=json.loads(record['receipt']))

    def feedback(self, actor, body):
        now = self.clock().astimezone(SHANGHAI)
        if not isinstance(actor, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', actor):
            raise PermissionError('vip_owner_required')
        common = {'case_id', 'request_id', 'event'}
        fields = {'claim': set(), 'contacted': {'contacted_at', 'reason', 'notes', 'next_review_day'},
                  'feedback': {'reason', 'notes', 'next_review_day'}, 'close': {'reason', 'notes'}}
        if (type(body) is not dict or not common <= set(body) or not isinstance(body['event'], str)
                or body['event'] not in EVENTS or set(body) - common - fields[body['event']]
                or not all(isinstance(body[key], str) and ID.fullmatch(body[key]) for key in ('case_id', 'request_id'))):
            raise ValueError('vip_feedback_fields')
        event, case_id, request_id = body['event'], body['case_id'], body['request_id']
        if event == 'feedback' and set(body) == common:
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
            if any(item['event'] == 'close' for item in events):
                raise ValueError('vip_case_closed')
            if event == 'claim' and case['owner'] is not None:
                raise ValueError('vip_already_assigned')
            if contacted_at and not local(case['opened_at']) <= contacted_at <= now:
                raise ValueError('vip_feedback_fields')
            if event == 'claim':
                db.execute('UPDATE vip_cases SET owner=? WHERE id=?', (actor, case_id))
            receipt = dict(status='recorded', case_id=case_id, event=event, owner=actor,
                           request_id=request_id, recorded_at=now.isoformat(), reused=False)
            db.execute('INSERT INTO vip_events VALUES(?,?,?,?,?,?)',
                       (request_id, case_id, actor, encoded(payload), now.isoformat(), encoded(receipt)))
            return receipt

    def refresh(self, week=None):
        now = self.clock().astimezone(SHANGHAI)
        current = week_for(now.date())
        week = checked_week(week) if week is not None else current
        if week != current:
            raise ValueError('vip_refresh_current_week')
        week = week.isoformat()
        stamp = now.isoformat()
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT * FROM vip_refresh WHERE id=1').fetchone()
            reused = bool(prior and (prior['status'] == 'ready' and local(prior['updated_at']).date() == now.date()
                                    or now - local(prior['attempted_at']) < RETRY_DELAY))
            if not reused:
                db.execute("INSERT OR REPLACE INTO vip_refresh VALUES(1,?,'pending',NULL)", (stamp,))
        if not reused:
            try:
                if self.source is None:
                    import vip_followup
                    self.source = vip_followup
                status = self._refresh(week, now)
            except Exception:
                with self.store.db() as db:
                    db.execute("UPDATE vip_refresh SET status='failed' WHERE attempted_at=?", (stamp,))
                raise
            with self.store.db() as db:
                db.execute('UPDATE vip_refresh SET status=?,updated_at=? WHERE attempted_at=?', (status, stamp, stamp))
        else:
            status = prior['status']
        self._publish_weekly(current)
        return dict(status=status, week=week, reused=reused)

    def _publish_weekly(self, current):
        if self.report_root is None:
            return
        with self.store.db() as db:
            latest = db.execute('SELECT updated_at FROM vip_refresh WHERE id=1').fetchone()
            event_revision = db.execute('SELECT max(rowid) FROM vip_events').fetchone()[0]
        revision = (current, latest['updated_at'], event_revision)
        if revision == self.report_revision:
            return
        for week in (current - OBSERVATION, current):
            cutoff = start_of(week + OBSERVATION)
            value = self.weekly_summary(week.isoformat(), cutoff)
            write_weekly_report(self.report_root, week, value)
        self.report_revision = revision

    def _refresh(self, week, now):
        with self.store.db() as db:
            frozen = db.execute('SELECT frozen_at FROM vip_weeks WHERE week=?', (week,)).fetchone()
            cases = db.execute('SELECT * FROM vip_cases ORDER BY opened_at,id').fetchall()
        if not frozen or not frozen['frozen_at']:
            cohort = self.source.read_cohort(anchor=checked_week(week), now=now)
            self._freeze(week, now, cohort, cases)
            with self.store.db() as db:
                known = {row['id'] for row in cases}
                cases += [row for row in db.execute('SELECT * FROM vip_cases WHERE week=?', (week,)) if row['id'] not in known]
        # Previously closed cases remain eligible for refund corrections within the source window.
        source_start = now - timedelta(days=365)
        active = [row for row in cases if local(row['opened_at']) >= source_start]
        if not active:
            with self.store.db() as db:
                frozen = db.execute('SELECT frozen_at FROM vip_weeks WHERE week=?', (week,)).fetchone()
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
                db.execute('UPDATE vip_cases SET observation=?,observed_at=? WHERE id=?',
                           (encoded(buyer), observed.isoformat() if observed else case['observed_at'], case['id']))
            frozen = db.execute('SELECT frozen_at FROM vip_weeks WHERE week=?', (week,)).fetchone()
            return 'ready' if complete and frozen and frozen['frozen_at'] else 'partial'

    def _freeze(self, week, now, cohort, active):
        coverage = cohort['coverage']
        frozen = coverage.get('datesComplete', coverage['complete']) is True
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT frozen_at FROM vip_weeks WHERE week=?', (week,)).fetchone()
            if existing and existing['frozen_at']:
                return
            db.execute('INSERT OR REPLACE INTO vip_weeks VALUES(?,?,?)',
                       (week, now.isoformat() if frozen else None, encoded(coverage)))
            previous = []
            for case in active:
                buyer = json.loads(case['observation'] or case['baseline'])
                current = case_view(case, events_for(db, case['id']), week)
                previous.append((case, buyer, current))
                if current['status'] not in {'closed', 'returned'} and current['outcome']['kind'] not in {'natural', 'post_contact'}:
                    db.execute('INSERT OR IGNORE INTO vip_week_cases VALUES(?,?)', (week, case['id']))
            if not frozen:
                return
            opened = start_of(checked_week(week))
            for buyer in cohort['buyers']:
                last_order = buyer.get('lastOrder') or {}
                last_paid = local(last_order.get('paidAtShanghai'))
                if (last_paid and (opened.date() - last_paid.date()).days < 9
                        and buyer.get('followUpStatus') == 'recent'
                        and last_order.get('afterSales') not in {'problem', 'fraud', 'dispute', 'after_sales'}
                        and last_order.get('refundStatus') in {'none_observed', 'partial_observed'}):
                    continue
                matching = [record for record in previous if same_buyer(buyer, record[1])]
                if any(current['reason'] == 'no_contact' and current['status'] == 'closed'
                       or current['status'] not in {'closed', 'returned'} and current['outcome']['kind'] not in {'natural', 'post_contact'}
                       or (json.loads(case['baseline']).get('lastOrder') or {}).get('orderNo') == last_order.get('orderNo')
                       for case, _, current in matching):
                    continue
                if matching:
                    prior = matching[-1][1]
                    buyer = dict(buyer, buyerId=prior['buyerId'], identity={
                        key: sorted(set(buyer['identity'][key]) | set(prior['identity'][key]))
                        for key in buyer['identity']})
                ident = uuid.uuid4().hex
                db.execute('INSERT INTO vip_cases VALUES(?,?,?,?,NULL,NULL,NULL)',
                           (ident, week, opened.isoformat(), encoded(buyer)))
                db.execute('INSERT INTO vip_week_cases VALUES(?,?)', (week, ident))
