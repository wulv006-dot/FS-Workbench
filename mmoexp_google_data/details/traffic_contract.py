"""Confirmed traffic rules; no source query or business execution authority."""
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re

RULE_VERSION = 'traffic-admin-first-20261017-v2'
GLOBAL_BRAND = 'fc27-pmax-coins-us'


def campaign_scope(name):
    raw = name if isinstance(name, str) else ''
    normalized = re.sub(r'^(?:google|bing)-', '', raw.strip(), flags=re.I).casefold()
    if normalized == GLOBAL_BRAND:
        return {'campaign_scope': 'global_brand', 'game_target': None,
                'basis': '用户2026-10-17明确确认：主站全局品牌投放', 'rule_version': RULE_VERSION}
    match = content_match_basis(raw)
    return {'campaign_scope': 'project' if match else 'unmatched',
            'game_target': 'FC27' if match else None, 'basis': match, 'rule_version': RULE_VERSION}


def content_match_basis(value):
    if not isinstance(value, str): return None
    if re.search(r'fc[\s_-]*27(?!\d)', value, re.I): return 'FC27名称'
    if re.search(r'(?<![a-z0-9])(?:madden(?:[\s_-]*nfl)?|nba[\s_-]*2k|mlb|nhl|cfb|diablo|d[234]|path[\s_-]*of[\s_-]*exile|poe|aion|wow|world[\s_-]*of[\s_-]*warcraft|osrs|runescape|eso|lost[\s_-]*ark|maplestory|albion|new[\s_-]*world|ffxiv)(?:[\s_-]*\d+)?(?![a-z0-9])', value, re.I): return None
    if not re.search(r'fc[\s_-]*\d+', value, re.I) and re.search(r'(?<![a-z0-9])coins(?![a-z0-9])', value, re.I): return 'Coins词条'
    return None


def source_value(admin, order):
    return (admin, 'Admin') if admin is not None else (order, 'Order' if order is not None else None)


def main_site_values(admin):
    """Use the existing verified website row; never relabel the all-site total."""
    channels = (admin.get('dimensions') or {}).get('channels') or []
    matches = [r for r in channels if (r.get('code') or r.get('name')) == 'www.mmoexp.com']
    if len(matches) == 1:
        values = {k: matches[0].get(k) for k in ('orders', 'revenueUsd')}
        for key, value in values.items():
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                values[key] = None
                continue
            try: amount = Decimal(str(value))
            except InvalidOperation:
                values[key] = None
                continue
            if not amount.is_finite() or amount < 0 or key == 'orders' and amount != int(amount): values[key] = None
        return {'values': values, 'scope': 'MMOEXP主站（Admin渠道www.mmoexp.com）', 'basis': 'unique_admin_website_row', 'distribution_group_exclusion': 'not_verified_by_website_row_alone'}
    metrics = admin.get('metrics') or {}
    if not channels and all(type((metrics.get(k) or {}).get('value')) in (int, float) and (metrics.get(k) or {}).get('value') == 0 for k in ('orders', 'revenueUsd')):
        return {'values': {'orders': 0, 'revenueUsd': 0}, 'scope': 'MMOEXP主站（Admin全零）', 'basis': 'admin_zero_without_site_rows', 'distribution_group_exclusion': 'not_verified_by_website_row_alone'}
    return {'values': {}, 'scope': 'Admin原统计范围；主站/排除分销尚未单独核实', 'basis': 'main_website_row_unavailable'}


def order_source(raw):
    if raw is None or isinstance(raw, str) and not raw.strip():
        return {'source_raw': raw, 'category': 'business_natural', 'label': '自然流量（业务默认）', 'verified_seo': False}
    if not isinstance(raw, str): raise ValueError('source_label_required')
    return {'source_raw': raw, 'category': 'advertising', **campaign_scope(raw)}


def closed_range(start, end_exclusive):
    lo, hi = date.fromisoformat(start), date.fromisoformat(end_exclusive)
    if lo.isoformat() != start or hi.isoformat() != end_exclusive or not 0 < (hi-lo).days <= 366:
        raise ValueError('half_open_period_required')
    return start, (hi-timedelta(days=1)).isoformat()


def revenue_decomposition(before_orders, before_revenue, after_orders, after_revenue):
    values = [Decimal(str(v)) for v in (before_orders, before_revenue, after_orders, after_revenue)]
    if not all(v.is_finite() and v >= 0 for v in values): raise ValueError('nonnegative_finite_required')
    n0, r0, n1, r1 = values
    if n0 != int(n0) or n1 != int(n1): raise ValueError('integer_orders_required')
    if not n0 or not n1: return {'status': 'unavailable', 'reason': 'zero_order_denominator'}
    a0, a1 = r0/n0, r1/n1
    return {'status': 'available', 'revenue_delta': str(r1-r0),
            'order_contribution': str((n1-n0)*(a0+a1)/2),
            'aov_contribution': str((a1-a0)*(n0+n1)/2),
            'rule': '对称数值分解；不证明流量、售价或履约原因'}
