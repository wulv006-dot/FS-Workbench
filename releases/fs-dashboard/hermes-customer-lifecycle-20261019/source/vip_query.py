"""Read a custom FC27 maintenance cohort without changing the weekly work queue."""
from datetime import date, datetime
from statistics import median


def query(period_reader, params, now):
    allowed = {'start', 'end', 'as_of', 'offset', 'segment'}
    if set(params) - allowed or not {'start', 'end'} <= params.keys():
        raise ValueError('vip_query_parameters')
    start, end = (date.fromisoformat(params[name][0]) for name in ('start', 'end'))
    as_of = datetime.fromisoformat(params['as_of'][0]) if 'as_of' in params else now
    if as_of.tzinfo is None or as_of > now:
        raise ValueError('vip_query_as_of')
    segment = params.get('segment', ['all'])[0]
    offset = int(params.get('offset', ['0'])[0])
    if offset < 0 or segment not in ('all', 'due', 'recent', 'unknown', 'refund'):
        raise ValueError('vip_query_window')
    result = period_reader(start=start, end=end, now=as_of)
    included = []
    for buyer in result['buyers']:
        last = buyer.get('lastOrder') or {}
        if segment == 'refund' and not last.get('observedRefund'):
            continue
        if segment not in ('all', 'refund') and buyer['followUpStatus'] != segment:
            continue
        included.append(buyer)
    rows = []
    for buyer in included[offset:offset + 20]:
        last = buyer.get('lastOrder') or {}
        days = sorted({date.fromisoformat(order['paidAtShanghai'][:10]) for order in buyer['history']})
        intervals = [(second - first).days for first, second in zip(days, days[1:])]
        rows.append({
            **{key: buyer.get(key) for key in ('buyerId','siteId','country','paymentCountries','windows',
                                               'daysSinceLastPaid','followUpStatus','paymentCoverage')},
            'orderContactEmail': buyer.get('email'), 'memberUid': buyer.get('uid'),
            'purchaseDaysObserved': len(days), 'medianGapDaysObserved': median(intervals) if intervals else None,
            'lastOrder': {key: last.get(key) for key in ('orderNo','paidAtShanghai','amountUsd','platform',
                                                        'purchaseK','orderState','observedRefund','refundStatus','afterSales','benefits')},
        })
    return {key: result.get(key) for key in ('status','asOfShanghai','windows','coverage','summary')} | {
        'splitMethod':result.get('splitMethod'), 'orderStateBasis':result.get('orderStateBasis'), 'segment':segment, 'total':len(included), 'offset':offset,
        'next_offset':offset+len(rows) if offset+len(rows)<len(included) else None, 'items':rows,
    }
