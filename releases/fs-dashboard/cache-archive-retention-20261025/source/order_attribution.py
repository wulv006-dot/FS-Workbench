"""Private ES attribution facts; publication pins, not capture time, select revisions."""
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone

VERSION = 'es-order-attribution-20261112-v1'
HEADERS = {'channel_raw': '归因渠道', 'source_raw': '归因来源明细',
           'first_visit_at_raw': '首访时间'}
CHANNELS = {v.casefold(): v for v in ('SEO', 'Direct', 'PPC', 'Referral', 'Campaign')}


def normalize_order_attribution(row, headers, header_contract):
    fields = header_contract['fields']
    present = {key: column in headers for key, column in fields.items()}
    raw = {key: row.get(column, '') if present[key] else None for key, column in fields.items()}
    channel = (raw['channel_raw'] or '').strip().casefold()
    status = ('field_absent' if not present['channel_raw'] else
              'empty' if not channel else 'available' if channel in CHANNELS else 'unrecognized')
    visit_status = ('field_absent' if not present['first_visit_at_raw'] else
                    'empty' if not (raw['first_visit_at_raw'] or '').strip() else 'semantics_unverified')
    return dict(raw, field_presence=present, channel=CHANNELS.get(channel, 'unknown'), status=status,
                first_visit_at=None, first_visit_status=visit_status, first_visit_timezone=None,
                first_visit_semantics_status='unverified', normalizer_version=VERSION,
                model=None, lookback_window=None, source_effective_at=None,
                source_revision=None, available_at=None, evidence_ref=[])


def published_dataset(args, publication, root, parse_files, make_dataset, excel_path, private_path):
    """Read one existing weekly/daily publication without advancing its revision or exporting."""
    # The caller supplies its already authorized publication; a digest is not an ACL.
    if (not isinstance(publication, dict) or publication.get('contract') != 'fs-users-weekly-publication-v1'
            or not isinstance(publication.get('data_version'), str)
            or not publication['data_version'].isdecimal()
            or not isinstance(publication.get('flag_manifests'), list)):
        raise ValueError('es_publication_contract')
    payload = {k: v for k, v in publication.items() if k != 'publication_id'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                      separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if publication.get('publication_id') != 'uw_' + digest[:32]:
        raise ValueError('es_publication_integrity')
    cutoff = datetime.fromisoformat(publication['cutoff'])
    published_at = datetime.fromisoformat(publication['published_at'])
    if cutoff.tzinfo is None or published_at.tzinfo is None:
        raise ValueError('es_publication_timezone')
    cutoff = cutoff.astimezone(timezone(timedelta(hours=8)))
    if cutoff.time() != datetime.min.time():
        raise ValueError('es_publication_cutoff')
    if date.fromisoformat(args['end']) >= cutoff.date():
        raise ValueError('es_publication_cutoff')
    pins = publication['flag_manifests']
    if len(pins) > 512:
        raise ValueError('es_publication_manifest_limit')
    manifests = {}
    for pin in pins:
        if (not isinstance(pin, dict) or set(pin) != {'name', 'sha256'}
                or not re.fullmatch('[a-f0-9]{64}\\.json', str(pin.get('name')))
                or not re.fullmatch('[a-f0-9]{64}', str(pin.get('sha256')))):
            raise ValueError('es_publication_pin')
        path = root / pin['name']
        if private_path(path).st_size > 1024*1024:
            raise ValueError('es_archive_manifest')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise ValueError('es_publication_manifest_changed')
        value = json.loads(raw)
        if pin['name'] in manifests:
            continue
        q = value.get('query') or {}
        # Archive profile is a request label; only ALL manifests attest this export range.
        if q.get('profile') != 'ALL' or q.get('status', 'all') != 'all':
            raise ValueError('es_publication_scope_unverified')
        if not q.get('start') or not q.get('end') or q['start'] > q['end']:
            raise ValueError('es_publication_period')
        if q['end'] < args['start'] or q['start'] > args['end']:
            continue
        captured = datetime.fromisoformat(value['captured_at'])
        closed_at = datetime.combine(date.fromisoformat(q['end']) + timedelta(days=1),
                                     datetime.min.time(), cutoff.tzinfo)
        if captured.tzinfo is None or not closed_at <= captured <= published_at:
            raise ValueError('es_publication_source_not_available')
        manifests[pin['name']] = value
    rows, hashes, days = [], set(), set()
    row_sources = {}
    total_bytes = 0
    for name, value in sorted(manifests.items()):
        ids = value.get('file_sha256')
        integrity = value.get('file_set') or {}
        if (not isinstance(ids, list) or not 0 < len(ids) <= 20 or len(set(ids)) != len(ids)
                or integrity.get('failed_files') != 0 or integrity.get('declared_files') != len(ids)):
            raise ValueError('es_publication_incomplete')
        files = []
        for ident in ids:
            if not isinstance(ident, str) or not re.fullmatch('[a-f0-9]{64}', ident):
                raise ValueError('es_archive_integrity')
            path = excel_path(root, ident)
            if private_path(path).st_size > 32*1024*1024:
                raise ValueError('es_file_size')
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != ident:
                raise ValueError('es_archive_integrity')
            total_bytes += len(raw)
            if total_bytes > 128*1024*1024:
                raise ValueError('es_archive_limit')
            files.append(raw)
        parsed, parsed_hashes, failures = parse_files(files)
        if failures:
            raise ValueError('es_publication_parse_failure')
        hashes.update(parsed_hashes)
        q = value['query']
        day = date.fromisoformat(max(q['start'], args['start']))
        stop = date.fromisoformat(min(q['end'], args['end']))
        while day <= stop:
            days.add(day.isoformat()); day += timedelta(days=1)
        for row in parsed:
            paid = str(row.get('付款时间') or '').replace('/', '-')
            try:
                day = datetime.strptime(paid, '%Y-%m-%d %H:%M:%S').date().isoformat()
            except ValueError:
                raise ValueError('es_publication_payment_time') from None
            if not args['start'] <= day <= args['end']:
                continue
            if not q['start'] <= day <= q['end']:
                raise ValueError('es_publication_row_outside_manifest')
            signature = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if signature not in row_sources:
                rows.append(row)
                row_sources[signature] = []
            row_sources[signature].append(name)
            if len(rows) > 200000:
                raise ValueError('es_row_limit')
    expected = (date.fromisoformat(args['end']) - date.fromisoformat(args['start'])).days + 1
    if len(days) != expected:
        raise ValueError('es_publication_coverage')
    # An absent column cannot clear a richer snapshot of exactly the same facts.
    # Choose that whole raw row; differing statuses/money remain conflicting variants.
    by_order = {}
    for row in rows:
        by_order.setdefault(row.get('订单号'), []).append(row)
    selected = []
    for key, variants in by_order.items():
        schemas = {}
        for row in variants:
            schemas.setdefault(tuple(sorted(row)), []).append(row)
        for columns, members in schemas.items():
            richer = set()
            if key:
                for other_columns, others in schemas.items():
                    if len(other_columns) > len(columns) and set(columns) <= set(other_columns):
                        richer.update(tuple(other[column] for column in columns) for other in others)
            selected.extend(row for row in members if tuple(row[column] for column in columns) not in richer)
    dataset = make_dataset(selected, sorted(hashes), 0, len(hashes), 0)
    variants = {}
    for row in dataset['rows']:
        key = row.get('订单号')
        if key:
            variants.setdefault(key, []).append(row)
        fact = row['marketing_attribution']
        evidence = row_sources[row['_signature']]
        captured = {datetime.fromisoformat(manifests[name]['captured_at']) for name in evidence}
        fact.update(source_revision=publication['publication_id'], available_at=publication['published_at'],
                    evidence_ref=evidence, source_captured_at=next(iter(captured)).isoformat() if len(captured)==1 else None)
    conflicts = [key for key, values in variants.items() if len(values) > 1]
    for key in conflicts:
        for row in variants[key]:
            row['marketing_attribution']['status'] = 'conflict'
    dataset.update(status='partial' if conflicts else 'available',
                   origin='published_archive_reuse', captured_at=publication['captured_at'],
                   publication_id=publication['publication_id'], source_revision=publication['publication_id'],
                   data_revision=publication['data_version'],
                   available_at=publication['published_at'], revision_selection='published_pins',
                   revision_conflicts=conflicts, archive_profile='ALL',
                   effective_scope={'start': args['start'], 'end': args['end'], 'site_verified': False,
                                    'game_filter_applied': False, 'status_filter_applied': False})
    return dataset
