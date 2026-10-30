"""Order-time ES flags, joined by order hash; queries only read retained exports."""
from datetime import datetime, timedelta
import json
import hashlib
import os
import re
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


def manifest_inventory(root=ARCHIVE):
    """Pin existing immutable export manifests; later exports cannot change a published week."""
    root = Path(root)
    safe(root)
    if not root.exists():
        return []
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError('private_customer_type_archive_required')
    result = []
    for path in sorted(root.glob('*.json')):
        if not re.fullmatch('[a-f0-9]{64}\\.json', path.name):
            continue
        safe(path)
        if (path.stat().st_size > 1024*1024
                or path.stat().st_uid != os.geteuid() or path.stat().st_mode & 0o077):
            raise ValueError('private_customer_type_manifest_required')
        raw = path.read_bytes(); value = json.loads(raw); query = value.get('query', {})
        if (query.get('profile') == 'ALL' and query.get('status', 'all') == 'all'
                and query.get('start') and query.get('end') and value.get('captured_at')
                and stamp(value['captured_at']) >= stamp(query['end'])+timedelta(days=1)):
            result.append(dict(name=path.name, sha256=hashlib.sha256(raw).hexdigest()))
    return result


def read_pinned_flags(query, manifests, root=ARCHIVE):
    """Read precisely the pinned file hashes, not archived_dataset's newest matching export."""
    root = Path(root); safe(root)
    start = stamp(query['start']).date().isoformat()
    end = (stamp(query['end_exclusive'])-timedelta(microseconds=1)).date().isoformat()
    values = []
    for item in manifests:
        if (not isinstance(item, dict) or set(item) != {'name', 'sha256'}
                or not re.fullmatch('[a-f0-9]{64}\\.json', item['name'])
                or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
            raise ValueError('frozen_customer_type_manifest')
        path = root/item['name']; safe(path)
        info = path.stat()
        if info.st_size > 1024*1024 or info.st_mode & 0o077 or info.st_uid != os.geteuid():
            raise ValueError('private_customer_type_manifest_required')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('frozen_customer_type_manifest_changed')
        values.append(json.loads(raw))
    cursor, selected = start, []
    while cursor <= end:
        options = [v for v in values if v['query']['start'] <= cursor <= v['query']['end']]
        if not options:break
        item = max(options, key=lambda v: (v['query']['end'], v['captured_at']))
        selected.append(item)
        cursor = (stamp(item['query']['end'])+timedelta(days=1)).date().isoformat()
    flags, hashes, captures = {}, set(), []
    complete = cursor > end
    if selected:
        import es_order_structure as es
        for item in selected:
            ids = item.get('file_sha256', [])
            if not isinstance(ids, list) or not 0 < len(ids) <= 20:
                raise ValueError('frozen_customer_type_file_set')
            files = []
            with es.archive_access(root):
                for ident in ids:
                    if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{64}', ident):
                        raise ValueError('frozen_customer_type_file_hash')
                    path = es.excel_path(root, ident); safe(path); info = path.stat()
                    if info.st_size > es.MAX_FILE or info.st_mode & 0o077 or info.st_uid != os.geteuid():
                        raise ValueError('private_customer_type_file_required')
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != ident:
                        raise ValueError('frozen_customer_type_file_changed')
                    files.append(raw)
                    if sum(map(len, files)) > 128*1024*1024:
                        raise ValueError('frozen_customer_type_read_budget')
            rows, parsed_hashes, failures = es.parse_files(files)
            integrity = item.get('file_set') or {}
            complete &= (failures == 0 and integrity.get('failed_files') == 0
                         and integrity.get('declared_files') == len(parsed_hashes))
            dataset = es.make_dataset(rows, parsed_hashes, failures, integrity.get('declared_files'), integrity.get('failed_files'))
            hashes.update(parsed_hashes); captures.append(item['captured_at'])
            for row in dataset['rows']:
                paid = str(row.get(es.COLUMNS['time']) or '').replace('/', '-')[:10]
                ident = row.get(es.COLUMNS['order'])
                if start <= paid <= end and ident:
                    flags.setdefault(ident, set()).add(str(row.get(es.COLUMNS['new_customer']) or '').strip())
    labels = {ident: ('new' if next(iter(items)) == '\u662f' else 'old' if next(iter(items)) == '\u5426' else 'unknown')
              if len(items) == 1 else 'conflict' for ident, items in flags.items()}
    return labels, dict(status='complete' if complete else 'partial', source='Admin ES order-time new-customer flag',
                        generatedAt=max(captures, default=None), files=len(hashes),
                        sourceVersion=hashlib.sha256(''.join(sorted(hashes)).encode()).hexdigest())


def ensure_period(start, end, now=None):
    """A week crossing a month boundary needs both monthly export portions."""
    now = now or datetime.now(TZ)
    begin, stop = stamp(start), stamp(end)
    if not begin < stop <= now.replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError('closed_customer_type_period_required')
    while begin < stop:
        month = (begin.replace(day=28)+timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        finish = min(month, stop)
        query = dict(start=begin.date().isoformat(), end_exclusive=finish.isoformat())
        _, info = read_flags(query)
        if info['status'] != 'complete':
            import es_order_structure as es
            value = es.server_bundle(dict(profile='ALL', start=query['start'], end=(finish-timedelta(days=1)).date().isoformat(),
                                          group_by='new_customer', status='all'))
            reason = str(value.get('reason', '')).lower()
            if value.get('status') in ('failed', 'unavailable') and any(word in reason for word in ('permission', 'denied', 'invalid', 'contract', 'unsupported')):
                raise ValueError('weekly_customer_type_source_contract')
            return dict(status='pending', source_status=value.get('status', 'unavailable'))
        begin = finish
    return dict(status='complete', start=start, end_exclusive=end)
