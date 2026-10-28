"""Current dual20 threshold over the original full financial algorithm; dual10 is archived for replay."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN
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
ROUNDING_RESERVE = Decimal('.02')
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
    """One console pool uses its newest verified delivery, preserving both observations."""
    records = [evidence['costs'][p] for p in CONSOLE]
    for p, row in zip(CONSOLE, records):
        if row.get('platform') != p or row.get('game') != 'FC27' or row.get('product') != 'Game Coins':
            raise ValueError('pricing_console_cost_scope')
        number(row.get('cny_per_1k'))
        if not str(row.get('record_id', '')).isdigit():
            raise ValueError('pricing_console_cost_identity')
    latest = max(records, key=lambda r: instant(r['trade_at']))
    at = instant(latest['trade_at'])
    tied = [r for r in records if instant(r['trade_at']) == at]
    if len({number(r['cny_per_1k']) for r in tied}) != 1:
        raise ValueError('pricing_console_simultaneous_cost_conflict')
    return number(latest['cny_per_1k']), dict(
        basis='newest_verified_delivery_in_user_confirmed_shared_console_pool',
        selected_platform=latest['platform'], record_id=str(latest['record_id']),
        trade_at=latest['trade_at'], cny_per_k=str(number(latest['cny_per_1k'])),
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


def catalog_floor(cost, fx, ratio, minimum, rules, *, average_ratio=None):
    margin=number(minimum,zero=True)
    hard_floor(cost,fx,1,ratio,minimum)
    qty=number(rules['min_custom_k'])
    retained=number(rules['minimum_package_retained_ratio'])
    delivered=number(rules['max_delivered_ratio'])
    if qty<1 or qty!=qty.to_integral_value() or retained>1 or not 1<=delivered<=2:
        raise ValueError('pricing_catalog_bounds_invalid')
    # At any q >= minimum, two downward cent roundings cost less than this bound.
    settlement=2*CENT/qty
    historical=number(average_ratio) if average_ratio is not None else Decimal(1)
    if historical>1:raise ValueError('pricing_historical_mix_ratio_invalid')
    unit=(number(cost)/number(fx)*delivered/(historical*(1-margin/100))+settlement)/retained
    return unit.quantize(STEP,rounding=ROUND_CEILING)


def prove_catalog(unit,cost,fx,ratio,minimum,rules, *, average_ratio=None):
    if number(unit)<catalog_floor(cost,fx,ratio,minimum,rules):raise ValueError('pricing_catalog_hard_margin_floor')
    floor=catalog_floor(cost,fx,ratio,minimum,rules,average_ratio=average_ratio)
    if number(unit)<floor:
        raise ValueError('pricing_average_catalog_margin_floor' if average_ratio is not None else 'pricing_catalog_hard_margin_floor')
    tiers=[prove_price(number(unit)*number(t['retained_ratio']),cost,fx,
                       number(t['base_k'])+number(t['bonus_k'],zero=True),
                       t['base_k'],ratio,minimum) for t in rules['tiers']]
    average_margins=[(number(t['public_usd'])*number(average_ratio)-number(t['delivered_cost_usd']))/(number(t['public_usd'])*number(average_ratio))*100 for t in tiers] if average_ratio is not None else []
    if average_margins and min(average_margins)<number(minimum):raise ValueError('pricing_average_margin_floor')
    return dict(minimum_unit_usd=str(floor),minimum_custom_k=rules['min_custom_k'],margin_basis=MARGIN_BASIS,
                all_integer_custom_quantities_covered=True,published_packages=len(tiers),
                historical_retained_ratio=str(average_ratio) if average_ratio is not None else None,
                minimum_estimated_average_margin_pct=str(min(average_margins)) if average_margins else None,
                worst_published_margin_pct=str(min(number(t['procurement_margin_pct']) for t in tiers)))


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

