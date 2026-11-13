"""Read-only V6 cost diagnostics from private historical attachments and D2 facts."""
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib

from .cost_model import BASES, LAYER_FIELDS, estimate_layer
from .financial import instant, number
from .platforms import PLATFORMS


BEIJING = timezone(timedelta(hours=8))
BOC_URL = 'https://www.bankofchina.com/sourcedb/whpj/'
PAID_SCOPES = ('original Admin-qualified paid nonrefund nonfraud nontest site266 FC27 Coins cohort',
               'site266_fc27_coins_paid')
MIN_COMPLETE = 10


def _instant(value):
    try:
        return instant(value)
    except ValueError:
        return None


def _number(value, *, zero=False):
    try:
        return number(value, zero=zero)
    except ValueError:
        return None


def _latest(versions, time_of, as_of):
    visible = [(available, version) for version in versions
               if (available := _instant(time_of(version))) is not None and available <= as_of]
    if not visible:
        return None, None
    selected_at, selected = max(visible, key=lambda item: item[0])
    if any(at == selected_at and version != selected for at, version in visible):
        raise ValueError('cost_source_revision_conflict')
    return selected, selected_at


def _fx(record, as_of):
    if not record or record.get('status') != 'valid' or record.get('url') != BOC_URL:
        return None, None
    rate = _number(record.get('cny_per_usd'))
    checked = _instant(record.get('checked_at'))
    available = _instant(record.get('available_at', record.get('checked_at')))
    try:
        published = datetime.fromisoformat(str(record.get('published_at')).replace('/', '-'))
    except ValueError:
        return None, None
    if published.tzinfo is None:
        published = published.replace(tzinfo=BEIJING)
    if rate is None or not (checked and available and published <= checked <= available <= as_of):
        return None, None
    if as_of - checked > timedelta(hours=1):
        return None, None
    return rate, {key: record[key] for key in ('cny_per_usd', 'published_at', 'checked_at', 'url')} | {
        'available_at': available.isoformat()}


def _fact_cost_window(period):
    if not period or not period.get('start') or not period.get('end'):
        return None
    lower = period.get('since') or period['start'] + ' 00:00:00'
    upper = period.get('until') or period['end'] + ' 23:59:59'
    lower = _instant(lower + ':00' if len(lower) == 16 else lower)
    upper = _instant(upper + ':59' if len(upper) == 16 else upper)
    return (lower, upper) if lower and upper and lower <= upper else None


def _facts(revisions, as_of):
    def captured(value):
        return (value.get('source_coverage') or {}).get('captured_at')

    value, available = _latest(revisions, captured, as_of)
    if value is None or value.get('private') is not True or value.get('version') != 'same-order-facts-20261113-v1':
        return {}, None
    coverage = value['source_coverage']
    proof = coverage.get('cost') or {}
    revision = proof.get('source_revision')
    generated = _instant(proof.get('generated_at'))
    if not revision or generated is None or generated > available or not coverage.get('source_revision'):
        return {}, None
    scope = value.get('input_scope') or {}
    if (scope.get('site_id') not in ('266', 'all') or scope.get('gid') not in ('1327', 'all')):
        return {}, None
    try:
        start = datetime.combine(datetime.fromisoformat(scope['start']).date(), time.min, BEIJING)
        end = datetime.combine(datetime.fromisoformat(scope['end']).date(), time.min, BEIJING) + timedelta(days=1)
    except (KeyError, TypeError, ValueError):
        return {}, None
    cost_window = _fact_cost_window(proof.get('period'))
    selected = {}
    for row in value['orders']:
        raw_id = row.get('order_no')
        if row.get('site_id') != '266' or row.get('gid') != '1327' or not raw_id:
            continue
        paid = _instant(row.get('paid_at'))
        if paid is None or not start <= paid < min(end, available):
            continue
        # Use the original identity only inside this private bridge.
        key = hashlib.sha256(('site266:FC27:Coins:' + raw_id).encode()).hexdigest()
        if key in selected:
            raise ValueError('cost_order_facts_identity_conflict')
        records = row['cost_records']
        valid = [r for r in records if _number(r.get('cost_cny'), zero=True) is not None]
        trade_times = [_instant(r.get('trade_at')) for r in valid]
        observed = None
        if valid and not any(trade and trade > generated for trade in trade_times):
            observed = _number(row.get('observed_cost_cny'), zero=True)
        actual = None
        if (proof.get('order_cost_complete') is True and coverage.get('admin_complete') is True
                and row.get('cost_coverage') == 'complete' and observed is not None
                and cost_window and len(valid) == len(records)
                and all(trade and cost_window[0] <= trade <= cost_window[1] for trade in trade_times)):
            actual = _number(row.get('actual_cost_cny'), zero=True)
            if actual != observed:
                raise ValueError('cost_order_facts_complete_total_mismatch')
        selected[key] = (paid, actual, observed, generated, records)
    return selected, dict(source_revision=revision, admin_revision=coverage['source_revision'],
                          available_at=available.isoformat(), generated_at=generated.isoformat(),
                          order_cost_complete=proof.get('order_cost_complete') is True)


def _delivery_quantity_evidence(records, purchase, bonus):
    """Corroborate a historical Coins quantity without inferring it from a CNY total."""
    if not records or purchase is None or bonus is None:
        return 'unverified'
    total_quantity = Decimal(0)
    for record in records:
        quantity = _number(record.get('quantity'))
        gift = _number(record.get('gift'), zero=True)
        unit_cost = _number(record.get('cost_unit_cny'))
        cost = _number(record.get('cost_cny'))
        if quantity is None or gift is None or unit_cost is None or cost is None:
            return 'unverified'
        # The same-order native Coins evidence supports an already inclusive quantity
        # with zero in the separate gift column. Nonzero gift requires separate proof.
        if gift or abs(quantity * unit_cost - cost) > Decimal('.01'):
            return 'unverified'
        total_quantity += quantity
    return 'matches_promised_delivered_k' if total_quantity == purchase + bonus else 'unverified'


def _window(rows, layer, quantity_basis, *, start, end, proof, source_available, as_of,
            layer_matches, facts, rate):
    samples, days, gaps, revisions, delivery_quantities = [], Counter(), Counter(), {}, Counter()
    lower = _instant(proof.get('paid_window_start'))
    upper = _instant(proof.get('paid_window_end_exclusive'))
    if not (lower and upper and lower <= start < end <= upper <= source_available
            and proof.get('population_status') == 'complete' and proof.get('window_complete') is True):
        gaps['paid_window_coverage_incomplete'] += 1
    for row in rows:
        if row.get('platform') in PLATFORMS and row['platform'] != layer['platform']:
            continue
        paid = _instant(row.get('paid_at'))
        if paid is None:
            gaps['paid_time_unknown'] += 1
            continue
        if not start <= paid < end:
            continue
        if lower is None or upper is None or not lower <= paid < upper:
            gaps['order_outside_attachment_scope'] += 1
            continue
        available = _instant(row.get('available_at'))
        if not available or not paid <= available <= source_available:
            gaps['order_availability_unverified'] += 1
            continue
        key, revision = row.get('order_key'), row.get('source_sha256')
        if not key or not revision:
            gaps['order_identity_or_revision_missing'] += 1
            continue
        previous = revisions.setdefault(key, row)
        if previous != row:
            raise ValueError('cost_attachment_order_revision_conflict')

    known_cny = partial_cny = Decimal(0)
    cny_count = partial_count = complete_count = 0
    for key, row in revisions.items():
        match = layer_matches.get(key) or {}
        matched_at = _instant(match.get('available_at'))
        source_at = instant(row['available_at'])
        mapped_layer = match.get('layer') or {}
        if (row.get('platform') not in PLATFORMS or mapped_layer.get('platform') != row['platform']
                or any(not mapped_layer.get(field) for field in LAYER_FIELDS)
                or match.get('order_revision') != row['source_sha256'] or not match.get('evidence_ref')
                or not matched_at or not source_at <= matched_at <= as_of):
            gaps['cost_layer_unverified'] += 1
            continue
        if any(mapped_layer[field] != layer[field] for field in LAYER_FIELDS):
            continue
        paid = instant(row['paid_at'])
        purchase = _number(row.get('base_k'))
        bonus = _number(row.get('bonus_k'), zero=True)
        actual, observed = None, _number(row.get('cost_cny'), zero=True)
        if key in facts:
            d2_paid, d2_actual, d2_observed, d2_generated, d2_records = facts[key]
            if d2_paid != paid:
                gaps['order_facts_paid_time_mismatch'] += 1
            elif d2_observed is not None and (observed is None or d2_generated >= source_at or d2_observed == observed):
                actual, observed = d2_actual, d2_observed
                delivery_quantities[_delivery_quantity_evidence(d2_records, purchase, bonus)] += 1
            elif d2_observed is not None:
                gaps['order_cost_source_revision_mismatch'] += 1
        amount = actual if actual is not None else observed
        if amount is not None:
            known_cny += amount
            cny_count += 1
            if actual is None:
                partial_cny += amount
                partial_count += 1
        usd = amount / rate if amount is not None and rate is not None else None
        complete = actual is not None and usd is not None
        if complete and purchase is not None and (quantity_basis == 'PURCHASE_K' or bonus is not None):
            complete_count += 1
        days[paid.astimezone(BEIJING).date().isoformat()] += 1
        samples.append(dict(order_key=key, layer=layer, purchase_k=purchase, promised_bonus_k=bonus,
                            cost_usd=usd, cost_complete=complete, cost_kind='TOTAL'))
    return samples, dict(start=start.isoformat(), end_exclusive=end.isoformat(),
                         paid_by_beijing_day=dict(sorted(days.items())),
                         order_delivery_quantity_evidence=dict(delivery_quantities),
                         complete_comparable_orders=complete_count, gap_counts=dict(gaps),
                         known_cost_cny=known_cny if cny_count else None,
                         known_partial_cost_cny=partial_cny if partial_count else None,
                         orders_with_known_cny=cny_count)


def estimate_historical_cost(attachments, layer, quantity_basis, *, as_of, layer_matches,
                             fact_revisions=(), fx=None, paid_cutoff=None):
    """Run a same-layer 72h/7d payment-cohort diagnostic with as-of source versions.

    attachments are successive snapshots from collect_historical_attachment for the
    requested population. The latest visible snapshot replaces prior membership.
    layer_matches maps an attachment order_key to an evidenced layer, order_revision,
    available_at and evidence_ref. D2 facts supply private same-order cost observations.
    fact_revisions are successive revisions of the same private D2 input scope.
    paid_cutoff sets the exclusive payment-window end, independently of source availability.
    Current BOC FX translates CNY solely for this forecast diagnostic. The available
    sources lack full procurement event times, so no write-capable proof is returned.
    """
    as_of = instant(as_of)
    cutoff = instant(paid_cutoff) if paid_cutoff is not None else as_of
    if (quantity_basis not in BASES or layer.get('platform') not in PLATFORMS
            or any(not layer.get(field) for field in LAYER_FIELDS) or cutoff > as_of):
        raise ValueError('cost_layer_basis_or_cutoff_invalid')
    source, source_at = _latest(attachments, lambda value: value.get('available_at'), as_of)
    source_gaps = ['procurement_time_unverified']
    rows, proof, revision = [], {}, None
    if source is None:
        source_gaps.append('historical_cost_source_unavailable')
    else:
        proof = source.get('historical_orders_coverage') or {}
        revision = source.get('source_sha256')
        if (not revision or revision != proof.get('source_sha256') or proof.get('population_scope') not in PAID_SCOPES
                or not isinstance(source.get('historical_orders'), list)):
            raise ValueError('cost_attachment_provenance_invalid')
        rows = source['historical_orders']
    facts, fact_evidence = _facts(fact_revisions, as_of)
    if fact_evidence is None or not fact_evidence['order_cost_complete']:
        source_gaps.append('order_cost_completeness_unverified')
    rate, fx_evidence = _fx(fx, as_of)
    if rate is None:
        source_gaps.append('forecast_fx_unavailable_as_of')

    def window(hours):
        return _window(rows, layer, quantity_basis, start=cutoff - timedelta(hours=hours), end=cutoff,
                       proof=proof, source_available=source_at, as_of=as_of, layer_matches=layer_matches,
                       facts=facts, rate=rate)

    samples, recent = window(72)
    selected = recent
    if recent['complete_comparable_orders'] < MIN_COMPLETE:
        samples, selected = window(7 * 24)
    estimate = estimate_layer(samples, layer, quantity_basis)
    return dict(status='PROOF_INCOMPLETE', time_basis='payment_cohort',
                window_hours=72 if selected is recent else 7 * 24, selected_window=selected, recent_72h=recent,
                gaps=sorted(set(source_gaps) | set(estimate['gaps']) | selected['gap_counts'].keys()),
                attachment_revision=revision, order_cost_source=fact_evidence, forecast_fx=fx_evidence,
                diagnostic_estimate=estimate)
