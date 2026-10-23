"""Order-time ES flags, joined by order hash; queries only read retained exports."""
from datetime import datetime, timedelta
import json
import os
from pathlib import Path

from user_contract import TZ, stamp
from user_store import safe

ARCHIVE = Path('/var/lib/fc27-es-exports')


def read_flags(query, root=ARCHIVE):
    start, end = stamp(query['start']).date().isoformat(), (stamp(query['end_exclusive'])-timedelta(microseconds=1)).date().isoformat()
    root = Path(root)
    safe(root)
    if not root.is_dir():
        return {}, dict(status='unavailable', source='Admin ES order-time new-customer flag', sourceVersion=None, files=0)
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError('private_customer_type_archive_required')
    names = []
    for path in root.glob('*.json'):
        safe(path)
        if path.stat().st_size > 1024*1024 or path.stat().st_mode & 0o077 or path.stat().st_uid != os.geteuid():
            raise ValueError('private_customer_type_manifest_required')
        value = json.loads(path.read_text('utf-8')); q = value.get('query', {})
        if q.get('profile') != 'ALL' or q.get('status','all') != 'all' or not q.get('start') or not q.get('end'):
            continue
        # A file exported before its last day finished cannot prove closed-day coverage.
        if value.get('captured_at') and stamp(value['captured_at']) >= stamp(q['end'])+timedelta(days=1):
            names.append(path.name)
    from channel_source import customer_types
    flags, info = customer_types(start, end, tuple(sorted(names)), str(root))
    info = {k:v for k,v in info.items() if k != 'orderSources'}
    return {key: 'new' if label == '\u65b0\u5ba2' else 'old' if label == '\u8001\u5ba2' else 'conflict' if '\u51b2\u7a81' in label else 'unknown' for key,label in flags.items()}, info


def ensure_closed_month(now=None):
    """One existing durable export/poll; the original timer remains the only scheduler."""
    now = now or datetime.now(TZ)
    stop = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = (stop-timedelta(days=1)).date()
    start = end.replace(day=1)
    query = dict(start=start.isoformat(),end_exclusive=stop.isoformat())
    _, info = read_flags(query)
    if info['status'] == 'complete':
        return dict(status='reused',start=start.isoformat(),end=end.isoformat(),sourceVersion=info.get('sourceVersion'))
    import es_order_structure as es
    value = es.server_bundle(dict(profile='ALL',start=start.isoformat(),end=end.isoformat(),group_by='new_customer',status='all'))
    return dict(status=value.get('status','unavailable'),start=start.isoformat(),end=end.isoformat(),reason=value.get('reason'),refresh_pending=value.get('refresh_pending',False))
