"""Order-time ES flags, joined by order hash; queries only read retained exports."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import hashlib
import os
import re
from pathlib import Path

from user_contract import TZ, stamp
from user_store import safe

ARCHIVE = Path('/var/lib/fc27-es-exports')


def _read_flags(query, root=ARCHIVE):
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


def _manifest_inventory(root=ARCHIVE):
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
    # Keep complete monthly replacements and only daily pieces extending their coverage.
    values={item['name']:json.loads((root/item['name']).read_text('utf-8')) for item in result}
    def complete(v):
        f=v.get('file_set') or {}
        return f.get('failed_files')==0 and f.get('declared_files')==len(v.get('file_sha256',[])) and bool(v.get('file_sha256'))
    selected=[]
    for item in result:
        value=values[item['name']];q=value['query']
        superseded=any(other['name']!=item['name'] and complete(values[other['name']])
            and values[other['name']]['query']['start']<=q['start']<=q['end']<=values[other['name']]['query']['end']
            and (stamp(values[other['name']]['captured_at']),other['name'])>(stamp(value['captured_at']),item['name']) for other in result)
        if not superseded:selected.append(item)
    return selected


def _read_pinned_flags(query, manifests, root=ARCHIVE, _identity=False):
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
    flags, hashes, captures, identities = {}, set(), [], {}
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
            if _identity:
                for row in rows:
                    paid = str(row.get(es.COLUMNS['time']) or '').replace('/', '-')[:10]
                    order = row.get(es.COLUMNS['order'])
                    if start <= paid <= end and isinstance(order, str) and order:
                        key = hashlib.sha256(order.encode()).hexdigest()
                        values = identities.setdefault(key, dict(buyer_id=set(), uid=set()))
                        for field in ('buyer_id', 'uid'):
                            ident = row.get(field)
                            if isinstance(ident, str) and ident.strip().lower() not in ('', '0', 'null', 'none', 'n/a', 'nan', 'undefined', '-') and len(ident) <= 160 and not any(ord(c)<32 for c in ident):
                                values[field].add(ident.strip())
            dataset = es.make_dataset(rows, parsed_hashes, failures, integrity.get('declared_files'), integrity.get('failed_files'))
            hashes.update(parsed_hashes); captures.append(item['captured_at'])
            for row in dataset['rows']:
                paid = str(row.get(es.COLUMNS['time']) or '').replace('/', '-')[:10]
                ident = row.get(es.COLUMNS['order'])
                if start <= paid <= end and ident:
                    flags.setdefault(ident, set()).add(str(row.get(es.COLUMNS['new_customer']) or '').strip())
    labels = {ident: ('new' if next(iter(items)) == '\u662f' else 'old' if next(iter(items)) == '\u5426' else 'unknown')
              if len(items) == 1 else 'conflict' for ident, items in flags.items()}
    if _identity:
        labels = {key: dict(status='verified' if len(v['buyer_id']) == 1 else 'conflict' if len(v['buyer_id']) > 1 else 'unknown',
                            buyer_id=next(iter(v['buyer_id'])) if len(v['buyer_id']) == 1 else None,
                            uid=next(iter(v['uid'])) if len(v['uid']) == 1 else None) for key,v in identities.items()}
    return labels, dict(status='complete' if complete else 'partial', source='Admin ES exact-order buyer/UID evidence' if _identity else 'Admin ES order-time new-customer flag',
                        generatedAt=max(captures, default=None), files=len(hashes),
                        sourceVersion=hashlib.sha256(''.join(sorted(hashes)).encode()).hexdigest())


def ensure_period(start, end, now=None, daily=False, fresh_after=None, cycle_id=None):
    """A week crossing a month boundary needs both monthly export portions."""
    now = now or datetime.now(TZ)
    begin, stop = stamp(start), stamp(end)
    if not begin < stop <= now.replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError('closed_customer_type_period_required')
    while begin < stop:
        month = (begin.replace(day=28)+timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        finish = min(begin+timedelta(days=1) if daily and fresh_after is None else month, stop)
        query = dict(start=begin.date().isoformat(), end_exclusive=finish.isoformat())
        if fresh_after is not None:
            import es_order_structure as es
            value=es.server_bundle_after(dict(profile='ALL',start=query['start'],end=(finish-timedelta(days=1)).date().isoformat(),group_by='new_customer',status='all'),fresh_after,cycle_id)
            if value.get('status')!='available':
                reason=str(value.get('reason','')).lower()
                if value.get('status') in ('failed','unavailable') and any(word in reason for word in ('permission','denied','invalid','contract','unsupported')):
                    raise ValueError('weekly_customer_type_source_contract')
                return dict(status='pending',source_status=value.get('status','unavailable'),reason=value.get('reason'))
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


def read_pinned_identities(query, manifests, root=ARCHIVE):
    """Private order-hash evidence only; never add IDs to the public ES dataset."""
    return read_pinned_flags(query, manifests, root, _identity=True)


def read_flags(query,root=ARCHIVE):
    if not Path(root).exists():return _read_flags(query,root)
    import es_order_structure as es
    with es.SERVER_LOCK,es.archive_access(root):return _read_flags(query,root)


def manifest_inventory(root=ARCHIVE):
    if not Path(root).exists():return []
    import es_order_structure as es
    with es.archive_access(root):return _manifest_inventory(root)


def read_pinned_flags(query,manifests,root=ARCHIVE,_identity=False):
    import es_order_structure as es
    with es.archive_access(root):return _read_pinned_flags(query,manifests,root,_identity=_identity)


def archive_reference_state(store,receipt_root=Path('/var/lib/fs-hermes-fc/fs/es-structures')):
    """Known raw-ES consumers: current publication and unresolved durable exports.

    Stored user recipes embed flags; source/report snapshots embed projections. Their
    provenance hashes do not require reopening original XLSX. Keep those stores intact.
    Caller retains the existing jobs/publication lock; no SERVER_LOCK is taken here.
    """
    from user_weekly import stored_publication
    value=stored_publication(store)
    if not value:return dict(complete=False,publication_id='',manifests=[],file_hashes=[],inflight=[],reason='current_publication_missing')
    result=dict(complete=True,publication_id=value['publication_id'],manifests=sorted({x['name'] for x in value['flag_manifests']}),file_hashes=[],inflight=[],
                consumers=['current-user-publication','durable-es-attempts','embedded-user-recipes','embedded-report-projections'])
    receipt_root=Path(receipt_root);safe(receipt_root)
    if not receipt_root.is_dir():
        result.update(complete=False,reason='es_receipt_root_missing');return result
    attempts=list(receipt_root.glob('*.attempt'))
    reviews=receipt_root/'.monthly-reviews';safe(reviews)
    if reviews.exists():
        for cycle in reviews.iterdir():
            safe(cycle)
            if not cycle.is_dir():raise ValueError('es_review_receipt_directory')
            attempts.extend(cycle.glob('*.attempt'))
    for path in attempts:
        safe(path)
        if path.stat().st_size>1024*1024 or path.stat().st_uid!=os.geteuid() or path.stat().st_mode&0o077:raise ValueError('es_attempt_permissions')
        q=json.loads(path.read_text('utf-8')).get('query') or {}
        if not q.get('start') or not q.get('end'):raise ValueError('es_attempt_period')
        result['inflight'].append(dict(start=q['start'],end=q['end']))
    result['inflight']=sorted(result['inflight'],key=lambda q:(q['start'],q['end']))
    return result


def compact_after_publication(store,expected_publication_id,root=ARCHIVE,receipt_root=Path('/var/lib/fs-hermes-fc/fs/es-structures'),apply=False,expected_plan_sha256=None):
    import es_order_structure as es
    def references():
        value=archive_reference_state(store,receipt_root)
        if value['publication_id']!=expected_publication_id:raise ValueError('archive_publication_changed')
        return value
    return es.compact_archive(root,references,apply=apply,expected_plan_sha256=expected_plan_sha256)


@contextmanager
def publication_archive_access(root=ARCHIVE):
    safe(Path(root))
    if not Path(root).exists():
        yield;return
    import es_order_structure as es
    with es.archive_access(root):yield
