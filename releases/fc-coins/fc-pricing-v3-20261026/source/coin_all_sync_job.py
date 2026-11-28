def allowed_admin_usernames():
    import sys
    sys.path.insert(0, '/usr/local/bin')
    from p2pah_session_service import allowed_admin_usernames as allowed
    return allowed()
"""Mirror confirmed MMOEXP FC27 coin prices to its three ALL fallback products.

No price calculation, recalc, cache clear, policy change or automatic replay.
Run only after the existing writer confirms MMOEXP, under its existing lock.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import hashlib
from math import isfinite
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import urlencode

PRODUCTS = {'PS': (163329309, 163329311, 21587),
            'XBOX': (163329275, 163329277, 21585),
            'PC': (163329343, 163329345, 21589)}
DEFAULT_KEYWORDS = {'PS':'fc 27 playstation 5 gold coins',
                    'XBOX':'fc 27 xbox series x s gold coins',
                    'PC':'fc 27 pc platform gold coins'}
# A just-dispatched ALL write can be served stale for a moment, so one read
# right after a POST is not proof of propagation. Confirmation re-reads are
# GET-only and bounded: the whole mirror normally takes well under 20s inside
# the writer's own 130s subprocess envelope, so the retry budget below stays
# far away from that envelope even when every product has to be re-read.
READBACK_STEP_SECONDS = 30        # budget for one product
READBACK_TOTAL_SECONDS = 45       # shared by every product of one mirror run
READBACK_INTERVAL_SECONDS = 3
READBACK_STABLE_ROUNDS = 2


def unchanged(before, after, platform, price_fields=False, *, tier_price_factors=False):
    """Allow only the native empty-to-exact catalog keyword normalization."""
    left = protected(before, tier_price_factors=tier_price_factors) if price_fields else editable(before)
    right = protected(after, tier_price_factors=tier_price_factors) if price_fields else editable(after)
    if (left.get('keywords') in ('', None)
            and right.get('keywords') == DEFAULT_KEYWORDS[platform]):
        right['keywords'] = left.get('keywords')
        if 'keywords' not in left: right.pop('keywords', None)
    return left == right


def money(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('coin_price_invalid') from None
    if isinstance(value, bool) or not result.is_finite() or result <= 0:
        raise ValueError('coin_price_invalid')
    return result


def api(manager, path, payload=None, observer=None):
    # In particular, never retry a POST whose outcome is unknown.
    started = datetime.now(timezone.utc).isoformat()
    try:
        status, raw = manager.request(path, data=payload, token=manager.token)
    except Exception as error:
        if observer: observer({'path':path,'started_at':started,'received_at':datetime.now(timezone.utc).isoformat(),
                               'transport_error':type(error).__name__})
        raise
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        if observer: observer({'path':path,'started_at':started,'received_at':datetime.now(timezone.utc).isoformat(),
                               'http_status':status,'response_code':None,'response_sha256':hashlib.sha256(raw.encode() if isinstance(raw,str) else raw).hexdigest()})
        raise ValueError('coin_backend_response_invalid') from None
    if observer:
        receipt = dict(path=path, started_at=started, received_at=datetime.now(timezone.utc).isoformat(),
                       http_status=status, response_code=value.get('code'),
                       response_sha256=hashlib.sha256(raw.encode() if isinstance(raw,str) else raw).hexdigest())
        if payload is not None and path.startswith('/admin/goods.Goods/edit?id=') and value.get('code') != 1:
            msg = value.get('msg')
            if isinstance(msg, str) and msg.strip():
                receipt['response_message_sha256'] = hashlib.sha256(msg.encode()).hexdigest()
                # Product validation messages are short and unstructured. Keep
                # their sanitized text privately; omit unexpected body fields.
                if len(msg) <= 160 and not re.search(
                        r'[@<>{}\r\n]|https?://|bearer|cookie|authorization|token|secret|password|passwd|凭据|密码',
                        msg, re.I):
                    receipt['response_message'] = re.sub(r'[A-Za-z0-9_-]{18,}|\d{7,}', '[redacted]', msg)
        observer(receipt)
    if status != 200 or value.get('code') != 1:
        raise ValueError('coin_backend_request_rejected')
    return value.get('data')


def editable(row):
    return deepcopy({k:v for k,v in row.items()
                     if not k.startswith(('_', 'stat_')) and v is not None})


def protected(row, *, tier_price_factors=False):
    value = editable(row)
    value.pop('unit_price', None)
    value['more'].pop('price', None)
    if tier_price_factors:
        value['more'].pop('discount', None)
    return value


def read_row(manager, platform, site, observer=None, *, recipient_id=None):
    all_id, site_id, aid = PRODUCTS[platform]
    product_id = all_id if site == 0 else site_id if site == 266 else recipient_id
    if type(product_id) is not int or product_id <= 0:
        raise ValueError('coin_product_scope_changed')
    result = api(manager, '/admin/goods.Goods/edit?id=' + str(product_id), observer=observer)
    row = result.get('row') if isinstance(result, dict) else None
    expected = {'id':product_id, 'mid':41217957, 'gid':1327, 'cid':9623,
                'site_id':site, 'aid':aid, 'unit':'K', 'title':'coins', 'status':1}
    if not isinstance(row, dict) or any(str(row.get(k)) != str(v) for k,v in expected.items()):
        raise ValueError('coin_product_scope_changed')
    money(row.get('unit_price'))
    more = row.get('more')
    if not isinstance(more, dict) or not isinstance(more.get('gold'), list) or not more['gold']:
        raise ValueError('coin_tiers_invalid')
    for key in ('price','gold','discount','give','delivery_time','hot'):
        if not isinstance(more.get(key), list) or len(more[key]) != len(more['gold']):
            raise ValueError('coin_tiers_invalid')
    for price in more['price']:
        money(price)
    return row


def read_curve_routes(manager):
    """Bind native ALL and same-model recipient identities from one Admin index read."""
    from fc_pricing_v3.financial import fingerprint

    params = dict(page=1, limit=100)
    for index, (name, value) in enumerate((('mid', 41217957), ('gid', 1327), ('cid', 9623), ('status', 1))):
        params.update({f'search[{index}][field]': name, f'search[{index}][operator]': '=',
                       f'search[{index}][val]': value})
    observed = []
    data = api(manager, '/admin/goods.Goods/index?' + urlencode(params), observer=observed.append)
    rows = data.get('list') if isinstance(data, dict) else None
    if not isinstance(rows, list) or str(data.get('total')) != str(len(rows)) or not rows:
        raise ValueError('pricing_curve_native_route_directory_incomplete')
    grouped = {p: {} for p in PRODUCTS}
    by_aid = {str(ids[2]): p for p, ids in PRODUCTS.items()}
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or any(str(row.get(name)) != value for name, value in
                (('mid', '41217957'), ('gid', '1327'), ('cid', '9623'), ('status', '1')))):
            raise ValueError('pricing_curve_native_route_directory_scope')
        platform = by_aid.get(str(row.get('aid')))
        if not platform:
            continue
        site, goods = str(row.get('site_id')), str(row.get('id'))
        if (not site.isascii() or not site.isdecimal() or str(int(site)) != site
                or not goods.isascii() or not goods.isdecimal() or int(goods) <= 0
                or site in grouped[platform] or goods in seen):
            raise ValueError('pricing_curve_native_route_identity_ambiguous')
        grouped[platform][site] = int(goods)
        seen.add(goods)
    routes = {}
    for platform, (all_id, main_id, _) in PRODUCTS.items():
        members = grouped[platform]
        if members.get('0') != all_id or members.get('266') != main_id:
            continue
        material = dict(platform=platform, all_goods_id=all_id,
                        recipient_goods={site: goods for site, goods in members.items() if site != '0'})
        routes[platform] = dict(material, propagation_revision=fingerprint(material), directory_read=observed[0])
    return routes


def curve_writer_capabilities(routes=None):
    """Expose an evidenced send route while actual propagation awaits original readback."""
    from fc_pricing_v3.financial import fingerprint
    from fc_pricing_v3.order_projection_v6 import OrderProjection
    from fc_pricing_v3.price_curve import EDITOR_ASSET_SHA256

    order = OrderProjection()
    result = {}
    for platform, ids in PRODUCTS.items():
        route = (routes or {}).get(platform) or {}
        directory = route.get('directory_read') or {}
        recipients = route.get('recipient_goods') or {}
        material = {key: route.get(key) for key in ('platform', 'all_goods_id', 'recipient_goods')}
        ready = (route.get('platform') == platform and route.get('all_goods_id') == ids[0]
                 and recipients.get('266') == ids[1] and directory.get('response_sha256')
                 and directory.get('http_status') == 200 and directory.get('response_code') == 1
                 and str(directory.get('path', '')).startswith('/admin/goods.Goods/index?')
                 and route.get('propagation_revision') == fingerprint(material))
        result[platform] = dict(
            evidence_ref='admin_goods_editor_sha256:' + EDITOR_ASSET_SHA256,
            catalogue_path='/admin/goods.Goods/edit?id=' + str(ids[0]),
            catalogue_status='native_route_ready' if ready else 'native_route_directory_unavailable',
            order_projection=order.adapter(platform),
            order_projection_status='native_route_ready',
            tier_price_factors=True,
        )
        if ready:
            result[platform].update(recipient_goods={int(site): goods for site, goods in recipients.items()},
                                    propagation_revision=route['propagation_revision'],
                                    directory_read=directory)
    return result


def curve_route_ready(capability):
    return (capability.get('catalogue_status') in ('native_route_ready', 'verified')
            and bool(capability.get('recipient_goods')))


def curve_admin_manager():
    sys.path.insert(0, '/usr/local/bin')
    from p2pah_session_service import SessionManager, read_private_config

    manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError('coin_auth_unavailable')
    return manager


def external_recovery_request(band, current, requested, context):
    """Return an inward cent target for a ledger-attributed out-of-range band."""
    from decimal import ROUND_CEILING, ROUND_FLOOR

    day = (context.get('day_anchors') or {}).get(band)
    if band not in context.get('recovery_bands', ()) or day is None:
        return None
    low = (Decimal(day) * Decimal('.6')).quantize(Decimal('.01'), rounding=ROUND_CEILING)
    high = (Decimal(day) * Decimal('1.4')).quantize(Decimal('.01'), rounding=ROUND_FLOOR)
    if current > high:
        ceiling = Decimal(context.get('market_high', {}).get(band, high))
        return max(low, min(requested, high, ceiling))
    if current < low:
        floor = Decimal(context.get('market_low', {}).get(band, low))
        return min(high, max(requested, low, floor))
    return None


def curve_price_insurance(before, target, context, *, restore=False):
    """Return bounded anchor controls; the caller must compile and prove them."""
    from decimal import ROUND_CEILING, ROUND_FLOOR
    from statistics import median
    from fc_pricing_v3.curve_strategy_v6 import band_anchors

    observed, requested = band_anchors(before), band_anchors(target)
    day = context.get('day_anchors') or {}
    market_by_band = context.get('market_per_100k_by_band', {})
    anchors, clipped, recovering, continuing = {}, {}, [], []
    for band, raw in requested.items():
        current, price = Decimal(observed[band]), Decimal(raw)
        if not restore:
            lower = (current * Decimal('.85')).quantize(Decimal('.01'), rounding=ROUND_CEILING)
            upper = (current * Decimal('1.15')).quantize(Decimal('.01'), rounding=ROUND_FLOOR)
            if band not in day:
                raise ValueError('pricing_curve_daily_reference_unavailable')
            recovery = external_recovery_request(band, current, price, context)
            if recovery is not None:
                recovering.append(band)
            bounded = min(upper, max(lower, recovery if recovery is not None else price))
            if bounded != price:
                clipped[band] = dict(requested=raw, bounded=str(bounded))
            price = bounded
            if not Decimal('.60') <= price / Decimal(day[band]) <= Decimal('1.40'):
                if recovery is None or price == current:
                    raise ValueError('pricing_curve_daily_move_exceeded')
                continuing.append(band)
        quantity = '100' if band == 'small' else '1000'
        tier = next(row for row in target['tiers'] if row['purchase_k'] == quantity)
        unit = price * 100 / (Decimal(quantity) + Decimal(tier['promised_bonus_k']))
        values = market_by_band.get(band, context.get('market_per_100k', []))
        market = median(Decimal(value) for value in values) if values else None
        if market is not None:
            low, high = market * Decimal('.5'), market * 2
            tested = unit
        elif band in day:
            low, high = Decimal(day[band]) * Decimal('.6'), Decimal(day[band]) * Decimal('1.6')
            tested = price
        else:
            raise ValueError('pricing_curve_market_reference_unavailable')
        if not low <= tested <= high:
            raise ValueError('pricing_curve_out_of_market_range')
        anchors[band] = str(price)
    return dict(anchors=anchors, clipped=clipped, recovering_bands=recovering, continuing_recovery=continuing)


def curve_catalog_plan(bundle, platform, capability):
    """Freeze price-only changes and bind them to the original proof and Goods rows."""
    from fc_pricing_v3.financial import fingerprint
    from fc_pricing_v3.price_curve import (COIN_BAND_ANCHORS, EDITOR_ASSET_SHA256, EDITOR_HANDLER_SHA256,
        FORWARD_TIER_EDIT, TWO_BAND_PRICE_EDIT, _editor_discount_input, _editor_price,
        _editor_price_derived_factor, band_price_usd, coin_quantity_band, curve_key, read_curve,
        two_band_unit_price)
    from fc_pricing_v3.pricing_proof_v6 import CONTRACT, PROVEN, DOMAIN_REVISIONS

    before = bundle['before_action']['curves'][platform]
    target = bundle['action']['curves'][platform]
    all_id, site_id, aid = PRODUCTS[platform]
    identity = dict(id=all_id, mid=41217957, gid=1327, cid=9623,
                    site_id=0, aid=aid, unit='K', status=1)
    before = read_curve(before['native_payload'], identity, before['native_contract'])
    target = read_curve(target['native_payload'], identity, target['native_contract'])
    before_row, target_row = before['native_payload'], target['native_payload']
    if before_row.get('title') != 'coins' or target_row.get('title') != 'coins':
        raise ValueError('coin_product_scope_changed')
    two_band = target['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT
    restore = bundle.get('restore_source_execution_id')
    if restore and not two_band:
        raise ValueError('pricing_curve_two_band_policy_missing')
    from fc_pricing_v3.average_discount_v6 import LEGACY_MODEL, MODEL
    proof = bundle['curve_proofs'][platform]
    insurance_context = (bundle.get('curve_price_insurance') or {}).get(platform)
    if two_band and (insurance_context is not None or capability and capability.get('catalogue_status') == 'native_route_ready'):
        if insurance_context is None:
            raise ValueError('pricing_curve_insurance_evidence_missing')
        insured = curve_price_insurance(before, target, insurance_context, restore=bool(restore))
        if insured['clipped']:
            raise ValueError('pricing_curve_single_move_requires_reproof')
        exception = proof.get('price_insurance')
        if exception and insured['recovering_bands']:
            raise ValueError('pricing_curve_recovery_requires_full_margin')
        if exception and (restore or exception.get('round') != insurance_context.get('below_margin_rounds', 0) + 1
                          or exception.get('round') not in (1, 2)):
            raise ValueError('pricing_curve_margin_exception_exhausted')
    if (capability and capability.get('catalogue_status') == 'native_route_ready' and not two_band
            and (before['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT
                 or (proof.get('average_discount') or {}).get('contract') in (MODEL, LEGACY_MODEL))):
        raise ValueError('pricing_curve_two_band_policy_missing')
    tier_price_factors = bool(not two_band and capability and capability.get('tier_price_factors'))
    if protected(before_row, tier_price_factors=tier_price_factors) != protected(
            target_row, tier_price_factors=tier_price_factors):
        raise ValueError('pricing_curve_non_price_field_changed')
    if two_band and target['unit_price_usd_per_k'] != two_band_unit_price(target['tiers']):
        raise ValueError('pricing_curve_two_band_unit_price_unsynced')
    if two_band and not restore:
        for anchor in COIN_BAND_ANCHORS.values():
            tiers = [(old,new) for old,new in zip(before['tiers'],target['tiers'])
                     if COIN_BAND_ANCHORS[coin_quantity_band(new['purchase_k'])] == anchor]
            if not any(old['native_price_usd'] != new['native_price_usd'] for old,new in tiers):
                continue
            amount = next((new['native_price_usd'] for _,new in tiers if new['purchase_k'] == anchor),None)
            if not amount or any(money(new['native_price_usd']) != band_price_usd(amount,anchor,new['purchase_k'])
                                 for _,new in tiers):
                raise ValueError('pricing_curve_two_band_price_table_invalid')
    if tier_price_factors:
        contract = target['native_contract']
        forward = (contract.get('price_edit_policy') == FORWARD_TIER_EDIT
                   and contract.get('editor_asset_sha256') == EDITOR_ASSET_SHA256
                   and contract.get('editor_handler_sha256') == EDITOR_HANDLER_SHA256)
        valid_factor = _editor_price_derived_factor if forward else _editor_discount_input
        for old, new in zip(before['tiers'], target['tiers']):
            if old['native_discount'] == new['native_discount']:
                continue
            factor = float(new['native_discount'])
            subtotal = float(target['unit_price_usd_per_k']) * float(new['purchase_k'])
            if not (isfinite(subtotal) and valid_factor(factor)
                    and Decimal(str(_editor_price(subtotal, factor))) == money(new['native_price_usd'])):
                raise ValueError('pricing_curve_native_tier_factor_mismatch')
    if curve_prices_match(before_row, target_row):
        raise ValueError('pricing_curve_price_payload_unchanged')
    scope = proof.get('scope', {})
    if (proof.get('contract') != CONTRACT or proof.get('status') != PROVEN
            or proof.get('curve_key') != curve_key(target)
            or scope.get('platform') != platform or scope.get('curve_site_id') != '0'
            or proof.get('proof_hash') != fingerprint({k: v for k, v in proof.items() if k != 'proof_hash'})):
        raise ValueError('pricing_curve_financial_proof_invalid')
    if not capability or not curve_route_ready(capability):
        raise ValueError('pricing_curve_catalog_save_unverified')
    recipients = capability['recipient_goods']
    priced_sites = {int(site) for site in scope.get('site_paths', {})}
    revisions = scope.get('source_revisions') or {}
    native_route = capability.get('catalogue_status') == 'native_route_ready'
    if (not capability.get('evidence_ref') or not scope.get('version')
            or (native_route and revisions.get('propagation') != capability['propagation_revision'])
            or (not native_route and (scope['version'] != capability.get('domain_version')
                                      or revisions != capability.get('source_revisions')))
            or set(revisions) != set(DOMAIN_REVISIONS) or not all(revisions.values())
            or 266 not in priced_sites or not priced_sites.issubset(recipients)
            or recipients.get(266) != site_id or 0 in recipients
            or all_id in recipients.values() or len(set(recipients.values())) != len(recipients)):
        raise ValueError('pricing_curve_native_evidence_mismatch')
    before_rate, target_rate = (next((Decimal(tier['native_price_usd'] + 'e-2')
                                    for tier in curve['tiers'] if tier['purchase_k'] == '100'), None)
                                for curve in (before, target))
    if before_rate is None or target_rate is None:
        raise ValueError('pricing_curve_100k_tier_missing')
    # The scalar B2C update does not preserve independent Admin tiers.
    projection_status = 'not_required'
    if not two_band:
        if before_rate != target_rate:
            if (capability.get('order_projection_status') not in ('native_route_ready', 'verified')
                    or not capability.get('order_projection')):
                raise ValueError('pricing_curve_order_projection_unverified')
            projection_status = 'pending'
        elif native_route:
            projection_status = 'read_only_pending'
    primary_before_hash = (bundle.get('curve_primary_before_hashes') or {}).get(platform)
    if native_route and not primary_before_hash:
        raise ValueError('pricing_curve_primary_before_unbound')
    return dict(platform=platform, all_goods_id=all_id, before=before_row, target=editable(target_row),
                before_hash=fingerprint(editable(before_row)), target_hash=fingerprint(editable(target_row)),
                target_curve_key=curve_key(target), native_contract=target['native_contract'],
                before_rate=str(before_rate), target_rate=str(target_rate), proof_hash=proof['proof_hash'],
                domain_version=scope['version'], source_revisions=revisions, evidence_ref=capability['evidence_ref'],
                catalogue_status=capability['catalogue_status'], directory_read=capability.get('directory_read'),
                primary_before_hash=primary_before_hash,
                tier_price_factors=tier_price_factors,
                recipient_goods={str(site): goods for site, goods in recipients.items()},
                required_recipient_sites=sorted(str(site) for site in priced_sites),
                catalog={'status': 'pending'}, propagation={'status': 'pending'},
                projection={'status': projection_status})


def curve_prices_match(row, target):
    return (money(row['unit_price']) == money(target['unit_price'])
            and list(map(money, row['more']['price'])) == list(map(money, target['more']['price']))
            and tier_array_matches(row, target, 'discount'))


def tier_array_matches(row, target, key):
    return ([Decimal(str(value)) for value in row['more'][key]] ==
            [Decimal(str(value)) for value in target['more'][key]])


def curve_specs_match(row, target):
    return all(tier_array_matches(row, target, key) for key in ('gold', 'give', 'discount'))


def curve_readback(manager, item):
    """Read the original Goods only and distinguish price, receipt and propagation."""
    from fc_pricing_v3.financial import fingerprint
    from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT

    platform = item['platform']
    tier_price_factors = item.get('tier_price_factors', False)
    catalog = item['catalog']
    if 'send_intent' not in catalog or catalog['status'] == 'not_sent':
        return False
    catalog['status'] = 'readback_pending' if curve_receipt_matches(catalog) else 'unknown'
    propagation = item['propagation']
    propagation['status'] = 'readback_pending'
    rejection = curve_rejected_receipt(item)
    if (item['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT and not rejection):
        if not curve_receipt_matches(catalog):
            catalog['reason'] = 'pricing_curve_original_receipt_unavailable'
            return False
        return curve_primary_readback(manager, item)
    all_row = read_row(manager, platform, 0)
    item.setdefault('observed_rows', {})['0'] = all_row
    if rejection:
        confirm_curve_rejection(manager, item, all_row)
        return False
    if not curve_receipt_matches(catalog):
        catalog['status'] = 'unknown'
        catalog['reason'] = 'pricing_curve_original_receipt_unavailable'
        return False
    if not (curve_prices_match(all_row, item['target']) and
            unchanged(item['before'], all_row, platform, True, tier_price_factors=tier_price_factors)):
        catalog['reason'] = 'pricing_curve_all_readback_mismatch'
        catalog['status'] = 'readback_pending'
        return False
    catalog.setdefault('confirmed_at', datetime.now(timezone.utc).isoformat())
    catalog.update(status='confirmed', actual_hash=fingerprint(editable(all_row)))
    catalog.pop('reason', None)
    required = set(item.get('required_recipient_sites', item['recipient_goods']))
    site_outcomes = {}
    first_mismatch = None
    actual_hashes = {}
    for site, goods in item['recipient_goods'].items():
        before = item['recipients_before'].get(site)
        try:
            row = read_row(manager, platform, int(site), recipient_id=goods)
        except (OSError, ValueError):
            item['observed_rows'].pop(site, None)
            site_outcomes[site] = 'readback_unavailable'
            if site in required:
                first_mismatch = first_mismatch or site
            continue
        item['observed_rows'][site] = row
        actual_hashes[site] = fingerprint(editable(row))
        if before is None:
            site_outcomes[site] = 'before_readback_unavailable'
        elif not unchanged(before, row, platform, True, tier_price_factors=tier_price_factors):
            site_outcomes[site] = 'protected_fields_changed'
            first_mismatch = first_mismatch or site
        elif curve_specs_match(row, item['target']) and curve_prices_match(row, item['target']):
            site_outcomes[site] = ('matches_target_already' if curve_prices_match(before, item['target'])
                                   else 'target_observed')
        elif unchanged(before, row, platform):
            site_outcomes[site] = 'unchanged'
        else:
            site_outcomes[site] = 'unexpected_price_change'
            first_mismatch = first_mismatch or site
        if site in required and site_outcomes[site] not in ('matches_target_already', 'target_observed'):
            first_mismatch = first_mismatch or site
    propagation.update(site_outcomes=site_outcomes, actual_hashes=actual_hashes)
    if first_mismatch is not None:
        propagation['reason'] = 'pricing_curve_recipient_readback_mismatch:' + first_mismatch
        return False
    return confirm_curve_primary(item)


def curve_primary_readback(manager, item):
    """Check the effective MMOEXP catalogue after the original successful save."""
    from fc_pricing_v3.financial import fingerprint

    platform = item['platform']
    catalog = item['catalog']
    propagation = item['propagation']
    catalog.setdefault('confirmed_at', datetime.now(timezone.utc).isoformat())
    catalog.update(status='confirmed', confirmation_basis='original_admin_save_receipt')
    catalog.pop('reason', None)
    observed = read_row(manager, platform, 266, recipient_id=item['recipient_goods']['266'])
    item.setdefault('observed_rows', {})['266'] = observed
    propagation['actual_hashes'] = {'266': fingerprint(editable(observed))}
    before = item['recipients_before']['266']
    if not (curve_specs_match(observed, item['target']) and curve_prices_match(observed, item['target'])
            and unchanged(before, observed, platform, True)):
        propagation.update(site_outcomes={'266': 'target_mismatch'},
                           reason='pricing_curve_recipient_readback_mismatch:266')
        return False
    propagation['site_outcomes'] = {'266': 'target_observed'}
    required = item.get('required_recipient_sites')
    if item.get('catalogue_status') == 'native_route_ready' and isinstance(required, list):
        for site in required:
            if site == '266':
                continue
            before = item['recipients_before'].get(site)
            try:
                row = read_row(manager, platform, int(site), recipient_id=item['recipient_goods'][site])
            except (OSError, ValueError):
                propagation['site_outcomes'][site] = 'readback_unavailable'
                propagation['reason'] = 'pricing_curve_recipient_readback_mismatch:' + site
                return False
            item['observed_rows'][site] = row
            propagation['actual_hashes'][site] = fingerprint(editable(row))
            if (before is None or not curve_specs_match(row, item['target'])
                    or not curve_prices_match(row, item['target'])
                    or not unchanged(before, row, platform, True)):
                propagation['site_outcomes'][site] = 'target_mismatch'
                propagation['reason'] = 'pricing_curve_recipient_readback_mismatch:' + site
                return False
            propagation['site_outcomes'][site] = 'target_observed'
    return confirm_curve_primary(item)


def confirm_curve_primary(item):
    from fc_pricing_v3.price_curve import CATALOGUE_ORIGIN_FIELD, IDENTITY_FIELDS, curve_key, read_curve

    observed = item['observed_rows']['266']
    propagation = item['propagation']
    native_contract = {key: value for key, value in item['native_contract'].items()
                       if key != CATALOGUE_ORIGIN_FIELD}
    actual = read_curve(
        observed, {key: observed[key] for key in IDENTITY_FIELDS}, native_contract)
    actual_key = curve_key(actual)
    item.update(actual_site266_curve=actual, actual_site266_curve_key=actual_key)
    propagation.setdefault('confirmed_at', datetime.now(timezone.utc).isoformat())
    propagation.update(status='confirmed',
                       curve_mapping=dict(target_curve_key=item['target_curve_key'],
                                          actual_site266_curve_key=actual_key,
                                          basis='full_prices_and_tier_specs_readback'))
    propagation.pop('reason', None)
    return True


def curve_receipt_matches(stage):
    receipt = stage.get('post_response') or {}
    intent = stage['send_intent']
    return (receipt.get('http_status') == 200 and type(receipt.get('response_code')) is int
            and receipt['response_code'] == 1
            and bool(receipt.get('response_sha256'))
            and receipt.get('path') == intent.get('path')
            and receipt.get('intent_hash') == intent['intent_hash'])


def curve_rejected_receipt(item):
    """Recognize only the original Admin Goods edit's explicit failure reply."""
    from fc_pricing_v3.financial import fingerprint

    catalog = item['catalog']
    receipt = catalog.get('post_response') or {}
    intent = catalog.get('send_intent') or {}
    path = '/admin/goods.Goods/edit?id=' + str(PRODUCTS[item['platform']][0])
    expected = dict(path=path, before_hash=item['before_hash'], target_hash=item['target_hash'],
                    operation_id=item['operation_id'])
    sha = receipt.get('response_sha256')
    return (item['all_goods_id'] == PRODUCTS[item['platform']][0]
            and intent == dict(expected, intent_hash=fingerprint(expected))
            and receipt.get('path') == path and receipt.get('intent_hash') == intent['intent_hash']
            and receipt.get('http_status') == 200 and type(receipt.get('response_code')) is int
            and receipt['response_code'] == 0 and isinstance(sha, str)
            and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha)
            and not catalog.get('confirmed_at')
            and not {'send_intent', 'post_response', 'write_performed'}.intersection(item['projection']))


def confirm_curve_rejection(manager, item, all_row):
    from fc_pricing_v3.financial import fingerprint

    catalog = item['catalog']
    catalog.pop('rejection_readback', None)
    catalog['reason'] = 'pricing_curve_admin_rejection_readback_mismatch'
    before = item['recipients_before']
    required = set(item.get('required_recipient_sites', item['recipient_goods']))
    if (not required.issubset(before) or not before.keys() <= item['recipient_goods'].keys()
            or fingerprint(editable(all_row)) != item['before_hash']):
        return
    for site, row in before.items():
        actual = read_row(manager, item['platform'], int(site), recipient_id=item['recipient_goods'][site])
        item['observed_rows'][site] = actual
        if editable(row) != editable(actual):
            return
    catalog['status'] = 'rejected_no_change'
    catalog['reason'] = 'pricing_curve_admin_rejected'
    catalog['rejection_readback'] = dict(checked_at=datetime.now(timezone.utc).isoformat(),
        hashes={site: fingerprint(editable(item['observed_rows'][site])) for site in ('0', *before)})
    item['propagation']['status'] = 'unchanged'


def curve_rejection_verified(item):
    """Verify the saved full before/after evidence before releasing the operation."""
    from fc_pricing_v3.financial import fingerprint

    catalog = item['catalog']
    if catalog.get('status') != 'rejected_no_change' or not curve_rejected_receipt(item):
        return False
    observed = item.get('observed_rows') or {}
    before = {'0': item['before'], **item['recipients_before']}
    required = set(item.get('required_recipient_sites', item['recipient_goods']))
    readback = catalog.get('rejection_readback') or {}
    return (required.issubset(item['recipients_before']) and '266' in required
            and fingerprint(editable(item['before'])) == item['before_hash']
            and fingerprint(editable(item['target'])) == item['target_hash']
            and bool(readback.get('checked_at'))
            and all(site in observed and editable(observed[site]) == editable(row) for site, row in before.items())
            and readback.get('hashes') == {site: fingerprint(editable(row)) for site, row in before.items()})


def all_curve_changes_rejected(items):
    rejected = {platform for platform, row in items.items() if curve_rejection_verified(row)}
    return bool(rejected) and all(platform in rejected or (
        ('send_intent' not in row['catalog'] or row['catalog'].get('status') == 'not_sent')
        and 'post_response' not in row['catalog']
        and 'send_intent' not in row['projection'] and 'post_response' not in row['projection'])
        for platform, row in items.items())


def curve_projection(item, projection, before_send, persist):
    """Use the existing Order adapter and require the original response plus readback."""
    from fc_pricing_v3.financial import fingerprint

    state = item['projection']
    if state['status'] == 'not_required':
        return
    if not projection:
        if 'send_intent' not in state:
            state.update(status='unverified', reason='pricing_curve_order_projection_unverified')
        return
    platform, target_rate = item['platform'], item['target_rate']
    if 'before_read_only_rate' in state:
        readback = money(projection['read'](platform))
        if readback == money(state['before_read_only_rate']):
            if readback == money(target_rate):
                state.update(status='confirmed', readback_rate=str(readback), write_performed=False)
                state.pop('reason', None)
            else:
                state.update(status='unchanged_mismatch', reason='pricing_curve_order_preexisting_rate_mismatch',
                             readback_rate=str(readback), expected_rate=target_rate, write_performed=False)
        else:
            state.update(status='read_only_pending', reason='pricing_curve_order_projection_unexpected_change',
                         readback_rate=str(readback), expected_rate=target_rate, write_performed=False)
        return
    if 'send_intent' not in state:
        if before_send is None:
            return
        send = projection['prepare'](platform, item['before_rate'], target_rate)
        intent = dict(path=projection['path'], evidence_ref=projection['evidence_ref'], platform=platform,
                      operation_id=item['operation_id'], before_rate=item['before_rate'], target_rate=target_rate)
        intent['intent_hash'] = fingerprint(intent)
        state.update(status='dispatching', send_intent=intent)
        persist()

        def observe(meta):
            state['post_response'] = dict(meta, intent_hash=intent['intent_hash'])
            persist()

        try:
            before_send(platform)
        except (OSError, ValueError):
            state.pop('send_intent')
            state['status'] = 'pending'
            raise
        send(observe)
    elif (projection['evidence_ref'], projection['path']) != (
            state['send_intent']['evidence_ref'], state['send_intent']['path']):
        raise ValueError('pricing_curve_projection_evidence_changed')
    if not curve_receipt_matches(state):
        state.update(status='unknown', reason='pricing_curve_original_projection_receipt_unavailable')
    else:
        state.update(status='readback_pending', reason='pricing_curve_order_projection_readback_pending')
        if money(projection['read'](platform)) == money(target_rate):
            state.setdefault('confirmed_at', datetime.now(timezone.utc).isoformat())
            state.update(status='confirmed', readback_rate=target_rate)
            state.pop('reason', None)
        else:
            state['reason'] = 'pricing_curve_order_projection_mismatch'


def curve_result(audit, save_audit):
    from fc_pricing_v3.dispatch import CURVE_REJECTED

    values = audit['curve_results'].values()
    if not values:
        raise ValueError('pricing_curve_original_scope_missing')
    started = any('send_intent' in item['catalog'] and item['catalog']['status'] != 'not_sent'
                  for item in values)
    if all(item['catalog']['status'] == 'confirmed' and item['propagation']['status'] == 'confirmed' and
           item['projection']['status'] in ('confirmed', 'not_required', 'unchanged_mismatch') for item in values):
        status, audit_status = 'CONFIRMED', 'CONFIRMED'
    elif all_curve_changes_rejected(audit['curve_results']):
        status = audit_status = CURVE_REJECTED
    elif any(item['catalog'].get('confirmed_at') for item in values):
        status, audit_status = 'PARTIAL', 'PARTIAL'
    elif started:
        status, audit_status = 'UNKNOWN', 'UNCERTAIN'
    else:
        status, audit_status = 'NOT_SENT', 'FAILED_BEFORE_WRITE'
    audit.update(status=audit_status, stage='curve_result', business_dispatch_started=started)
    save_audit(audit)
    return dict(status=status, execution_id=audit['execution_id'], write_protocol=audit['write_protocol'],
                curve_results=audit['curve_results'], price_posts_retried=0, sync_replayed=False)


def drive_curve_catalog(manager, audit, save_audit, before_send, capabilities):
    """Use the original writer lock to dispatch each exact ALL target once."""
    from socket import timeout as socket_timeout
    from urllib.error import HTTPError, URLError
    from fc_pricing_v3.financial import fingerprint
    from fc_pricing_v3.price_curve import TWO_BAND_PRICE_EDIT

    def persist():
        save_audit(audit)

    retry_used = False
    for item in audit['curve_results'].values():
        platform = item['platform']
        capability = capabilities[platform]
        catalog = item['catalog']
        if 'send_intent' in catalog:
            raise ValueError('pricing_curve_catalog_already_dispatched')
        try:
            projection = capability.get('order_projection')
            if item['projection']['status'] == 'read_only_pending':
                if not projection:
                    raise ValueError('pricing_curve_order_projection_unverified')
                item['projection']['before_read_only_rate'] = str(money(projection['read'](platform)))
            if item['projection']['status'] == 'pending':
                if not projection:
                    raise ValueError('pricing_curve_order_projection_unverified')
                if money(projection['read'](platform)) != money(item['before_rate']):
                    raise ValueError('pricing_curve_order_before_rate_changed')
            explicit = item.get('required_recipient_sites')
            direct = (item['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT
                      and item.get('catalogue_status') == 'native_route_ready' and explicit is not None)
            if direct and (not isinstance(explicit, list) or not explicit
                           or any(not isinstance(site, str) for site in explicit)
                           or len(set(explicit)) != len(explicit) or '266' not in explicit
                           or not set(explicit).issubset(item['recipient_goods'])):
                raise ValueError('pricing_curve_required_recipient_scope_invalid')
            required = set(explicit if explicit is not None else item['recipient_goods'])
            item['recipients_before'] = {}

            def check_recipient(site, recipient):
                if site == '266' and item.get('primary_before_hash') and (
                        fingerprint(editable(recipient)) != item['primary_before_hash']):
                    raise ValueError('pricing_curve_primary_before_hash_changed')
                if site in required and not curve_specs_match(recipient, item['before']):
                    raise ValueError('pricing_curve_recipient_specs_changed:' + site)

            def read_preflight(site, goods=None):
                nonlocal retry_used
                def get():
                    return (read_row(manager, platform, 0) if site == 0 else
                            read_row(manager, platform, int(site), recipient_id=goods))
                try:
                    return get()
                except (TimeoutError, socket_timeout, URLError) as error:
                    if (isinstance(error, URLError) and (isinstance(error, HTTPError)
                            or not isinstance(error.reason, (TimeoutError, socket_timeout)))):
                        raise
                    if retry_used or (site != 0 and site not in required):
                        raise
                    retry_used = True
                    before_send(platform)
                    # A long timeout must not leave an earlier required CAS stale.
                    for prior, prior_goods in item['recipient_goods'].items():
                        if prior in required and prior in item['recipients_before']:
                            current = read_row(manager, platform, int(prior), recipient_id=prior_goods)
                            check_recipient(prior, current)
                            item['recipients_before'][prior] = current
                    return get()

            for site, goods in item['recipient_goods'].items():
                if direct and site not in required:
                    continue
                try:
                    recipient = read_preflight(site, goods)
                except (OSError, ValueError):
                    if site in required:
                        raise
                    continue
                item['recipients_before'][site] = recipient
                check_recipient(site, recipient)
            live = read_preflight(0)
            if fingerprint(editable(live)) != item['before_hash']:
                raise ValueError('pricing_curve_before_hash_changed')
            path = '/admin/goods.Goods/edit?id=' + str(item['all_goods_id'])
            intent = dict(path=path, before_hash=item['before_hash'], target_hash=item['target_hash'],
                          operation_id=item['operation_id'])
            intent['intent_hash'] = fingerprint(intent)
            catalog.update(status='dispatching', send_intent=intent)
            audit['business_dispatch_started'] = True
            persist()

            def observe(meta):
                catalog['post_response'] = dict(meta, intent_hash=intent['intent_hash'])
                persist()

            try:
                before_send(platform)
            except (OSError, ValueError):
                catalog['status'] = 'not_sent'
                raise
            try:
                api(manager, path, item['target'], observer=observe)
            except ValueError:
                if not curve_rejected_receipt(item):
                    raise
            if curve_readback(manager, item):
                persist()
                try:
                    curve_projection(item, projection, before_send, persist)
                finally:
                    if 'send_intent' in item['projection']:
                        curve_readback(manager, item)
        except (OSError, ValueError) as error:
            item['last_error'] = str(error) if isinstance(error, ValueError) else type(error).__name__
            if catalog['status'] == 'dispatching':
                catalog['status'] = 'readback_pending' if curve_receipt_matches(catalog) else 'unknown'
            if item['projection']['status'] == 'dispatching':
                item['projection']['status'] = ('readback_pending' if curve_receipt_matches(item['projection'])
                                                 else 'unknown')
        persist()
    return curve_result(audit, save_audit)


def reconcile_curve_catalog(manager, audit, save_audit, capabilities):
    """Retry GETs on the original intent, retaining an unknown write if its receipt is lost."""
    def persist():
        save_audit(audit)

    for platform, item in audit['curve_results'].items():
        try:
            if curve_readback(manager, item):
                capability = capabilities.get(platform, {})
                curve_projection(item, capability.get('order_projection'), None, persist)
                item.pop('last_error', None)
        except (OSError, ValueError) as error:
            item['last_error'] = str(error) if isinstance(error, ValueError) else type(error).__name__
        persist()
    return curve_result(audit, save_audit)


def wait_sources(manager, audit, policy, record, persist, read_policy,
                 max_seconds=45, interval_seconds=5, clock=None, sleep=None):
    """Only GETs: two stable confirmations; no POST/auth retry on any failure."""
    clock = clock or time.monotonic; sleep = sleep or time.sleep
    rates = validate(audit, policy)
    old = {r['platform']:money(r['b2c']) for r in audit.get('before',{}).get('rows',[])}
    identity = api(manager,'/admin/index/index')
    if not isinstance(identity,dict) or identity.get('adminInfo',{}).get('username') not in allowed_admin_usernames():raise ValueError('coin_identity_invalid')
    deadline=clock()+max_seconds;previous=None;baseline={}
    evidence={'status':'waiting','started_at':datetime.now(timezone.utc).isoformat(),
              'deadline_at':datetime.fromtimestamp(time.time()+max_seconds,timezone.utc).isoformat(),
              'max_seconds':max_seconds,'interval_seconds':interval_seconds,'required_stable_rounds':2,'rounds':[]}
    record['source_confirmation']=evidence;persist(record)
    try:
        while True:
            if clock()>=deadline:raise ValueError('coin_source_confirmation_timeout')
            current_policy=read_policy();validate(audit,current_policy)
            if current_policy!=policy:raise ValueError('coin_source_confirmation_policy_changed')
            round_evidence={'started_at':datetime.now(timezone.utc).isoformat(),'observations':[]}
            evidence['rounds'].append(round_evidence);persist(record)
            snapshot={};matched=True
            for platform in PRODUCTS:
                if clock()>=deadline:raise ValueError('coin_source_confirmation_timeout')
                item={'platform':platform,'product_id':PRODUCTS[platform][1],
                      'expected_unit_price':str(rates[platform]),'allowed_before_unit_price':str(old.get(platform,rates[platform]))}
                round_evidence['observations'].append(item);persist(record)
                def observe(meta):item.update(meta);persist(record)
                row=read_row(manager,platform,266,observe)
                item.update(observed_unit_price=str(row['unit_price']),raw_value_type=type(row['unit_price']).__name__,
                            tier_prices=deepcopy(row['more']['price']),
                            record_timestamps={k:row[k] for k in ('update_time','updated_at','updatetime','create_time','createtime') if k in row})
                persist(record)
                if clock()>=deadline:raise ValueError('coin_source_confirmation_timeout')
                value=money(row['unit_price'])
                if value not in (rates[platform],old.get(platform,rates[platform])):
                    raise ValueError('coin_source_or_before_changed')
                if platform in baseline and not unchanged(baseline[platform],row,platform,True):
                    raise ValueError('coin_source_protected_changed')
                baseline.setdefault(platform,deepcopy(row))
                matched=matched and value==rates[platform];snapshot[platform]=editable(row)
            round_evidence['all_rates_match']=matched;persist(record)
            if matched and previous==snapshot:
                evidence.update(status='confirmed',confirmed_at=datetime.now(timezone.utc).isoformat())
                persist(record);return snapshot
            previous=snapshot if matched else None
            remaining=deadline-clock()
            if remaining<=0:raise ValueError('coin_source_confirmation_timeout')
            sleep(min(interval_seconds,remaining))
    except Exception as error:
        evidence.update(status='stopped',stopped_at=datetime.now(timezone.utc).isoformat(),
                        reason=str(error) if isinstance(error,ValueError) else type(error).__name__)
        persist(record);raise


def validate(audit, policy):
    if (audit.get('status') not in ('CONFIRMED','PARTIAL') or audit.get('sync_confirmed') is not True
            or audit.get('automation_policy_revision') != policy.get('revision')
            or policy.get('system_enabled') is not True
            or set(policy.get('platforms', [])) != set(PRODUCTS)
            or (audit.get('automatic') is True and policy.get('mode') != 'auto')):
        raise ValueError('coin_all_sync_preflight_changed')
    if audit['status'] == 'PARTIAL' and audit.get('stage') != 'all_baseline_pending':
        raise ValueError('coin_all_sync_execution_unconfirmed')
    rows = audit.get('after', {}).get('rows', [])
    if len(rows) != 3 or {r.get('platform') for r in rows} != set(PRODUCTS):
        raise ValueError('coin_confirmed_rates_incomplete')
    return {r['platform']: money(r.get('b2c')) for r in rows}


def plan(manager, audit, policy):
    rates = validate(audit, policy)
    identity = api(manager, '/admin/index/index')
    if not isinstance(identity, dict) or identity.get('adminInfo', {}).get('username') not in allowed_admin_usernames():
        raise ValueError('coin_identity_invalid')
    steps = []
    for platform in PRODUCTS:
        fallback, source = read_row(manager, platform, 0), read_row(manager, platform, 266)
        if money(source['unit_price']) != rates[platform]:
            raise ValueError('coin_mmoexp_confirmed_rate_mismatch')
        # Only mirror actual, already-confirmed prices. Do not invent tiers or discounts.
        if any(fallback['more'][k] != source['more'][k] for k in ('gold','discount','give')):
            raise ValueError('coin_tier_basis_changed')
        payload = editable(fallback)
        payload['unit_price'] = deepcopy(source['unit_price'])
        payload['more']['price'] = deepcopy(source['more']['price'])
        changed = (money(fallback['unit_price']) != rates[platform]
                   or fallback['more']['price'] != source['more']['price'])
        steps.append({'platform':platform, 'product_id':fallback['id'],
                      'source_product_id':source['id'], 'before':fallback,
                      'source':source, 'payload':payload, 'changed':changed})
    return steps


def synchronize(manager, audit, policy, save_audit, claim, persist, read_policy, current_quote=None):
    validate(audit, policy)
    # The main execution itself blocks later writes and Players until all six reads pass.
    audit.update(status='PARTIAL', stage='all_baseline_pending')
    save_audit(audit)
    record = {'execution_id':audit['execution_id'], 'status':'preflight', 'steps':[]}
    try:
        claim(record)  # Exclusive ledger: an interrupted invocation must be reconciled.
        confirmed_sources=wait_sources(manager,audit,policy,record,persist,read_policy)
        steps = plan(manager, audit, policy)
        if any(editable(s['source'])!=confirmed_sources[s['platform']] for s in steps):
            raise ValueError('coin_source_changed_after_confirmation')
        record['steps'] = [{k:deepcopy(step[k]) for k in ('platform','product_id','source_product_id',
                            'before','source','payload','changed')} | {'status':'pending'} for step in steps]
        persist(record)
        return drive(manager, audit, policy, steps, record, save_audit, persist, read_policy, current_quote)
    except Exception:
        # Never turn a possibly successful POST into an automatic retry.
        record['status'] = 'needs_reconcile'
        try:
            persist(record)
        except (OSError, ValueError):
            pass
        audit['all_baseline'] = {'status':'needs_reconcile'}
        save_audit(audit)
        raise


def confirm_timed_out_write(manager, audit, step, item, record, persist, read_policy,
                            clock=None, sleep=None):
    """Prove a landed original POST with two stable GET rounds; never POST again."""
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    deadline = clock() + 30
    proof = {'status':'checking','original_error':'TimeoutError','max_seconds':30,
             'required_stable_rounds':2,'rounds':[],'price_posts_retried':0}
    item['timeout_readback'] = proof
    persist(record)
    previous = None
    for attempt in range(2):
        if clock() >= deadline:
            raise ValueError('coin_timeout_readback_deadline')
        rates = validate(audit, read_policy())
        identity = api(manager, '/admin/index/index')
        if not isinstance(identity, dict) or identity.get('adminInfo', {}).get('username') not in allowed_admin_usernames():
            raise ValueError('coin_identity_invalid')
        source = read_row(manager, step['platform'], 266)
        actual = read_row(manager, step['platform'], 0)
        if (not unchanged(step['source'], source, step['platform'])
                or money(source['unit_price']) != rates[step['platform']]):
            raise ValueError('coin_timeout_source_changed')
        verify_step(step, actual, source)
        observed = {'source':editable(source),'actual':editable(actual)}
        if clock() >= deadline or (previous is not None and observed != previous):
            raise ValueError('coin_timeout_readback_not_stable')
        proof['rounds'].append({'checked_at':datetime.now(timezone.utc).isoformat(),
            'product_id':step['product_id'],'source_product_id':step['source_product_id'],
            'snapshot_sha256':hashlib.sha256(json.dumps(observed,sort_keys=True).encode()).hexdigest()})
        persist(record)
        previous = observed
        if attempt == 0:
            sleep(5)
    proof.update(status='confirmed',confirmed_at=datetime.now(timezone.utc).isoformat())
    persist(record)


def drive(manager, audit, policy, steps, record, save_audit, persist, read_policy, current_quote=None):
    try:
        # One shared read-only budget for every post-dispatch confirmation below.
        readback_deadline = time.monotonic() + READBACK_TOTAL_SECONDS
        for step, item in zip(steps, record['steps']):
            validate(audit, read_policy())
            current_source = read_row(manager, step['platform'], 266)
            current = read_row(manager, step['platform'], 0)
            if not unchanged(step['source'], current_source, step['platform']):
                raise ValueError('coin_source_or_before_changed')
            if item['status'] == 'confirmed':
                # Explicitly reconciled landed write: read it, NEVER dispatch it again.
                verify_step(step, current, current_source)
                continue
            if item['status'] != 'pending' or editable(current) != editable(step['before']):
                raise ValueError('coin_source_or_before_changed')
            if step['changed']:
                from automation_policy import hooks_before_write
                native = (audit.get('pricing_decision_receipt') or {}).get('price_scope_contract') == 'fc27_three_platform_v1'
                scope = [step['platform']] if native else (['PS','XBOX'] if step['platform'] in ('PS','XBOX') else ['PC'])
                hooks_before_write(read_policy(), scope, audit.get('automatic') is True,
                                   current_quote=current_quote)
                item['status'] = 'dispatching'
                record['status'] = 'dispatching'
                persist(record)  # Durable intent BEFORE a single POST.
                def observe_post(meta):
                    item['post_response'] = meta
                    persist(record)
                try:
                    api(manager, '/admin/goods.Goods/edit?id=' + str(step['product_id']),
                        step['payload'], observer=observe_post)
                except TimeoutError:
                    confirm_timed_out_write(manager, audit, step, item, record, persist, read_policy)
            if step['changed']:
                # Confirm only by re-reading: a momentary stale row is not a failed write,
                # and the POST above is never repeated by this bounded GET loop.
                verify_dispatch_readback(manager, step, current_source, item, record, persist,
                                         max_seconds=readback_deadline - time.monotonic())
            else:
                verify_step(step, read_row(manager, step['platform'], 0), current_source)
            item['status'] = 'confirmed'
            persist(record)
        for step in steps:
            source = read_row(manager, step['platform'], 266)
            actual = read_row(manager, step['platform'], 0)
            if (not unchanged(step['source'], source, step['platform'])
                    or not unchanged(step['before'], actual, step['platform'], True)
                    or money(actual['unit_price']) != money(source['unit_price'])
                    or actual['more']['price'] != source['more']['price']):
                raise ValueError('coin_six_product_readback_mismatch')
        record.update(status='confirmed', completed_at=datetime.now(timezone.utc).isoformat())
        persist(record)
        audit.update(status='CONFIRMED', stage='readback_confirmed',
                     all_baseline={'status':'confirmed', 'platforms':list(PRODUCTS),
                                   'products':[s['product_id'] for s in steps],
                                   'completed_at':record['completed_at']})
        save_audit(audit)
        return {'status':'confirmed', 'platforms':list(PRODUCTS),
                'changed_products':[s['product_id'] for s in steps if s['changed']]}
    except Exception:
        # Never turn a possibly successful POST into an automatic retry.
        record['status'] = 'needs_reconcile'
        try:
            persist(record)
        except (OSError, ValueError):
            pass
        audit['all_baseline'] = {'status':'needs_reconcile'}
        save_audit(audit)
        raise


def verify_step(step, actual, source):
    if (not unchanged(step['before'], actual, step['platform'], True)
            or money(actual['unit_price']) != money(source['unit_price'])
            or actual['more']['price'] != source['more']['price']):
        raise ValueError('coin_all_readback_mismatch')


def verify_dispatch_readback(manager, step, source, item, record, persist,
                             max_seconds=None, interval_seconds=READBACK_INTERVAL_SECONDS,
                             clock=None, sleep=None):
    """Confirm a just-dispatched ALL product with bounded, read-only re-reads.

    The product is read again until READBACK_STABLE_ROUNDS consecutive rounds
    match the already confirmed MMOEXP source, so a momentary stale row cannot
    be mistaken for a failed write. This loop only ever issues GETs: the price
    POST is never dispatched again here, and the whole loop is bounded by
    max_seconds (itself capped by READBACK_STEP_SECONDS).
    """
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    budget = READBACK_STEP_SECONDS if max_seconds is None else max(0.0, max_seconds)
    budget = min(budget, READBACK_STEP_SECONDS)
    deadline = clock() + budget
    proof = {'status':'checking', 'read_only':True, 'price_posts_retried':0,
             'max_seconds':budget, 'interval_seconds':interval_seconds,
             'required_stable_rounds':READBACK_STABLE_ROUNDS, 'rounds':[]}
    item['dispatch_readback'] = proof
    persist(record)
    previous = None
    rounds = max(READBACK_STABLE_ROUNDS, int(budget // interval_seconds) + READBACK_STABLE_ROUNDS)
    for attempt in range(rounds):
        actual = read_row(manager, step['platform'], 0)
        try:
            verify_step(step, actual, source)
        except ValueError:
            matched = False
        else:
            matched = True
        observed = editable(actual)
        proof['rounds'].append({'checked_at':datetime.now(timezone.utc).isoformat(),
            'attempt':attempt, 'product_id':step['product_id'], 'matched':matched,
            'unit_price':str(actual.get('unit_price')),
            'row_sha256':hashlib.sha256(json.dumps(observed, sort_keys=True).encode()).hexdigest()})
        persist(record)
        if matched and previous == observed:
            proof.update(status='confirmed', confirmed_at=datetime.now(timezone.utc).isoformat())
            persist(record)
            return actual
        previous = observed if matched else None
        if attempt == rounds - 1:
            break
        remaining = deadline - clock()
        # An exhausted budget only stops the waiting, never the minimum proof.
        if remaining > 0:
            sleep(min(interval_seconds, remaining))
    proof.update(status='stopped', stopped_at=datetime.now(timezone.utc).isoformat(),
                 reason='coin_all_readback_timeout')
    persist(record)
    raise ValueError('coin_all_readback_mismatch')


def resume_synchronize(manager, audit, policy, record, save_audit, persist, read_policy):
    """Explicit once-only reconciliation; unfinished dispatch must already read back."""
    validate(audit, policy)
    if (audit.get('kind') != 'all_baseline_repair'
            or record.get('execution_id') != audit['execution_id']
            or record.get('status') != 'needs_reconcile'
            or [s.get('platform') for s in record.get('steps', [])] != list(PRODUCTS)
            or [s.get('status') for s in record['steps']] != ['dispatching','pending','pending']):
        raise ValueError('coin_reconcile_scope_changed')
    steps = record['steps']
    # Validate every persisted identity and payload against the original snapshots.
    for step in steps:
        platform = step['platform']; all_id, source_id, aid = PRODUCTS[platform]
        if step['product_id'] != all_id or step['source_product_id'] != source_id:
            raise ValueError('coin_reconcile_scope_changed')
        expected = editable(step['before'])
        expected['unit_price'] = step['source']['unit_price']
        expected['more']['price'] = step['source']['more']['price']
        if step['payload'] != expected: raise ValueError('coin_reconcile_payload_changed')
        source = read_row(manager, platform, 266); current = read_row(manager, platform, 0)
        if (not unchanged(step['source'], source, platform)
                or money(source['unit_price']) != validate(audit, policy)[platform]):
            raise ValueError('coin_reconcile_source_changed')
        if step['status'] == 'dispatching': verify_step(step, current, source)
        elif editable(current) != editable(step['before']):
            raise ValueError('coin_reconcile_pending_changed')
    # Only ledger changes here; the PS business write is already independently proven.
    steps[0]['status'] = 'confirmed'
    steps[0]['reconciled_read_only_at'] = datetime.now(timezone.utc).isoformat()
    record['status'] = 'reconciled_continuation'
    persist(record)
    return drive(manager, audit, policy, steps, record, save_audit, persist, read_policy)


def resume_empty_preflight(manager, audit, policy, record, save_audit, persist, read_policy):
    """Continue only a proven empty ALL preflight; never repeat MMOEXP synchronization."""
    if (audit.get('status')!='PARTIAL' or audit.get('stage')!='stopped'
            or audit.get('error')!='coin_mmoexp_confirmed_rate_mismatch'
            or audit.get('sync_confirmed') is not True or audit.get('automatic') is not True
            or record.get('execution_id')!=audit.get('execution_id')
            or record.get('status')!='needs_reconcile' or record.get('steps')!=[]):
        raise ValueError('coin_empty_recovery_scope_changed')
    context=deepcopy(audit);context['stage']='all_baseline_pending'
    validate(context,policy)
    confirmed_sources=wait_sources(manager,context,policy,record,persist,read_policy)
    steps=plan(manager,context,policy)
    if any(editable(s['source'])!=confirmed_sources[s['platform']] for s in steps):
        raise ValueError('coin_source_changed_after_confirmation')
    record['steps']=[{k:deepcopy(s[k]) for k in ('platform','product_id','source_product_id','before','source','payload','changed')}|{'status':'pending'} for s in steps]
    record['status']='continued_after_source_confirmation';persist(record)
    audit.setdefault('recovery_history',[]).append({'stage':audit['stage'],'error':audit['error'],
        'continued_at':datetime.now(timezone.utc).isoformat(),'mmoexp_replayed':False})
    audit.update(stage='all_baseline_pending');save_audit(audit)
    return drive(manager,audit,policy,steps,record,save_audit,persist,read_policy)


def atomic(path, value):
    fd, name = tempfile.mkstemp(prefix='.coin-all-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(',',':'))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o640)
        if path.exists():
            os.chown(name, -1, path.stat().st_gid)
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def mirror_confirmed(audit, policy, save_audit, root, read_policy, current_quote=None, manager=None):
    sys.path.insert(0, '/usr/local/bin')
    from p2pah_session_service import SessionManager, read_private_config
    ledger = root / 'all-coin-sync' / (audit['execution_id'] + '.json')
    claimed = False
    def claim(record):
        nonlocal claimed
        with ledger.open('x', encoding='utf-8') as stream:
            json.dump(record, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(ledger, 0o640)
        claimed = True
    def persist(record):
        if not claimed: raise ValueError('coin_all_ledger_not_owned')
        atomic(ledger, record)
    manager = manager or SessionManager(read_private_config())
    if not manager.ensure(): raise ValueError('coin_auth_unavailable')
    return synchronize(manager, audit, policy, save_audit, claim, persist, read_policy, current_quote)


def reconcile_original(manager, audit, record, save_audit, persist, read_policy,
                       current_quote=None, sleep=None):
    """Reconcile one original ALL ledger; only persisted pending steps may dispatch."""
    sleep = sleep or time.sleep
    if record.get('execution_id') != audit.get('execution_id') or record.get('status') not in (
            'preflight', 'dispatching', 'needs_reconcile', 'confirmed',
            'reconciled_continuation', 'continued_after_source_confirmation'):
        raise ValueError('coin_original_ledger_scope_invalid')
    steps = record.get('steps')
    if not isinstance(steps,list) or steps and [step.get('platform') for step in steps] != list(PRODUCTS):
        raise ValueError('coin_original_ledger_scope_invalid')
    rates = {r['platform']:money(r['b2c']) for r in audit.get('after',{}).get('rows',[])}
    if set(rates)!=set(PRODUCTS) or audit.get('sync_confirmed') is not True:
        raise ValueError('coin_original_order_confirmation_missing')
    if not steps:
        if current_quote is None:
            return dict(status='requires_fresh_postwrite_authorization',all_posts_retried=0)
        policy=read_policy()
        context=dict(audit,status='PARTIAL',stage='all_baseline_pending')
        confirmed=wait_sources(manager,context,policy,record,persist,read_policy)
        planned=plan(manager,context,policy)
        if any(editable(step['source'])!=confirmed[step['platform']] for step in planned):
            raise ValueError('coin_original_source_changed')
        record['steps']=[{k:deepcopy(step[k]) for k in ('platform','product_id','source_product_id',
                         'before','source','payload','changed')} | {'status':'pending'} for step in planned]
        record['status']='continued_after_source_confirmation';persist(record)
        return drive(manager,context,policy,record['steps'],record,save_audit,persist,read_policy,current_quote)
    for step in steps:
        platform=step['platform'];all_id,source_id,_=PRODUCTS[platform]
        if (step.get('product_id')!=all_id or step.get('source_product_id')!=source_id
                or step.get('status') not in ('pending','dispatching','confirmed')):
            raise ValueError('coin_original_ledger_scope_invalid')
        expected=editable(step['before'])
        expected['unit_price']=step['source']['unit_price']
        expected['more']['price']=step['source']['more']['price']
        if step.get('payload')!=expected:
            raise ValueError('coin_original_ledger_payload_changed')
    previous=None
    for attempt in range(2):
        identity=api(manager,'/admin/index/index')
        if not isinstance(identity,dict) or identity.get('adminInfo',{}).get('username') not in allowed_admin_usernames():
            raise ValueError('coin_identity_invalid')
        observed={}
        for step in steps:
            platform=step['platform']
            source=read_row(manager,platform,266)
            actual=read_row(manager,platform,0)
            if (not unchanged(step['source'],source,platform)
                    or money(source['unit_price'])!=rates[platform]):
                raise ValueError('coin_original_source_changed')
            if step['status'] in ('confirmed','dispatching'):
                verify_step(step,actual,source)
            elif editable(actual)!=editable(step['before']):
                verify_step(step,actual,source)
            observed[platform]=dict(source=editable(source),actual=editable(actual))
        if previous is not None and observed!=previous:
            raise ValueError('coin_original_all_readback_unstable')
        previous=observed
        if attempt==0:sleep(2)
    checked=datetime.now(timezone.utc).isoformat()
    for step in steps:
        if step['status']=='dispatching':
            step.update(status='confirmed',reconciled_read_only_at=checked,
                        original_post_not_retried=True)
        elif step['status']=='pending' and editable(previous[step['platform']]['actual'])==editable(step['payload']):
            step.update(status='confirmed',observed_target_without_original_post_at=checked,
                        original_post_not_retried=True)
    record['original_reconciliation']=dict(checked_at=checked,stable_rounds=2,
        readback_sha256=hashlib.sha256(json.dumps(previous,sort_keys=True).encode()).hexdigest(),
        price_posts_retried=0)
    persist(record)
    if any(step['status']=='pending' for step in steps):
        if current_quote is None:
            return dict(status='requires_fresh_postwrite_authorization',all_posts_retried=0)
        context=dict(audit,status='PARTIAL',stage='all_baseline_pending')
        return drive(manager,context,read_policy(),steps,record,save_audit,persist,read_policy,current_quote)
    record.update(status='confirmed',completed_at=checked)
    persist(record)
    audit.update(status='CONFIRMED',stage='readback_confirmed',sync_confirmed=True,
        all_baseline=dict(status='confirmed',platforms=list(PRODUCTS),
                          products=[step['product_id'] for step in steps],
                          completed_at=checked,reconciled_read_only=True))
    save_audit(audit)
    return dict(status='confirmed',platforms=list(PRODUCTS),all_posts_retried=0)
