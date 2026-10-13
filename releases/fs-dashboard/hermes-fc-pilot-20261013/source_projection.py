"""Project an existing FC evidence capture; never return raw orders or identities."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pilot import EvidenceBook, money


def project_capture(evidence, order_references=None):
    if evidence.get('project') != 'FC27' or evidence.get('currency') != 'USD':
        raise ValueError('source_identity')
    if evidence.get('plan', {}).get('in_progress'):
        raise ValueError('complete_week_required')
    result = {}
    for row in evidence['windows']:
        name = row['key']
        if name not in {'target', 'previous'}:
            continue
        if name in result or row['status'] != 'available' or row['complete_days'] is not True:
            raise ValueError('incomplete_week_capture')
        main = row['main']
        if main['revenue_usd'] is None:
            raise ValueError('main_revenue_unavailable')
        revenue = money(format(Decimal(str(main['revenue_usd'])).quantize(Decimal('.01')), 'f'))
        ref = {'source_system': 'Order', 'scope': 'FC27/all-sites', 'status': 'unavailable',
               'reference_margin_pct': None, 'estimated_profit_usd': None, 'cost_coverage_pct': None}
        warnings = ['cost_coverage_missing', 'order_scope_differs']
        candidate = (order_references or {}).get(name)
        if candidate is not None:
            if set(candidate) != {'period', 'source_system', 'scope', 'reference_margin_pct', 'cost_coverage_pct'}:
                raise ValueError('reference_fields')
            if candidate['period'] != {'start': row['start'], 'end': row['end']} or candidate['source_system'] != 'Order' or candidate['scope'] != 'FC27/all-sites':
                raise ValueError('reference_period_or_scope')
            margin = money(candidate['reference_margin_pct'])
            estimate = (Decimal(revenue)*Decimal(margin)/100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
            ref.update(status='partial', reference_margin_pct=margin, estimated_profit_usd=money(format(estimate, 'f')),
                       cost_coverage_pct=candidate['cost_coverage_pct'])
        dimensions = {}
        for dimension in ('platform', 'product', 'bucket'):
            allowed = {'PS', 'XBOX', 'PC'} if dimension == 'platform' else {'Coins', 'Items'} if dimension == 'product' else {str(i) for i in range(10)}
            projected = []
            for item in row['dimensions'].get(dimension, []):
                if item['key'] not in allowed or item['revenue_usd'] is None:
                    if item.get('orders') and 'partial_source' not in warnings:
                        warnings.append('partial_source')
                    continue
                projected.append({'key': item['key'], 'orders': item['orders'],
                                  'revenue_usd': money(format(Decimal(str(item['revenue_usd'])).quantize(Decimal('.01')), 'f'))})
            dimensions[dimension] = projected
        result[name] = {'source_system': 'Admin', 'scope': 'FC27/main', 'currency': 'USD',
                        'period': {'start': row['start'], 'end_exclusive': (date.fromisoformat(row['end'])+timedelta(days=1)).isoformat(),
                                   'timezone': 'Asia/Shanghai'},
                        'as_of': evidence['generated_at'], 'orders': main['orders'], 'revenue_usd': revenue,
                        'breakdown': dimensions, 'order_reference': ref, 'warnings': warnings}
    if set(result) != {'target', 'previous'}:
        raise ValueError('comparison_required')
    # Source capture timestamp, rather than analysis generation time, is authoritative.
    for name, window in result.items():
        source = next((x for x in evidence['evidence'] if x['ref'] == name+'.main'), None)
        if source is None or source['snapshot_id'] != evidence['snapshot_id']:
            raise ValueError('capture_reference')
        window['as_of'] = source['captured_at']
    return EvidenceBook(evidence['snapshot_id'], result)
