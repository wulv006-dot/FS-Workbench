"""Keep the existing paid-order contract within the upstream calendar-month limit."""
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import time


def windows(start, end):
    current, last = date.fromisoformat(start), date.fromisoformat(end)
    result = []
    while current <= last:
        stop = min(last, current.replace(day=monthrange(current.year, current.month)[1]))
        result.append((current.isoformat(), stop.isoformat()))
        current = stop + timedelta(days=1)
    return result


def collect(request, query, single_month):
    segments = windows(query['start'], query['end'])
    if len(segments) == 1:
        return single_month(request, query)
    deadline, calls = time.monotonic() + 850, 0
    def bounded(path, timeout):
        nonlocal calls
        remaining = deadline - time.monotonic()
        if calls >= 300 or remaining <= 0:
            raise TimeoutError('cohort_paid_total_read_budget')
        calls += 1
        return request(path, min(timeout, remaining))
    parts, rows, seen, pages, evidence = [], [], set(), [], []
    for start, end in reversed(segments):
        part = single_month(bounded, dict(query, start=start, end=end))
        coverage = part['coverage']
        for row in part['orders']:
            if row['id'] in seen:
                raise ValueError('cohort_paid_cross_month_duplicate')
            seen.add(row['id']); rows.append(row)
        for page in coverage['pages']:
            pages.append(dict(page, page=len(pages) + 1, source_page=page['page'],
                              segment_start=start, segment_end=end))
        evidence.append({'start': start, 'end': end, 'status': part['status'],
                         'source_total': coverage['source_total'], 'received': coverage['received'],
                         'paid_complete': coverage['paid_complete'],
                         'source_scanned_total': coverage.get('source_scanned_total'),
                         'source_scanned_received': coverage.get('source_scanned_received'),
                         'excluded_refunded': coverage.get('excluded_refunded', 0)})
        parts.append(part)
        if part['status'] != 'available' or coverage['paid_complete'] is not True:
            break
    complete = len(parts) == len(segments) and all(p['coverage']['paid_complete'] is True for p in parts)
    total = sum(p['coverage']['source_total'] for p in parts) if complete else None
    if complete and total != len(rows):
        raise ValueError('cohort_paid_merged_total_mismatch')
    result = dict(parts[0], query=dict(query), orders=rows,
                  status='available' if complete else 'partial',
                  as_of=datetime.now(timezone.utc).isoformat())
    result['coverage'] = dict(parts[0]['coverage'], paid_complete=complete,
        period={'start': query['start'] + ' 00:00',
                'end': (date.fromisoformat(query['end']) + timedelta(days=1)).isoformat() + ' 00:00'},
        source_total=total, received=len(rows), pages=pages, segments=evidence,
        source_scanned_total=sum(p['coverage']['source_scanned_total'] for p in parts)
            if complete and all(p['coverage'].get('source_scanned_total') is not None for p in parts) else None,
        source_scanned_received=sum(p['coverage'].get('source_scanned_received', p['coverage']['received']) for p in parts),
        excluded_refunded=sum(p['coverage'].get('excluded_refunded', 0) for p in parts))
    result['snapshot_id'] = 'cohort-paid-' + hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:20]
    return result
