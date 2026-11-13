"""Lossless native catalogue reader; no inferred custom-quantity or save rules.

The native payload is retained independently of the semantic price key. Neither
this reader nor its key certifies that an edited payload can be saved/published.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json


IDENTITY_FIELDS = ('id', 'mid', 'gid', 'cid', 'site_id', 'aid', 'unit', 'status')
NUMERIC_ARRAYS = ('gold', 'give', 'discount', 'price')
OBSERVATION_FIELDS = frozenset(('checked_at', 'captured_at', 'observed_at'))


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
                if k not in OBSERVATION_FIELDS}
    body = dict(native_payload=payload, native_contract=contract)
    raw = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                     allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()
