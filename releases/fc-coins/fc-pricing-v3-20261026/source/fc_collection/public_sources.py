"""The existing official ArabUT normal quote contract; no account or business runtime."""
from decimal import Decimal
import json

from .contracts import fingerprint, instant

VERSIONS = {'ArabUT': 'arab-public-quote-collection-v1'}
ARAB_QUERY = dict(platform='playstation', delivery='normal', quantity='100000')
REGISTRY = {'ArabUT': {
    'warm': dict(host='www.arab-ut.com', path='/', query=dict(ARAB_QUERY, currency='USD'), max_bytes=2097153),
    'quote': dict(host='www.arab-ut.com', path='/coins/quote', query=ARAB_QUERY, max_bytes=1048576)}}


def arab_offers(value, now):
    if (not isinstance(value, dict) or not isinstance(value.get('total'), dict)
            or not isinstance(value.get('displayTotal'), dict) or value.get('platform') != 'playstation'
            or value.get('delivery') != 'normal' or type(value.get('quantity')) is not int
            or value['quantity'] != 100000 or value.get('market') != 'console'
            or value.get('total', {}).get('currency') != 'SAR'
            or value.get('displayTotal', {}).get('currency') != 'USD'):
        raise ValueError('arab_quote_selection_invalid')
    amount = value['displayTotal'].get('amountMinor')
    settlement = value['total'].get('amountHalalah')
    if type(amount) is not int or amount <= 0 or type(settlement) is not int or settlement <= 0:
        raise ValueError('arab_quote_amount_invalid')
    if not isinstance(value.get('priceVersion'), str) or not value['priceVersion'] or len(value['priceVersion']) > 120:
        raise ValueError('arab_quote_version_invalid')
    instant(value.get('pricedAt'))
    safe_evidence = {key: value[key] for key in ('platform', 'delivery', 'quantity', 'market',
                     'total', 'displayTotal', 'priceVersion', 'pricedAt')}
    digest = fingerprint(safe_evidence)
    common = dict(region_id=21, currency='USD', settlement_currency='SAR', conversion_source='official_display_quote',
        purchase_quantity='100', bonus_quantity='0', delivered_quantity='100', quantity_unit='K',
        amount=str(Decimal(amount) / 100), price_basis='public_merchandise', delivery_method='normal',
        discount_source='official_no_coupon', coupon_excluded=True, auth_state='public', conditional=False,
        comparable=True, observed_at=instant(now).isoformat(), selection_verified=True, sanitized_evidence_ref='sha256:' + digest)
    return [dict(common, platform=platform) for platform in ('PS', 'XBOX')]


def arab_adapter(task, transport):
    if task['requested_platforms'] != ['PS', 'XBOX'] or task['region_scope'] != [21]:
        raise ValueError('arab_quote_scope_invalid')
    transport.get('warm')
    try:
        data = json.loads(transport.get('quote'))
    except (ValueError, TypeError, RecursionError):
        raise ValueError('arab_quote_JSON_invalid') from None
    if not isinstance(data, dict):
        raise ValueError('arab_quote_JSON_invalid')
    value = data.get('data', data)
    offers = arab_offers(value, transport.clock())
    return dict(status='ok', reason_code=None, offers=offers,
                evidence_hash=offers[0]['sanitized_evidence_ref'].removeprefix('sha256:'))
