"""Batch raw Admin adapter over existing channel paging and shared-session credentials."""
from datetime import datetime, timedelta
import sys
import re
from time import monotonic

from user_contract import TZ, stamp

PATH = '/admin/order.Order/index'


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


def shared_correct(store, site, requested):
    """Read selected IDs in any state; do not infer absence from a status filter."""
    if store.config.get('activation_status') != 'W0_verified':
        raise RuntimeError('W0_live_contract_required')
    if (site not in store.config['sites'] or not isinstance(requested, dict) or not 1 <= len(requested) <= 400
            or any(not isinstance(ident,str) or not re.fullmatch(r'[1-9][0-9]{0,18}', ident) for ident in requested)
            or sum(len(ident)+3 for ident in requested)>6000):
        raise ValueError('targeted_request_scope')
    sys.path[:0] = ['/opt/sales-dashboard/collector', '/opt/fs-hermes-fc']
    import p2pah_auth as auth
    from channel_source import pages
    session = auth.Session()
    try:
        token, reason = auth.admin_token_from_service()
        if not token:
            raise RuntimeError('admin_shared_source_unavailable')
        session.bind_admin_token(token); del token
        filters = [('site_id', '=', site), ('id', 'IN', ','.join(sorted(requested, key=int)))]
        class Observed:
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
                        or not 0<=data['total']<=len(requested) or not isinstance(data.get('list'),list)
                        or len(data['list'])!=data['total'] or any(not isinstance(row,dict) for row in data['list'])):raise ValueError('targeted_source_contract')
                return status,payload
        rows = pages(Observed(), PATH, filters, 1000)
        ids = [str(row.get('id') or '') for row in rows]
        if (any(ident not in requested for ident in ids) or len(set(ids)) != len(ids)
                or [int(ident) for ident in ids] != sorted((int(ident) for ident in ids), reverse=True)):
            raise ValueError('targeted_source_identity_or_sort')
        return store.correct_orders(site, requested, rows, datetime.now(TZ).isoformat())
    finally:
        session.close()
