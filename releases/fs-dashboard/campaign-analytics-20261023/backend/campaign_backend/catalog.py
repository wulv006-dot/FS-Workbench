"""Explicit model/goods field mapping and public-safe catalog projection."""
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from .core import ContractError, Money, identity, source_identity, timestamp


def field(row, path):
    try:
        for part in path.split('.'):
            row = row[part]
        return row
    except (KeyError, TypeError, AttributeError):
        raise ContractError('SOURCE_FIELD_MISSING') from None


def mapped(value, enums):
    # Preserve type distinctions: True and 1 must not become the same payment enum.
    for raw, normalized in enums:
        if type(value) is type(raw) and value == raw:
            return normalized
    raise ContractError('SOURCE_ENUM_UNKNOWN')


@dataclass(frozen=True)
class CatalogMapping:
    verification_ref: str
    goods_fields: dict
    model_fields: dict
    sale_states: tuple
    currency_scales: dict
    currency_code: str = None


def project_product(model, goods, mapping, purchase):
    """purchase is an independently verified normalized buying descriptor, never guessed from title."""
    identity(mapping.verification_ref)
    g = lambda key: field(goods, mapping.goods_fields[key])
    m = lambda key: field(model, mapping.model_fields[key])
    try:
        ref = {key: source_identity(g(key)) for key in ('site_id', 'game_id', 'model_id', 'goods_id')}
        if ref['site_id'] == '0' or ref['model_id'] != source_identity(m('model_id')):
            raise ContractError('PRODUCT_SCOPE_MISMATCH')
        if 'sku_id' in mapping.goods_fields:
            ref['sku_id'] = source_identity(g('sku_id'))
        title = identity(m('title'))
        available = mapped(g('sale_state'), mapping.sale_states)
        if type(available) is not bool:
            raise ContractError('INVALID_SALE_MAPPING')
        currency = g('currency') if 'currency' in mapping.goods_fields else mapping.currency_code
        if mapping.currency_code is not None and mapping.currency_code != currency:
            raise ContractError('CURRENCY_MAPPING_CONFLICT')
        price = Money.parse(g('price'), currency, mapping.currency_scales)
        timestamp(purchase['captured_at'])
        identity(purchase['catalog_version'])
        identity(purchase['verification_ref'])
        platform = purchase['platform']
        platform = {key: identity(platform[key]) for key in ('code', 'attribute_id', 'label')}
        if source_identity(g('platform_attribute_id')) != platform['attribute_id']:
            raise ContractError('PLATFORM_SCOPE_MISMATCH')
        quantity = purchase['quantity']
        if (set(quantity) - {'unit', 'minimum', 'step', 'group'}
                or type(quantity['minimum']) is not int or quantity['minimum'] < 1
                or type(quantity['step']) is not int or quantity['step'] < 1):
            raise ContractError('INVALID_QUANTITY')
        identity(quantity['unit'])
        if 'group' in quantity:
            identity(quantity['group'])
        attributes = []
        seen = set()
        for attribute in purchase['attributes']:
            aid = identity(attribute['attribute_id'])
            if aid in seen:
                raise ContractError('DUPLICATE_ATTRIBUTE')
            seen.add(aid)
            values = [{key: identity(v[key]) for key in ('value_id', 'label')}
                      for v in attribute['values']]
            if not values or len({v['value_id'] for v in values}) != len(values):
                raise ContractError('INVALID_ATTRIBUTE_VALUES')
            if type(attribute['required']) is not bool:
                raise ContractError('INVALID_ATTRIBUTE')
            attributes.append(dict(attribute_id=aid, required=attribute['required'], values=values))
        urls = {}
        for key in ('image_url', 'product_url'):
            if purchase.get(key):
                parsed = urlsplit(purchase[key])
                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                    raise ContractError('INVALID_PUBLIC_URL')
                urls[key] = purchase[key]
        return dict(product_ref=ref, title=title, platform=platform, quantity=dict(quantity),
                    attributes=attributes, price=asdict(price), availability={'available': available},
                    catalog_version=purchase['catalog_version'], captured_at=purchase['captured_at'],
                    authoritative=False, **urls)
    except (KeyError, TypeError, AttributeError):
        raise ContractError('CATALOG_MAPPING_REQUIRED') from None
