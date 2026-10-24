"""Read a bounded <=100-row sample; output format/equality counts, never monetary values."""
import argparse
import contextlib
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime
from decimal import Decimal

from campaign_backend.adapters import AdminRead, search
from campaign_backend.core import ContractError, canonical


def number(value):
    if type(value) not in (str, int) or not re.fullmatch(r'-?\d{1,18}(?:\.\d{1,6})?', str(value)):
        return None
    return Decimal(value)


def observe(rows):
    names = ('amount', 'pay_money', 'pay_money_format', 'return_money')
    values = {name: [row.get(name) for row in rows] for name in names}
    values['pay_money_format2[1]'] = [row.get('pay_money_format2', [None, None])[1]
        if isinstance(row.get('pay_money_format2'), list) and len(row['pay_money_format2']) > 1 else None for row in rows]
    parsed = {name: [number(v) for v in items] for name, items in values.items()}
    codes = Counter(row.get('currency_code') for row in rows if isinstance(row.get('currency_code'), str)
                    and re.fullmatch('[A-Z]{3}', row['currency_code']))
    comparisons = {}
    for left, right in (('amount', 'pay_money'), ('amount', 'pay_money_format2[1]'),
                        ('pay_money', 'pay_money_format2[1]'), ('pay_money_format', 'pay_money_format2[1]')):
        pairs = [(a, b) for a, b in zip(parsed[left], parsed[right]) if a is not None and b is not None]
        comparisons[left + '==' + right] = dict(comparable=len(pairs), equal=sum(a == b for a, b in pairs))
    return dict(sample_rows=len(rows), sample_only=True, currency_codes=dict(codes),
        decimal_parseable={name: sum(value is not None for value in items) for name, items in parsed.items()},
        comparisons=comparisons, pay_money_format2_currency_matches=sum(
            isinstance(row.get('pay_money_format2'), list) and bool(row['pay_money_format2'])
            and row['pay_money_format2'][0] == row.get('currency_code') for row in rows),
        capture_sha256=hashlib.sha256(canonical(rows).encode()).hexdigest(),
        semantic_status='relations_do_not_prove_amount_basis')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', required=True)
    parser.add_argument('--from', dest='start', required=True)
    parser.add_argument('--to', dest='end', required=True)
    args = parser.parse_args()
    try:
        start, end = datetime.fromisoformat(args.start), datetime.fromisoformat(args.end)
        if not 0 <= (end - start).total_seconds() <= 28 * 86400:
            raise ContractError('BOUNDED_TIME_WINDOW_REQUIRED')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            reader = AdminRead.from_shared_session()
            try:
                data = reader._get('/admin/order.Order/index', page=1, limit=100,
                    **search([('site_id', '=', args.site), ('paytime', 'RANGE', args.start + ',' + args.end)]))
                rows = data['list']
                if (not isinstance(rows, list) or len(rows) > 100 or any(str(r.get('site_id')) != args.site
                        or not args.start <= str(r.get('paytime')) <= args.end for r in rows)):
                    raise ContractError('UPSTREAM_SCOPE_MISMATCH')
                output = observe(rows)
            finally:
                reader.close()
        response = dict(status='ok', data=output)
    except Exception:
        response = dict(status='error', error='MONEY_SHAPE_PROBE_UNAVAILABLE')
    print(json.dumps(response, ensure_ascii=True))


if __name__ == '__main__':
    main()
