"""Build private V6 planning baskets from payment-window order attachments."""
from collections import Counter
from datetime import datetime, timedelta

from .business_source import historical_period
from .financial import fingerprint, instant, number
from .platforms import PLATFORMS
from .pricing_proof_v6 import REFUND_RECOVERY_POLICY


PAID_SCOPE = 'site266_fc27_coins_paid'
HISTORICAL_SCOPE = 'original Admin-qualified paid nonrefund nonfraud nontest site266 FC27 Coins cohort'
STRUCTURE_ORDERS = 30


def _instant(value):
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
        if parsed.tzinfo is not None:
            return parsed
    except ValueError:
        pass
    try:
        return instant(value)
    except ValueError:
        return None


def _ref(value):
    return isinstance(value, str) and bool(value.strip())


def _quantity(value):
    try:
        return number(value)
    except ValueError:
        return None


def _attachment(attachment, start, end, as_of, source_gap):
    if attachment is None:
        return [], None, None, Counter({source_gap or 'paid_source_unavailable': 1})
    rows = attachment.get('historical_orders')
    proof = attachment.get('historical_orders_coverage') or {}
    revision = attachment.get('source_sha256')
    available = _instant(attachment.get('available_at'))
    if available is None or available > as_of:
        return [], None, None, Counter({'paid_source_not_available_at_as_of': 1})
    if not _ref(revision) or proof.get('source_sha256') != revision or not isinstance(rows, list):
        return [], None, None, Counter({'paid_source_revision_or_rows_missing': 1})

    scope = proof.get('population_scope')
    if scope not in (PAID_SCOPE, HISTORICAL_SCOPE):
        return [], revision, available, Counter({'paid_source_scope_unverified': 1})
    gaps = Counter()
    lower = _instant(proof.get('paid_window_start'))
    upper = _instant(proof.get('paid_window_end_exclusive'))
    if not (lower and upper and lower <= start < end <= upper <= available):
        gaps['paid_source_window_uncovered'] += 1
    if proof.get('population_status') != 'complete' or proof.get('window_complete') is not True:
        gaps['paid_source_population_incomplete'] += 1
    # Refund and recovery revisions remain historical diagnostics. Basket coverage
    # uses the attached ordinary paid population under the V6 forecast policy.
    return rows, revision, available, gaps


def _path_for(row, match, purchase, curve_key, as_of):
    if not isinstance(match, dict) or match.get('curve_key') != curve_key:
        return None
    if not _ref(row.get('source_sha256')) or match.get('order_revision') != row['source_sha256']:
        return None
    if _quantity(match.get('purchase_k')) != purchase:
        return None
    available = _instant(match.get('available_at'))
    observed = _instant(row.get('available_at'))
    if not available or not observed <= available <= as_of:
        return None
    if any(not _ref(match.get(key)) for key in ('path_id', 'quote_ref', 'eligibility_ref', 'fulfilment_ref')):
        return None
    return {key: match[key] for key in ('path_id', 'quote_ref', 'eligibility_ref', 'fulfilment_ref')}


def _window(attachment, start, end, as_of, platform, curve_key, repriced_orders, selection, *, source_gap=None):
    rows, revision, source_available, gaps = _attachment(attachment, start, end, as_of, source_gap)
    seen, scoped, conflict, counts, weights, mappings = {}, set(), set(), Counter(), Counter(), []
    for row in rows:
        if not isinstance(row, dict):
            gaps['paid_source_row_invalid'] += 1
            continue
        paid = _instant(row.get('paid_at'))
        in_scope = row.get('platform') not in PLATFORMS or row['platform'] == platform
        in_scope = in_scope and (paid is None or start <= paid < end)
        key = row.get('order_key')
        if _ref(key):
            if key in seen and seen[key] != row:
                conflict.add(key)
            else:
                seen[key] = row
        if not in_scope:
            continue
        available = _instant(row.get('available_at'))
        if available is None or available > source_available:
            gaps['order_not_available_at_as_of'] += 1
            continue
        if paid is None:
            gaps['paid_time_unknown'] += 1
            continue
        if not _ref(key):
            gaps['order_identity_missing'] += 1
            continue
        scoped.add(key)

    if scoped & conflict:
        gaps['order_revision_conflict'] += len(scoped & conflict)
    population_gaps = bool(gaps)
    for key in sorted(scoped - conflict):
        row = seen[key]
        if row.get('platform') != platform:
            gaps['platform_unknown'] += 1
            population_gaps = True
            continue
        counts['paid_orders'] += 1
        if row.get('cost_cny') is None:
            counts['orders_without_historical_cost'] += 1
        purchase = _quantity(row.get('base_k'))
        if purchase is None:
            gaps['purchase_quantity_unknown'] += 1
            continue
        match = _path_for(row, repriced_orders.get(key), purchase, curve_key, as_of)
        if match is None:
            gaps['current_quote_or_eligibility_unverified'] += 1
            continue
        mappings.append(dict(order_key=key, order_revision=row['source_sha256'], **match))
    quotes, mismatched = {}, set()
    for match in mappings:
        path, quote = match['path_id'], match['quote_ref']
        if quotes.setdefault(path, quote) != quote:
            mismatched.add(path)
        weights[path] += 1
    for path in mismatched:
        gaps['current_quote_path_revision_conflict'] += weights.pop(path)
    evidence_ref = fingerprint(dict(curve_key=curve_key, platform=platform, selection=selection,
                                    start=start.isoformat(), end=end.isoformat(),
                                    source_sha256=revision, mappings=mappings, coverage=dict(gaps),
                                    refund_recovery_policy=REFUND_RECOVERY_POLICY))
    return dict(selection=selection, evidence_ref=evidence_ref,
                window=dict(start=start.isoformat(), end_exclusive=end.isoformat()),
                source_sha256=revision, coverage_status='partial' if gaps else 'complete',
                population_status='partial' if population_gaps else 'complete',
                coverage_gaps=sorted(gaps), gap_counts=dict(sorted(gaps.items())),
                paid_orders=counts['paid_orders'], matched_orders=sum(weights.values()),
                orders_without_historical_cost=counts['orders_without_historical_cost'],
                members=[dict(path_id=path, weight=str(weight), quote_ref=quotes[path])
                         for path, weight in sorted(weights.items())])


def build_planning_baskets(platform, curve_key, closed_attachment, recent_attachment, repriced_orders, *,
                           paid_cutoff, as_of, recent_source_gap=None):
    """Select site266 payments and map each known order to a verified current path.

    The closed input accepts business_source.collect_historical_attachment's
    private return envelope. A recent source uses the same payment-window fields.
    `repriced_orders` is a private mapping by the same anonymous order_key.
    Current path qualification and fulfilment come from the quote producer.
    """
    cutoff, available = instant(paid_cutoff), instant(as_of)
    if platform not in PLATFORMS or not _ref(curve_key) or cutoff > available:
        raise ValueError('planning_basket_scope_or_time_invalid')
    closed = historical_period('7d', now=cutoff)

    def window(source, start, end, selection, *, source_gap=None):
        return _window(source, start, end, available, platform, curve_key, repriced_orders, selection,
                       source_gap=source_gap)

    main = window(closed_attachment, instant(closed['paid_window_start']),
                  instant(closed['paid_window_end_exclusive']), 'closed_bjt_7d')
    daily = window(recent_attachment, cutoff - timedelta(hours=24), cutoff, 'latest_24h', source_gap=recent_source_gap)
    recent = daily
    if daily['population_status'] == 'complete' and daily['paid_orders'] < STRUCTURE_ORDERS:
        recent = window(recent_attachment, cutoff - timedelta(days=3), cutoff, 'latest_3d')
        recent['previous_attempt'] = daily
        if recent['coverage_status'] == 'complete' and recent['paid_orders'] < STRUCTURE_ORDERS:
            recent = dict(main, selection='main_fallback', weak_structure=True, previous_attempt=recent,
                          evidence_ref=fingerprint(dict(main=main['evidence_ref'], recent=recent['evidence_ref'],
                                                        reason='fewer_than_30_same_platform_paid_orders')))
    return dict(main=main, recent=recent)
