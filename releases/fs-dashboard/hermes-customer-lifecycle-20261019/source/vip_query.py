"""Read a custom FC27 maintenance cohort without changing the weekly work queue."""
from datetime import date, datetime
from statistics import median


def order_projection(order):
    return {key: order.get(key) for key in ('orderNo', 'paidAtShanghai', 'amountUsd', 'platform', 'purchaseK',
                                            'orderState', 'observedRefund', 'refundStatus', 'afterSales', 'benefits')}


def query(period_reader, params, now, preferred_reader=None):
    allowed = {'start', 'end', 'as_of', 'offset', 'segment', 'scope'}
    if set(params) - allowed or not {'start', 'end'} <= params.keys():
        raise ValueError('vip_query_parameters')
    start, end = (date.fromisoformat(params[name][0]) for name in ('start', 'end'))
    as_of = datetime.fromisoformat(params['as_of'][0]) if 'as_of' in params else now
    if as_of.tzinfo is None or as_of > now:
        raise ValueError('vip_query_as_of')
    segment = params.get('segment', ['all'])[0]
    scope = params.get('scope', ['uk_us'])[0]
    offset = int(params.get('offset', ['0'])[0])
    if offset < 0 or scope not in ('uk_us', 'global_preferred') or segment not in ('all', 'due', 'recent', 'unknown', 'refund'):
        raise ValueError('vip_query_window')
    preferred = scope == 'global_preferred'
    if preferred:
        from vip_followup import preferred_disposition, read_preferred_period
        period_reader = preferred_reader or read_preferred_period
    result = period_reader(start=start, end=end, now=as_of)
    included = []
    for buyer in result['buyers']:
        last = buyer.get('lastObservedOrder' if preferred else 'lastOrder') or {}
        if segment == 'refund' and not last.get('observedRefund'):
            continue
        if segment not in ('all', 'refund') and buyer['followUpStatus'] != segment:
            continue
        included.append(buyer)
    rows = []
    for buyer in included[offset:offset + 20]:
        last = buyer.get('lastOrder') or {}
        days = sorted({date.fromisoformat(order['paidAtShanghai'][:10]) for order in buyer['history']
                       if not preferred or preferred_disposition(order) == 'effective'})
        intervals = [(second - first).days for first, second in zip(days, days[1:])]
        row = {
            **{key: buyer.get(key) for key in ('buyerId','siteId','country','paymentCountries','windows',
                                               'daysSinceLastPaid','followUpStatus','paymentCoverage')},
            'orderContactEmail': buyer.get('email'), 'memberUid': buyer.get('uid'),
            'purchaseDaysObserved': len(days), 'medianGapDaysObserved': median(intervals) if intervals else None,
            'lastOrder': order_projection(last),
        }
        if preferred:
            observed = buyer.get('lastObservedOrder') or {}
            row.update(quality=buyer['quality'],
                       lastObservedOrder=dict(order_projection(observed), preferredDisposition=observed.get('preferredDisposition')),
                       checksBeforeContact=buyer.get('checksBeforeContact', []))
        rows.append(row)
    return {key: result.get(key) for key in ('status','asOfShanghai','windows','coverage','summary')} | {
        'splitMethod':result.get('splitMethod'), 'orderStateBasis':result.get('orderStateBasis'),
        'scope':scope, 'segment':segment, 'total':len(included), 'offset':offset,
        'next_offset':offset+len(rows) if offset+len(rows)<len(included) else None, 'items':rows,
    }
