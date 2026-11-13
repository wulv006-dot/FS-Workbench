"""Batch raw Admin adapter over existing channel paging and shared-session credentials."""
from datetime import datetime, timedelta
import json
import sys
import re
from time import monotonic
from urllib.parse import urlencode

from user_contract import TZ, stamp

PATH = '/admin/order.Order/index'
# shortcut: cap occupied windows at 16; revisit selection if this visible budget failure recurs.
TARGETED_MAX_WINDOWS = 16
TARGETED_READ_SECONDS = 180


def windows(start, end):
    current, end = stamp(start), stamp(end)
    if current.microsecond or end.microsecond or not current < end:
        raise ValueError('source_second_precision_required')
    while current < end:
        stop = min(current + timedelta(days=28), end)
        yield current, stop
        current = stop


def synchronize(store, site, start, end, session, page_reader):
    """One all-status enumeration per slice, never costs/coupons or one scan per email."""
    receipts = []
    for begin, stop in windows(start, end):
        at = monotonic()
        try:
            source_start = begin.strftime('%Y-%m-%d %H:%M:%S')
            source_end = (stop - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S')
            rows = page_reader(session, PATH, [('site_id', '=', str(site)), ('paytime', 'RANGE', source_start + ',' + source_end)], 100)
            receipt = store.replace_window(site, begin.isoformat(), stop.isoformat(), rows, datetime.now(TZ).isoformat())
            receipts.append(dict(receipt, elapsed_seconds=round(monotonic() - at, 3)))
        except Exception as error:
            # Persist a non-sensitive error code, never the upstream payload or exception text.
            code = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[a-z_]{1,80}', str(error)) else type(error).__name__
            store.failed_window(site, begin.isoformat(), stop.isoformat(), code)
            raise RuntimeError('user_source_window_failed:' + code) from None
    return receipts


def shared_sync(store, site, start, end):
    if store.config.get('activation_status') != 'W0_verified':
        raise RuntimeError('W0_live_contract_required')
    # Identical established Admin-session route as channel_source.collect; no new login flow.
    sys.path[:0] = ['/opt/sales-dashboard/collector', '/opt/fs-hermes-fc']
    import p2pah_auth as auth
    from channel_source import pages
    def ordered_pages(session, path, filters, limit):
        # Verified 2026-10-23: original Admin returns 1000 rows; retain every paging/sort guard.
        rows = pages(session, path, filters, 1000)
        ids = [str(r.get('id') or '') for r in rows]
        if any(not i.isdigit() or int(i) <= 0 for i in ids) or len(set(ids)) != len(ids) or [int(i) for i in ids] != sorted((int(i) for i in ids), reverse=True):
            raise ValueError('source_order_sort_or_identity')
        if any(str(row.get('status')) not in store.config['known_order_statuses'] for row in rows):
            from user_contract import digest
            from user_jobs import atomic
            fields = ('id','order_no','email','uid','site_id','gid','paytime','pay_status','status','status_format',
                      'currency_code','payback','return_money','amount_usd_format','amount_rmb_format')
            atomic(store.root/('source-review-'+digest(filters)[:24]+'.json'),
                   dict(contract='fs-users-source-window-review-v1',filters=filters,captured_at=datetime.now(TZ).isoformat(),
                        source_rows=len(rows),rows=[{key:row.get(key) for key in fields} for row in rows]))
            raise ValueError('unmapped_order_status')
        return rows
    session = auth.Session()
    try:
        token, reason = auth.admin_token_from_service()
        if not token:
            raise RuntimeError('admin_shared_source_unavailable')
        session.bind_admin_token(token)
        del token
        return synchronize(store, site, start, end, session, ordered_pages)
    finally:
        session.close()




def shared_es_native_day(day):
    """One complete native payment-day mapping for all sites and games."""
    from collections import defaultdict
    from contextlib import closing
    from datetime import date
    from channel_effects import clean
    from channel_source import COLLECTOR, pages

    day = date.fromisoformat(day).isoformat()
    sys.path.insert(0, COLLECTOR)
    import p2pah_auth as auth

    with closing(auth.Session()) as session:
        token, _ = auth.admin_token_from_service()
        if not token:
            raise RuntimeError('admin_shared_source_unavailable')
        session.bind_admin_token(token)
        del token
        start, end = day + ' 00:00:00', day + ' 23:59:59'
        rows = pages(session, PATH, [('pay_status', '=', '1'), ('paytime', 'RANGE', start + ',' + end)], 1000)
        observed_at = datetime.now(TZ)
        ids = [int(row['id']) for row in rows]
        if ids != sorted(ids, reverse=True) or len(set(ids)) != len(ids):
            raise ValueError('shared_es_admin_order_sort')
        by_site = defaultdict(list)
        for row in rows:
            site, number = str(row.get('site_id') or ''), row.get('order_no')
            if (not site.isdecimal() or not isinstance(number, str) or not number
                    or not start <= str(row.get('paytime') or '') <= end
                    or str(row.get('pay_status')) not in ('1', '2')):
                raise ValueError('shared_es_admin_scope')
            by_site[site].append(number)
            if (projection := fc27_coins_projection(row, observed_at)) is not None:
                row['fc27_coins'] = projection

        logs, seen, coupon_gaps = defaultdict(list), set(), set()
        for site, numbers in by_site.items():
            for offset in range(0, len(numbers), 100):
                group = numbers[offset:offset + 100]
                try:
                    batch = pages(session, '/admin/user.MemberCouponLog/index',
                                  [('site_id', '=', site), ('order_no', 'IN', ','.join(group))])
                except (OSError, ValueError):
                    coupon_gaps.update((site, number) for number in group)
                    continue
                accepted = set()
                for log in batch:
                    identity = str(log.get('id') or '')
                    if (str(log.get('site_id')) != site or log.get('order_no') not in group
                            or not identity or identity in seen or identity in accepted):
                        raise ValueError('shared_es_coupon_scope')
                    accepted.add(identity)
                seen.update(accepted)
                for log in batch:
                    if log.get('use_time'):
                        logs[(site, log['order_no'])].append(log)
        from shared_es_facts import coupon_tracking

        return rows, coupon_tracking(rows, logs, clean, coupon_gaps)


def fc27_coins_projection(raw, observed_at):
    """Use native ordered K quantities only; keep buyer and title text out of the shared store."""
    if str(raw.get('site_id')) != '266' or str(raw.get('gid')) != '1327':
        return None
    from pathlib import Path
    module_root = '/opt/fc27-cloud-browser'
    if Path(module_root).is_dir() and module_root not in sys.path:
        sys.path.insert(0,module_root)
    from fc_pricing_v3.business_source import _platform, _quantity
    from user_contract import digest, money

    quantity, platform = _quantity(raw), _platform(raw)
    if not quantity or not platform:
        return None
    regional = str(raw.get('is_region_price'))
    region = str(raw.get('region_price_lang_region_id') or '')
    region_id = 0 if regional == '0' else int(region) if regional == '1' and region.isdecimal() and int(region)>0 else None
    evidence = {key:raw.get(key) for key in ('id','order_no','site_id','gid','paytime','aid','content','show_game_pro',
        'before_discount','discount','points','is_region_price','region_price_lang_region_id')}
    at = observed_at if isinstance(observed_at,str) else observed_at.isoformat()
    return dict(platform=platform, purchase_k=quantity['purchase_k'], bonus_k=quantity['bonus_k'],
        delivered_k=quantity['delivered_k'],
        single_line_unit_purchase=len(quantity['lines'])==1 and quantity['lines'][0]['multiplier']==1,
        region_id=region_id, regular_usd=money(raw.get('before_discount')),
        retained_percent=money(raw.get('discount')), points=money(raw.get('points')),
        source_sha256=digest(evidence), observed_at=stamp(at).isoformat())


def shared_discount_catalog():
    """Read the main site's discount inventory once through the existing Admin session."""
    from contextlib import closing
    from channel_source import COLLECTOR, pages

    sys.path.insert(0, COLLECTOR)
    import p2pah_auth as auth

    with closing(auth.Session()) as session:
        token, _ = auth.admin_token_from_service()
        if not token:
            raise RuntimeError('admin_shared_source_unavailable')
        session.bind_admin_token(token)
        del token
        return pages(session, '/admin/market.Discount/index', [('site_id', '=', '266')])


def targeted_windows(store, site, requested):
    """Locate only selected primary keys, then group bounded payment-date slices."""
    days = {}
    with store.db() as db:
        for ident, key in requested.items():
            if not isinstance(key, str) or not key.startswith('admin:' + site + ':'):
                raise ValueError('targeted_request_scope')
            row = db.execute('SELECT site,paid_at,body FROM orders WHERE order_key=?', (key,)).fetchone()
            if row is None or row['site'] != site:
                raise ValueError('targeted_existing_order_required')
            body = json.loads(row['body'])
            if (not isinstance(body, dict) or str(body.get('id')) != ident
                    or key != 'admin:' + site + ':' + str(body.get('order_no') or '')):
                raise ValueError('targeted_projection_identity')
            days[ident] = stamp(row['paid_at']).astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    result = []
    while days:
        begin = min(days.values()); end = begin + timedelta(days=28)
        group = {ident: requested[ident] for ident, day in days.items() if day < end}
        result.append((begin, end, group))
        if len(result) > TARGETED_MAX_WINDOWS:
            raise RuntimeError('targeted_read_budget_exhausted')
        for ident in group: del days[ident]
    return result


def shared_correct(store, site, requested):
    """Read selected IDs in any state; do not infer absence from a status filter."""
    if store.config.get('activation_status') != 'W0_verified':
        raise RuntimeError('W0_live_contract_required')
    if (site not in store.config['sites'] or not isinstance(requested, dict) or not 1 <= len(requested) <= 400
            or any(not isinstance(ident,str) or not re.fullmatch(r'[1-9][0-9]{0,18}', ident) for ident in requested)
            or sum(len(ident)+3 for ident in requested)>6000):
        raise ValueError('targeted_request_scope')
    groups = targeted_windows(store, site, requested)
    deadline = monotonic() + TARGETED_READ_SECONDS
    sys.path[:0] = ['/opt/sales-dashboard/collector', '/opt/fs-hermes-fc']
    import p2pah_auth as auth
    from channel_source import pages, search
    prepared = []
    for begin, end, group in groups:
        filters = [('site_id', '=', site), ('id', 'IN', ','.join(sorted(group, key=int))),
                   ('paytime', 'RANGE', begin.strftime('%Y-%m-%d %H:%M:%S') + ',' +
                    (end-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'))]
        if len(PATH.encode('ascii')) + 1 + len(urlencode(dict(page=1, limit=1000, order='id,desc', **search(filters))).encode('ascii')) > 6000:
            raise ValueError('targeted_request_scope')
        prepared.append((filters, group))
    session = auth.Session()
    try:
        token, reason = auth.admin_token_from_service()
        if not token:
            raise RuntimeError('admin_shared_source_unavailable')
        session.bind_admin_token(token); del token
        class Observed:
            def __init__(self, allowed): self.allowed = allowed
            def get_admin(self,*args,**kwargs):
                if kwargs.get('page',1)!=1:raise ValueError('targeted_source_contract')
                status,payload=session.get_admin(*args,**kwargs)
                if type(status) is not int or not 100<=status<=599:raise ValueError('targeted_source_contract')
                if status==429 or status>=500:raise RuntimeError('targeted_source_temporary')
                if not isinstance(payload,dict) or type(payload.get('code')) is not int:raise ValueError('targeted_source_contract')
                if status in (401,403) or payload.get('code') in (401,403):raise ValueError('targeted_permission_denied')
                if status!=200 or payload['code']!=1:raise ValueError('targeted_source_contract')
                data=payload.get('data')
                if (not isinstance(data,dict) or type(data.get('total')) is not int
                        or not 0<=data['total']<=len(self.allowed) or not isinstance(data.get('list'),list)
                        or len(data['list'])!=data['total'] or any(not isinstance(row,dict) for row in data['list'])):raise ValueError('targeted_source_contract')
                return status,payload
        rows, seen = [], set()
        for filters, group in prepared:
            if monotonic() >= deadline: raise RuntimeError('targeted_read_budget_exhausted')
            # Original pages/search supplies render=datetime for RANGE.
            batch = pages(Observed(group), PATH, filters, 1000)
            if monotonic() >= deadline: raise RuntimeError('targeted_read_budget_exhausted')
            ids = [str(row.get('id') or '') for row in batch]
            if (any(ident not in group or ident in seen for ident in ids) or len(set(ids)) != len(ids)
                    or [int(ident) for ident in ids] != sorted((int(ident) for ident in ids), reverse=True)):
                raise ValueError('targeted_source_identity_or_sort')
            seen.update(ids); rows.extend(batch)
        # No group can commit independently; a later group failure leaves facts untouched.
        rows.sort(key=lambda row: int(row['id']), reverse=True)
        return store.correct_orders(site, requested, rows, datetime.now(TZ).isoformat())
    finally:
        session.close()
