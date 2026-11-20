"""Read-only FC27 VIP cohort and subsequent exact same-site payment evidence."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re
import sqlite3
from types import SimpleNamespace

from customer_tracking import EMAIL, SHANGHAI, payment_moment
from user_contract import money, stamp

SITE, GAME = '266', '1327'
COUNTRIES = ('GB', 'US')
DAY = timedelta(days=1)
THRESHOLD = Decimal('300.00')
SCHEMA = 'fs-fc27-vip-followup-v1'
IDENTITY_FIELDS = ('customerIds', 'uids', 'emails', 'esBuyerIds')


def midnight(day):
    return datetime.combine(day, time.min, SHANGHAI)


def day_range(start, end):
    return [start + i * DAY for i in range((end - start).days)]


def uid(value):
    value = str(value or '')
    return value if re.fullmatch(r'[1-9][0-9]{0,31}', value) else None


def email(value):
    value = value.strip().casefold() if isinstance(value, str) else ''
    return value if len(value) <= 254 and '*' not in value and EMAIL.fullmatch(value) else None


def clock(value):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('vip_clock')
    return value.astimezone(SHANGHAI)


def exact_evidence(native, archived):
    return bool(archived and payment_moment(archived.get('paytime')) == stamp(native['paytime'])
                and (archived.get('id') is None or str(archived['id']) == str(native.get('id'))))


def snapshot_evidence(result):
    by_order, buyers = {}, defaultdict(set)
    duplicates = {r['order_no'] for r in (result['identity_catalog'] or {}).get('rows', ())
                  if str(r['site_id']) != SITE}
    for row in result['rows']:
        number = row['order_no']
        digest = sha256(number.encode()).hexdigest()
        if digest in by_order or str(row['site_id']) != SITE or str(row['gid']) != GAME:
            raise ValueError('vip_es_scope')
        by_order[digest] = row
    for row in (result['dataset'] or {}).get('rows', ()):
        digest = row.get('订单号')
        archived = by_order.get(digest)
        buyer = str(row.get('buyer_id') or '')
        if (archived and archived['order_no'] not in duplicates and buyer not in ('', '0')
                and ''.join(str(row.get('游戏') or '').split()).upper() == 'FC27'
                and payment_moment(str(row.get('付款时间') or '').replace('/', '-')) ==
                    payment_moment(archived.get('paytime'))):
            buyers[digest].add(buyer)
    return {row['order_no']: (row, buyers[digest]) for digest, row in by_order.items()}


def archive_orders(start, end, _as_of):
    from shared_es_facts import DB, read

    scope = dict(site_id=SITE, gid=GAME, start=start.isoformat(), end=(end - DAY).isoformat())
    snapshot = read(scope, db=DB)
    evidence = snapshot_evidence(snapshot)
    rows, coverage = native_archive_orders(start, end, midnight(end), evidence=evidence)
    return rows, dict(coverage, esPublication=snapshot['coverage'].get('publication_id'),
                      esCoverage=snapshot['coverage'])


def native_archive_orders(start, end, stop, *, evidence=None, wanted=None):
    from shared_es_facts import DB, _read_db

    evidence = evidence or {}
    receipts, rows = {}, []
    paid_count = 0
    days = day_range(start, end)
    begin, end_time = midnight(start).isoformat(), midnight(end).isoformat()
    with closing(_read_db(DB)) as db:
        db.execute('BEGIN')
        revision = db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0]
        for first, last, job_revision, blob in db.execute(
                """SELECT start,end,revision,body FROM jobs WHERE site=? AND state='complete'
                   AND end>? AND start<? ORDER BY revision""", (SITE, begin, end_time)):
            job = json.loads(blob)
            observed = stamp(job['captured_at'])
            if job.get('correction_coverage') != 'complete_reenumeration_of_payment_window_only':
                continue
            opened, closed = stamp(first), min(stamp(last), observed)
            for day in days:
                if opened <= midnight(day) and midnight(day + DAY) <= closed:
                    receipts[day.isoformat()] = dict(revision=job_revision, observedAt=observed.isoformat())
        for key, customer, paid, body in db.execute(
                """SELECT order_key,customer_id,paid_at,body FROM orders
                   WHERE site=? AND gid=? AND paid_at>=? AND paid_at<?""", (SITE, GAME, begin, stop.isoformat())):
            raw = json.loads(body)
            if str(raw.get('pay_status')) not in ('1', '2') or raw.get('test_order'):
                continue
            paid_count += 1
            if wanted is not None:
                tokens = {('customerIds', customer), ('uids', uid(raw.get('uid'))), ('emails', email(raw.get('email')))}
                if any(value for _, value in tokens) and not (tokens & wanted):
                    continue
            number = raw.get('order_no')
            if not isinstance(number, str) or not number or key != f'admin:{SITE}:{number}':
                raise ValueError('vip_archived_order_scope')
            raw['paytime'] = paid
            archived, es_buyers = evidence.get(number, (None, set()))
            if not exact_evidence(raw, archived):
                archived, es_buyers = None, set()
            native_es = raw.get('es_identity') or {}
            if native_es.get('status') == 'verified' and native_es.get('buyer_id') and es_buyers:
                es_buyers = es_buyers | {native_es.get('buyer_id')}
            rows.append(project_order(raw, archived=archived, customer=customer, es_buyers=es_buyers))
    missing = sorted({d.isoformat() for d in days} - receipts.keys())
    return rows, dict(nativeRevision=revision, nativeMissingDays=missing, nativeReceipts=receipts,
                      nativePaidOrders=paid_count, nativeSelectedOrders=len(rows))


def project_order(raw, *, archived=None, customer=None, es_buyers=()):
    native = archived if archived is not None else raw
    paid = stamp(raw['paytime']).isoformat()
    state = raw.get('status_format')
    pay = str(raw['pay_status'])
    country = str(native.get('country_code') or '')
    country = country if re.fullmatch('[A-Z]{2}', country) else None
    refund = 'unknown' if not state else 'none_observed'
    if '部分退款' in (state or ''):
        refund = 'partial_observed'
    elif any(label in (state or '') for label in ('全额退款', '全部退款')):
        refund = 'full_observed'
    elif pay == '2' or '已退款' in (state or ''):
        refund = 'marked_amount_unknown'
    after_sales = 'unknown' if not state else next(
        (label for needle, label in (('欺诈', 'fraud'), ('争议', 'dispute'), ('申诉', 'dispute'),
         ('问题订单', 'problem'), ('售后', 'after_sales')) if needle in state), 'none_observed')
    source_amount = money(raw.get('amount_usd', raw.get('amount_usd_format')))
    amount = source_amount if source_amount is not None and Decimal(source_amount) >= 0 else None
    coupons = (native.get('tracking') or {}).get('coupons')
    coins = native.get('fc27_coins') or {}
    native_uid, native_email = uid(raw.get('uid')), email(raw.get('email'))
    return dict(siteId=SITE, orderNo=raw['order_no'], adminOrderId=str(raw['id']), paidAtShanghai=paid,
                country=country, amountUsd=amount, payStatus=pay, orderState=state,
                observedRefund=refund not in ('unknown', 'none_observed'), refundStatus=refund,
                sourceRefundAmount=money(raw.get('source_refund_amount', raw.get('return_money'))),
                sourceCurrency=raw.get('currency_code'), knownSettledRefundUsd=None, afterSales=after_sales,
                benefits=dict(discountCode=native.get('discount_code'),
                              coupons=[{k: c.get(k) for k in ('id','templateId','title','batch','usedAt','status')}
                                       for c in coupons] if coupons is not None else None,
                              points=money(coins.get('points', raw.get('points')))),
                platform=coins.get('platform'), purchaseK=coins.get('purchase_k'),
                source='Admin order archive + pinned ES exact order' if archived is not None else
                       'Admin order archive' if 'amount_usd' in raw else 'Admin exact site and game payment scan',
                identity=dict(customerIds=[customer] if customer else [],
                              uids=[native_uid] if native_uid else [],
                              emails=[native_email] if native_email else [],
                              esBuyerIds=list(es_buyers) if len(es_buyers) == 1 else []),
                identityConflict=len(es_buyers) > 1)


def grouped_orders(rows):
    """ES links incomplete Admin identities. It cannot resolve conflicting Admin groups."""
    parents = list(range(len(rows)))
    group_uids = [set(row['identity']['uids']) for row in rows]

    def root(i):
        while i != parents[i]:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    def matches(field):
        result = defaultdict(list)
        for i, row in enumerate(rows):
            for value in row['identity'][field]:
                result[value].append(i)
        return result

    def join(indices, primary=None):
        heads = {root(i) for i in indices}
        if primary is None:
            primary = min(heads)
        for head in heads:
            group_uids[primary].update(group_uids[head])
            parents[head] = primary

    def mark_conflict(indices, field, value):
        for i in indices:
            row = rows[i]
            row['identityConflict'] = True
            row['scopedIdentityConflict'] = True
            if row['identity']['uids']:
                row['identity'][field].remove(value)
            else:
                row['identity'] = {name: [] for name in IDENTITY_FIELDS}

    # A native customer ID is email-derived; distinct positive UIDs take precedence
    # over a shared customer ID or a shared address.
    for field in ('uids', 'customerIds', 'emails'):
        for value, indices in matches(field).items():
            observed_uids = set().union(*(group_uids[root(i)] for i in indices))
            if len(observed_uids) > 1:
                mark_conflict(indices, field, value)
            else:
                join(indices)

    confirmed = {root(i) for i, row in enumerate(rows) if any(row['identity'][f] for f in IDENTITY_FIELDS[:-1])}
    for value, indices in matches('esBuyerIds').items():
        native_roots = {root(i) for i in indices} & confirmed
        if len(native_roots) > 1:
            for i in indices:
                rows[i]['identityConflict'] = True
                rows[i]['identity']['esBuyerIds'].remove(value)
        else:
            join(indices, next(iter(native_roots), None))
    groups = defaultdict(list)
    for i, row in enumerate(rows):
        if any(row['identity'].values()):
            groups[root(i)].append(row)
    return list(groups.values())


def order_key(row):
    return row['paidAtShanghai'], int(row['adminOrderId'])


def window_summary(orders):
    amounts = [Decimal(r['amountUsd']) for r in orders if r['amountUsd'] is not None]
    paid = sum(amounts, Decimal('0.00'))
    marked = [r for r in orders if r['observedRefund']]
    marked_amount = sum((Decimal(r['amountUsd']) for r in marked if r['amountUsd'] is not None), Decimal('0.00'))
    return dict(orders=len(orders), salesUsd=format(paid, '.2f'), qualified=paid >= THRESHOLD,
                ordersWithoutUsd=len(orders) - len(amounts), refundMarkedOrders=len(marked),
                refundMarkedOriginalPaidUsd=format(marked_amount, '.2f'), knownSettledRefundUsd=None)


def observed_buyer(buyer, history, now, complete, *, through=None, observed_through=None):
    history = sorted(history, key=order_key)
    last = history[-1] if history else buyer.get('lastOrder')
    elapsed = (now.date() - stamp(last['paidAtShanghai']).date()).days if last else None
    status = 'recent' if elapsed is not None and elapsed <= 14 else 'due' if complete and last else 'unknown'
    return dict(buyer, history=history, lastOrder=last, daysSinceLastPaid=elapsed,
                followUpStatus=status, paymentCoverage=dict(
                    complete=complete, through=through, observedThrough=observed_through))


def read_cohort(*, anchor, now, archive_reader=None):
    """Freeze the latest 30 full Shanghai days as two consecutive 15-day windows."""
    now = clock(now)
    if not isinstance(anchor, date) or isinstance(anchor, datetime) or anchor.weekday() != 0 or anchor > now.date():
        raise ValueError('vip_cohort_anchor')
    return read_population(anchor - 30 * DAY, anchor, now, archive_reader)


def read_period(*, start, end, now, archive_reader=None, activity_reader=None):
    """Read a closed inclusive Shanghai payment period and recency as of the specified instant."""
    now = clock(now)
    if (not isinstance(start, date) or isinstance(start, datetime)
            or not isinstance(end, date) or isinstance(end, datetime) or not start <= end < now.date()
            or (end - start).days >= 365 or (now.date() - end).days > 365):
        raise ValueError('vip_period_dates')
    result = read_population(start, end + DAY, now, archive_reader)
    result['orderStateBasis'] = 'current source evidence for payments through asOfShanghai'
    if result['status'] == 'unavailable':
        return result
    refreshed = (activity_reader or refresh_period)(result['buyers'], since=midnight(end + DAY), now=now)
    result['buyers'] = refreshed['buyers']
    result['coverage']['paymentRefresh'] = refreshed['coverage']
    result['coverage']['complete'] &= refreshed['coverage']['complete']
    if not result['coverage']['complete']:
        result['status'] = 'partial'
    result['summary']['followUpStatus'] = {
        status: sum(b['followUpStatus'] == status for b in result['buyers'])
        for status in ('due', 'recent', 'unknown')
    }
    return result


def refresh_period(buyers, *, since, now, archive_reader=None, live_reader=None):
    """Observe closure-day traffic from the native archive and fetch only the actual open day."""
    today = midnight(datetime.now(SHANGHAI).date())
    now = now.replace(microsecond=0)
    archived_until = min(today, now + timedelta(seconds=1))
    end_day = min(today.date(), now.date() + DAY)
    archived, coverage = [], {}
    if buyers and since < archived_until:
        wanted = {(field, value) for buyer in buyers for field in IDENTITY_FIELDS[:-1]
                  for value in buyer['identity'][field]}
        try:
            archived, coverage = (archive_reader or native_archive_orders)(
                since.date(), end_day, archived_until, wanted=wanted)
        except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
            coverage = dict(nativeMissingDays=[day.isoformat() for day in day_range(since.date(), end_day)],
                            error=type(error).__name__)

    def activity(_, cutoff):
        yield from archived
        if cutoff >= today:
            yield from (live_reader or live_orders)(max(since, today), cutoff)

    result = refresh_buyers(buyers, since=since, now=now, live_reader=activity,
                            missing_days=coverage.get('nativeMissingDays', ()))
    result['coverage']['closedDayArchive'] = coverage
    return result


def read_population(start, anchor, now, archive_reader):
    duration = (anchor - start).days
    midpoint = start + ((duration + 1) // 2) * DAY
    ranges = dict(month=(start, anchor), firstHalf=(start, midpoint), secondHalf=(midpoint, anchor))
    result = dict(schema=SCHEMA, anchorDay=anchor.isoformat(), asOfShanghai=now.isoformat(),
                  splitMethod='closed Shanghai calendar days; the first half gets the extra odd day',
                  windows={name: dict(start=a.isoformat(), endExclusive=b.isoformat()) if a < b else None
                           for name, (a, b) in ranges.items()})
    try:
        rows, coverage = (archive_reader or archive_orders)(start, anchor, now)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError) as error:
        return dict(result, status='unavailable', buyers=[], summary=None,
                    coverage=dict(complete=False, datesComplete=False, error=type(error).__name__))
    counts = Counter()
    seen = set()
    for row in rows:
        ident = row['orderNo']
        if ident in seen or not start <= stamp(row['paidAtShanghai']).date() < anchor:
            raise ValueError('vip_cohort_row_scope')
        seen.add(ident)
    groups = grouped_orders(rows)
    latest_unidentified = ''
    for row in rows:
        counts['paidOrders'] += 1
        counts['unknownCountryOrders'] += row['country'] is None
        counts['unknownIdentityOrders'] += not any(row['identity'].values())
        counts['identityConflictOrders'] += row['identityConflict']
        counts['unknownQualifyingUsdOrders'] += row['country'] in COUNTRIES and row['amountUsd'] is None
        if not any(row['identity'].values()) and not row.get('scopedIdentityConflict'):
            latest_unidentified = max(latest_unidentified, row['paidAtShanghai'])
    dates_complete = not coverage['nativeMissingDays'] and coverage['esCoverage'].get('complete') is True
    complete = dates_complete and not any(counts[key] for key in (
        'unknownCountryOrders', 'unknownIdentityOrders', 'identityConflictOrders', 'unknownQualifyingUsdOrders'))
    buyers = []
    for history in groups:
        matching = [r for r in history if r['country'] in COUNTRIES]
        month = window_summary(matching)
        if not month['qualified']:
            continue
        aliases = {field: sorted({value for r in history for value in r['identity'][field]})
                   for field in IDENTITY_FIELDS}
        field = next(field for field in IDENTITY_FIELDS if aliases[field])
        buyer_id = 'vip_' + sha256(f'{SITE}:{field}:{aliases[field][0]}'.encode()).hexdigest()[:32]
        contact = next((r['identity']['emails'][0] for r in sorted(history, key=order_key, reverse=True)
                        if r['identity']['emails']), None)
        latest = max(history, key=order_key)
        buyer = dict(buyerId=buyer_id, siteId=SITE, identity=aliases, email=contact,
                     uid=latest['identity']['uids'][0] if latest['identity']['uids'] else
                         aliases['uids'][0] if len(aliases['uids']) == 1 else None,
                     country=max(matching, key=order_key)['country'], paymentCountries=sorted({r['country'] for r in matching}),
                     windows={name: window_summary([r for r in matching if a <= stamp(r['paidAtShanghai']).date() < b])
                              if a < b else None for name, (a, b) in ranges.items()})
        native_complete = (latest_unidentified < latest['paidAtShanghai']
                           and not any(r['identityConflict'] for r in history)
                           and not any(day >= latest['paidAtShanghai'][:10] for day in coverage['nativeMissingDays']))
        through = midnight(anchor).isoformat() if native_complete else None
        buyers.append(observed_buyer(buyer, history, now, False, through=through,
                                     observed_through=midnight(anchor).isoformat()))
    buyers.sort(key=lambda r: (-Decimal(r['windows']['month']['salesUsd']), r['buyerId']))
    coverage = dict(coverage, complete=complete, datesComplete=dates_complete, **counts)
    summary = dict(buyers=len(buyers), contactEmailAvailable=sum(r['email'] is not None for r in buyers),
                   qualifiedEachWindow={key: sum(r['windows'][key]['qualified'] for r in buyers)
                                        if result['windows'][key] else None for key in ranges})
    status = 'available' if complete else 'partial' if rows or dates_complete else 'unavailable'
    return dict(result, status=status, coverage=coverage, summary=summary, buyers=buyers)


def admin_session(expected_count=None):
    from summary_bridge import dc_request
    from urllib.parse import urlencode

    def get_admin(path, **params):
        status, body = dc_request(path + '?' + urlencode(params), method='GET')
        payload = json.loads(body)
        if expected_count is not None and (
                params.get('page') != 1 or int((payload.get('data') or {}).get('total', -1)) > expected_count):
            raise ValueError('vip_exact_order_filter_ignored')
        return status, payload

    return SimpleNamespace(get_admin=get_admin)


def admin_filters(begin, end):
    return [('site_id', '=', SITE), ('gid', '=', GAME),
            ('paytime', 'RANGE', begin.strftime('%Y-%m-%d %H:%M:%S') + ',' + end.strftime('%Y-%m-%d %H:%M:%S'))]


def live_orders(since, now):
    """Use the existing Admin read transport and bounded order pagination."""
    from channel_source import pages
    from user_runtime import configuration
    from user_source import PATH, windows

    verified_tests = configuration()['verified_test_rules']
    session = admin_session()
    seen = set()
    seen_ids = set()
    for begin, stop in windows(since.isoformat(), (now + timedelta(seconds=1)).isoformat()):
        filters = admin_filters(begin, stop - timedelta(seconds=1))
        batch = pages(session, PATH, filters, 1000)
        ids = [int(r['id']) for r in batch]
        if ids != sorted(ids, reverse=True):
            raise ValueError('vip_live_order_sort')
        for row in batch:
            number = row.get('order_no')
            if (str(row.get('site_id')) != SITE or str(row.get('gid')) != GAME
                    or not begin <= stamp(row['paytime']) < stop or number in seen
                    or not isinstance(number, str) or not number or int(row['id']) <= 0 or int(row['id']) in seen_ids
                    or str(row.get('pay_status')) not in ('0', '1', '2')):
                raise ValueError('vip_live_order_scope')
            seen.add(number)
            seen_ids.add(int(row['id']))
            test = verified_tests.get(number)
            if test and (str(test['gid']) != GAME or money(test['salesUsd']) != money(row.get('amount_usd_format'))):
                raise ValueError('vip_live_test_identity')
            if str(row['pay_status']) in ('1', '2') and not test:
                yield project_order(row)


def same_order(observed, expected):
    return all(observed[field] == expected[field] for field in ('siteId','orderNo','adminOrderId','paidAtShanghai'))


def recheck_existing_orders(orders, now):
    """Recheck known original Admin IDs in ranges of 28 calendar days or less."""
    from channel_source import pages
    from user_source import PATH

    groups = defaultdict(list)
    for order in orders:
        paid = stamp(order['paidAtShanghai'])
        groups[paid.date().toordinal() // 28].append(order)
    for group in groups.values():
        for offset in range(0, len(group), 100):
            chunk = group[offset:offset + 100]
            expected = {r['adminOrderId']: r for r in chunk}
            moments = [stamp(r['paidAtShanghai']) for r in chunk]
            filters = admin_filters(min(moments), min(max(moments), now)) + [('id', 'IN', ','.join(expected))]
            for row in pages(admin_session(len(expected)), PATH, filters, 1000):
                target = expected.get(str(row.get('id')))
                if (target is None or str(row.get('site_id')) != SITE or str(row.get('gid')) != GAME
                        or str(row.get('pay_status')) not in ('0','1','2')):
                    raise ValueError('vip_exact_order_scope')
                observed = project_order(row)
                if not same_order(observed, target):
                    raise ValueError('vip_exact_order_identity')
                if observed['payStatus'] == '0':
                    observed['refundStatus'] = 'unknown'
                yield observed


def refresh_buyers(buyers, *, since, now, live_reader=None, recheck_orders=(), recheck_reader=None, missing_days=()):
    """Reread the payment range, retaining frozen buyers even when identity or coverage is partial."""
    now = clock(now).replace(microsecond=0)
    since = clock(since).replace(microsecond=0)
    if since > now or now - since > 365 * DAY:
        raise ValueError('vip_refresh_window')
    identities = {field: defaultdict(set) for field in IDENTITY_FIELDS[:-1]}
    numbers, originals = defaultdict(set), {}
    known = {}
    for buyer in buyers:
        identifier = buyer['buyerId']
        if buyer['siteId'] != SITE or identifier in known:
            raise ValueError('vip_refresh_buyer_scope')
        known[identifier] = buyer
        for field, index in identities.items():
            for value in buyer['identity'][field]:
                index[value].add(identifier)
        for row in buyer['history']:
            numbers[row['orderNo']].add(identifier)
            originals[row['orderNo']] = row

    matched, conflicts = defaultdict(list), set()
    counts = Counter()
    failed = None
    rows = []
    try:
        if known:
            rows.extend((live_reader or live_orders)(since, now))
    except (OSError, ValueError, KeyError, TypeError) as error:
        failed = type(error).__name__
    counts['paidOrders'] = len(rows)
    requested = {}
    for row in recheck_orders:
        original = originals.get(row['orderNo'])
        if (original is None or not same_order(original, row) or uid(row['adminOrderId']) is None
                or not now - 365 * DAY <= stamp(row['paidAtShanghai']) <= now):
            raise ValueError('vip_recheck_identity')
        requested[row['orderNo']] = row
    exact = {row['orderNo'] for row in rows
             if row['orderNo'] in requested and same_order(row, requested[row['orderNo']])}
    remaining = [value for key, value in requested.items() if key not in exact]
    refund_error = None
    if remaining:
        try:
            rechecked = list((recheck_reader or recheck_existing_orders)(remaining, now))
            exact.update(row['orderNo'] for row in rechecked)
            rows.extend(rechecked)
        except (OSError, ValueError, KeyError, TypeError) as error:
            refund_error = type(error).__name__
    for row in rows:
        signals = [numbers[row['orderNo']]] + [
            identities[field][value] for field in identities for value in row['identity'][field]]
        candidates = set().union(*signals)
        if not candidates:
            counts['unidentifiedOrders'] += not any(row['identity'].values())
            continue
        if len(candidates) > 1:
            conflicts.update(candidates)
            counts['ambiguousOrders'] += 1
            exact.discard(row['orderNo'])
            continue
        buyer_id = next(iter(candidates))
        observed_uids = set(row['identity']['uids'])
        expected_uids = set(known[buyer_id]['identity']['uids'])
        if observed_uids and expected_uids and observed_uids.isdisjoint(expected_uids):
            conflicts.add(buyer_id)
            counts['ambiguousOrders'] += 1
            exact.discard(row['orderNo'])
            continue
        matched[buyer_id].append(row)
        counts['matchedOrders'] += 1

    refreshed = []
    through = now.isoformat() if failed is None else None
    for buyer_id, buyer in known.items():
        history = {r['orderNo']: r for r in buyer['history']}
        observations = matched[buyer_id]
        observed_uids = {value for r in observations for value in r['identity']['uids']}
        if not buyer['identity']['uids'] and len(observed_uids) > 1:
            conflicts.add(buyer_id)
            for row in observations:
                if row['orderNo'] not in history:
                    exact.discard(row['orderNo'])
                    counts['matchedOrders'] -= 1
            observations = [row for row in observations if row['orderNo'] in history]
        for row in observations:
            previous = history.get(row['orderNo'])
            if previous:
                if any(row[field] != previous[field] for field in ('paidAtShanghai', 'adminOrderId')):
                    conflicts.add(buyer_id)
                    exact.discard(row['orderNo'])
                    continue
                row = dict(row, country=row['country'] or previous['country'],
                           platform=row['platform'] or previous['platform'], purchaseK=row['purchaseK'] or previous['purchaseK'],
                           benefits={key: row['benefits'][key] if row['benefits'][key] is not None else prior
                                     for key, prior in previous['benefits'].items()},
                           identity={key: sorted(set(row['identity'][key]) | set(previous['identity'][key]))
                                     for key in IDENTITY_FIELDS})
            history[row['orderNo']] = row
        for number in history.keys() & requested.keys():
            status = 'verified' if number in exact else 'unavailable' if refund_error else 'missing'
            history[number] = dict(history[number], refundReadback=dict(status=status, asOfShanghai=now.isoformat()))
        cutoff = buyer.get('paymentCoverage', {}).get('through')
        latest = max(history.values(), key=order_key, default=buyer.get('lastOrder'))
        gap_after_last = bool(latest) and any(day >= latest['paidAtShanghai'][:10] for day in missing_days)
        # A replay that starts after the last observed cutoff leaves an unchecked interval.
        complete = (failed is None and not counts['unidentifiedOrders'] and buyer_id not in conflicts
                    and bool(buyer['identity']['uids'] or buyer['identity']['emails'])
                    and not gap_after_last
                    and (bool(cutoff) and since <= stamp(cutoff)
                         or bool(buyer.get('lastOrder')) and since <= stamp(buyer['lastOrder']['paidAtShanghai'])))
        refreshed.append(observed_buyer(buyer, history.values(), now, bool(complete),
                                         through=through if complete else cutoff, observed_through=through))
    complete = failed is None and len(exact) == len(requested) and all(
        r['paymentCoverage']['complete'] for r in refreshed)
    coverage = dict(complete=complete, sinceShanghai=since.isoformat(), through=through, missingDays=list(missing_days),
                    identityConflictBuyers=len(conflicts), **counts)
    coverage['refundReadback'] = dict(complete=len(exact) == len(requested), requested=len(requested),
                                     verified=len(exact), missing=len(requested) - len(exact), error=refund_error)
    if failed:
        coverage['error'] = failed
    return dict(schema=SCHEMA, status='unavailable' if failed else 'available' if complete else 'partial',
                asOfShanghai=now.isoformat(), coverage=coverage, buyers=refreshed)
