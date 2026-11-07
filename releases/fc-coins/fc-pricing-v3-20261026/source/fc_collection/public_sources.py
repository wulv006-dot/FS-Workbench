"""Official independent ArabUT Console and PC public quotes; no account or writer."""
from decimal import Decimal
import json

from .contracts import fingerprint, instant, fresh, ARAB_WARM_PATHS

VERSIONS = {'ArabUT': 'arab-public-quote-collection-v3'}
ARAB_QUERY = dict(platform='playstation', delivery='normal', quantity='100000')
ARAB_PC_QUERY = dict(platform='pc', quantity='100000')
REGISTRY = {'ArabUT': {name:dict(host='www.arab-ut.com', path=path,
    query=dict(ARAB_QUERY, currency='USD'), max_bytes=2097153) for name,path in ARAB_WARM_PATHS.items()}}
REGISTRY['ArabUT']['quote'] = dict(host='www.arab-ut.com', path='/en/coins/quote', query=ARAB_QUERY, max_bytes=1048576)
REGISTRY['ArabUT']['quote_pc'] = dict(host='www.arab-ut.com', path='/en/coins/quote', query=ARAB_PC_QUERY, max_bytes=1048576)


def arab_offers(value, now, *, platform='playstation'):
    pc = platform == 'pc'
    if (platform not in ('playstation', 'pc') or not isinstance(value, dict)
            or not isinstance(value.get('total'), dict) or not isinstance(value.get('displayTotal'), dict)
            or value.get('platform') != platform or 'delivery' not in value
            or value['delivery'] != (None if pc else 'normal') or type(value.get('quantity')) is not int
            or value['quantity'] != 100000 or value.get('market') != ('pc' if pc else 'console')
            or value['total'].get('currency') != 'SAR' or value['displayTotal'].get('currency') != 'USD'
            or any(value.get(key, 0) != 0 for key in ('bonus', 'bonusQuantity'))
            or value.get('deliveredQuantity', 100000) != 100000):
        raise ValueError('arab_quote_selection_invalid')
    amount = value['displayTotal'].get('amountMinor')
    settlement = value['total'].get('amountHalalah')
    if type(amount) is not int or amount <= 0 or type(settlement) is not int or settlement <= 0:
        raise ValueError('arab_quote_amount_invalid')
    version = value.get('priceVersion')
    if not (type(version) is int and 0 <= version <= 2**63 - 1
            or isinstance(version, str) and 0 < len(version) <= 120):
        raise ValueError('arab_quote_version_invalid')
    fresh(value.get('pricedAt'), now)
    safe_evidence = {key: value[key] for key in ('platform', 'delivery', 'quantity', 'market',
                     'total', 'displayTotal', 'priceVersion', 'pricedAt')}
    digest = fingerprint(safe_evidence)
    common = dict(region_id=21, currency='USD', settlement_currency='SAR', conversion_source='official_display_quote',
        purchase_quantity='100', bonus_quantity='0', delivered_quantity='100', quantity_unit='K',
        amount=str(Decimal(amount) / 100), price_basis='public_merchandise', delivery_method='standard' if pc else 'normal',
        discount_source='official_no_coupon', coupon_excluded=True, auth_state='public', conditional=False,
        comparable=True, observed_at=instant(now).isoformat(), selection_verified=True, sanitized_evidence_ref='sha256:' + digest,
        source_metadata=dict(original_currency='SAR', original_amount_minor=settlement,
            price_version=version, priced_at=value['pricedAt'], original_platform=platform,
            original_market=value['market'], original_delivery=value['delivery']))
    return [dict(common, platform=p) for p in (('PC',) if pc else ('PS', 'XBOX'))]


def arab_payload(payload, now, platform):
    from .adapters import SourceUnavailable
    try:
        data = json.loads(payload)
    except (ValueError, TypeError, RecursionError):
        raise SourceUnavailable('arab_quote_html_response' if payload.lstrip().startswith(b'<') else 'arab_quote_json_invalid') from None
    if not isinstance(data, dict):
        raise SourceUnavailable('arab_quote_json_invalid')
    try:
        return arab_offers(data.get('data', data), now, platform=platform)
    except ValueError as exc:
        allowed = {'arab_quote_selection_invalid', 'arab_quote_amount_invalid', 'arab_quote_version_invalid',
                   'timestamp_invalid', 'observation_stale'}
        raise SourceUnavailable(str(exc) if str(exc) in allowed else 'arab_quote_contract_invalid') from None


def arab_adapter(task, transport):
    from .adapters import SourceUnavailable, WarmLanguageRedirect
    requested = set(task['requested_platforms'])
    if not requested or requested - {'PS', 'XBOX', 'PC'} or task['region_scope'] != [21]:
        raise ValueError('arab_quote_scope_invalid')
    try:
        transport.get('warm')
    except WarmLanguageRedirect as redirect:
        transport.get(redirect.template_id)
    offers, errors, retry_after = [], {}, 0
    groups = [('quote', 'playstation', requested & {'PS', 'XBOX'}), ('quote_pc', 'pc', requested & {'PC'})]
    blockers = {'http_401', 'http_403', 'http_429', 'challenge', 'captcha'}
    unknown = {'transport_unavailable', 'request_timeout', 'dns_unavailable'}
    for template, platform, platforms in groups:
        if not platforms:
            continue
        try:
            payload = transport.get(template)
            rows = arab_payload(payload, transport.clock(), platform)
            offers.extend(row for row in rows if row['platform'] in platforms)
        except (SourceUnavailable, OSError, TimeoutError) as exc:
            reason = str(exc) if isinstance(exc, SourceUnavailable) else 'transport_unavailable'
            errors.update({p: reason for p in sorted(platforms)})
            retry_after = max(retry_after, getattr(exc, 'retry_after_seconds', 0))
            if reason in blockers or reason in unknown:
                errors.update({p: reason if reason in blockers else 'origin_request_pending' for p in sorted(requested)
                               if p not in errors and not any(row['platform'] == p for row in offers)})
                break
    if not offers and requested <= {'PS', 'XBOX'}:
        raise SourceUnavailable(next(iter(errors.values())), retry_after)
    reason = next((value for value in errors.values() if value in blockers), next(iter(errors.values()), None))
    status = 'ok' if not errors else 'partial' if offers else 'blocked' if reason in blockers else 'failed'
    result = dict(status=status, reason_code=reason, offers=offers,
        evidence_hash=fingerprint([row['sanitized_evidence_ref'] for row in offers]))
    if errors:
        result['platform_errors'] = errors
    if retry_after:
        result['retry_after_seconds'] = retry_after
    return result
