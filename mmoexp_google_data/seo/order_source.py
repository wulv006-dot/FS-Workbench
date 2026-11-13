"""Project already authorized private D2 facts into the existing nightly snapshot.

The injected reader must reuse selected shared facts; this module has no export,
credential, network or background-task capability. It never joins GA4 sessions.
"""
import datetime as dt
import hashlib
import json
from decimal import Decimal, InvalidOperation

from .contracts import game, GAME_IDS, SITE_ID
from .sources import SourceError

CONTRACT = 'admin-recorded-order-attribution-v1'


class OrderSource:
    name = 'orders'
    timezone = 'Asia/Shanghai'

    def __init__(self, read):
        self.read = read

    def pages(self, scope, day, cursor=0):
        game(scope)
        dt.date.fromisoformat(day)
        if cursor:
            raise SourceError('ORDER_FACTS_CURSOR_INVALID')
        value = self.read(scope, day)
        if value is None:
            raise SourceError('ORDER_FACTS_UNAVAILABLE')
        expected = dict(start=day, end=day, site_id=SITE_ID, gid=GAME_IDS[scope])
        source = value.get('source_coverage') or {}
        if (value.get('private') is not True or any(value.get('input_scope', {}).get(k) != v for k,v in expected.items())
                or source.get('admin_date_basis') != 'paytime'):
            raise SourceError('ORDER_FACTS_SCOPE_MISMATCH')
        rows = {}
        for row in value['orders']:
            if (row.get('site_id') != SITE_ID or row.get('gid') != GAME_IDS[scope]
                    or not str(row.get('paid_at') or '').startswith(day+' ')
                    or not row.get('order_no')):
                raise SourceError('ORDER_FACTS_MEMBER_SCOPE_MISMATCH')
            identity = hashlib.sha256(json.dumps([row['site_id'], row['order_no']],
                ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
            revenue = row.get('admin_paid_usd')
            if revenue is not None:
                try:
                    amount = Decimal(str(revenue))
                except InvalidOperation:
                    raise SourceError('ORDER_FACTS_AMOUNT_INVALID') from None
                if not amount.is_finite():
                    raise SourceError('ORDER_FACTS_AMOUNT_INVALID')
                revenue = str(amount)
            fact = dict(contract=CONTRACT, order_ref=identity, channel=row['channel'], revenue_usd=revenue)
            if identity in rows and rows[identity] != fact:
                raise SourceError('ORDER_FACTS_REVISION_CONFLICT')
            rows[identity] = fact
        complete = source.get('admin_complete') is True and not value.get('coverage', {}).get('unlinked_admin_rows')
        if not rows and not complete:
            raise SourceError('ORDER_FACTS_EMPTY_PARTIAL')
        attribution = source.get('attribution') or {}
        quality = dict(contract=CONTRACT, expected_total=len(rows), pagination_complete=True,
            admin_complete=complete, requested_scope=expected, payment_basis='admin_native_paid_selection',
            date_basis='paytime', currency='USD', revenue_basis='admin_paid_amount_not_net', fee_coverage='unknown',
            attribution_basis='admin_recorded_channel', source_revision=source.get('source_revision'),
            attribution_source_revision=attribution.get('source_revision'), data_revision=attribution.get('data_revision'),
            attribution_status=attribution.get('status', 'unavailable'),
            attribution_source_scope=attribution.get('effective_scope'),
            members_digest=hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest(),
            attribution_complete=complete and all(r['channel'] in ('SEO','Direct','PPC','Referral','Campaign') for r in rows.values()),
            order_session_link='unavailable')
        yield dict(rows=[dict(key=k, metrics=v) for k,v in sorted(rows.items())], next_cursor=None,
            source_timezone=self.timezone, status='available' if complete else 'partial', quality=quality)


def recorded_metrics(rows):
    """A deduplicated parent-order cohort; unknown income is never filled with zero."""
    unique = {}
    for row in rows:
        if row.get('contract') != CONTRACT:
            raise ValueError('MIXED_ORDER_ATTRIBUTION_CONTRACTS')
        key = row['order_ref']
        if key in unique and unique[key] != row:
            raise ValueError('CONFLICTING_PARENT_ORDER')
        unique[key] = row
    rows = list(unique.values())
    known = [r for r in rows if r['channel'] in ('SEO','Direct','PPC','Referral','Campaign')]
    seo = [r for r in known if r['channel'] == 'SEO']
    revenue_rows = [r for r in rows if r['revenue_usd'] is not None]
    known_revenue = sum((Decimal(r['revenue_usd']) for r in revenue_rows), Decimal(0))
    attributed_revenue = sum((Decimal(r['revenue_usd']) for r in known if r['revenue_usd'] is not None), Decimal(0))
    seo_revenue = sum((Decimal(r['revenue_usd']) for r in seo if r['revenue_usd'] is not None), Decimal(0))
    unknown = bool(rows) and not known
    missing_seo_revenue = sum(r['revenue_usd'] is None for r in seo)
    from .metrics import ratio
    return dict(contract=CONTRACT, paid_orders=len(rows), seo_orders=None if unknown else len(seo),
        seo_revenue_usd=None if unknown or missing_seo_revenue else str(seo_revenue),
        known_recorded_seo_revenue_usd=None if unknown else str(seo_revenue),
        missing_seo_revenue_orders=missing_seo_revenue,
        average_order_usd=None if missing_seo_revenue or unknown else ratio(seo_revenue, Decimal(len(seo))),
        attribution_coverage=ratio(Decimal(len(known)), Decimal(len(rows))),
        attribution_amount_coverage=ratio(attributed_revenue, known_revenue) if known_revenue > 0 and all(Decimal(r['revenue_usd'])>=0 for r in revenue_rows) else None,
        known_paid_revenue_usd=str(known_revenue), missing_revenue_orders=len(rows)-len(revenue_rows),
        attributed_orders=len(known), unknown_channel_orders=len(rows)-len(known),
        attribution_status='unknown' if unknown else 'partial' if len(known)<len(rows) else 'available',
        attribution_basis='admin_recorded_channel', revenue_basis='admin_paid_amount_not_net',
        fee_coverage='unknown', order_session_link='unavailable')
