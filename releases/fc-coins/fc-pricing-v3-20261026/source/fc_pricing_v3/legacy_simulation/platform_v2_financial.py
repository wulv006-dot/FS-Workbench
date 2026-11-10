"""Dual20 on the actual 100K package and gifts; other sizes are outside the hard pricing floor."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
import hashlib
import json
MARGIN_BASIS = 'undiscounted_and_historical_average_v2'
LEGACY_FINANCIAL_CONTRACT_VERSION = 'fc27_dual20_v1'
FINANCIAL_CONTRACT_VERSION = 'fc27_dual20_d9_d2_v2'
HISTORY_WINDOW_CONTRACT = 'd9_d2_eight_closed_days_v1'
HARD_MARGIN = Decimal('20')
CENT = Decimal('.01')
STEP = Decimal('.0001')
CONSOLE = ('PS', 'XBOX')
CONSOLE_COST_CONTRACT = 'ps_latest_six_valid_order_delivery_max_v1'
ROUNDING_RESERVE = Decimal('.02')
PRICING_SCOPE = '100k_package_only'
def number(value, *, zero=False):
    if value is None or isinstance(value, bool):
        raise ValueError('pricing_number_invalid')
    try:
        n = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('pricing_number_invalid') from None
    if not n.is_finite() or n > Decimal('1e12') or n < 0 or not zero and n == 0:
        raise ValueError('pricing_number_invalid')
    return n


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def instant(value):
    text = str(value).strip()
    for pattern in ('%y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('pricing_source_time_invalid') from None
    if parsed.tzinfo is None:
        raise ValueError('pricing_source_timezone_missing')
    return parsed


def fresh(value, now, seconds=3600):
    age = (now - instant(value)).total_seconds()
    if not -5 <= age <= seconds:
        raise ValueError('pricing_source_stale')


def common_cost(evidence):
    """PS and Xbox share the highest unit cost among the latest six valid PS deliveries."""
    ps = evidence['costs']['PS']
    if ps.get('sample_contract') != CONSOLE_COST_CONTRACT or ps.get('sample_complete') is not True:
        raise ValueError('pricing_console_cost_sample_unverified')
    records = ps.get('sample_records')
    if not isinstance(records, list) or len(records) != 6:
        raise ValueError('pricing_console_cost_sample_incomplete')
    boundary = ps.get('sample_boundary')
    if not isinstance(boundary, dict) or boundary.get('complete') is not True:
        raise ValueError('pricing_console_cost_sample_boundary')
    try:
        start, end = instant(boundary.get('start')), instant(boundary.get('end'))
    except ValueError:
        raise ValueError('pricing_console_cost_sample_boundary') from None
    if not start < end or end - start > timedelta(days=8):
        raise ValueError('pricing_console_cost_sample_boundary')
    ids = set()
    for row in records:
        if (row.get('platform') != 'PS' or row.get('game') != 'FC27'
                or row.get('product') != 'Game Coins' or row.get('unit') != 'CNY/K'
                or row.get('genre') != '1' or row.get('delivery_type') != '\u8ba2\u5355\u53d1\u8d27'):
            raise ValueError('pricing_console_cost_scope')
        number(row.get('cny_per_1k'))
        record_id = str(row.get('record_id', ''))
        if not record_id.isdigit() or int(record_id) in ids:
            raise ValueError('pricing_console_cost_identity')
        ids.add(int(record_id))
        if not start <= instant(row['trade_at']) <= end:
            raise ValueError('pricing_console_cost_sample_boundary')
    ordered = sorted(records, key=lambda r: (instant(r['trade_at']), int(r['record_id'])), reverse=True)
    if records != ordered:
        raise ValueError('pricing_console_cost_sample_order')
    selected = max(records, key=lambda r: number(r['cny_per_1k']))
    for platform in CONSOLE:
        row = evidence['costs'][platform]
        if (row.get('platform') != platform or row.get('source_platform') != 'PS'
                or row.get('sample_contract') != CONSOLE_COST_CONTRACT or row.get('sample_complete') is not True
                or row.get('sample_boundary') != boundary
                or row.get('sample_records') != records
                or any(row.get(key) != selected.get(key) for key in ('game', 'product', 'record_id', 'trade_at'))
                or number(row.get('cny_per_1k')) != number(selected['cny_per_1k'])):
            raise ValueError('pricing_console_cost_selection_mismatch')
    return number(selected['cny_per_1k']), dict(
        basis=CONSOLE_COST_CONTRACT, sample_size=6,
        selected_platform='PS', record_id=str(selected['record_id']),
        trade_at=selected['trade_at'], cny_per_k=str(number(selected['cny_per_1k'])),
        observations=[{k:r.get(k) for k in ('platform','record_id','trade_at','checked_at','cny_per_1k')} for r in records])


def envelope_ratio(envelope, now):
    if not isinstance(envelope, dict) or envelope.get('contract') != 'fc-coins-promotion-envelope-v1':
        raise ValueError('pricing_promotions_missing')
    if envelope.get('status') != 'verified' or envelope.get('site_id') != 266 or envelope.get('game_id') != 1327:
        raise ValueError('pricing_promotions_unverified')
    fresh(envelope.get('checked_at'), now, 900)
    body = {k:v for k,v in envelope.items() if k not in ('sha256','checked_at')}
    if envelope.get('sha256') != fingerprint(body):
        raise ValueError('pricing_promotions_hash_changed')
    ratio = number(envelope.get('minimum_retained_ratio'), zero=True)
    if ratio > 1:
        raise ValueError('pricing_promotions_ratio_invalid')
    return ratio


def hard_floor(cost_cny, fx, delivered_per_base, retained_ratio, minimum=HARD_MARGIN):
    margin = number(minimum, zero=True)
    if margin < HARD_MARGIN or margin >= 100:
        raise ValueError('pricing_hard_margin_minimum_20')
    cost = number(cost_cny) / number(fx) * number(delivered_per_base)
    ratio = number(retained_ratio, zero=True)
    if ratio > 1:
        raise ValueError('pricing_promotions_ratio_invalid')
    return (cost / (1 - margin / 100)).quantize(STEP, rounding=ROUND_CEILING)


def prove_price(unit, cost_cny, fx, delivered_k, base_k, ratio, minimum=HARD_MARGIN):
    base, delivered = number(base_k), number(delivered_k)
    if delivered < base:
        raise ValueError('pricing_package_invalid')
    cost = number(cost_cny) / number(fx) * delivered
    gross = (number(unit) * base).quantize(CENT, rounding=ROUND_DOWN)
    ratio = number(ratio, zero=True)
    reserve=ROUNDING_RESERVE if ratio<1 else Decimal(0)
    promotional = max(Decimal(0), (gross * ratio).quantize(CENT, rounding=ROUND_DOWN)-reserve)
    hard_floor(cost_cny, fx, delivered/base, ratio, minimum)
    required = cost / (1 - number(minimum) / 100)
    if gross <= 0 or gross < required:
        raise ValueError('pricing_hard_margin_floor')
    return dict(public_usd=str(gross), undiscounted_net_usd=str(gross), margin_basis=MARGIN_BASIS,
                worst_net_usd=str(promotional), promotional_net_usd=str(promotional),
                promotional_gross_usd=str(promotional-cost),
                promotional_margin_pct=str((promotional-cost)/promotional*100) if promotional else None,
                promotions_exempt_from_margin_floor=True, rounding_reserve_usd=str(reserve), delivered_k=str(delivered),
                delivered_cost_usd=str(cost), procurement_gross_usd=str(gross-cost),
                procurement_margin_pct=str((gross-cost)/gross*100), minimum_margin_pct=str(minimum))


def package_100k(rules):
    tiers=[tier for tier in rules['tiers'] if number(tier['base_k'])==100]
    if len(tiers)!=1:raise ValueError('pricing_100k_package_required')
    tier=tiers[0]
    if number(tier['retained_ratio'])>1 or number(tier['bonus_k'],zero=True)>100:
        raise ValueError('pricing_package_invalid')
    return tier


def catalog_floor(cost, fx, ratio, minimum, rules, *, average_ratio=None):
    margin=number(minimum,zero=True)
    hard_floor(cost,fx,1,ratio,minimum)
    tier=package_100k(rules)
    historical=number(average_ratio) if average_ratio is not None else Decimal(1)
    if historical>1:raise ValueError('pricing_historical_mix_ratio_invalid')
    required=(number(cost)/number(fx)*(100+number(tier['bonus_k'],zero=True))/(historical*(1-margin/100))).quantize(CENT,rounding=ROUND_CEILING)
    return ((required-CENT/2)/number(tier['retained_ratio'])).quantize(CENT,rounding=ROUND_CEILING)/100


def prove_catalog(unit,cost,fx,ratio,minimum,rules, *, average_ratio=None):
    tier=package_100k(rules)
    public=(number(unit)*100*number(tier['retained_ratio'])).quantize(CENT,rounding=ROUND_HALF_UP)
    proof=prove_price(public/100,cost,fx,100+number(tier['bonus_k'],zero=True),100,ratio,minimum)
    floor=catalog_floor(cost,fx,ratio,minimum,rules,average_ratio=average_ratio)
    average_net=public*number(average_ratio) if average_ratio is not None else None
    average_margin=(average_net-number(proof['delivered_cost_usd']))/average_net*100 if average_net else None
    if average_margin is not None and average_margin<number(minimum):raise ValueError('pricing_average_catalog_margin_floor')
    return dict(minimum_unit_usd=str(floor),pricing_scope=PRICING_SCOPE,purchase_k='100',delivered_k=proof['delivered_k'],margin_basis=MARGIN_BASIS,
                all_integer_custom_quantities_covered=False,published_packages=1,
                historical_retained_ratio=str(average_ratio) if average_ratio is not None else None,
                minimum_estimated_average_margin_pct=str(average_margin) if average_margin is not None else None,
                worst_published_margin_pct=proof['procurement_margin_pct'])


def average_margin(public_usd, delivered_cost_usd, mix):
    """Historical discount scenario; execution separately validates its source and minimum."""
    if not isinstance(mix,dict) or mix.get('status') not in ('available','partial') or mix.get('retained_ratio') is None:
        return dict(status='not_available',reason=mix.get('reason','historical_discount_mix_missing') if isinstance(mix,dict) else 'historical_discount_mix_missing',procurement_margin_pct=None)
    if mix.get('sha256') != fingerprint({k:v for k,v in mix.items() if k!='sha256'}):
        raise ValueError('pricing_historical_mix_hash_changed')
    ratio=number(mix['retained_ratio'],zero=True)
    if ratio>1:raise ValueError('pricing_historical_mix_ratio_invalid')
    net=number(public_usd)*ratio;cost=number(delivered_cost_usd)
    return dict(status=mix['status'],period=mix['period'],observed_orders=mix['observed_orders'],
                eligible_orders=mix['eligible_orders'],retained_ratio=str(ratio),estimated_net_usd=str(net),
                estimated_procurement_gross_usd=str(net-cost),
                procurement_margin_pct=str((net-cost)/net*100) if net else None,
                historical_mix_sha256=mix['sha256'],source_times=mix.get('source_times'),
                scope='100K package; shared all-Coins historical discount distribution, not platform-specific or portfolio forecast',
                assumptions='same historical discount intensity at candidate price; current delivery cost incl gifts; unknown demand, package mix, Ads and refund settlement')


def history_period(now):
    today=now.astimezone(timezone(timedelta(hours=8))).date()
    return dict(start=(today-timedelta(days=9)).isoformat(),end=(today-timedelta(days=2)).isoformat())


def required_history_ratio(evidence,now,*,require_current=False):
    mix=evidence.get('historical_discount_mix')
    if not isinstance(mix,dict) or mix.get('status') not in ('available','partial'):
        raise ValueError('pricing_average_history_required')
    if mix.get('sha256')!=fingerprint({k:v for k,v in mix.items() if k!='sha256'}):raise ValueError('pricing_historical_mix_hash_changed')
    today=now.astimezone(timezone(timedelta(hours=8))).date()
    window=mix.get('history_window_contract')
    if require_current and window!=HISTORY_WINDOW_CONTRACT:raise ValueError('pricing_average_history_window_migration_required')
    if window not in (None,HISTORY_WINDOW_CONTRACT):raise ValueError('pricing_average_history_window_invalid')
    expected=history_period(now) if window==HISTORY_WINDOW_CONTRACT else {'start':(today-timedelta(days=7)).isoformat(),'end':(today-timedelta(days=1)).isoformat()}
    if mix.get('period')!=expected:
        raise ValueError('pricing_average_history_period')
    observed,eligible=mix.get('observed_orders'),mix.get('eligible_orders')
    if type(observed) is not int or type(eligible) is not int or observed<=0 or observed!=eligible:
        raise ValueError('pricing_average_history_coverage')
    net=number(mix.get('net_order_usd'));discount=number(mix.get('actual_discount_usd'),zero=True)
    if number(mix.get('undiscounted_order_usd'))!=net+discount or number(mix.get('retained_ratio'))!=net/(net+discount):
        raise ValueError('pricing_historical_mix_ratio_invalid')
    return net/(net+discount)



# Original e915cce catalog adapters, bound to this frozen arithmetic.
CATALOG_CONTRACT='fc-coins-catalog-dual20-v1'


def input_ratio(envelope,now):
    """Old promotion evidence is unchanged; V3 catalog makes no worst-offer claim."""
    if not isinstance(envelope,dict) or envelope.get('contract')!=CATALOG_CONTRACT:
        return envelope_ratio(envelope,now)
    if envelope.get('status')!='verified' or envelope.get('site_id')!=266 or envelope.get('game_id')!=1327:
        raise ValueError('pricing_catalog_unverified')
    if envelope.get('worst_status')!='unknown' or 'minimum_retained_ratio' in envelope:
        raise ValueError('pricing_catalog_promotional_claim')
    fresh(envelope.get('checked_at'),now,900)
    if envelope.get('sha256')!=fingerprint({k:v for k,v in envelope.items() if k not in ('sha256','checked_at')}):
        raise ValueError('pricing_catalog_hash_changed')
    if not isinstance(envelope.get('packages'),dict) or set(envelope['packages'])!={'PS','XBOX','PC'}:
        raise ValueError('pricing_catalog_scope_invalid')
    return None


def _math_ratio(ratio):
    # The frozen dual20 formulas do not use this legacy argument for a hard or
    # historical-average floor. Zero is internal numeric compatibility only;
    # it is never stored/returned as an observed promotion or fresh envelope.
    return 0 if ratio is None else ratio


def input_catalog_floor(cost,fx,ratio,minimum,rules,*,average_ratio=None):
    return catalog_floor(cost,fx,_math_ratio(ratio),minimum,rules,average_ratio=average_ratio)


def input_prove_catalog(unit,cost,fx,ratio,minimum,rules,*,average_ratio=None):
    return prove_catalog(unit,cost,fx,_math_ratio(ratio),minimum,rules,average_ratio=average_ratio)


def input_prove_price(unit,cost_cny,fx,delivered_k,base_k,ratio,minimum=HARD_MARGIN):
    result=prove_price(unit,cost_cny,fx,delivered_k,base_k,_math_ratio(ratio),minimum)
    if ratio is None:
        for key in ('worst_net_usd','promotional_net_usd','promotional_gross_usd','promotional_margin_pct','rounding_reserve_usd'):
            result[key]=None
        result['promotional_status']='unknown'
    return result


