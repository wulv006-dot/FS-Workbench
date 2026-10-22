"""FC Coins deterministic decisions and non-overridable purchase-margin checks."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_DOWN
import hashlib
import json

VERSION = 'fc-coins-decision-v2'
MARGIN_BASIS = 'undiscounted_published_package_v1'
HARD_MARGIN = Decimal('10')
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


def hard_floor(cost_cny, fx, delivered_per_base, retained_ratio, minimum='10'):
    margin = number(minimum, zero=True)
    if margin < HARD_MARGIN or margin >= 100:
        raise ValueError('pricing_hard_margin_minimum_10')
    cost = number(cost_cny) / number(fx) * number(delivered_per_base)
    ratio = number(retained_ratio, zero=True)
    if ratio > 1:
        raise ValueError('pricing_promotions_ratio_invalid')
    return (cost / (1 - margin / 100)).quantize(STEP, rounding=ROUND_CEILING)


def prove_price(unit, cost_cny, fx, delivered_k, base_k, ratio, minimum='10'):
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


def catalog_floor(cost, fx, ratio, minimum, rules):
    margin=number(minimum,zero=True)
    hard_floor(cost,fx,1,ratio,minimum)
    qty=number(rules['min_custom_k'])
    retained=number(rules['minimum_package_retained_ratio'])
    delivered=number(rules['max_delivered_ratio'])
    if qty<1 or qty!=qty.to_integral_value() or retained>1 or not 1<=delivered<=2:
        raise ValueError('pricing_catalog_bounds_invalid')
    # At any q >= minimum, two downward cent roundings cost less than this bound.
    settlement=2*CENT/qty
    unit=(number(cost)/number(fx)*delivered/(1-margin/100)+settlement)/retained
    return unit.quantize(STEP,rounding=ROUND_CEILING)


def prove_catalog(unit,cost,fx,ratio,minimum,rules):
    floor=catalog_floor(cost,fx,ratio,minimum,rules)
    if number(unit)<floor:
        raise ValueError('pricing_catalog_hard_margin_floor')
    tiers=[prove_price(number(unit)*number(t['retained_ratio']),cost,fx,
                       number(t['base_k'])+number(t['bonus_k'],zero=True),
                       t['base_k'],ratio,minimum) for t in rules['tiers']]
    return dict(minimum_unit_usd=str(floor),minimum_custom_k=rules['min_custom_k'],margin_basis=MARGIN_BASIS,
                all_integer_custom_quantities_covered=True,published_packages=len(tiers),
                worst_published_margin_pct=str(min(number(t['procurement_margin_pct']) for t in tiers)))


def average_margin(public_usd, delivered_cost_usd, mix):
    """A 100K scenario under observed revenue-weighted discounts, never a guard or forecast."""
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


def ending(main, checks):
    if main % 1 == Decimal('.99'):
        return main, 'already_99'
    target = main.to_integral_value(rounding=ROUND_DOWN) - CENT
    if target <= 0:
        return main, 'no_positive_99'
    for base, delivered, cost, fx, ratio, margin in checks:
        before = prove_price(main/base, cost, fx, delivered, base, ratio, margin)
        try:
            after = prove_price(target/base, cost, fx, delivered, base, ratio, margin)
        except ValueError:
            return main, 'hard_floor'
        net0, net1 = number(before['undiscounted_net_usd']), number(after['undiscounted_net_usd'])
        loss = net0-net1
        if loss > net0*Decimal('.01') or loss > number(before['procurement_gross_usd'])*Decimal('.05'):
            return main, 'ending_budget'
        if number(before['procurement_margin_pct'])-number(after['procurement_margin_pct']) > 1:
            return main, 'ending_margin_budget'
    return target, 'accepted'


def apply_decision(rows, evidence, edits, *, now=None):
    now = now or datetime.now(timezone.utc)
    fresh(evidence['checked_at'], now)
    fresh(evidence['fx']['checked_at'], now)
    ratio = envelope_ratio(evidence.get('promotion_envelope'), now)
    package_rules=evidence['promotion_envelope'].get('packages') or {}
    if set(package_rules)!={'PS','XBOX','PC'}:
        raise ValueError('pricing_catalog_coverage_missing')
    margin = str(edits.get('minimum_gross_margin_pct', '10'))
    pooled, basis = common_cost(evidence)
    fx = number(evidence['fx']['cny_per_usd'])
    by = {row['platform']:row for row in rows}
    for p in ('PS','XBOX','PC'):
        observed=evidence['costs'][p]
        if observed.get('platform')!=p or observed.get('game')!='FC27' or observed.get('product')!='Game Coins' or not str(observed.get('record_id','')).isdigit():
            raise ValueError('pricing_cost_scope_invalid')
        fresh(observed['checked_at'], now)
        if instant(observed['trade_at']) > now + timedelta(seconds=5):
            raise ValueError('pricing_cost_trade_in_future')
        fresh(evidence['storefront']['rows'][p]['checked_at'], now)
    if edits.get('costs') or edits.get('offers'):
        raise ValueError('pricing_observed_source_edit_forbidden')
    quotes = edits.get('quotes') or {}
    if any(p in quotes for p in CONSOLE) and (set(quotes)&set(CONSOLE) != set(CONSOLE) or number(quotes['PS']) != number(quotes['XBOX'])):
        raise ValueError('pricing_common_console_quote_required')
    decisions = []
    for group in (CONSOLE, ('PC',)):
        cost = pooled if len(group)==2 else number(evidence['costs']['PC']['cny_per_1k'])
        checks, current, anchors = [], [], []
        for p in group:
            own = evidence['storefront']['rows'][p]
            base = number(own['base_k']); delivered = base + number(own['bonus_k'], zero=True)
            if base != 100 or delivered > 200:
                raise ValueError('pricing_package_invalid')
            current.append(number(own['package_usd']))
            loot = evidence['offers'][p]['Lootbar']
            fresh(loot['checked_at'], now)
            if loot.get('conditional') or loot.get('comparable') is not True or number(loot['base_k']) != 100:
                raise ValueError('pricing_comparable_anchor_required')
            anchors.append(number(loot['usd_price']) / (number(loot['base_k'])+number(loot.get('bonus_k',0),zero=True))*delivered)
            checks.append((base,delivered,cost,fx,ratio,margin))
        floor = max(hard_floor(c,rate,d/base,r,m)*base for base,d,c,rate,r,m in checks).quantize(CENT,rounding=ROUND_CEILING)
        floor=max(floor,max(catalog_floor(cost,fx,ratio,margin,package_rules[p])*100 for p in group)).quantize(CENT,rounding=ROUND_CEILING)
        anchor = min(anchors).quantize(CENT,rounding=ROUND_CEILING)
        # Parity takes the smallest needed move; high margin alone never buys an extra cut.
        hold = max(current)
        main = max(floor, min(hold, anchor))
        reason = 'cost_or_promotion_floor' if floor > hold else 'public_anchor_parity' if main < hold else 'already_competitive_hold'
        if reason=='already_competitive_hold' and len(set(current))>1:reason='unify_common_console_base'
        if group[0] in quotes:
            main = number(quotes[group[0]])*100
            if main != main.quantize(CENT):
                raise ValueError('pricing_package_cents_required')
            reason = 'operator_or_hermes_candidate'
        while True:
            try:
                for base,d,c,rate,r,m in checks:prove_price(main/base,c,rate,d,base,r,m)
                break
            except ValueError as exc:
                if str(exc) != 'pricing_hard_margin_floor' or group[0] in quotes:
                    raise
                main += CENT
        target, tail = ending(main, checks)
        if any(target/100<catalog_floor(cost,fx,ratio,margin,package_rules[p]) for p in group):
            target,tail=main,'catalog_hard_floor'
        if group[0] in quotes:
            target, tail = main, 'explicit_candidate_no_hidden_adjustment'
        for p, (base, delivered, c, rate, r, m), old in zip(group, checks, current):
            row = by[p]
            proof = prove_price(target/base,c,rate,delivered,base,r,m)
            proof['catalog']=prove_catalog(target/base,c,rate,r,m,package_rules[p])
            average=average_margin(proof['public_usd'],proof['delivered_cost_usd'],evidence.get('historical_discount_mix'))
            old_average=average_margin(old,proof['delivered_cost_usd'],evidence.get('historical_discount_mix'))
            old_net = old.quantize(CENT,rounding=ROUND_DOWN)
            old_gp = old_net-number(proof['delivered_cost_usd'])
            new_gp = number(proof['procurement_gross_usd'])
            average_old_gp=Decimal(old_average['estimated_procurement_gross_usd']) if 'estimated_procurement_gross_usd' in old_average else None
            average_new_gp=Decimal(average['estimated_procurement_gross_usd']) if 'estimated_procurement_gross_usd' in average else None
            multiplier=average_old_gp/average_new_gp if average_old_gp is not None and average_old_gp>0 and average_new_gp>0 else None
            public_anchor=evidence['offers'][p]['Lootbar']
            row.update(cost_cny=str(cost), proposal=f'{target/base:.4f}', auto_proposal=f'{target/base:.4f}',
                raw_cost_record_id=evidence['costs'][p]['record_id'],
                raw_cost_trade_at=evidence['costs'][p]['trade_at'],
                cost_record_id=basis['record_id'] if p in CONSOLE else evidence['costs'][p]['record_id'],
                cost_trade_at=basis['trade_at'] if p in CONSOLE else evidence['costs'][p]['trade_at'],
                target_page_usd=f'{target:.2f}', floor_usd_per_1k=f'{floor/base:.4f}',
                gross_margin_pct=f"{Decimal(proof['procurement_margin_pct']):.2f}",
                margin_basis=MARGIN_BASIS,estimated_average_margin=average,
                minimum_gross_margin_pct=str(margin),
                margin_below_minimum=False, auto_blocked_reason=None, pricing_mode=VERSION,
                pricing_tier=None, requested_discount_pct=None, profit_floor_applied=reason=='cost_or_promotion_floor',
                pricing_basis='page_total_100k', strategy_version=VERSION, quote_manual=p in quotes,
                own_bonus_k=str(delivered-base), decision_reason=reason, ending_reason=tail,
                pricing_quantity_basis='both_sides_actual_delivered_quantity',
                reference_fallback='reference_prices_do_not_force_extra_discount',
                lootbar_page_usd=f"{number(public_anchor['usd_price']):.2f}",
                lootbar_usd_per_1k=str(number(public_anchor['usd_price'])/(number(public_anchor['base_k'])+number(public_anchor.get('bonus_k',0),zero=True))),
                pre_change_margin_pct=str(old_gp/old_net*100) if old_net else None,
                main_page_usd=f'{main:.2f}', anchor_page_usd=f'{anchor:.2f}',
                change_pct=str((target/old-1)*100), break_even_order_multiplier=str(multiplier) if multiplier is not None else None,
                proof=proof, cost_basis=basis if p in CONSOLE else {'basis':'latest_verified_pc_delivery'},
                break_even_order_basis='same historical discount mix and fixed delivered cost; conditional, not demand forecast',
                warning='10%仅约束未用优惠的前台套餐价，含赠送与数量公式；合法优惠允许低于10%或亏损。平均毛利为历史折扣情景估算，广告后贡献另核。',
                status='10%硬红线核算通过 · 待执行', benchmark_site='Lootbar public display',
                lootbar_reduction_pct=str((1-target/anchors[group.index(p)])*100))
        candidates={'baseline':str(target)}
        if hold>=floor:
            candidates['hold']=str(hold)
        parity=max(floor,anchor)
        parity_tail,_=ending(parity,checks)
        if all(parity_tail/100>=catalog_floor(cost,fx,ratio,margin,package_rules[p]) for p in group):
            parity=parity_tail
        candidates['parity']=str(parity)
        decisions.append(dict(platforms=list(group),reason=reason,current_public_usd=[str(v) for v in current],
                              main_usd=str(main),selected_usd=str(target),floor_usd=str(floor),ending=tail,
                              candidates=candidates))
    receipt=dict(strategy_version=VERSION, hard_minimum_margin_pct=str(HARD_MARGIN),margin_basis=MARGIN_BASIS,
        promotions_exempt_from_margin_floor=True,
        historical_discount_mix_sha256=(evidence.get('historical_discount_mix') or {}).get('sha256'),
        minimum_retained_ratio=str(ratio), promotion_envelope_sha256=evidence['promotion_envelope']['sha256'],
        common_console_cost=basis, decisions=decisions, ad_after_profit='unknown_until_same_scope_ads',
        causal_effect='not_established', comparison_scope='current_public_display_delivered_100K',
        code_sha256=hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes()).hexdigest())
    receipt['sha256']=fingerprint(receipt)
    return receipt


def verify_quote(quote, policy, selected, *, now=None, for_execution=False):
    configured=number(policy['minimum_gross_margin_pct'],zero=True)
    if configured < HARD_MARGIN:
        raise ValueError('pricing_hard_margin_minimum_10')
    if for_execution and quote['evidence']['promotion_envelope'].get('coupon_other_benefits_contract') not in {'not_applicable','verified_mutually_exclusive','verified_included_in_envelope'}:
        raise ValueError('pricing_coupon_other_benefits_unverified')
    if number((quote.get('edits') or {}).get('minimum_gross_margin_pct','10'),zero=True)!=configured:
        raise ValueError('pricing_policy_margin_changed')
    if (not isinstance(selected,list) or not selected or len(set(selected))!=len(selected)
            or set(selected)-{'PS','XBOX','PC'}):
        raise ValueError('pricing_platform_selection_invalid')
    if set(selected)&set(CONSOLE) and not set(CONSOLE)<=set(selected):
        raise ValueError('pricing_common_console_scope_required')
    rows=quote['result']['rows']
    if len(rows)!=3 or {r.get('platform') for r in rows}!={'PS','XBOX','PC'}:
        raise ValueError('pricing_platform_rows_invalid')
    expected=deepcopy(quote['result']['rows'])
    receipt=apply_decision(expected,quote['evidence'],quote.get('edits') or {},now=now)
    if quote['result'].get('decision_receipt') != receipt:
        raise ValueError('pricing_decision_receipt_changed')
    actual={r['platform']:r for r in quote['result']['rows']}
    for row in expected:
        if row['platform'] not in selected:continue
        for key in ('proposal','cost_cny','target_page_usd','proof','strategy_version','decision_reason','estimated_average_margin','margin_basis'):
            if row[key]!=actual[row['platform']].get(key):
                raise ValueError('pricing_quote_tampered')
    return receipt
