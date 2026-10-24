"""Explicit model/goods field mapping and public-safe catalog projection."""
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

from .core import ContractError, Money, identity, source_identity, timestamp


def positive_id(value):
    if (type(value) not in (int, str) or not str(value).isascii()
            or not str(value).isdecimal() or len(str(value)) > 19 or int(value) < 1):
        raise ContractError('POSITIVE_ID_REQUIRED')
    return str(int(value))


def _switch(value):
    if type(value) not in (str, int) or value not in (0, 1, '0', '1'):
        raise ContractError('PRODUCT_SWITCH_UNKNOWN')
    return int(value)


def _reference_id(value):
    if type(value) in (int, str) and str(value) == '0':
        return '0'
    return positive_id(value)


def discover_product(row, site_id, game_id):
    """Observed Admin metadata only: no currency, availability or checkout inference."""
    if not isinstance(row, dict):
        raise ContractError('INVALID_PRODUCT_ROW')
    site_id, game_id = positive_id(site_id), positive_id(game_id)
    try:
        if (positive_id(row['site_id']) != site_id or positive_id(row['gid']) != game_id):
            raise ContractError('PRODUCT_SCOPE_MISMATCH')
        ref = dict(site_id=site_id, game_id=game_id, model_id=positive_id(row['mid']),
                   goods_id=positive_id(row['id']))
        title = identity(row['title'])
        minimum = positive_id(row['min_qty'])
        unit = row['unit']
        if not isinstance(unit, str) or len(unit) > 64 or any(ord(c) < 32 for c in unit):
            raise ContractError('PRODUCT_UNIT_UNKNOWN')
        status, buy_status = row['status'], row['buy_status']
        if any(type(value) not in (str, int) for value in (status, buy_status)):
            raise ContractError('PRODUCT_STATUS_UNKNOWN')
        return dict(product_ref=ref, title=title, platform_attribute_id=_reference_id(row['aid']),
            server_id=_reference_id(row['sid']), category_id=_reference_id(row['cid']),
            minimum_quantity=int(minimum), unit=unit, sku_switch=_switch(row['sku_switch']),
            attr_switch=_switch(row['attr_switch']), raw_status=status, raw_buy_status=buy_status,
            status_semantics='unknown', purchase_mapping_required=True,
            purchase_mapping_reasons=['PRODUCT_DETAIL_REQUIRED'], authoritative=False, checkout_enabled=False)
    except KeyError:
        raise ContractError('PRODUCT_METADATA_MISSING') from None


def read_product_metadata(model, goods, site_id, game_id):
    product = discover_product(goods, site_id, game_id)
    if (not isinstance(model, dict)
            or positive_id(model.get('id')) != product['product_ref']['model_id']):
        raise ContractError('MODEL_SCOPE_MISMATCH')
    if 'gid' in model and positive_id(model['gid']) != product['product_ref']['game_id']:
        raise ContractError('MODEL_SCOPE_MISMATCH')
    product['model_title'] = identity(model.get('title'))
    reasons = []
    sale_properties_observed = False
    specifications = {}
    for source, row in (('goods', goods), ('model', model)):
        more = row.get('more')
        if not isinstance(more, dict):
            reasons.append(source.upper() + '_SPEC_SCHEMA_UNKNOWN')
            continue
        specifications[source] = {}
        for key in ('saleprop', 'skuTableSet'):
            if key not in more:
                specifications[source][key] = dict(present=False)
                continue
            value = more[key]
            if not isinstance(value, (list, dict)):
                specifications[source][key] = dict(present=True, schema_status='unknown')
                reasons.append(source.upper() + '_SPEC_SCHEMA_UNKNOWN')
                continue
            if key == 'saleprop':
                sale_properties_observed = True
            # Empty observed containers have no IDs to invent. Nonempty shapes await exact mapping.
            specifications[source][key] = dict(present=True, schema_status='empty' if not value else 'mapping_required',
                                                entry_count=len(value))
            if value:
                reasons.append(source.upper() + '_SPEC_MAPPING_REQUIRED')
    if product['sku_switch']:
        reasons.append('SKU_SELECTION_MAPPING_REQUIRED')
    if not sale_properties_observed:
        reasons.append('SALE_PROPERTY_PRESENCE_UNKNOWN')
    if product['platform_attribute_id'] == '0':
        reasons.append('PLATFORM_ATTRIBUTE_MAPPING_REQUIRED')
    # attr_switch=1 alone does not imply selectable attributes; actual saleprop decides.
    if not product['sku_switch'] and not reasons:
        product['purchase_mapping_required'] = False
    product['purchase_mapping_reasons'] = sorted(set(reasons))
    product['specification_sources'] = specifications
    product['verification_scope'] = 'observed_admin_metadata_not_checkout_mapping'
    return product


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
