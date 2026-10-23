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
