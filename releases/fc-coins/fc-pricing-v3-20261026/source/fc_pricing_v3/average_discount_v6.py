"""The operator-approved seven-day amount-weighted Coins pricing forecast."""
from collections import Counter
from datetime import timedelta
from decimal import Context, Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, localcontext

from .business_source import TZ
from .financial import fingerprint, instant, number
from .price_curve import COIN_BAND_ANCHORS, TWO_BAND_PRICE_EDIT, band_price_usd, coin_quantity_band, curve_key


MODEL = 'fc_v6_d8_d2_amount_weighted_discount_v1'
CENT = Decimal('.01')


def _decimal(value, *, zero=False):
    try:
        return number(value, zero=zero)
    except ValueError:
        return None


def average_discount_window(paid_cutoff):
    today = instant(paid_cutoff).astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=8), today - timedelta(days=1)


def average_discount(closed, platform, paid_cutoff):
    start, end = average_discount_window(paid_cutoff)
    proof = (closed or {}).get('historical_orders_coverage') or {}
    gaps = Counter()
    if not (proof.get('window_complete') and proof.get('population_status') == 'complete'
            and proof.get('shared_publication_id') and proof.get('shared_source_revision')
            and proof.get('paid_window_start') and instant(proof['paid_window_start']) <= start
            and proof.get('paid_window_end_exclusive') and instant(proof['paid_window_end_exclusive']) >= end):
        gaps['average_discount_window_unavailable'] += 1
    gross = discount = Decimal(0)
    eligible, matched = 0, 0
    seen = set()
    for row in (closed or {}).get('historical_orders', ()):
        if not start <= instant(row['paid_at']) < end:
            continue
        if row.get('platform') not in ('PS', 'XBOX', 'PC'):
            gaps['average_discount_platform_unknown'] += 1
            continue
        if row['platform'] != platform:
            continue
        eligible += 1
        if row['order_key'] in seen:
            gaps['average_discount_order_conflict'] += 1
            continue
        seen.add(row['order_key'])
        before = _decimal(row.get('merchandise_before_discount_usd'))
        off = _decimal(row.get('actual_es_discount_usd'), zero=True)
        if before is None or off is None or off > before:
            gaps['average_discount_amount_unknown'] += 1
            continue
        matched += 1
        gross += before
        discount += off
    if not gross:
        gaps['average_discount_positive_merchandise_missing'] += 1
    value = dict(contract=MODEL, platform=platform, site_id='266', status='partial' if gaps else 'complete',
                 start=start.isoformat(), end_exclusive=end.isoformat(),
                 eligible_orders=eligible, matched_orders=matched, gap_counts=dict(gaps),
                 merchandise_before_discount_usd=str(gross) if matched else None,
                 actual_discount_usd=str(discount) if matched else None,
                 retained_ratio=str((gross - discount) / gross) if gross and not gaps else None,
                 publication_id=proof.get('shared_publication_id'), source_revision=proof.get('shared_source_revision'),
                 amount_basis='same_order_admin_before_discount_and_shared_es_discount_usd')
    return dict(value, revision=fingerprint(value))


def quantity_group(purchase):
    return coin_quantity_band(purchase)


def forecast_receipt(amount, retained):
    with localcontext(Context(prec=80)):
        return (amount * retained).quantize(CENT, rounding=ROUND_DOWN)


def forecast_quotes(curve, quantities, average, *, observed_gifts=None):
    """Current/compiled fixed amounts and lower-anchor custom quantity assumptions."""
    tiers = {Decimal(tier['purchase_k']): tier for tier in curve['tiers']}
    anchors = sorted(tiers)
    key = curve_key(curve)
    values = {}
    observed_gifts = observed_gifts or {}
    two_band = curve['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT
    for purchase in sorted(set(quantities) | tiers.keys()):
        before = max((anchor for anchor in anchors if anchor <= purchase), default=anchors[0])
        after = min((anchor for anchor in anchors if anchor >= purchase), default=anchors[-1])
        lower = tiers[before]
        amount = Decimal(lower['native_price_usd'])
        gift = Decimal(lower['promised_bonus_k'])
        if purchase not in tiers and two_band:
            anchor = COIN_BAND_ANCHORS[quantity_group(purchase)]
            if Decimal(anchor) in tiers:
                lower = tiers[Decimal(anchor)]
                amount = band_price_usd(lower['native_price_usd'], anchor, purchase)
        elif purchase != before:
            amount = (amount * purchase / before).quantize(CENT, rounding=ROUND_HALF_UP)
        if purchase not in tiers:
            if two_band:
                gift = max(observed_gifts.get(purchase, Decimal(0)),
                           (purchase * Decimal(lower['promised_bonus_k']) / Decimal(lower['purchase_k'])
                            ).to_integral_value(rounding=ROUND_CEILING))
            else:
                upper_gift = Decimal(tiers[after]['promised_bonus_k'])
                gift = max(gift, upper_gift, observed_gifts.get(purchase, Decimal(0)),
                           (purchase * gift / before).to_integral_value(rounding=ROUND_CEILING))
        quantity = format(purchase.normalize(), 'f')
        tier_rule = 'goods.more.price[' + str(lower['native_index']) + ']'
        if purchase not in tiers:
            rule = 'forecast_two_band_price_anchor:' if two_band else 'forecast_lower_native_tier_unit_rate:'
            tier_rule = rule + lower['purchase_k']
        quote = dict(curve_key=key, path_id='average:' + quantity, site_id='266', currency='USD',
                     amount_kind='TOTAL', purchase_k=quantity, promised_bonus_k=format(gift.normalize(), 'f'),
                     promised_delivered_k=format((purchase + gift).normalize(), 'f'), regular_usd=str(amount),
                     native_tier_or_rule=tier_rule, rounding_contract='forecast_merchandise_usd_cent_v1',
                     quote_basis=MODEL, offer_version=average['revision'],
                     fulfilment_contract='ordinary_native_coins_promised_delivered_k',
                     gift_basis=('admin_fixed_tier' if purchase in tiers else
                                 'forecast_observed_or_prorated_band_gift_upper_bound' if two_band else
                                 'forecast_observed_adjacent_or_prorated_gift_upper_bound'),
                     proof_status='verified', receipt_status='forecast_under_average_discount')
        if average['retained_ratio'] is not None:
            quote['net_receipt_usd'] = str(forecast_receipt(amount, Decimal(average['retained_ratio'])))
        quote['quote_ref'] = fingerprint(quote)
        values[quantity] = quote
    return values


def repair_controls(current, proof, *, affected=None):
    """Compute cent floors from failed average-model paths and weighted baskets."""
    from .pricing_proof_v6 import FAILED, HARD_MARGIN

    paths = {row['path_id']: row for row in proof['paths']}
    failed = affected or {quantity_group(Decimal(row['purchase_k']))
                          for row in paths.values() if row['zero_line_status'] == FAILED}
    if not failed:
        failed = {quantity_group(Decimal(paths[member['path_id']]['purchase_k']))
                  for basket in proof['baskets'].values() if basket['status'] == FAILED
                  for member in basket['members']}
    retained = Decimal(proof['average_discount']['retained_ratio'])
    if not retained:
        return {}, failed
    anchors = {group: min(Decimal(tier['purchase_k']) for tier in current['tiers']
                          if quantity_group(Decimal(tier['purchase_k'])) == group) for group in failed}
    if current['native_contract'].get('price_edit_policy') == TWO_BAND_PRICE_EDIT:
        anchors = {group: Decimal(COIN_BAND_ANCHORS[group]) for group in failed}
    required = {group: Decimal(0) for group in failed}
    for row in paths.values():
        purchase = Decimal(row['purchase_k'])
        group = quantity_group(purchase)
        if group in failed:
            stress = Decimal(row['stress_cost_usd']) + Decimal(row['known_fee_usd'])
            required[group] = max(required[group], stress.quantize(CENT, rounding=ROUND_CEILING) / purchase)
    for basket in proof['baskets'].values():
        if basket['status'] != FAILED:
            continue
        # Existing other-segment receipts stay fixed. The candidate's complete
        # proofs will check the realized cent amounts across all active groups.
        total = Decimal(basket['safe_cost_usd']) / (1 - HARD_MARGIN)
        quantities = Counter()
        retained_other = Decimal(0)
        for member in basket['members']:
            row = paths[member['path_id']]
            purchase = Decimal(row['purchase_k'])
            group = quantity_group(purchase)
            weight = Decimal(member['weight'])
            if group in failed:
                quantities[group] += weight * purchase
            else:
                retained_other += weight * Decimal(row['net_receipt_usd'])
        if quantities:
            rate = max(Decimal(0), total - retained_other) / sum(quantities.values())
            for group in quantities:
                required[group] = max(required[group], rate)
    controls = {}
    for group, anchor in anchors.items():
        # Existing small-tier cents include rounding. Use the minimum rate
        # that rounds back to each saved amount, and verify the entire table.
        min_keep = max((Decimal(tier['native_price_usd']) - CENT / 2) / Decimal(tier['purchase_k'])
                       for tier in current['tiers'] if quantity_group(Decimal(tier['purchase_k'])) == group)
        controls[format(anchor.normalize(), 'f')] = (max(required[group] / retained, min_keep)
                                                     * anchor).quantize(CENT, rounding=ROUND_CEILING)
    return controls, failed
