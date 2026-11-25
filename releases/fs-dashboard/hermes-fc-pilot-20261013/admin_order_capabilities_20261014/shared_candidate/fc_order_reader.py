"""Read FC27 problem-order clues or Hermes events through Order HTTP."""
from datetime import datetime, timezone
import json
import sys
import time
from fc_order_diagnostics import classify_logs, choose_sample, summarize

if '/opt/fs-order-session' not in sys.path:
    sys.path.insert(0, '/opt/fs-order-session')
from order_http import BASE, OrderHTTP

SAFE_REASONS = {'source_login_or_page', 'source_filter_contract', 'source_scope_contract', 'detail_contract'}


def run(capability=None, *, reader=None):
    deadline = time.monotonic() + 105
    if reader is None:
        reader = OrderHTTP()
        reader.acquire_session()
    rows, samples, errors = [], [], []
    pages, has_more = 0, None
    for page in range(1, (capability['pages'] if capability else 3) + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append('read_budget')
            break
        page_rows, has_more = reader.problem_order_page(page, timeout=min(15, remaining))
        pages += 1
        rows.extend(page_rows)
        if not has_more:
            break

    selected = [row for row in rows if not capability or capability['platform'] in ('all', row['platform'])]
    for row in choose_sample(selected, capability['samples'] if capability else 12):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            errors.append('sample_budget')
            break
        try:
            timeout = min(8, remaining)
            if capability:
                events = reader.problem_order_events(row['id'], timeout=timeout)
                samples.append({'id': row['id'], 'gid': 1322, 'source': 'www.mmoexp.com',
                                'status': '问题单', 'platform': row['platform'], **events})
            else:
                clue = classify_logs(reader.problem_order_logs(row['id'], timeout=timeout))
                samples.append({'ref': 'order-' + row['id'], 'platform': row['platform'],
                                'amount_usd': row['amount_usd'], 'review_url': BASE + row['detail'],
                                **clue})
        except Exception:
            errors.append('sample_unavailable')

    captured_at = datetime.now(timezone.utc).isoformat()
    if capability:
        return {'contract': 'fc-order-events-raw-v1', 'status': 'partial', 'captured_at': captured_at,
                'listed': len({row['id'] for row in rows}), 'pages': pages, 'has_more': has_more,
                'samples': samples, 'errors': errors}
    return summarize(rows, samples, pages, errors, captured_at)


if __name__ == '__main__':
    try:
        capability = json.loads(sys.argv[1]) if len(sys.argv) > 1 else None
        print(json.dumps(run(capability), ensure_ascii=True, allow_nan=False))
    except Exception as error:
        reason = str(error) if str(error) in SAFE_REASONS else 'source_read_' + type(error).__name__
        print(json.dumps({'contract': 'fc-order-problem-clues-v1', 'status': 'unavailable',
                          'reason': reason, 'captured_at': datetime.now(timezone.utc).isoformat()}))
