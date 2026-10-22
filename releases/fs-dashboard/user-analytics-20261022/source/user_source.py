"""Batch raw Admin adapter over existing channel paging and shared-session credentials."""
from datetime import datetime, timedelta
import sys
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
        except Exception:
            # Persist a non-sensitive error code, never the upstream payload or exception text.
            store.failed_window(site, begin.isoformat(), stop.isoformat(), 'source_or_contract_failure')
            raise RuntimeError('user_source_window_failed') from None
    return receipts


def shared_sync(store, site, start, end):
    if store.config.get('activation_status') != 'W0_verified':
        raise RuntimeError('W0_live_contract_required')
    # Identical established Admin-session route as channel_source.collect; no new login flow.
    sys.path.insert(0, '/opt/sales-dashboard/collector')
    import p2pah_auth as auth
    from channel_source import pages
    session = auth.Session()
    try:
        token, reason = auth.admin_token_from_service()
        if not token:
            raise RuntimeError('admin_shared_source_unavailable')
        session.bind_admin_token(token)
        del token
        return synchronize(store, site, start, end, session, pages)
    finally:
        session.close()
