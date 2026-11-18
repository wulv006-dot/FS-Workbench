"""Bounded, credential-free observations; freshness is checked again at consumption."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

SOURCES = {'ItemD2R', 'Lootbar', 'ArabUT'}
ARAB_CONSOLE_DELIVERIES = ('normal', 'fast')
ARAB_WARM_PATHS = {'warm':'/', 'warm_en':'/en', 'warm_en_slash':'/en/', 'warm_ar':'/ar', 'warm_ar_slash':'/ar/'}
ARAB_PRICE_TABLE = dict(host='arab-ut.com', path='/en/coins/prices', max_bytes=2097153)
ARAB_TABLE_QUANTITIES = ('100', '1000', '2000', '5000')
ARAB_TABLE_SCOPE = dict(purchase_quantities=list(ARAB_TABLE_QUANTITIES), quantity_unit='K')
PLATFORMS = {'PS', 'XBOX', 'PC'}
CONTEXT = {'requested_platforms', 'region_scope', 'quantity_scope', 'discount_scope',
           'currency', 'policy_version', 'adapter_version', 'assignment_generation',
           'total_attempt_limit', 'total_request_budget'}
BINDING = ('job_id', 'parent_run_id', 'source_id', 'task_context_hash', 'policy_version',
           'adapter_version', 'assignment_generation', 'attempt_id', 'lease_epoch', 'node_id', 'node_boot_id')
OBSERVATION = set(BINDING) | {'schema_version', 'observation_id', 'status', 'reason_code',
    'request_budget_used', 'evidence_hash', 'capture_started_at', 'capture_finished_at', 'offers'}
OFFER = {'platform', 'region_id', 'currency', 'settlement_currency', 'conversion_source',
    'purchase_quantity', 'bonus_quantity', 'delivered_quantity', 'quantity_unit', 'amount',
    'price_basis', 'delivery_method', 'discount_source', 'coupon_excluded', 'auth_state',
    'conditional', 'comparable', 'observed_at', 'selection_verified', 'sanitized_evidence_ref'}


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode('utf-8')).hexdigest()


def instant(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError, OverflowError):
        raise ValueError('timestamp_invalid') from None


def label(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}', value):
        raise ValueError('identifier_invalid')
    return value


def integer(value, minimum=1, maximum=10000):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('integer_invalid')
    return value


def decimal(value, zero=False):
    try:
        if not isinstance(value, str) or not re.fullmatch(r'\d{1,12}(?:\.\d{1,12})?', value):
            raise ValueError()
        result = Decimal(value)
        if not result.is_finite() or result < 0 or (not zero and result == 0):
            raise ValueError()
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('decimal_invalid') from None


def quantity(value, unit, zero=False):
    if unit not in ('K', 'coin'):
        raise ValueError('quantity_unit_invalid')
    return decimal(value, zero) / (1000 if unit == 'coin' else 1)


def fresh(value, now):
    if not -5 <= (instant(now) - instant(value)).total_seconds() <= 900:
        raise ValueError('observation_stale')


def build_job(parent_run, source_id, context, deadline_at):
    if source_id not in SOURCES or set(context) != CONTEXT:
        raise ValueError('source_or_context_invalid')
    context = deepcopy(context)
    platforms, regions = context['requested_platforms'], context['region_scope']
    if (not isinstance(platforms, list) or not platforms or set(platforms) - PLATFORMS
            or len(set(platforms)) != len(platforms) or not isinstance(regions, list)
            or not regions or len(set(regions)) != len(regions)
            or any(type(value) is not int or value < 0 for value in regions)):
        raise ValueError('scope_invalid')
    q = context['quantity_scope']
    table = source_id == 'ArabUT' and q == ARAB_TABLE_SCOPE
    if table:
        if regions != [21] or context['total_request_budget'] != 1 or context['total_attempt_limit'] != 1:
            raise ValueError('arab_price_table_scope_invalid')
    else:
        if not isinstance(q, dict) or set(q) != {'purchase_quantity', 'quantity_unit'}:
            raise ValueError('quantity_scope_invalid')
        if quantity(q['purchase_quantity'], q['quantity_unit']) != 100:
            raise ValueError('purchase_scope_invalid')
        # Canonical quantities make equivalent coin/K demands share a job.
        context['quantity_scope'] = dict(purchase_quantity='100', quantity_unit='K')
    context['requested_platforms'] = sorted(platforms)
    context['region_scope'] = sorted(regions)
    if context['discount_scope'] != 'coupon_excluded' or context['currency'] != ('native' if table else 'USD'):
        raise ValueError('price_scope_invalid')
    for key in ('policy_version', 'adapter_version'):
        label(context[key])
    for key in ('assignment_generation', 'total_attempt_limit', 'total_request_budget'):
        integer(context[key])
    run_id = label(parent_run['run_id'])
    created, deadline = instant(parent_run['created_at']), instant(deadline_at)
    if deadline <= created:
        raise ValueError('deadline_invalid')
    context_hash = fingerprint(context)
    return dict(context, schema_version=1, job_id=fingerprint([run_id, source_id, context_hash]),
                parent_run_id=run_id, source_id=source_id, task_context_hash=context_hash,
                created_at=created.isoformat(), deadline_at=deadline.isoformat())


def validate_observation(body, task, now):
    table = task['source_id'] == 'ArabUT' and task.get('quantity_scope') == ARAB_TABLE_SCOPE
    if (not isinstance(body, dict) or set(body) - {'retry_after_seconds', 'platform_errors','request_accounting'} != OBSERVATION
            or type(body['schema_version']) is not int or body['schema_version'] != 1):
        raise ValueError('observation_schema_invalid')
    if 'request_accounting' in body:
        item = body['request_accounting']
        if (task['source_id'] != 'Lootbar' or not isinstance(item, dict)
                or set(item) != {'basis','charged','browser_requests_allowed'}
                or item['basis'] != 'reserved_browser_group' or type(item['charged']) is not int
                or item['charged'] != body['request_budget_used']
                or item['browser_requests_allowed'] is not None and
                    (type(item['browser_requests_allowed']) is not int or not 0 <= item['browser_requests_allowed'] <= item['charged'])):
            raise ValueError('request_accounting_invalid')
    elif task['source_id'] == 'Lootbar' and task['adapter_version'] == 'lootbar-public-browser-v1':
        raise ValueError('request_accounting_required')
    if 'retry_after_seconds' in body:
        integer(body['retry_after_seconds'], 0, 31536000)
    if len(encoded(body).encode('utf-8')) > 65536:
        raise ValueError('observation_too_large')
    label(body['observation_id'])
    if any(body[key] != task[key] or type(body[key]) is not type(task[key]) for key in BINDING):
        raise ValueError('observation_binding_invalid')
    if body['status'] not in ('ok', 'partial', 'failed', 'blocked'):
        raise ValueError('observation_status_invalid')
    if 'platform_errors' in body:
        errors = body['platform_errors']
        if (task['source_id'] not in ('ArabUT', 'Lootbar') or not isinstance(errors, dict) or not errors
                or set(errors) - set(task['requested_platforms'])):
            raise ValueError('platform_errors_invalid')
        for reason in errors.values():
            label(reason)
    if body['reason_code'] is not None:
        label(body['reason_code'])
    integer(body['request_budget_used'], 0, task['total_request_budget'])
    if table and body['offers'] and body['request_budget_used'] != 1:
        raise ValueError('arab_price_table_request_required')
    if not isinstance(body['evidence_hash'], str) or not re.fullmatch('[a-f0-9]{64}', body['evidence_hash']):
        raise ValueError('evidence_hash_invalid')
    started, finished = instant(body['capture_started_at']), instant(body['capture_finished_at'])
    if started > finished:
        raise ValueError('capture_time_invalid')
    earliest = max(instant(task['created_at']), instant(task.get('lease_started_at', task['created_at'])))
    if (earliest - started).total_seconds() > min(5, task.get('clock_margin_seconds', 5)):
        raise ValueError('capture_predates_attempt')
    if (finished - instant(task['deadline_at'])).total_seconds() > min(5, task.get('clock_margin_seconds', 5)):
        raise ValueError('capture_after_deadline')
    fresh(started, now)
    fresh(finished, now)
    if not isinstance(body['offers'], list) or len(body['offers']) > (20 if table else 9):
        raise ValueError('offers_invalid')
    if body['status'] in ('failed', 'blocked') and body['offers']:
        raise ValueError('failed_observation_has_offers')
    seen, times, currencies = set(), [], set()
    for row in body['offers']:
        if not isinstance(row, dict) or set(row) - {'source_metadata'} != OFFER:
            raise ValueError('offer_schema_invalid')
        if table:
            if ('source_metadata' in row or row['currency'] not in ('USD','SAR') or row['settlement_currency'] != row['currency']
                    or row['conversion_source'] != 'not_required' or row['price_basis'] != 'official_public_price_table'
                    or row['discount_source'] != 'official_public_no_coupon' or row['coupon_excluded'] is not True
                    or row['conditional'] is not False or row['comparable'] is not False or row['auth_state'] != 'public'
                    or row['delivery_method'] not in (('standard',) if row['platform'] == 'PC' else ('normal','fast'))
                    or row['bonus_quantity'] != '0' or not isinstance(row['amount'],str)
                    or not re.fullmatch(r'\d{1,12}\.\d{2}',row['amount'])):
                raise ValueError('arab_price_table_offer_invalid')
        elif 'source_metadata' in row and task['source_id'] == 'Lootbar':
            meta = row['source_metadata']
            fields = {'coupon_state','raw_coupon_excluded','logged_in','observed_coupon_price',
                      'excluded_coupon_discount','stable_reads','raw_usd_price','coupon_evidence','reconstruction','parser_reconstruction'}
            if not isinstance(meta, dict) or set(meta) != fields:
                raise ValueError('source_metadata_invalid')
            from .lootbar import snapshot_offer
            raw = dict(selected=[{'PS':'PS4/5','XBOX':'Xbox','PC':'PC'}[row['platform']]],
                loggedIn=meta['logged_in'], currencyState='ready', tierState='ready', baseK=100,
                priceState='ready', usdPrice=meta['raw_usd_price'], giftState='ready', bonusK=row['bonus_quantity'],
                couponState=meta['coupon_state'], observedCouponPrice=meta['observed_coupon_price'],
                excludedCouponDiscount=meta['excluded_coupon_discount'], stable_reads=meta['stable_reads'], couponEvidence=meta['coupon_evidence'],
                reconstruction=meta['parser_reconstruction'], observed_at=row['observed_at'])
            expected = snapshot_offer(raw, row['platform'], row['observed_at'])
            if (type(meta['raw_coupon_excluded']) is not bool
                    or meta['raw_coupon_excluded'] != (meta['coupon_state'] == 'excluded')
                    or meta['reconstruction'] != expected['source_metadata']['reconstruction']
                    or any(row[k] != expected[k] for k in ('amount','price_basis','discount_source','coupon_excluded','auth_state','conditional','comparable'))):
                raise ValueError('source_metadata_invalid')
        elif 'source_metadata' in row:
            meta = row['source_metadata']
            if (task['source_id'] != 'ArabUT' or not isinstance(meta, dict)
                    or set(meta) not in ({'original_currency', 'original_amount_minor', 'price_version', 'priced_at'},
                        {'original_currency', 'original_amount_minor', 'price_version', 'priced_at',
                         'original_platform', 'original_market', 'original_delivery'})
                    or meta['original_currency'] != 'SAR'):
                raise ValueError('source_metadata_invalid')
            integer(meta['original_amount_minor'], 1, 2**63 - 1)
            version = meta['price_version']
            if not (type(version) is int and 0 <= version <= 2**63 - 1
                    or isinstance(version, str) and 0 < len(version) <= 120):
                raise ValueError('source_metadata_invalid')
            instant(meta['priced_at'])
            if 'original_platform' in meta:
                pc = row['platform'] == 'PC'
                if (meta['original_platform'] != ('pc' if pc else 'playstation')
                        or meta['original_market'] != ('pc' if pc else 'console')
                        or (meta['original_delivery'] is not None if pc else
                            meta['original_delivery'] not in ARAB_CONSOLE_DELIVERIES)
                        or row['delivery_method'] != ('standard' if pc else meta['original_delivery'])):
                    raise ValueError('source_metadata_invalid')
                fresh(meta['priced_at'], now)
        elif task['source_id'] == 'Lootbar' and task['adapter_version'] == 'lootbar-public-browser-v1':
            raise ValueError('lootbar_source_metadata_required')
        if (task['source_id'] == 'ArabUT' and not table and row['delivery_method'] == 'fast'
                and row.get('source_metadata', {}).get('original_delivery') != 'fast'):
            raise ValueError('source_metadata_invalid')
        key = row['platform'], row['region_id']
        if table:
            key += (row['purchase_quantity'], row['delivery_method'])
        if (row['platform'] not in task['requested_platforms'] or type(row['region_id']) is not int
                or row['region_id'] not in task['region_scope'] or key in seen):
            raise ValueError('offer_scope_invalid')
        seen.add(key)
        valid_conversion = (row['settlement_currency'], row['conversion_source']) == ('USD', 'not_required')
        if table:
            valid_conversion = (row['settlement_currency'], row['conversion_source']) == (row['currency'], 'not_required')
            currencies.add(row['currency'])
        if task['source_id'] == 'ArabUT':
            valid_conversion = valid_conversion or (row['settlement_currency'], row['conversion_source']) == ('SAR', 'official_display_quote')
        if (not table and row['currency'] != task['currency']) or not valid_conversion:
            raise ValueError('currency_invalid')
        purchase = quantity(row['purchase_quantity'], row['quantity_unit'])
        bonus = quantity(row['bonus_quantity'], row['quantity_unit'], True)
        delivered = quantity(row['delivered_quantity'], row['quantity_unit'])
        valid_quantity = (row['quantity_unit'] == 'K' and row['purchase_quantity'] in ARAB_TABLE_QUANTITIES
                          if table else purchase == 100)
        if not valid_quantity or delivered != purchase + bonus:
            raise ValueError('quantity_identity_invalid')
        decimal(row['amount'])
        for field in ('coupon_excluded', 'conditional', 'comparable', 'selection_verified'):
            if type(row[field]) is not bool:
                raise ValueError('offer_boolean_invalid')
        if row['selection_verified'] is not True or row['auth_state'] not in ('public', 'logged_in', 'unknown'):
            raise ValueError('selection_invalid')
        for field in ('discount_source', 'price_basis', 'delivery_method'):
            if not isinstance(row[field], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,79}', row[field]):
                raise ValueError('price_basis_invalid')
        if not isinstance(row['sanitized_evidence_ref'], str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', row['sanitized_evidence_ref']):
            raise ValueError('evidence_reference_invalid')
        observed = instant(row['observed_at'])
        fresh(observed, now)
        if not started <= observed <= finished:
            raise ValueError('capture_time_invalid')
        times.append(observed)
    if len(currencies) > 1:
        raise ValueError('arab_price_table_currency_mixed')
    if times and (max(times) - min(times)).total_seconds() > 300:
        raise ValueError('observation_span_invalid')
    return body


def to_fc_quote_rows(accepted, expected_context, now):
    rows, times, seen = [], [], set()
    for body in accepted:
        validate_observation(body, expected_context, now)
        for offer in body['offers']:
            key = offer['platform'], offer['region_id']
            if key in seen:
                raise ValueError('offer_duplicate')
            seen.add(key)
            if (offer['conditional'] or not offer['comparable'] or not offer['coupon_excluded']
                    or offer['auth_state'] == 'unknown' or offer['discount_source'] == 'unknown'):
                continue
            times.append(instant(offer['observed_at']))
            purchase = quantity(offer['purchase_quantity'], offer['quantity_unit'])
            bonus = quantity(offer['bonus_quantity'], offer['quantity_unit'], True)
            row = dict(source=body['source_id'], platform=offer['platform'], region_id=offer['region_id'],
                run_id=body['parent_run_id'], captured_at=offer['observed_at'], currency='USD',
                purchase_k=str(purchase), bonus_k=str(bonus), gross_usd=offer['amount'],
                effective_usd_per_k=str(decimal(offer['amount']) / (purchase + bonus)),
                coupon_excluded=True, conditional=False, comparable=True, status='valid', reason=None,
                auth_state=offer['auth_state'], delivery_method=offer['delivery_method'],
                price_basis=offer['price_basis'], discount_source=offer['discount_source'],
                selection_verified=True, observation_id=body['observation_id'])
            row.update(settlement_currency=offer['settlement_currency'], conversion_source=offer['conversion_source'])
            if body['source_id'] == 'ArabUT':
                expected_deliveries = ('standard',) if offer['platform'] == 'PC' else ARAB_CONSOLE_DELIVERIES
                if offer['delivery_method'] not in expected_deliveries:
                    continue
                row.update(arab_quote_details(offer))
            elif body['source_id'] == 'Lootbar':
                if 'source_metadata' in offer:
                    row['source_metadata'] = deepcopy(offer['source_metadata'])
                row['request_accounting'] = deepcopy(body.get('request_accounting'))
                row['url'] = 'https://www.lootbar.com/game-coins/fc27'
            rows.append(row)
    if times and (max(times) - min(times)).total_seconds() > 300:
        raise ValueError('observation_span_invalid')
    missing = [dict(platform=p, region_id=r, reason='same_run_valid_quote_missing')
               for p in expected_context['requested_platforms'] for r in expected_context['region_scope']
               if not any(row['platform'] == p and row['region_id'] == r for row in rows)]
    return dict(status='captured' if rows else 'unavailable', run_id=expected_context['parent_run_id'],
                offers=rows, missing=missing)


def arab_quote_details(offer):
    pc = offer['platform'] == 'PC'
    result = dict(total_usd=offer['amount'], delivery=offer['delivery_method'])
    if 'source_metadata' in offer:
        modern = 'original_platform' in offer['source_metadata']
        query = ('platform=pc&quantity=100000' if pc else
                 'platform=playstation&delivery=' + offer['delivery_method'] + '&quantity=100000')
        result.update(deepcopy(offer['source_metadata']),
            delivered_k=str(quantity(offer['delivered_quantity'], offer['quantity_unit'])),
            comparison_currency='USD', quantity_basis='official_quote_quantity_bonus_not_advertised',
            platform_mapping='official_pc_market_independent' if pc else 'official_playstation_market_console_shared_PS_Xbox',
            parser_version='arab-public-quote-v2' if modern else 'arab-public-quote-v1',
            url='https://www.arab-ut.com' + ('/en' if modern else '') + '/coins/quote?' + query,
            reference_scope='global', source_region_id=21)
    return result


def arab_status(rows, requested_platforms, errors=None):
    """Keep valid platform quotes when the other independent market is missing."""
    errors = errors or {}
    for row in rows:
        pc = row['platform'] == 'PC'
        if (not {'original_currency', 'original_amount_minor', 'price_version', 'priced_at'} <= set(row)
                or row['region_id'] != 21 or decimal(row['bonus_k'], True) != 0
                or row['settlement_currency'] != 'SAR' or row['conversion_source'] != 'official_display_quote'
                or row['price_basis'] != 'public_merchandise' or row['auth_state'] != 'public'
                or row['discount_source'] != 'official_no_coupon'
                or row['delivery'] not in (('standard',) if pc else ARAB_CONSOLE_DELIVERIES)
                or pc and (row.get('original_platform') != 'pc' or row.get('original_market') != 'pc'
                           or row.get('original_delivery', 'missing') is not None)):
            raise ValueError('arab_source_metadata_required')
    console = [row for row in rows if row['platform'] in ('PS', 'XBOX')]
    if len(console) == 2 and {k:v for k,v in console[0].items() if k != 'platform'} != {k:v for k,v in console[1].items() if k != 'platform'}:
        raise ValueError('arab_console_quote_inconsistent')
    present = {row['platform'] for row in rows}
    missing = [dict(platform=p, region_id=21, reason=errors.get(p, 'same_run_valid_quote_missing'))
               for p in requested_platforms if p not in present]
    shared_delivery = console[0]['delivery'] if console else None
    labels = dict(PS=shared_delivery + '_verified' if shared_delivery else None,
                  XBOX='official_shared_console', PC='independent_standard_verified')
    coverage = {p: labels[p] if p in present else errors.get(p, 'same_run_valid_quote_missing') if p in requested_platforms else 'not_requested'
                for p in ('PS', 'XBOX', 'PC')}
    return dict(status='partial' if rows and missing else 'available' if rows else 'unavailable',
                offers=rows, coverage=coverage, missing=missing)


def to_arab_status(accepted, task, now):
    if task['source_id'] != 'ArabUT':
        raise ValueError('arab_source_invalid')
    if task.get('quantity_scope') == ARAB_TABLE_SCOPE:
        rows = []
        for body in accepted:
            validate_observation(body,task,now)
            rows.extend(arab_table_row(offer, run_id=task['parent_run_id'],
                observation_id=body['observation_id']) for offer in body['offers'])
        return dict(status='available' if rows else 'unavailable', offers=[],
                    quantity_offers=rows, reason=next((b['reason_code'] for b in accepted if b['reason_code']), None))
    rows = to_fc_quote_rows(accepted, task, now)['offers']
    errors = {}
    for body in accepted:
        errors.update(body.get('platform_errors', {}))
        if body.get('reason_code'):
            for platform in task['requested_platforms']:
                errors.setdefault(platform, body['reason_code'])
    return arab_status(rows, task['requested_platforms'], errors)


def arab_table_row(offer, **binding):
    return dict(source='ArabUT', status='valid', platform=offer['platform'], region_id=offer['region_id'],
        purchase_k=offer['purchase_quantity'], bonus_k=None, regular_price=offer['amount'], currency=offer['currency'],
        conversion_source='native_public_display_currency', original_currency=offer['currency'],
        original_amount_minor=int(decimal(offer['amount'])*100),
        delivery_method=offer['delivery_method'], delivery_tier=offer['delivery_method'],
        captured_at=offer['observed_at'], source_url='https://' + ARAB_PRICE_TABLE['host'] + ARAB_PRICE_TABLE['path'],
        reference_scope='official_shared_console' if offer['platform'] != 'PC' else 'official_independent_PC',
        promotion_eligibility='all_customers', conditional=False, comparable=False, coupon_excluded=True,
        selection_verified=True, auth_state='public', price_basis='official_public_price_table',
        evidence_ref=offer['sanitized_evidence_ref'], **binding)
