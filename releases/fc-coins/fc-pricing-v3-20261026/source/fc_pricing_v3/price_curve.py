"""Lossless native catalogue reader and offline Admin editor compilation.

The native payload is retained independently of the semantic price key. Neither
this reader nor its key certifies that an edited payload can be saved/published.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
from math import isfinite


IDENTITY_FIELDS = ('id', 'mid', 'gid', 'cid', 'site_id', 'aid', 'unit', 'status')
NUMERIC_ARRAYS = ('gold', 'give', 'discount', 'price')
OBSERVATION_FIELDS = frozenset(('checked_at', 'captured_at', 'observed_at'))
CATALOGUE_ORIGIN_FIELD = 'catalogue_origin'
EDITOR_CATALOGUE_ORIGIN = 'editor_candidate'
EDITOR_ASSET_SHA256 = '859f07a7dadc48054b740ee09b66c494d11bcb0fef1faf5ecd0a9c6d0b98dfe7'
EDITOR_HANDLER_SHA256 = 'c9341a511d39a79736e6d7e7147654c8c24202b928954e11b1a13ed7a612b451'
EDITOR_UNVERIFIED_DOMAINS = ('admin_save', 'all_site_propagation', 'order_projection',
                             'customer_checkout_quote', 'custom_quantity',
                             'cart_multiplier', 'offer_paths')


def _number(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError('curve_number_invalid')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('curve_number_invalid') from None
    if not result.is_finite() or result < 0 or positive and result == 0:
        raise ValueError('curve_number_invalid')
    # Fixed notation and equivalent decimal representations share one key.
    text = format(result, 'f')
    return (text.rstrip('0').rstrip('.') if '.' in text else text) if result else '0'


def _more(goods):
    value = goods.get('more')
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError('curve_more_invalid')
    arrays = [value.get(key) for key in NUMERIC_ARRAYS]
    if any(not isinstance(a, list) or not a for a in arrays):
        raise ValueError('curve_tiers_invalid')
    if len({len(a) for a in arrays}) != 1:
        raise ValueError('curve_tiers_invalid')
    return value


def read_curve(native_goods, identity, native_contract):
    """Read exact native prices without multiplying unit_price or discounts.

    identity is the caller's verified expected Goods identity, not inferred from
    the row. native_contract retains the caller's source/domain evidence, which
    may explicitly be incomplete. Unknown native fields survive in payload.
    """
    if not isinstance(native_goods, dict) or not isinstance(identity, dict):
        raise ValueError('curve_identity_invalid')
    if any(key not in identity or str(native_goods.get(key)) != str(identity[key])
           for key in IDENTITY_FIELDS):
        raise ValueError('curve_identity_mismatch')
    if identity['unit'] != 'K' or str(identity['status']) != '1':
        # Same exact identity domain as coin_all_sync_job.read_row; the six
        # real rows were recorded with unit=K/status=1 in MASTER appendix B 3.3.
        raise ValueError('curve_identity_inactive_or_unit')
    if not isinstance(native_contract, dict):
        raise ValueError('curve_native_contract_invalid')
    more = _more(native_goods)
    tiers, seen = [], set()
    for index, values in enumerate(zip(*(more[key] for key in NUMERIC_ARRAYS))):
        quantity, bonus, discount, price = values
        quantity = _number(quantity, positive=True)
        if quantity in seen:
            raise ValueError('curve_duplicate_quantity')
        seen.add(quantity)
        tiers.append(dict(native_index=index, purchase_k=quantity,
                          promised_bonus_k=_number(bonus),
                          native_discount=_number(discount),
                          native_price_usd=_number(price, positive=True)))
    return dict(contract='fc-native-price-curve-v1',
                identity={key: str(identity[key]) for key in IDENTITY_FIELDS},
                unit_price_usd_per_k=_number(native_goods.get('unit_price'), positive=True),
                tiers=tiers, native_payload=deepcopy(native_goods),
                native_contract=deepcopy(native_contract),
                quotation_status='native_semantics_not_evaluated')


def _editor_fixed(value, places):
    """Number(value.toFixed(places)) for finite non-negative binary64 values."""
    if value >= 1e21:
        return value
    # toFixed rounds the exact binary value to nearest, with ties upward.
    # Multiplying the float by 10**places first would round it a second time.
    numerator, denominator = value.as_integer_ratio()
    scale = 10 ** places
    rounded, remainder = divmod(numerator * scale, denominator)
    if remainder * 2 >= denominator:
        rounded += 1
    whole, fraction = divmod(rounded, scale)
    return float(f'{whole}.{fraction:0{places}d}')


def _editor_price(subtotal, discount):
    return _editor_fixed(subtotal * (discount / 100), 2)


def _editor_discount_input(discount):
    return .01 <= discount <= 100 and _editor_fixed(discount, 2) == discount


def _editor_discount(subtotal, price):
    """Find a two-place Je input whose oe result exactly matches price."""
    # Start with Ke's inverse, including its normalization near 100. The
    # observed direct Je input supports .01–100. A larger Ke result is outside
    # this evidence, even though the pure function can return it.
    inverse = price / subtotal * 100
    if isfinite(inverse):
        discount = _editor_fixed(inverse, 2)
        if 100 < discount <= 100.05:
            discount = 100.0
        if _editor_discount_input(discount) and _editor_price(subtotal, discount) == price:
            return discount

    # At a rounding edge, check the exact native grid. oe is monotone on
    # this grid, and any returned discount is verified at the requested cent.
    low, high = 1, 10000
    while low <= high:
        middle = (low + high) // 2
        discount = middle / 100
        computed = _editor_price(subtotal, discount)
        if computed == price:
            return discount
        if computed < price:
            low = middle + 1
        else:
            high = middle - 1
    return None


def _editor_gap(code, **detail):
    return dict(compilation_status='PROOF_INCOMPLETE',
                gaps=[dict(code=code, **detail)],
                unverified_domains=list(EDITOR_UNVERIFIED_DOMAINS))


def _editor_target(value, places):
    normalized = _number(value, positive=True)
    if len(normalized.partition('.')[2]) > places:
        raise ValueError('editor_target_precision')
    number = float(normalized)
    if not isfinite(number) or _number(number) != normalized:
        raise ValueError('editor_target_number_unrepresentable')
    return number


def compile_curve(current, segment_targets, native_contract):
    """Compile exact segment anchors into a full, offline editor candidate.

    ``current`` is a read_curve result. ``segment_targets`` accepts
    ``anchor_prices_usd`` (optional mapping from 100/1000/explicit 2000 K
    anchors to exact USD cents) and ``unit_price_usd_per_k`` (optional explicit
    Admin unit price, at most eight decimals). The 100K control covers the
    entire small segment. Omitted segments keep each saved tier amount.

    The evidence is scoped to the matching popup editor asset and handler
    excerpt. Backend saves, site propagation, checkout and Order projection
    need their own evidence. PROOF_INCOMPLETE carries no candidate payload.
    """
    if (not isinstance(native_contract, dict)
            or native_contract.get('editor_asset_sha256') != EDITOR_ASSET_SHA256
            or native_contract.get('editor_handler_sha256') != EDITOR_HANDLER_SHA256):
        return _editor_gap('editor_contract_evidence_missing_or_mismatched')
    captured_contract = current['native_contract']
    if any(key in captured_contract and captured_contract[key] != native_contract[key]
           for key in ('editor_asset_sha256', 'editor_handler_sha256')):
        return _editor_gap('editor_contract_evidence_missing_or_mismatched')
    if (not isinstance(segment_targets, dict)
            or segment_targets.keys() - {'anchor_prices_usd', 'unit_price_usd_per_k'}):
        raise ValueError('editor_segment_targets_invalid')
    requested = segment_targets.get('anchor_prices_usd', {})
    if not isinstance(requested, dict):
        raise ValueError('editor_segment_targets_invalid')
    anchors = {}
    for quantity, price in requested.items():
        quantity = _number(quantity, positive=True)
        if quantity not in ('100', '1000', '2000') or quantity in anchors:
            raise ValueError('editor_segment_anchor_invalid')
        try:
            anchors[quantity] = _editor_target(price, 2)
        except ValueError as exc:
            return _editor_gap(str(exc), anchor_k=quantity)

    checked = read_curve(current['native_payload'], current['identity'], native_contract)
    tiers = checked['tiers']
    by_quantity = {tier['purchase_k']: i for i, tier in enumerate(tiers)}
    for quantity in anchors:
        if quantity not in by_quantity:
            return _editor_gap('editor_segment_anchor_missing', anchor_k=quantity)
    payload = checked['native_payload']
    more = _more(payload)
    unit = float(checked['unit_price_usd_per_k'])
    if 'unit_price_usd_per_k' in segment_targets:
        try:
            unit = _editor_target(segment_targets['unit_price_usd_per_k'], 8)
        except ValueError as exc:
            return _editor_gap(str(exc), field='unit_price_usd_per_k')

    quantities = [float(tier['purchase_k']) for tier in tiers]
    subtotals = [unit * quantity for quantity in quantities]
    if any(not isfinite(value) or value <= 0 for value in subtotals):
        return _editor_gap('editor_native_number_unrepresentable')
    if any(left >= right for left, right in zip(quantities, quantities[1:])):
        return _editor_gap('editor_native_order_not_ascending')

    segment_discounts = {}
    for anchor, target in anchors.items():
        subtotal = subtotals[by_quantity[anchor]]
        discount = _editor_discount(subtotal, target)
        if discount is None:
            return _editor_gap('editor_anchor_not_expressible', anchor_k=anchor,
                               required_usd=_number(target))
        segment_discounts[anchor] = discount

    unit_changed = ('unit_price_usd_per_k' in segment_targets
                    and _number(unit) != checked['unit_price_usd_per_k'])
    discount_changes = []
    if anchors or unit_changed:
        # W recalculates even the lower tiers after Je. Work out the controls
        # needed to retain the original cents of every unselected tier.
        discounts = more['discount']
        for i, (tier, subtotal) in enumerate(zip(tiers, subtotals)):
            quantity = quantities[i]
            anchor = '100' if quantity < 1000 else '1000'
            if quantity >= 2000 and '2000' in anchors:
                anchor = '2000'
            expected = tier['native_price_usd']
            discount = segment_discounts.get(anchor)
            if discount is None:
                discount = float(tier['native_discount'])
                original_price = _editor_price(subtotal, discount)
                original_control_retained = _number(discounts[i]) == tier['native_discount']
                if (not isfinite(original_price) or _number(original_price) != expected
                        or not (original_control_retained or _editor_discount_input(discount))):
                    discount = _editor_discount(subtotal, float(expected))
                if discount is None:
                    return _editor_gap('editor_untouched_tier_not_expressible',
                                       purchase_k=tier['purchase_k'], required_usd=expected)

            if _number(discounts[i]) != _number(discount):
                # Je applies one control to this index and all following
                # indexes. Later controls restore/override from low to high.
                if not _editor_discount_input(discount):
                    return _editor_gap('editor_discount_input_domain_unverified',
                                       purchase_k=tier['purchase_k'],
                                       discount=_number(discount))
                discounts[i:] = [discount] * (len(tiers) - i)
            final_discount = _number(discounts[i])
            if final_discount != tier['native_discount']:
                discount_changes.append(dict(purchase_k=tier['purchase_k'],
                                             before=tier['native_discount'],
                                             after=final_discount,
                                             source='segment_anchor' if anchor in anchors
                                             else 'preserve_saved_tier_price'))

            price = _editor_price(subtotal, float(final_discount))
            if not isfinite(price) or price <= 0:
                return _editor_gap('editor_tier_price_outside_reader_domain',
                                   purchase_k=tier['purchase_k'])
            if anchor not in anchors and _number(price) != expected:
                return _editor_gap('editor_untouched_tier_not_expressible',
                                   purchase_k=tier['purchase_k'], required_usd=expected)
            if tier['purchase_k'] in anchors and price != anchors[tier['purchase_k']]:
                return _editor_gap('editor_anchor_not_expressible', anchor_k=anchor,
                                   required_usd=_number(anchors[anchor]))
            more['price'][i] = price

        if unit_changed:
            payload['unit_price'] = unit
        if isinstance(payload['more'], str):
            payload['more'] = json.dumps(more, ensure_ascii=False, separators=(',', ':'))

    candidate_contract = dict(native_contract, catalogue_origin=EDITOR_CATALOGUE_ORIGIN)
    result = read_curve(payload, checked['identity'], candidate_contract)
    tier_100 = by_quantity.get('100')
    base_rate = (None if tier_100 is None else
                 _number(Decimal(result['tiers'][tier_100]['native_price_usd'] + 'e-2')))
    result.update(compilation_status='EDITOR_CANDIDATE', discount_changes=discount_changes,
                  base_rate_usd_per_k=base_rate,
                  base_rate_basis='candidate_100k_regular_usd_div_100',
                  unverified_domains=list(EDITOR_UNVERIFIED_DOMAINS))
    return result


def quote_native(curve, order_context):
    """Project one explicit USD catalogue tier from the exact Goods row.

    Context supplies per-item purchase_k, integer multiplier, site_id and
    currency. It can also supply promised_bonus_k for historical comparison,
    region_id for an override, and offer_path for a requested checkout path.
    A regular amount and promised quantities are available for a matched tier
    only, and applies to Admin ALL/site0 and MMOEXP/site266. Checkout,
    net receipt, fees and offer rules remain unverified. A saved tier is
    only the caller's frozen readback; this function cannot authenticate it.
    """
    if not isinstance(order_context, dict):
        raise ValueError('native_quote_context_invalid')
    checked = read_curve(curve['native_payload'], curve['identity'], curve['native_contract'])
    identity = checked['identity']
    result = dict(regular_usd=None, net_receipt_usd=None, purchase_k=None,
                  promised_bonus_k=None, promised_delivered_k=None, known_fee_usd=None,
                  fee_status='unknown', native_tier_or_rule=None, rounding_contract=None,
                  offer_version=None, proof_status='PROOF_INCOMPLETE',
                  catalogue_status='unavailable', site_id=identity['site_id'],
                  goods_id=identity['id'], currency=None, amount_kind=None, gaps=[])
    gaps = result['gaps']
    if str(order_context.get('site_id')) != identity['site_id']:
        gaps.append('catalogue_site_mismatch')
    elif identity['site_id'] not in ('0', '266'):
        gaps.append('catalogue_site_currency_unverified')
    if order_context.get('currency') != 'USD':
        gaps.append('currency_projection_unverified')
    region = order_context.get('region_id')
    if region is not None and str(region) != '0':
        gaps.append('regional_projection_unverified')
    multiplier = order_context.get('multiplier')
    if type(multiplier) is not int or multiplier < 1:
        gaps.append('native_quote_multiplier_invalid')
    elif multiplier != 1:
        gaps.append('cart_multiplier_unverified')
    try:
        purchase = _number(order_context.get('purchase_k'), positive=True)
    except ValueError:
        gaps.append('native_quote_quantity_invalid')
        return result
    tier = next((tier for tier in checked['tiers'] if tier['purchase_k'] == purchase), None)
    if tier is None:
        gaps.append('custom_quantity_unverified')
    if tier is not None and 'promised_bonus_k' in order_context:
        try:
            expected_bonus = _number(order_context['promised_bonus_k'])
        except ValueError:
            gaps.append('native_quote_bonus_invalid')
        else:
            if expected_bonus != tier['promised_bonus_k']:
                gaps.append('catalogue_bonus_mismatch')
    if gaps:
        return result

    bonus = tier['promised_bonus_k']
    with localcontext() as context:
        context.prec = max(len(purchase.partition('.')[0]), len(bonus.partition('.')[0])) + max(
            len(purchase.partition('.')[2]), len(bonus.partition('.')[2])) + 1
        delivered = _number(Decimal(purchase) + Decimal(bonus))
    editor_candidate = (curve.get('compilation_status') == 'EDITOR_CANDIDATE'
                        or checked['native_contract'].get(CATALOGUE_ORIGIN_FIELD)
                        == EDITOR_CATALOGUE_ORIGIN)
    result.update(regular_usd=tier['native_price_usd'], purchase_k=purchase,
                  promised_bonus_k=bonus, promised_delivered_k=delivered,
                  native_tier_or_rule=f"goods.more.price[{tier['native_index']}]",
                  rounding_contract=('admin_editor_tofixed2' if editor_candidate
                                     else 'admin_saved_tier_amount_as_read'),
                  catalogue_status='editor_candidate_tier' if editor_candidate else 'saved_tier',
                  curve_key=curve_key(checked), currency='USD', amount_kind='TOTAL')
    gaps.extend(('customer_checkout_unverified', 'offer_path_unverified', 'necessary_fee_unverified'))
    return result


def curve_key(curve):
    """Business price/spec key, not a raw-byte hash or a writer CAS receipt.

    Preserve unknown native controls until the quote contract classifies them.
    Exclude capture timestamps and the same server metadata that the existing
    coin_all_sync_job.editable already excludes. This is not yet a certified
    minimal economic-equivalence key for unknown native fields. Contract
    semantics and region projection versions remain part of the key.
    """
    # Re-read the original payload so callers cannot make the convenience tier
    # projection disagree silently with the authoritative native arrays.
    checked = read_curve(curve['native_payload'], curve['identity'], curve['native_contract'])
    payload = deepcopy({key: value for key, value in checked['native_payload'].items()
                        if not key.startswith(('_', 'stat_')) and value is not None})
    payload['more'] = deepcopy(_more(payload))
    for key in NUMERIC_ARRAYS:
        payload['more'][key] = [_number(v, positive=key in ('gold', 'price'))
                               for v in payload['more'][key]]
    payload['unit_price'] = checked['unit_price_usd_per_k']
    # Retain unknown native controls conservatively rather than silently
    # declaring two potentially different native quote rules equivalent.
    for key in OBSERVATION_FIELDS | {'update_time', 'updated_at', 'updatetime',
                                     'create_time', 'createtime'}:
        payload.pop(key, None)
    for key in IDENTITY_FIELDS:
        payload[key] = checked['identity'][key]
    if 'discount' in payload:
        payload['discount'] = _number(payload['discount'])
    contract = {k: v for k, v in checked['native_contract'].items()
                if k not in OBSERVATION_FIELDS and k != CATALOGUE_ORIGIN_FIELD}
    body = dict(native_payload=payload, native_contract=contract)
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                     allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
