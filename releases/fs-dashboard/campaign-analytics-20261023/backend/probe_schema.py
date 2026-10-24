"""Controller-run read-only probe. Emits schemas, numeric enums, counts and hashes only."""
import argparse
import contextlib
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime

from campaign_backend.adapters import AdminRead
from campaign_backend.core import ContractError, canonical


def schema(rows):
    result = {}
    def walk(value, prefix='', depth=0):
        if depth > 3:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                safe = key if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', str(key)) else '<dynamic-key>'
                name = prefix + safe
                result.setdefault(name, set()).add(type(child).__name__)
                walk(child, name + '.', depth + 1)
        elif isinstance(value, list):
            for child in value[:20]:
                walk(child, prefix + '[].', depth + 1)
    for row in rows:
        walk(row)
    enums = {}
    for name in ('pay_status', 'status', 'type', 'mode_type', 'time_effect', 'fetch_scene', 'is_open', 'refund_status'):
        values = Counter(canonical(row.get(name)) for row in rows if name in row)
        enums[name] = [dict(raw_numeric=json.loads(value), count=count)
                      if type(json.loads(value)) in (int, bool) or re.fullmatch(r'"\d{1,5}"', value)
                      else dict(value_sha256=hashlib.sha256(value.encode()).hexdigest(), count=count)
                      for value, count in sorted(values.items())[:32]]
    return dict(rows=len(rows), schema={k: sorted(v) for k, v in sorted(result.items())}, enums=enums,
                capture_sha256=hashlib.sha256(canonical(rows).encode()).hexdigest())


def probe(reader, site_id, start=None, end=None, coupon_id=None, discount_id=None):
    result = {}
    for kind, object_id in (('coupon', coupon_id), ('discount', discount_id)):
        if object_id is not None:
            result[kind] = schema([reader.detail(kind, object_id)])
    if start is not None or end is not None:
        try:
            begin, stop = datetime.fromisoformat(start), datetime.fromisoformat(end)
            if not 0 <= (stop - begin).total_seconds() <= 28 * 86400:
                raise ValueError()
        except (ValueError, TypeError):
            raise ContractError('BOUNDED_TIME_WINDOW_REQUIRED') from None
        orders = reader.orders(site_id, start, end)
        logs = reader.coupon_logs(site_id, [str(row['order_no']) for row in orders])
        result.update(orders=schema(orders), coupon_logs=schema(logs),
                      associated_orders=len({str(row['order_no']) for row in logs}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True)
    parser.add_argument('--from', dest='start')
    parser.add_argument('--to', dest='end')
    parser.add_argument('--coupon-id')
    parser.add_argument('--discount-id')
    args = parser.parse_args()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            reader = AdminRead.from_shared_session()
            try:
                output = probe(reader, args.site, args.start, args.end, args.coupon_id, args.discount_id)
            finally:
                reader.close()
        response = dict(status='ok', data=output)
    except Exception:
        response = dict(status='error', error='SCHEMA_PROBE_UNAVAILABLE')
    print(json.dumps(response, ensure_ascii=True))


if __name__ == '__main__':
    main()
