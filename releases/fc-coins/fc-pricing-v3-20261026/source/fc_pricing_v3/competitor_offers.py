"""Quantity-specific competitor observations; no extrapolation or pricing decisions."""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json

POLICY = 'v6_four_source_purchase_packages_v1'
LEGACY_POLICY = 'v6_1_three_source_quantity_v1'
VERSION = 'fc27-ordinary-package-offers-v1'
SOURCES = ('Lootbar', 'U7Buy', 'U4GM', 'IGGM')
LEGACY_SOURCES = ('Lootbar', 'U7Buy', 'ArabUT')
PLATFORMS = ('PS', 'XBOX', 'PC')
QUANTITIES = ('100', '1000', '2000', '5000')
CURRENT_QUANTITIES = ('100', '1000')


def decimal(value, *, zero=False):
    try:result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):raise ValueError('competitor_amount_invalid') from None
    if not result.is_finite() or result < 0 or not zero and result == 0:
        raise ValueError('competitor_amount_invalid')
    if result == 0:return '0'
    value = format(result, 'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def quantities(values=QUANTITIES):
    result = tuple(decimal(v) for v in values)
    if not result or len(set(result)) != len(result) or set(result)-set(QUANTITIES):
        raise ValueError('competitor_quantity_scope')
    return result


def offer_key(row):
    material = [row.get(k) for k in ('source','platform','purchase_k','promotion_eligibility',
                'delivery_method','delivery_tier','currency','region_id')]
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',',':')).encode()).hexdigest()


def _lootbar_merchandise(raw, purchase, currency, tier):
    if (raw['source'] != 'Lootbar' or currency != 'USD' or tier is not None
            or raw.get('conditional') is True or raw.get('comparable') is False
            or raw.get('coupon_excluded') is not True
            or raw.get('discount_source') not in ('visible_no_coupon', 'visible_coupon_excluded','public_no_coupon')):
        return False
    evidence = raw.get('evidence_ref', raw.get('source_metadata'))
    if not isinstance(evidence, dict):
        return False
    if raw.get('price_basis') == 'public_platform_sku':
        return (raw.get('auth_state') == 'public' and raw.get('selection_verified') is True
                and raw.get('discount_source') == 'public_no_coupon' and evidence.get('spu_id') == 1461
                and evidence.get('platform') == raw.get('platform') and evidence.get('selected_currency') == 'USD'
                and evidence.get('asset_name') in {'100':('100K Safe Coins',),
                    '1000':('1M Safe Coins','1000K Safe Coins')}.get(purchase, ()))
    # The 187 reader validates the current no-coupon amount and exact card
    # selection. The 183 projection also reports its standard delivery method.
    return (
        raw.get('price_basis') == 'visible_public_sale_price'
        and raw.get('auth_state') == 'logged_in'
        and type(raw.get('raw_coupon_excluded')) is bool
        and raw.get('delivery_method') is None
        and (purchase == '100' or raw.get('selection_verified') is True)
        or raw.get('price_basis') in ('visible_public_sale_price', 'reconstructed_no_coupon_lower_bound')
        and purchase == '100'
        and raw.get('selection_verified') is True
        and raw.get('observation_id')
        and raw.get('auth_state') in ('public', 'logged_in')
        and raw.get('delivery_method') == 'standard'
        and raw.get('comparable') is True
    )


def normalize_offers(rows, run_id, now, *, max_age=900):
    """Retain observed native packages and explicit unknown conditions, dedup by full key."""
    output = {}
    for raw in rows:
        if raw.get('status') != 'valid':continue
        source, platform = raw.get('source'), raw.get('platform')
        if source not in SOURCES + ('ArabUT',) or platform not in PLATFORMS:raise ValueError('competitor_source_platform')
        if raw.get('run_id', run_id) != run_id:raise ValueError('competitor_run_mismatch')
        captured = raw.get('captured_at') or raw.get('checked_at')
        try:stamp = datetime.fromisoformat(captured.replace('Z','+00:00'))
        except (TypeError, ValueError, AttributeError):raise ValueError('competitor_capture_time') from None
        if stamp.tzinfo is None or not 0 <= (now-stamp).total_seconds() <= max_age:
            raise ValueError('competitor_capture_stale')
        purchase = decimal(raw.get('purchase_k',raw.get('base_k')))
        if purchase not in QUANTITIES:raise ValueError('competitor_quantity_scope')
        currency = raw.get('currency')
        if not isinstance(currency,str) or len(currency)!=3 or not currency.isascii() or not currency.isupper():
            raise ValueError('competitor_currency')
        tier = raw.get('delivery_tier', raw.get('delivery'))
        lootbar_merchandise = _lootbar_merchandise(raw, purchase, currency, tier)
        conditional = False if lootbar_merchandise else raw.get('conditional')
        regular = raw.get('regular_price')
        if 'regular_price' not in raw and currency == 'USD' and conditional is not True:
            regular = raw.get('gross_usd', raw.get('total_usd'))
        displayed = raw.get('display_price')
        if displayed is None and source == 'U7Buy' and conditional is True and currency == 'USD':
            displayed = raw.get('gross_usd')
        bonus = raw.get('bonus_k')
        eligibility = raw.get('promotion_eligibility')
        if eligibility is None:
            eligibility = 'all_customers' if conditional is False and raw.get('coupon_excluded') is True else 'unknown'
        if not isinstance(eligibility,(str,dict)):raise ValueError('competitor_eligibility')
        eligibility_known = (isinstance(eligibility,str) and eligibility not in ('','unknown')
            or isinstance(eligibility,dict) and eligibility.get('status')=='verified')
        row = dict(source=source, platform=platform, run_id=run_id, purchase_k=purchase,
            bonus_k=decimal(bonus,zero=True) if bonus is not None else None, currency=currency,
            regular_price=decimal(regular) if regular is not None else None,
            display_price=decimal(displayed) if displayed is not None else None,
            eligible_net_price=decimal(raw['eligible_net_price']) if raw.get('eligible_net_price') is not None and eligibility_known else None,
            promotion_eligibility=deepcopy(eligibility), coupon_cap=deepcopy(raw.get('coupon_cap')),
            usage_limit=deepcopy(raw.get('usage_limit')), necessary_fees=deepcopy(raw.get('necessary_fees')),
            tax_bearer=raw.get('tax_bearer'), delivery_method=raw.get('delivery_method'),
            delivery_tier=tier,
            captured_at=captured, source_url=raw.get('source_url',raw.get('url')),
            fx=deepcopy(raw.get('fx')), fx_version=raw.get('fx_version'),
            conditional=conditional, selection_verified=raw.get('selection_verified'),
            auth_state=raw.get('auth_state'), coupon_excluded=raw.get('coupon_excluded'),
            comparable=(raw.get('comparable') is True or lootbar_merchandise) and eligibility_known,
            evidence_ref=deepcopy(raw.get('evidence_ref',raw.get('source_metadata'))),
            status='valid', observation_basis='native_observed_quantity')
        # Preserve the official settlement/display currency relationship and shared
        # Console provenance. Neither an implied FX rate nor PC/Normal equivalence
        # is manufactured from labels.
        row.update({k:deepcopy(raw[k]) for k in ('region_id','settlement_currency','conversion_source',
            'original_currency','original_amount_minor','price_version','priced_at',
            'original_platform','original_market','original_delivery','source_region_id',
            'reference_scope','observation_id','price_basis','discount_source','raw_coupon_excluded',
            'delivery_estimate','extra_bonus_tier','collection_node') if k in raw})
        package = (source in ('U4GM','IGGM') and raw.get('selection_verified') is True
                   and raw.get('coupon_excluded') is True and conditional is False
                   and row['delivery_method']=='comfort_trade' and isinstance(row['evidence_ref'],dict)
                   and row['evidence_ref'].get('price_basis') in ('selected_native_price','native_volume_rule','ordinary_native_package'))
        row['comparable'] = (row['comparable'] and row['bonus_k'] is not None
            and (row['regular_price'] is not None or row['eligible_net_price'] is not None)
            and (package or lootbar_merchandise or row['delivery_method'] not in (None,'unknown') and tier not in (None,'unknown')))
        row['comparability_basis'] = (('lootbar_observed_100k_merchandise_no_delivery_tier' if purchase == '100'
            else 'lootbar_observed_native_merchandise_no_delivery_tier') if lootbar_merchandise
            else 'merchandise_quote_only_fees_and_tax_separate')
        row['delivered_k'] = decimal(Decimal(purchase)+Decimal(row['bonus_k'])) if row['bonus_k'] is not None else None
        row['offer_key'] = key = offer_key(row)
        if key in output and output[key]!=row:raise ValueError('competitor_offer_revision_conflict')
        output[key]=row
    return list(output.values())


def quantity_coverage(rows, platforms=PLATFORMS, requested=QUANTITIES, *, sources=SOURCES):
    requested=quantities(requested)
    observed={(r['source'],r['platform'],r['purchase_k']) for r in rows}
    comparable={(r['source'],r['platform'],r['purchase_k']) for r in rows if r['comparable']}
    expected={(s,p,q) for s in sources for p in platforms for q in requested}
    return dict(version=VERSION, ready=True, required_sources=[], optional_sources=list(sources),
        readiness_basis='optional_sources_do_not_block_not_quantity_completeness',
        pricing_source_policy='optional_market_signals_no_missing_source_price_action',
        observations=len(rows), quantity_scope=list(requested),
        comparable_observations=sum(r['comparable'] for r in rows),
        quantity_coverage_complete=expected<=comparable,
        quantities=[dict(source=s,platform=p,purchase_k=q,
            status='comparable_merchandise' if (s,p,q) in comparable else 'observed_conditions_unverified' if (s,p,q) in observed else 'unknown')
            for s,p,q in sorted(expected)],
        optional_missing=[dict(source=s,platform=p,purchase_k=q,status='unknown',reason='native_quantity_not_observed')
            for s in sources for p in platforms for q in requested if (s,p,q) not in observed])


def legacy_100k_projection(rows):
    """Explicit ordinary USD 100K-only compatibility; never choose a first variant."""
    grouped={}
    for row in rows:
        if (row['purchase_k']!='100' or row['currency']!='USD' or row['promotion_eligibility']!='all_customers'
                or row['conditional'] is True or not row['comparable'] or row['regular_price'] is None
                or row['bonus_k'] is None):continue
        grouped.setdefault((row['source'],row['platform']),[]).append(row)
    result=[]
    for candidates in grouped.values():
        if len(candidates)!=1:continue  # Ambiguous delivery/eligibility never selects by list order.
        row=candidates[0]
        result.append(dict(row,gross_usd=row['regular_price'],
            effective_usd_per_k=str(Decimal(row['regular_price'])/Decimal(row['delivered_k'])),
            url=row['source_url'],delivery=row['delivery_tier'],compatibility_scope='100k_observed_only'))
    return result


def select_offer(rows, *, source, platform, purchase_k, promotion_eligibility,
                 delivery_method, delivery_tier, currency):
    """Exact source/quantity/eligibility/delivery dispatch for V6 consumers."""
    criteria=dict(source=source,platform=platform,purchase_k=decimal(purchase_k),
        promotion_eligibility=promotion_eligibility,delivery_method=delivery_method,
        delivery_tier=delivery_tier,currency=currency)
    matches=[row for row in rows if all(row.get(k)==v for k,v in criteria.items())]
    if len(matches)!=1:raise ValueError('competitor_offer_missing' if not matches else 'competitor_offer_ambiguous')
    return deepcopy(matches[0])
