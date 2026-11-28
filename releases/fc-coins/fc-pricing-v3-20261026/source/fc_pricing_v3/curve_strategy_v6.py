"""Offline V6 fixed-reference candidates and confirmation-bound adoption."""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, localcontext
import json
import re
from statistics import median

from .financial import fingerprint, instant
from .price_curve import (COIN_BAND_ANCHORS, FORWARD_TIER_EDIT, TWO_BAND_PRICE_EDIT, coin_quantity_band,
                          compile_curve, curve_key, quote_native, read_curve, two_band_unit_price)
from .pricing_proof_v6 import CONTRACT as PROOF_CONTRACT, FAILED, INCOMPLETE, PROVEN
from .admin_readback import GID_FC27, MID_FC27_COINS, PLATFORM_AID, SITE_MAIN


ANCHORS = COIN_BAND_ANCHORS
MARKET_ANCHOR_VERSION = 'market-anchor-v1'
CARNIVAL_CAMPAIGN = 'carnival_202611'
CARNIVAL_START_DAY = '2026-11-19'
STEP = Decimal('.03')
CENT = Decimal('.01')
INTERMEDIATE_TRIAL_STEPS = (Decimal('.02'), Decimal('.01'))
INITIAL_MARKET_ANCHOR = {
    'PS': {'small': {'p': '.08', 'u': '0'}, 'large': {'p': '.06', 'u': '0'}},
    'XBOX': {'small': {'p': '.08', 'u': '0'}, 'large': {'p': '.06', 'u': '0'}},
    'PC': {'small': {'p': '.12', 'u': '-.03'}, 'large': {'p': '.10', 'u': '-.03'}},
}


def market_anchor_parameters(value=None):
    """Keep all platform/band ratios explicit in the versioned plan."""
    value = INITIAL_MARKET_ANCHOR if value is None else value
    if not isinstance(value, dict) or set(value) != set(INITIAL_MARKET_ANCHOR):
        raise ValueError('market_anchor_parameters_invalid')
    result = {}
    for platform, bands in value.items():
        if not isinstance(bands, dict) or set(bands) != set(ANCHORS):
            raise ValueError('market_anchor_parameters_invalid')
        result[platform] = {}
        for band, terms in bands.items():
            if not isinstance(terms, dict) or set(terms) not in ({'p', 'u'}, {'p', 'u', 'p_low'}):
                raise ValueError('market_anchor_parameters_invalid')
            parsed = {}
            for field, lower, upper in (('p', '0', '.15'), ('u', '-.05', '.03'), ('p_low', '-.15', '0')):
                if field not in terms:
                    continue
                try:
                    number = Decimal(str(terms[field]))
                    valid = number.is_finite() and Decimal(lower) <= number <= Decimal(upper)
                except (ArithmeticError, TypeError, ValueError):
                    valid = False
                if not valid:
                    raise ValueError('market_anchor_parameters_invalid')
                parsed[field] = str(number)
            result[platform][band] = parsed
    return result


def margin_band_parameters(value, anchors):
    """Validate the optional Stage 5 plan parameters at the revision boundary."""
    if value is None:
        return None
    invalid = 'margin_band_parameters_invalid'
    platforms = set(INITIAL_MARKET_ANCHOR)
    if (not isinstance(value, dict) or set(value) - {'schedule_hours', 'promotion_guard'} != platforms
            or not all('p_low' in terms for bands in anchors.values() for terms in bands.values())):
        raise ValueError(invalid)
    hours = value.get('schedule_hours', [2, 6, 9, 13, 17, 21])
    if (not isinstance(hours, list) or not hours or any(type(hour) is not int or not 0 <= hour <= 23 for hour in hours)
            or len(set(hours)) != len(hours)):
        raise ValueError(invalid)
    parsed = dict(schedule_hours=sorted(hours))
    for platform in INITIAL_MARKET_ANCHOR:
        terms = value[platform]
        if not isinstance(terms, dict) or set(terms) != {'target'}:
            raise ValueError(invalid)
        try:
            target = Decimal(str(terms['target']))
        except (ArithmeticError, TypeError, ValueError):
            raise ValueError(invalid) from None
        if not target.is_finite() or not Decimal('.28') <= target <= Decimal('.35') or target % Decimal('.005'):
            raise ValueError(invalid)
        parsed[platform] = dict(target=str(target.normalize()))
    if 'promotion_guard' in value:
        parsed['promotion_guard'] = _promotion_guard_parameters(value['promotion_guard'])
    return parsed


DEFAULT_PROMOTION_MAX_ABSORB = Decimal('.045')


def _promotion_guard_parameters(value):
    invalid = 'margin_band_parameters_invalid'
    if (not isinstance(value, dict)
            or set(value) - {'max_absorb'} != {'campaign', 'start_day', 'last_redeem_day', 'baseline', 'baseline_revision'}
            or value['campaign'] != CARNIVAL_CAMPAIGN or value['start_day'] != CARNIVAL_START_DAY
            or not isinstance(value['baseline_revision'], str)
            or not re.fullmatch(r'se_[0-9a-f]{32}', value['baseline_revision'])
            or not isinstance(value['baseline'], dict) or set(value['baseline']) != set(INITIAL_MARKET_ANCHOR)):
        raise ValueError(invalid)
    try:
        last_day = date.fromisoformat(value['last_redeem_day'])
        baseline = {platform: Decimal(str(ratio)) for platform, ratio in value['baseline'].items()}
        max_absorb = Decimal(str(value.get('max_absorb', DEFAULT_PROMOTION_MAX_ABSORB)))
        if (not max_absorb.is_finite() or not 0 <= max_absorb <= Decimal('.05')
                or last_day.isoformat() != value['last_redeem_day'] or last_day.isoformat() < CARNIVAL_START_DAY
                or any(not ratio.is_finite() or not 0 <= ratio < 1 for ratio in baseline.values())):
            raise ValueError(invalid)
        parsed = dict(value, baseline={platform: str(ratio.normalize()) for platform, ratio in baseline.items()})
        if 'max_absorb' in parsed:
            parsed['max_absorb'] = str(max_absorb.normalize())
        return parsed
    except (ArithmeticError, TypeError, ValueError):
        raise ValueError(invalid) from None


def _position_quotes(platform, offers, at, quantity):
    """Choose an ordinary same-size package, estimating only a missing 1M tier."""
    candidates = {}
    for row in offers:
        source, size = row.get('source'), row.get('purchase_k')
        if (source not in ('Lootbar', 'U7Buy') or size not in ('100', quantity)
                or row.get('platform') != platform or row.get('currency') != 'USD'
                or str(row.get('region_id') or 0) != '0' or row.get('comparable') is not True
                or row.get('conditional') is not False or row.get('promotion_eligibility') != 'all_customers'
                or row.get('extra_bonus_tier') is True):
            continue
        merchandise = source == 'Lootbar' and row.get('comparability_basis') in (
            'lootbar_observed_100k_merchandise_no_delivery_tier', 'lootbar_observed_native_merchandise_no_delivery_tier')
        if row.get('delivery_method') != 'comfort_trade' and not merchandise:
            continue
        try:
            captured = instant(row['captured_at'])
            price = Decimal(row['regular_price'])
            if not price.is_finite() or price <= 0 or not 0 <= (at-captured).total_seconds() <= 900:
                continue
        except (ArithmeticError, KeyError, TypeError, ValueError):
            continue
        candidates.setdefault(source, {}).setdefault(size, []).append((captured, price, row))

    quotes = {}
    for source, sizes in candidates.items():
        for observed in dict.fromkeys((quantity, '100')):
            if observed not in sizes:
                continue
            rows = sizes[observed]
            latest = max(stamp for stamp, _, _ in rows)
            latest_rows = [(price, row) for stamp, price, row in rows if stamp == latest]
            if len({(price, row.get('bonus_k')) for price, row in latest_rows}) != 1:
                continue
            price, row = latest_rows[0]
            quotes[source] = dict(source=source, purchase_k=quantity, observed_purchase_k=observed,
                price_usd=str(price * (Decimal(quantity) / Decimal(observed))), captured_at=row['captured_at'],
                basis='native' if quantity == observed else 'linear_from_100k',
                observation_id=row.get('observation_id'), bonus_k=row.get('bonus_k'))
            break
    return quotes


def _band_market_position(platform, quantity, offers, now, history):
    quotes = _position_quotes(platform, offers, now, quantity)
    previous = {}
    for row in history:
        try:
            at = instant(row['as_of'])
        except (KeyError, TypeError, ValueError):
            continue
        if now - timedelta(days=7) <= at < now and row.get('round_id'):
            if row['round_id'] not in previous or previous[row['round_id']]['at'] < at:
                previous[row['round_id']] = dict(row, at=at, quotes=_position_quotes(platform, row.get('offers') or [], at, quantity))
    recent = sorted((row for row in previous.values() if row.get('automatic', True)),
                    key=lambda row: row['at'], reverse=True)[:2]
    prices = {source: median([Decimal(quote['price_usd'])] +
                            [Decimal(row['quotes'][source]['price_usd'])
                             for row in recent if source in row['quotes']])
              for source, quote in quotes.items()}
    pairs = {}
    for observed in [quotes] + [row['quotes'] for row in previous.values()]:
        if not {'Lootbar', 'U7Buy'} <= observed.keys():
            continue
        pair = [observed[source] for source in ('Lootbar', 'U7Buy')]
        if all(instant(row['captured_at']) >= now - timedelta(days=7) for row in pair):
            key = tuple((row['captured_at'], row['price_usd']) for row in pair)
            pairs[key] = Decimal(pair[0]['price_usd']) / Decimal(pair[1]['price_usd'])
    ratio = median(list(pairs.values())) if pairs else None
    gaps = []
    fallback = 'direct' if {'Lootbar', 'U7Buy'} <= prices.keys() else 'lootbar_only'
    if 'Lootbar' not in prices:
        if 'U7Buy' in prices and ratio is not None:
            prices['Lootbar'] = prices['U7Buy'] * ratio
            fallback = 'u7_ratio'
        else:
            fallback = 'floor_only'
            if 'U7Buy' in prices:
                gaps.append('market_anchor_ratio_unavailable')
    return dict(prices=prices, current_quotes=quotes, fallback=fallback, gaps=gaps,
                ratio_r=str(ratio) if ratio is not None else None, ratio_pairs=len(pairs),
                median_round_ids=[row['round_id'] for row in recent])


def market_anchor_targets(platform, current, offers, now, *, parameters=None, history=()):
    """Compare ordinary ticket prices at the same purchased quantity."""
    terms = market_anchor_parameters(parameters)[platform]
    anchors, low_anchors, bands = {}, {}, {}
    for band, quantity in ANCHORS.items():
        position = _band_market_position(platform, quantity, offers, now, history)
        prices = position.pop('prices')
        position['reference_package_usd'] = {source: str(price) for source, price in prices.items()}
        bands[band] = position
        if position['fallback'] == 'floor_only':
            continue
        target = prices['Lootbar'] * (1 + Decimal(terms[band]['p']))
        if 'U7Buy' in prices:
            target = min(target, prices['U7Buy'] * (1 + Decimal(terms[band]['u'])))
        anchors[band] = str(target.quantize(CENT, rounding=ROUND_HALF_UP))
        if 'p_low' in terms[band]:
            low = prices['Lootbar'] * (1 + Decimal(terms[band]['p_low']))
            low_anchors[band] = str(low.quantize(CENT, rounding=ROUND_HALF_UP))
    small = bands['small']
    result = dict(source='market_anchor', comparison_basis='ordinary_purchase_package',
                  anchors=anchors, parameters=terms, market_bands=bands,
                  reference_usd_per_100k=small['reference_package_usd'],
                  floor_only=not anchors, gaps=sorted({gap for band in bands.values() for gap in band['gaps']}))
    for key in ('fallback', 'ratio_r', 'ratio_pairs', 'median_round_ids', 'current_quotes'):
        result[key] = small[key]
    if any('p_low' in term for term in terms.values()):
        result['low_anchors'] = low_anchors
    return result


def band_anchors(curve):
    prices = {row['purchase_k']: row['native_price_usd'] for row in curve['tiers']}
    return {band: prices[quantity] for band, quantity in ANCHORS.items() if quantity in prices}


def large_market_reference(platform, offers, now, *, region_id, delivery_method):
    if delivery_method in (None, '', 'unknown'):
        return []
    references = []
    for row in offers:
        if row.get('source') in ('IGGM', 'U4GM') or row.get('delivery_method') != delivery_method:
            continue
        reference = _linear_market_reference(platform, row, now, region_id)
        if reference:
            references.append(reference)
    return references


def _linear_market_reference(platform, row, now, region_id):
    if (row.get('platform') != platform or row.get('purchase_k') != '100'
            or row.get('currency') != 'USD' or row.get('promotion_eligibility') != 'all_customers'
            or row.get('conditional') is True or row.get('comparable') is not True
            or str(row.get('region_id') or 0) != str(region_id)):
        return None
    try:
        if not 0 <= (now - instant(row['captured_at'])).total_seconds() <= 900:
            return None
        price = Decimal(row['regular_price']) * 10
        bonus = Decimal(row['bonus_k']) * 10
        if not price.is_finite() or not bonus.is_finite() or price <= 0 or bonus < 0:
            return None
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None
    return dict(source=row['source'], captured_at=row['captured_at'], observation_id=row.get('observation_id'),
                basis='linear_from_100k', purchase_k='1000', price_usd=str(price), bonus_k=str(bonus),
                usd_per_delivered_100k=str(price * 100 / (1000 + bonus)),
                delivery_method=row.get('delivery_method'), comparability_basis=row.get('comparability_basis'))


def large_market_comparison(references, normal, final):
    def unit_rate(curve):
        tier = next((row for row in curve['tiers'] if row['purchase_k'] == '1000'), None)
        if tier:
            return Decimal(tier['native_price_usd']) * 100 / (1000 + Decimal(tier['promised_bonus_k']))

    normal_rate, final_rate = unit_rate(normal), unit_rate(final)
    if normal_rate is None or final_rate is None:
        return []
    return [dict(row, normal_usd_per_delivered_100k=str(normal_rate), final_usd_per_delivered_100k=str(final_rate),
                 normal_difference_pct=str((normal_rate / Decimal(row['usd_per_delivered_100k']) - 1) * 100),
                 final_difference_pct=str((final_rate / Decimal(row['usd_per_delivered_100k']) - 1) * 100))
            for row in references]


def market_preference(current, platform, offers, performance, now):
    """Use the directly observed 100K comparison for the small band."""
    segment, quantity = 'small', ANCHORS['small']
    matched = []
    for row in offers:
        if (row.get('source') != 'Lootbar' or row.get('platform') != platform
                or row.get('purchase_k') != quantity or row.get('currency') != 'USD'
                or row.get('promotion_eligibility') != 'all_customers' or row.get('comparable') is not True
                or row.get('conditional') is True or row.get('region_id') not in (None, 0, '0')
                or not row.get('regular_price') or not row.get('delivered_k')):
            continue
        try:
            if 0 <= (now-instant(row['captured_at'])).total_seconds() <= 900:
                matched.append(row)
        except (KeyError, ValueError, TypeError):
            continue
    own = next((tier for tier in current['tiers'] if tier['purchase_k'] == quantity), None)
    if len(matched) != 1 or own is None:
        return None
    try:
        rival = Decimal(matched[0]['regular_price']) / Decimal(matched[0]['delivered_k'])
        current_rate = Decimal(own['native_price_usd']) / (Decimal(quantity) + Decimal(own['promised_bonus_k']))
        difference = current_rate / rival - 1
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None
    result = market_direction(segment, difference, performance)
    return dict(result, lootbar_price_difference=str(difference)) if result else None


def market_direction(segment, difference, performance):
    comparison = performance.get(segment) or {}
    if comparison.get('coverage_status') != 'comparable':
        return None
    try:
        current_metrics, previous_metrics = comparison['current'], comparison['previous']
        orders, prior_orders = (Decimal(str(row['paid_orders'])) for row in (current_metrics, previous_metrics))
        revenue, prior_revenue = (Decimal(str(row['net_paid_usd'])) for row in (current_metrics, previous_metrics))
        if not all(v.is_finite() for v in (orders, prior_orders, revenue, prior_revenue)):
            return None
        margin_field = comparison.get('margin_basis')
        margin, prior_margin = None, None
        if margin_field in ('contribution_usd', 'procurement_gross_usd'):
            margin, prior_margin = (Decimal(str(row[margin_field])) for row in (current_metrics, previous_metrics))
            if not margin.is_finite() or not prior_margin.is_finite():
                return None
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return None
    if prior_orders <= 0 or orders < 0:
        return None
    if (difference >= Decimal('.05') and orders <= prior_orders * Decimal('.90')
            and (revenue < prior_revenue or margin is not None and margin < prior_margin)):
        label = 'B'
    elif (difference <= Decimal('-.03') and orders >= prior_orders
            and margin is not None and margin >= prior_margin):
        label = 'C'
    else:
        return None
    return dict(segment=segment, label=label, comparison=comparison)


def _repair_rank(current, target, affected_segments):
    old_unit = Decimal(current['unit_price_usd_per_k'])
    new_unit = Decimal(target['unit_price_usd_per_k'])
    forward = target['native_contract'].get('price_edit_policy') == FORWARD_TIER_EDIT
    two_band = target['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT
    # Two-band unit_price is derived from the large tiers, so the tier checks cover it.
    if (current['identity'] != target['identity'] or _shape(current) != _shape(target)
            or not two_band and (new_unit < old_unit
                                 or not forward and new_unit != old_unit and 'small' not in affected_segments)):
        return None
    moves = {}
    for before, after in zip(current['tiers'], target['tiers']):
        segment = _group(before['purchase_k'])
        old, new = Decimal(before['native_price_usd']), Decimal(after['native_price_usd'])
        if (new < old and not (two_band and old - new <= CENT)) or segment not in affected_segments and (new != old or
                not forward and after['native_discount'] != before['native_discount']):
            return None
        if new > old:
            moves.setdefault(segment, []).append((new - old) / old)
    if not moves:
        return None
    return (max(max(values) for values in moves.values()), len(moves),
            sum(sum(values) for values in moves.values()),
            tuple(segment for segment in ANCHORS if segment in moves))


def minimum_repair(current, proven, affected_segments):
    """Rank independently quoted native repair points; never infer monotonicity."""
    eligible = [(rank, curve_key(candidate['curve']), candidate) for candidate in proven
                if (rank := _repair_rank(current, candidate['curve'], affected_segments)) is not None]
    return min(eligible, key=lambda item: item[:2], default=(None, None, None))[-1]


def curve_strategy_key(platform):
    return 'owned-curve-strategy-v6:' + platform


def primary_reference_curve(curve, platform):
    from .regional_public import SKU_IDS

    confirmed = _saved(curve)
    identity = confirmed['identity']
    if (identity['site_id'] != SITE_MAIN or identity['aid'] != PLATFORM_AID.get(platform)
            or identity['mid'] != MID_FC27_COINS or identity['gid'] != GID_FC27 or identity['cid'] != '9623'
            or identity['id'] != str(SKU_IDS.get(platform))):
        raise ValueError('strategy_reference_scope_mismatch')
    return confirmed


def _saved(curve):
    # Reuse F0's catalogue-origin check. A caller still supplies the confirmed
    # Goods readback and its original operation/receipt provenance.
    quote = quote_native(curve, dict(site_id=curve['identity']['site_id'], currency='USD',
                                     purchase_k='100', multiplier=1))
    if quote['catalogue_status'] != 'saved_tier':
        raise ValueError('strategy_confirmed_catalogue_required')
    return read_curve(curve['native_payload'], curve['identity'], curve['native_contract'])


def _shape(curve):
    """Compare saved terms apart from editor price controls and provenance."""
    row = deepcopy(curve['native_payload'])
    more = row['more'] if isinstance(row['more'], dict) else json.loads(row['more'])
    more['price'] = ['1'] * len(more['gold'])
    more['discount'] = ['100'] * len(more['gold'])
    row.update(unit_price='1', more=more)
    # Keep versioned semantics and unknown native controls in the terms key.
    contract = {key: value for key, value in curve['native_contract'].items()
                if key not in ('source', 'verified_domain', 'editor_asset_sha256', 'editor_handler_sha256',
                               'price_edit_policy')}
    return curve_key(read_curve(row, curve['identity'], contract))


def _group(quantity):
    return coin_quantity_band(quantity)


def segment_terms(curve, segment):
    tiers = [tier for tier in curve['tiers'] if _group(tier['purchase_k']) == segment]
    # Two-band unit_price is derived from the large tiers, not a separate term.
    owns_unit = segment == 'small' and curve['native_contract'].get('price_edit_policy') != TWO_BAND_PRICE_EDIT
    return dict(tiers=tiers, unit_price_usd_per_k=curve['unit_price_usd_per_k'] if owns_unit else None)


def segment_changes(before, after):
    return [segment for segment in ANCHORS if segment_terms(before, segment) != segment_terms(after, segment)]


def comparison_background_key(curve, segment):
    other = 'large' if segment == 'small' else 'small'
    return fingerprint([_shape(curve), segment_terms(curve, other)])


def segment_reference_id(reference, segment):
    return (reference.get('segment_sources') or {}).get(segment, reference)['reference_curve_id']


def update_reference_segments(reference, confirmed, segments, reference_id, receipt, kind):
    previous = reference['reference_curve']
    current_terms = read_curve(confirmed['native_payload'], confirmed['identity'], previous['native_contract'])
    if not segments or set(segments) - ANCHORS.keys() or _shape(previous) != _shape(current_terms):
        raise ValueError('strategy_reference_segment_terms_changed')
    previous_sources = reference.get('segment_sources') or {}
    prior_source = dict(reference_curve_id=reference['reference_curve_id'], curve_key=curve_key(previous),
                        readback_ref=reference.get('readback_ref'),
                        operation_id=reference.get('confirmed_operation_id'))
    sources = {segment: deepcopy(previous_sources.get(segment, prior_source)) for segment in ANCHORS}
    confirmed_key = curve_key(confirmed)
    for segment in segments:
        sources[segment] = dict(reference_curve_id=reference_id, curve_key=confirmed_key,
                                readback_ref=receipt['readback_ref'], operation_id=receipt['operation_id'],
                                kind=kind)
    payload = deepcopy(confirmed['native_payload'])
    if 'small' not in segments:
        payload['unit_price'] = previous['native_payload']['unit_price']
    raw = payload['more']
    more = raw if isinstance(raw, dict) else json.loads(raw)
    old_raw = previous['native_payload']['more']
    old_more = old_raw if isinstance(old_raw, dict) else json.loads(old_raw)
    for row in confirmed['tiers']:
        if _group(row['purchase_k']) not in segments:
            index = row['native_index']
            for field in ('price', 'discount'):
                more[field][index] = old_more[field][index]
    if confirmed['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT:
        unit = two_band_unit_price([dict(row, native_price_usd=more['price'][row['native_index']])
                                    for row in confirmed['tiers']])
        if unit is None:
            raise ValueError('pricing_curve_reference_anchor_missing')
        payload['unit_price'] = float(unit)
    if not isinstance(raw, dict):
        payload['more'] = json.dumps(more, ensure_ascii=False, separators=(',', ':'))
    baseline = (confirmed if payload == confirmed['native_payload'] else
                read_curve(payload, confirmed['identity'], confirmed['native_contract']))
    return dict(reference_curve=baseline, reference_curve_id=reference_id, segment_sources=sources,
                reference_curve_is_composite=len({source['reference_curve_id'] for source in sources.values()}) > 1,
                confirmed_operation_id=receipt['operation_id'], readback_ref=receipt['readback_ref'])


def _saved_discount_changed_at_same_price(current, adopted):
    previous_tiers = {tier['purchase_k']: tier for tier in adopted['tiers']}
    for tier in current['tiers']:
        previous = previous_tiers.get(tier['purchase_k'])
        if (previous and tier['native_price_usd'] == previous['native_price_usd']
                and tier['native_discount'] != previous['native_discount']):
            return True
    return False


def _candidate(curve, labels, current, *, tier_price_factors_verified=False):
    discount_changes = [dict(purchase_k=before['purchase_k'], before=before['native_discount'],
                             after=after['native_discount'])
                        for before, after in zip(current['tiers'], curve['tiers'])
                        if before['native_discount'] != after['native_discount']]
    return dict(curve=curve, curve_key=curve_key(curve), labels=labels,
                discount_changes=discount_changes,
                write_gaps=['native_discount_write_unverified']
                if discount_changes and not tier_price_factors_verified else [])


def _compiled_step(adopted, selected_segment, anchor, target, direction, editor_contract, unit_price, *, current=None):
    targets = dict(anchor_prices_usd={anchor: str(target)})
    if unit_price is not None:
        targets['unit_price_usd_per_k'] = unit_price
    two_band = editor_contract.get('price_edit_policy') == TWO_BAND_PRICE_EDIT
    compiled = compile_curve(current if two_band and current is not None else adopted, targets, editor_contract)
    if compiled['compilation_status'] != 'EDITOR_CANDIDATE':
        return None, compiled['gaps']
    forward = editor_contract.get('price_edit_policy') == FORWARD_TIER_EDIT
    for before, after, live in zip(adopted['tiers'], compiled['tiers'], (current or adopted)['tiers']):
        old, new = Decimal(before['native_price_usd']), Decimal(after['native_price_usd'])
        if two_band and _group(before['purchase_k']) != selected_segment:
            legal = Decimal(live['native_price_usd']) == new
        elif two_band:
            legal = 0 <= direction * (new - old) <= STEP * old + CENT
        elif (forward and Decimal(before['purchase_k']) < Decimal(anchor)
                or not forward and _group(before['purchase_k']) != selected_segment):
            legal = old == new
        else:
            with localcontext() as context:
                context.prec = max(28, len(old.as_tuple().digits) + len(new.as_tuple().digits) + 6)
                legal = 0 <= direction * (new - old) <= STEP * old
        if not legal:
            return None, [dict(code='compiled_tier_outside_segment_step', purchase_k=before['purchase_k'])]
    return compiled, []


def intermediate_candidates(comparison, preferred_label, editor_contract, *, tier_price_factors_verified=False,
                            step_sizes=None):
    """Yield distinct bounded native price steps from the outer bound toward fixed A."""
    if preferred_label not in ('B', 'C') or comparison['gaps'].get(preferred_label) == ['current_reference_catalogue_terms_differ']:
        return
    adopted = comparison['reference_curve']
    current = comparison['confirmed_current_curve']
    segment = comparison['selected_segment']
    anchor = ANCHORS[segment]
    basis = next((Decimal(tier['native_price_usd']) for tier in adopted['tiers'] if tier['purchase_k'] == anchor), None)
    if basis is None:
        return
    direction, rounding = (-1, ROUND_CEILING) if preferred_label == 'B' else (1, ROUND_FLOOR)
    outer = (basis * (1 + direction * STEP)).quantize(CENT, rounding=rounding)
    seen = {candidate['curve_key'] for candidate in comparison['candidates'] if preferred_label in candidate['labels']}
    if step_sizes is None:
        count = int(abs(outer - basis) / CENT)
        targets = (outer - direction * CENT * index for index in range(1, count + 1))
    else:
        targets = ((basis * (1 + direction * step)).quantize(CENT, rounding=rounding) for step in step_sizes)
    for target in targets:
        if not 0 < direction * (target - basis) < direction * (outer - basis):
            continue
        compiled, _ = _compiled_step(adopted, segment, anchor, target, direction, editor_contract, None, current=current)
        if compiled is not None:
            candidate = _candidate(compiled, [preferred_label], current,
                                   tier_price_factors_verified=tier_price_factors_verified)
            if candidate['curve_key'] not in seen:
                seen.add(candidate['curve_key'])
                yield candidate


def build_candidates(confirmed_current_curve, reference, episode, selected_segment,
                     *, unit_price_usd_per_k=None, editor_contract=None,
                     check_saved_discount_terms=False, tier_price_factors_verified=False):
    """Freeze one platform and compile only the requested segment off adopted A.

    Reference holds reference_curve/reference_curve_id. Episode holds
    comparison_episode_id and initial_reference_curve/initial_reference_curve_id.
    The caller supplies the evidence-appropriate editor base, when needed.
    Offline editor evidence can be separate from the saved curve's own contract.
    A fresh saved preview also checks for discount edits with no price change.
    """
    anchor = ANCHORS.get(selected_segment)
    if anchor is None:
        raise ValueError('strategy_segment_invalid')
    current = _saved(confirmed_current_curve)
    adopted = _saved(reference['reference_curve'])
    initial = _saved(episode['initial_reference_curve'])
    if current['identity'] != adopted['identity'] or current['identity'] != initial['identity']:
        raise ValueError('strategy_curve_identity_mismatch')
    if any(not isinstance(value, str) or not value.strip() for value in
           (reference['reference_curve_id'], episode['comparison_episode_id'],
            episode['initial_reference_curve_id'])):
        raise ValueError('strategy_reference_or_episode_invalid')
    result = dict(confirmed_current_curve=current, confirmed_current_curve_key=curve_key(current),
                  reference_curve=adopted, reference_curve_id=reference['reference_curve_id'],
                  comparison_episode_id=episode['comparison_episode_id'],
                  initial_reference_curve=initial,
                  initial_reference_curve_id=episode['initial_reference_curve_id'],
                  selected_segment=selected_segment, candidates=[], gaps={},
                  boundary_search_status='intermediate_native_steps_unsearched')
    if (_shape(current) != _shape(adopted)
            or (check_saved_discount_terms and _saved_discount_changed_at_same_price(current, adopted))):
        result['candidates'] = [_candidate(current, ['CURRENT'], current)]
        result['gaps'] = {label: ['current_reference_catalogue_terms_differ'] for label in 'ABC'}
        return result

    by_key = {}

    def add(curve, label):
        key = curve_key(curve)
        if key in by_key:
            by_key[key]['labels'].append(label)
        else:
            by_key[key] = _candidate(curve, [label], current,
                                     tier_price_factors_verified=tier_price_factors_verified)

    add(current, 'CURRENT')
    active_editor = current['native_contract'] if editor_contract is None else editor_contract
    if active_editor.get('price_edit_policy') == TWO_BAND_PRICE_EDIT:
        adopted_prices = {row['purchase_k']: row['native_price_usd'] for row in adopted['tiers']}
        controls = ({anchor: adopted_prices[anchor]} if anchor in adopted_prices
                    and segment_terms(adopted, selected_segment) != segment_terms(current, selected_segment) else {})
        reference_candidate = compile_curve(current, dict(anchor_prices_usd=controls), active_editor) if controls else current
        if reference_candidate.get('compilation_status', 'EDITOR_CANDIDATE') == 'EDITOR_CANDIDATE':
            add(reference_candidate, 'A')
        else:
            result['gaps']['A'] = reference_candidate['gaps']
    else:
        add(adopted, 'A')
    result['candidates'] = list(by_key.values())
    basis = next((Decimal(tier['native_price_usd']) for tier in adopted['tiers']
                  if tier['purchase_k'] == anchor), None)
    if basis is None:
        result['gaps'].update(B=['reference_anchor_missing'], C=['reference_anchor_missing'])
        return result
    for label, direction, rounding in (('B', -1, ROUND_CEILING), ('C', 1, ROUND_FLOOR)):
        with localcontext() as context:
            context.prec = max(28, len(basis.as_tuple().digits) + 6)
            target = (basis * (1 + direction * STEP)).quantize(CENT, rounding=rounding)
        if target == basis:
            result['gaps'][label] = ['anchor_rounding_has_no_price_step']
            continue
        compiled, gaps = _compiled_step(adopted, selected_segment, anchor, target, direction,
                                       active_editor, unit_price_usd_per_k, current=current)
        if gaps:
            result['gaps'][label] = gaps
        else:
            add(compiled, label)
    result['candidates'] = list(by_key.values())
    return result


def curve_proof_bound(proof, key):
    return (isinstance(proof, dict) and proof.get('contract') == PROOF_CONTRACT
            and proof.get('curve_key') == key
            and proof.get('proof_hash') == fingerprint({k: v for k, v in proof.items() if k != 'proof_hash'}))


def choose_action(comparison, curve_proofs, *, preferred_label='CURRENT'):
    """Evaluate the caller's frozen F2 outputs. Runtime freshness is separate.

    The explicit label can come from the existing scheduler or a documented
    business decision. There is no automatic rank by target margin or competitor.
    """
    if preferred_label not in ('CURRENT', 'A', 'B', 'C'):
        raise ValueError('strategy_preferred_label_invalid')
    result = dict(status=INCOMPLETE, execution_authorized=False, selected=None,
                  comparison_episode_id=comparison['comparison_episode_id'],
                  reference_curve_id=comparison['reference_curve_id'],
                  confirmed_current_curve_key=comparison['confirmed_current_curve_key'],
                  preferred_label=preferred_label, candidate_proofs={},
                  gaps=list(comparison['gaps'].get(preferred_label, [])))
    for candidate in comparison['candidates']:
        key = candidate['curve_key']
        proof = curve_proofs.get(key)
        bound = curve_proof_bound(proof, key)
        status = proof.get('status') if bound else INCOMPLETE
        result['candidate_proofs'][key] = status
        if preferred_label not in candidate['labels']:
            continue
        if status != PROVEN:
            result['gaps'].extend(proof.get('gaps', []) if bound else ['curve_proof_missing_or_unbound'])
            if bound and proof.get('hard_failures'):
                result['gaps'].extend(proof['hard_failures'])
            if status == FAILED:
                result['status'] = 'PREFERRED_HARD_CONSTRAINT_FAILED'
            continue
        result.update(status='KEEP' if key == comparison['confirmed_current_curve_key'] else 'BOUNDED_TRIAL',
                      selected=deepcopy(candidate), proof_hash=proof['proof_hash'])
        result['gaps'].extend(candidate['write_gaps'])
    if result['selected'] is None and not result['gaps']:
        result['gaps'].append('preferred_candidate_or_complete_proof_unavailable')
    return result


def propose_adoption(reference, comparison, decision, evidence, *, operation_id):
    """Record a proposed business adoption and its meaningful evidence delta.

    order_revisions maps stable order identities to upstream semantic revisions
    (amounts, costs, customer cohort and outcome, without capture timestamps).
    The caller supplies the judgment and comparable cumulative business results.
    """
    selected = decision.get('selected') or {}
    segment = comparison.get('selected_segment')
    if (decision.get('status') not in ('KEEP', 'BOUNDED_TRIAL') or not selected
            or decision.get('proof_hash') is None or selected['curve_key'] == curve_key(reference['reference_curve'])
            or decision.get('reference_curve_id') != reference['reference_curve_id']
            or decision.get('comparison_episode_id') != comparison['comparison_episode_id']
            or selected not in comparison['candidates']
            or segment is not None and (segment not in ANCHORS or
                segment not in segment_changes(reference['reference_curve'], selected['curve']))):
        raise ValueError('strategy_adoption_candidate_unproven')
    revisions = evidence.get('order_revisions')
    windows = evidence.get('window_ids')
    cumulative = evidence.get('cumulative') or {}
    required = [operation_id, evidence.get('reason'), evidence.get('changed_judgment'),
                evidence.get('maturity'), evidence.get('cost_revision'), cumulative.get('evidence_ref')]
    if (not isinstance(revisions, dict) or not revisions or not isinstance(windows, list) or not windows
            or any(not isinstance(value, str) or not value.strip()
                   for value in required + list(revisions) + list(revisions.values()) + windows)
            or cumulative.get('initial_reference_curve_id') != comparison['initial_reference_curve_id']
            or any(cumulative.get(key) is None for key in ('revenue_delta_usd', 'procurement_gross_delta_usd',
                                                           'new_customer_delta'))
            or instant(evidence['window_start']) >= instant(evidence['window_end'])):
        raise ValueError('strategy_adoption_evidence_incomplete')
    evidence_hash = fingerprint(revisions)
    history = reference.get('adoption_evidence') or {}
    prior_revisions = history.get('order_revisions', {})
    seen_revisions = history.get('used_order_revisions', {})
    changed = {key: dict(before=prior_revisions.get(key), after=value) for key, value in revisions.items()
               if prior_revisions.get(key) != value and value not in seen_revisions.get(key, ())}
    if not changed or evidence_hash in history.get('used_evidence_hashes', ()):
        raise ValueError('strategy_adoption_has_no_new_evidence')
    initial_prices = {tier['purchase_k']: tier['native_price_usd']
                      for tier in comparison['initial_reference_curve']['tiers']}
    proposed_tiers = selected['curve']['tiers']
    if segment is not None:
        proposed_tiers = [new if _group(new['purchase_k']) == segment else old for old, new in
                          zip(reference['reference_curve']['tiers'], proposed_tiers)]
    cumulative_tier_prices = [dict(purchase_k=tier['purchase_k'],
                                  initial_usd=initial_prices.get(tier['purchase_k']),
                                  target_usd=tier['native_price_usd']) for tier in proposed_tiers]
    proposal = dict(kind='BUSINESS_ADOPT', operation_id=operation_id, target_curve_key=selected['curve_key'],
                    proof_hash=decision['proof_hash'], reference_curve_id=reference['reference_curve_id'],
                    comparison_episode_id=comparison['comparison_episode_id'],
                    initial_reference_curve_id=comparison['initial_reference_curve_id'],
                    evidence_hash=evidence_hash, order_revisions=dict(revisions), evidence_delta=changed,
                    window_ids=sorted(set(windows)), window_start=evidence['window_start'],
                    window_end=evidence['window_end'], cost_revision=evidence['cost_revision'],
                    maturity=evidence['maturity'], reason=evidence['reason'],
                    changed_judgment=evidence['changed_judgment'], cumulative=deepcopy(cumulative),
                    cumulative_tier_prices=cumulative_tier_prices)
    if segment is not None:
        proposal['selected_segment'] = segment
    proposal['adoption_id'] = fingerprint(proposal)
    return proposal


def confirm_adoption(reference, proposal, confirmed_current_curve, receipt):
    """Promote adopted A only against the original operation's full readback.

    Receipt is the caller's normalized operation confirmation. An already
    confirmed target can use that original operation id and its receipt.
    """
    confirmed = _saved(confirmed_current_curve)
    if (receipt.get('operation_id') != proposal['operation_id']
            or receipt.get('status') not in ('COMPLETED', 'NO_CHANGE')
            or receipt.get('complete_curve_readback') is not True
            or receipt.get('curve_key') != proposal['target_curve_key']
            or curve_key(confirmed) != proposal['target_curve_key']
            or confirmed['identity'] != reference['reference_curve']['identity']
            or not isinstance(receipt.get('readback_ref'), str) or not receipt['readback_ref'].strip()):
        raise ValueError('strategy_adoption_original_readback_unconfirmed')
    if reference['reference_curve_id'] == proposal['adoption_id']:
        return deepcopy(reference)
    if reference['reference_curve_id'] != proposal['reference_curve_id']:
        raise ValueError('strategy_adoption_reference_changed')
    history = reference.get('adoption_evidence') or {}
    revisions = dict(history.get('order_revisions', {}))
    seen = deepcopy(history.get('used_order_revisions', {}))
    for order, delta in proposal['evidence_delta'].items():
        used_order = seen.setdefault(order, [])
        for revision in (revisions.get(order), delta['after']):
            if revision is not None and revision not in used_order:
                used_order.append(revision)
        revisions[order] = delta['after']
    used = list(history.get('used_evidence_hashes', ())) + [proposal['evidence_hash']]
    segments = [proposal['selected_segment']] if 'selected_segment' in proposal else list(ANCHORS)
    adopted = update_reference_segments(reference, confirmed, segments, proposal['adoption_id'], receipt,
                                        'BUSINESS_ADOPT')
    return dict(adopted, adoption_evidence=dict(order_revisions=revisions, used_evidence_hashes=used, used_order_revisions=seen),
                comparison_episode_id=proposal['comparison_episode_id'],
                initial_reference_curve_id=proposal['initial_reference_curve_id'],
                adoption=deepcopy(proposal))
