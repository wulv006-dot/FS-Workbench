"""Derivative-product purchase basis: confirmed Admin main-site 100K / 100."""
from decimal import Decimal, InvalidOperation
import json

PRODUCTS = {'PS': (163329311, 21587), 'XBOX': (163329277, 21585),
            'PC': (163329345, 21589)}


def read_purchase_rates(manager=None):
    if manager is None:
        from fc_shared_admin import SessionManager, read_private_config
        manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError('admin_100k_identity_unconfirmed')
    rates, errors = {}, {}
    for platform, (product, _) in PRODUCTS.items():
        try:
            status, raw = manager.request('/admin/goods.Goods/edit?id=' + str(product))
            value = json.loads(raw)
            if status != 200 or not isinstance(value, dict) or value.get('code') not in (1, '1'):
                raise ValueError('admin_100k_read_unconfirmed')
            rates[platform] = str(purchase_rate(value['data']['row'], platform))
        except (ValueError, KeyError, TypeError, OSError) as exc:
            # Do not log response bodies, credentials, or fall back to stale Order rates.
            errors[platform] = type(exc).__name__
    return rates, errors


def purchase_rate(row, platform):
    product, area = PRODUCTS[platform]
    expected = dict(id=product, mid=41217957, gid=1327, cid=9623,
                    site_id=266, aid=area, unit='K', status=1)
    if not isinstance(row, dict) or any(str(row.get(k)) != str(v) for k, v in expected.items()):
        raise ValueError('admin_100k_product_identity_mismatch:' + platform)
    return tier_purchase_rate(row.get('more'), platform)


def tier_purchase_rate(more, platform):
    if not isinstance(more, dict):
        raise ValueError('admin_100k_tier_missing:' + platform)
    gold, prices = more.get('gold'), more.get('price')
    if not isinstance(gold, list) or not isinstance(prices, list) or len(gold) != len(prices):
        raise ValueError('admin_100k_tier_invalid:' + platform)
    try:
        indices = [i for i, quantity in enumerate(gold) if Decimal(str(quantity)) == 100]
        if len(indices) != 1:
            raise ValueError('admin_100k_tier_not_unique:' + platform)
        price = Decimal(str(prices[indices[0]]))
        if not price.is_finite() or price <= 0:
            raise ValueError('admin_100k_price_invalid:' + platform)
    except (InvalidOperation, TypeError):
        raise ValueError('admin_100k_price_invalid:' + platform) from None
    return price / 100
