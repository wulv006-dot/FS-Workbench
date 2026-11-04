"""Deterministic same-grain metrics; unknown values never become zero."""
from decimal import Decimal


def number(value):
    value = Decimal(str(value))
    if not value.is_finite() or value < 0:
        raise ValueError('INVALID_METRIC')
    return value


def ratio(numerator, denominator):
    return str(numerator / denominator) if denominator else None


def compute_metrics(rows, contract):
    if contract == 'gsc':
        clicks = impressions = weighted = Decimal(0)
        for row in rows:
            clicks += number(row['clicks'])
            weight = number(row['impressions'])
            impressions += weight
            weighted += number(row['position']) * weight
        return dict(clicks=str(clicks), impressions=str(impressions),
                    ctr=ratio(clicks, impressions), position=ratio(weighted, impressions))
    if contract == 'ga4':
        sessions = engaged = Decimal(0)
        for row in rows:
            sessions += number(row['sessions'])
            engaged += number(row['engagedSessions'])
        return dict(sessions=str(sessions), engaged_sessions=str(engaged), engagement_rate=ratio(engaged, sessions))
    if contract == 'rankings':
        rows = list(rows)
        valid = [r for r in rows if r['status'] == 'found' or
                 (r['status'] == 'not_found' and r['effective_depth'] >= 10)]
        top = sum(r['status'] == 'found' and 0 < r['rank'] <= 10 for r in valid)
        return dict(top10=ratio(Decimal(top), Decimal(len(valid))),
                    coverage=ratio(Decimal(len(valid)), Decimal(len(rows))))
    if contract == 'orders':
        lines = {}
        for row in rows:
            key = row['order_ref'], row['line_ref']
            if key in lines and lines[key] != row:
                raise ValueError('CONFLICTING_ORDER_LINE')
            lines[key] = row
        paid = [r for r in lines.values() if r['paid']]
        orders = {r['order_ref'] for r in paid}
        seo = {r['order_ref'] for r in paid if r['attribution'] in ('A', 'B')}
        revenue = sum((number(r['revenue_usd']) for r in paid if r['attribution'] in ('A', 'B')), Decimal(0))
        known = {r['order_ref'] for r in paid if r['attribution'] in ('A', 'B', 'non_seo')}
        return dict(paid_orders=len(orders), seo_orders=len(seo), seo_revenue_usd=str(revenue),
                    average_order_usd=ratio(revenue, Decimal(len(seo))),
                    attribution_coverage=ratio(Decimal(len(known)), Decimal(len(orders))))
    raise ValueError('INVALID_METRIC_CONTRACT')
