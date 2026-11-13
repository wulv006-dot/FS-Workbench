"""Read-only V6 cost diagnostics from private historical attachments and D2 facts."""
from collections import Counter
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib
import json

from .cost_model import BASES, LAYER_FIELDS, estimate_layer, normalize_cost
from .financial import fingerprint, instant, number
from .platforms import PLATFORMS


BEIJING = timezone(timedelta(hours=8))
BOC_URL = 'https://www.bankofchina.com/sourcedb/whpj/'
PAID_SCOPES = ('original Admin-qualified paid nonrefund nonfraud nontest site266 FC27 Coins cohort',
               'site266_fc27_coins_paid')
MIN_COMPLETE = 10
MERCHANT_FEE_POLICY = 'creator-confirmed-site266-fc27-coins-20261113'
ADMIN_LOSS_ENDPOINT = '/admin/order.Order/orderStaticsDetailByEs'
ADMIN_LOSS_BUCKETS = ('ts', 'tssj', 'dc', 'cb', 'tkwtg', 'wh', 'bftk', 'qt', 'bh',
                      'ts_zhui', 'tssj_zhui', 'dc_zhui', 'cb_zhui',
                      'ts_zhui_no', 'tssj_zhui_no', 'dc_zhui_no', 'cb_zhui_no', 'pianzi')
ORDINARY_COST_BASIS = 'same_order_ordinary_delivery_total_at_verified_promised_k'


def merchant_fee_components(site_id):
    """Creator-confirmed merchant rates for MMOEXP FC27 Coins."""
    if site_id != '266':
        return None
    return dict(source='creator_confirmation_2026-11-13', policy=MERCHANT_FEE_POLICY,
                scope='site266_fc27_coins', payment_rate='0', fulfilment_rate='0',
                known_fee_usd='0')


def project_admin_loss_statistics(raw, request, captured_at):
    """Keep the scoped aggregate and membership coverage without releasing Admin IDs."""
    if (not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024
            or not isinstance(request, dict)
            or any(str(request.get(k)) != v for k,v in (
                ('site','266'), ('game','1327'), ('cid','1'), ('pay_status','1')))):
        raise ValueError('admin_loss_request_scope_invalid')
    period = request.get('date')
    if not isinstance(period, list) or len(period) != 2 or not all(isinstance(value,str) for value in period):
        raise ValueError('admin_loss_request_period_invalid')
    dates = [datetime.strptime(value, '%Y-%m-%d %H:%M') for value in period]
    if ([value.strftime('%Y-%m-%d %H:%M') for value in dates] != period
            or dates[1] <= dates[0] or dates[1] - dates[0] > timedelta(days=31)):
        raise ValueError('admin_loss_request_period_invalid')
    payload = json.loads(raw)
    if not isinstance(payload,dict):
        raise ValueError('admin_loss_response_scope_invalid')
    if payload.get('code') in (401,403):
        raise PermissionError('admin_loss_source_denied')
    envelope = payload.get('data') or {}
    if not isinstance(envelope,dict):
        raise ValueError('admin_loss_response_scope_invalid')
    data = envelope.get('data',envelope)
    if not isinstance(data,dict):
        raise ValueError('admin_loss_response_scope_invalid')
    ranks, sites = data.get('game_rank'), data.get('site_rank')
    if ranks == []:
        ranks = {}
    if (payload.get('code') != 1 or not isinstance(ranks,dict) or len(ranks)>1
            or not isinstance(sites,(dict,list)) or (not isinstance(sites,dict) and sites)
            or (isinstance(sites,dict) and set(sites)-{'www.mmoexp.com'})):
        raise ValueError('admin_loss_response_scope_invalid')
    game = next(iter(ranks.values()),{})
    if not isinstance(game,dict):
        raise ValueError('admin_loss_response_scope_invalid')
    categories = game.get('cat') or {}
    if game and (str(game.get('gid'))!='1327' or set(categories)!={'gold'} or not sites):
        raise ValueError('admin_loss_response_scope_invalid')
    if not game and data.get('total') not in (0,'0'):
        raise ValueError('admin_loss_response_scope_invalid')
    buckets, members = {}, {}
    for field in ADMIN_LOSS_BUCKETS:
        row = game.get(field)
        if row is None:
            continue
        if not isinstance(row,dict):
            raise ValueError('admin_loss_bucket_invalid')
        count = row.get('n')
        amount = row.get('amount')
        amount = _number(amount.replace(',','') if isinstance(amount,str) else amount, zero=True)
        if type(count) is not int or count<0 or amount is None:
            raise ValueError('admin_loss_bucket_invalid')
        original_ids = row.get('order_id')
        ids = str(original_ids).split(',') if original_ids else []
        valid_ids = {value.strip() for value in ids if value.strip().isascii() and value.strip().isdecimal()}
        members[field] = valid_ids
        buckets[field] = dict(count=count, amount_usd=str(amount), observed_order_ids=len(valid_ids),
                              order_id_coverage='complete' if count == len(ids) == len(valid_ids) else 'partial')
    overlap = Counter(order_id for values in members.values() for order_id in values)
    return dict(contract='admin_es_fc27_coins_loss_statistics_v1', scope='site266_fc27_coins',
                endpoint=ADMIN_LOSS_ENDPOINT, period=dict(start=period[0],end=period[1],timezone='Asia/Shanghai'),
                period_basis='native_statistics_interval_event_clock_unverified',
                available_at=instant(captured_at).isoformat(), source_sha256=hashlib.sha256(raw).hexdigest(),
                buckets=buckets, unique_observed_order_ids=len(overlap),
                multi_bucket_order_ids=sum(n>1 for n in overlap.values()),
                cost_completeness='unverified', procurement_completion='unverified',
                reshipment_and_recovery_net_cny=None)


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
    shipment_windows = []
    for source in proof.get('shipment_windows', ()):
        lower, upper = _instant(source.get('start')), _instant(source.get('end'))
        captured = _instant(source.get('generated_at'))
        if (lower is None or upper is None or captured is None
                or not lower <= upper or captured > generated or not source.get('revision')):
            raise ValueError('ordinary_delivery_source_window_invalid')
        shipment_windows.append((lower, upper, captured))
    if not shipment_windows and cost_window is not None:
        shipment_windows = [(*cost_window, generated)]
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
        ordinary_records_observed = bool(proof.get('shipment_window_complete') is True
            and coverage.get('admin_complete') is True and row.get('pay_status') == '1'
            and observed is not None and shipment_windows
            and len(valid) == len(records)
            and all(trade and any(lower <= trade <= upper and trade <= captured
                                  for lower, upper, captured in shipment_windows) for trade in trade_times))
        ordinary_records_complete = ordinary_records_observed and row.get('status') == '已完成'
        selected[key] = (paid, actual, observed, generated, records, ordinary_records_complete,
                         ordinary_records_observed)
    return selected, dict(source_revision=revision, admin_revision=coverage['source_revision'],
                          available_at=available.isoformat(), generated_at=generated.isoformat(),
                          order_cost_complete=proof.get('order_cost_complete') is True,
                          shipment_window_complete=proof.get('shipment_window_complete') is True)


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


def _ordinary_delivery_total(records, paid, observed):
    ids = {record.get('cost_record_id') for record in records}
    if (None in ids or len(ids) != len(records)
            or any(not record.get('cost_record_id') or record.get('component') != 'order_delivery'
                   or _instant(record.get('trade_at')) < paid for record in records)):
        return None
    return observed if sum((_number(record.get('cost_cny'), zero=True) for record in records), Decimal(0)) == observed else None


def _window(rows, layer, quantity_basis, *, start, end, proof, source_available, as_of,
            layer_matches, facts, rate, ordinary_forecast=False):
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
    cny_count = partial_count = complete_count = ordinary_count = 0
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
        ordinary = None
        if key in facts:
            d2_paid, d2_actual, d2_observed, d2_generated, d2_records, ordinary_complete, ordinary_observed = facts[key]
            if d2_paid != paid:
                gaps['order_facts_paid_time_mismatch'] += 1
            elif d2_observed is not None and (observed is None or d2_generated >= source_at or d2_observed == observed):
                actual, observed = (None if ordinary_forecast else d2_actual), d2_observed
                quantity_evidence = _delivery_quantity_evidence(d2_records, purchase, bonus)
                delivery_quantities[quantity_evidence] += 1
                if ordinary_forecast and ordinary_observed and quantity_evidence == 'matches_promised_delivered_k':
                    ordinary = _ordinary_delivery_total(d2_records, paid, observed)
                    if ordinary is not None and ordinary_complete:
                        actual = ordinary
                        ordinary_count += 1
            elif d2_observed is not None:
                gaps['order_cost_source_revision_mismatch'] += 1
        amount = actual if actual is not None else observed
        if amount is not None:
            known_cny += amount
            cny_count += 1
            if actual is None:
                partial_cny += amount
                partial_count += 1
        model_amount = None
        if amount is not None and rate is not None:
            # Keep ordinary-source amounts exact until after the comparable
            # rates and bounds are combined. The layer arithmetic is homogeneous.
            model_amount = amount if ordinary_forecast else amount / rate
        complete = actual is not None and model_amount is not None
        if complete and purchase is not None and (quantity_basis == 'PURCHASE_K' or bonus is not None):
            complete_count += 1
        days[paid.astimezone(BEIJING).date().isoformat()] += 1
        samples.append(dict(order_key=key, layer=layer, purchase_k=purchase, promised_bonus_k=bonus,
                            cost_usd=model_amount, cost_complete=complete, cost_kind='TOTAL',
                            ordinary_cost_floor_verified=ordinary is not None and model_amount is not None))
    return samples, dict(start=start.isoformat(), end_exclusive=end.isoformat(),
                         paid_by_beijing_day=dict(sorted(days.items())),
                         order_delivery_quantity_evidence=dict(delivery_quantities),
                         complete_comparable_orders=complete_count, gap_counts=dict(gaps),
                         ordinary_delivery_orders=ordinary_count,
                         known_cost_cny=known_cny if cny_count else None,
                         known_partial_cost_cny=partial_cny if partial_count else None,
                         orders_with_known_cny=cny_count)


def estimate_historical_cost(attachments, layer, quantity_basis, *, as_of, layer_matches,
                             fact_revisions=(), fx=None, paid_cutoff=None, admin_loss_statistics=(),
                             ordinary_forecast=False, selected_orders=None, current_cost=None):
    """Run a same-layer 72h/7d payment-cohort diagnostic with as-of source versions.

    attachments are successive snapshots from collect_historical_attachment for the
    requested population. The latest visible snapshot replaces prior membership.
    layer_matches maps an attachment order_key to an evidenced layer, order_revision,
    available_at and evidence_ref. D2 facts supply private same-order cost observations.
    fact_revisions are successive revisions of the same private D2 input scope.
    paid_cutoff sets the exclusive payment-window end, independently of source availability.
    Admin ES loss snapshots only annotate source coverage. Their intervals differ from
    the payment cohort and their original order sales never modify procurement cost.
    The ordinary forecast may use completed Admin orders whose complete Order
    delivery window and original amounts corroborate the promised delivery.
    The source transaction time is retained independently of procurement settlement.
    """
    as_of = instant(as_of)
    cutoff = instant(paid_cutoff) if paid_cutoff is not None else as_of
    if (quantity_basis not in BASES or layer.get('platform') not in PLATFORMS
            or any(not layer.get(field) for field in LAYER_FIELDS) or cutoff > as_of):
        raise ValueError('cost_layer_basis_or_cutoff_invalid')
    source, source_at = _latest(attachments, lambda value: value.get('available_at'), as_of)
    source_gaps = [] if ordinary_forecast else ['procurement_time_unverified']
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
        if selected_orders is not None:
            selected_keys = set(selected_orders)
            rows = [row for row in rows if row.get('order_key') in selected_keys]
    facts, fact_evidence = _facts(fact_revisions, as_of)
    if ordinary_forecast:
        if fact_evidence is None or not fact_evidence['shipment_window_complete']:
            source_gaps.append('ordinary_delivery_window_unverified')
    elif fact_evidence is None or not fact_evidence['order_cost_complete']:
        source_gaps.append('order_cost_completeness_unverified')
    rate, fx_evidence = _fx(fx, as_of)
    loss, _ = _latest(admin_loss_statistics, lambda value: value.get('available_at'), as_of)
    if loss is not None and (loss.get('contract') != 'admin_es_fc27_coins_loss_statistics_v1'
            or loss.get('scope') != 'site266_fc27_coins'):
        raise ValueError('admin_loss_source_contract')
    if rate is None:
        source_gaps.append('forecast_fx_unavailable_as_of')

    def window(hours):
        return _window(rows, layer, quantity_basis, start=cutoff - timedelta(hours=hours), end=cutoff,
                       proof=proof, source_available=source_at, as_of=as_of, layer_matches=layer_matches,
                       facts=facts, rate=rate, ordinary_forecast=ordinary_forecast)

    samples, recent = window(72)
    selected = recent
    if recent['complete_comparable_orders'] < MIN_COMPLETE:
        samples, selected = window(7 * 24)
    upper = None
    upper_basis = None
    current_source = None
    if ordinary_forecast:
        # The maximum of the latest six comparable ordinary deliveries is a planning
        # fallback, subject to estimate_layer's observed partial-cost floor.
        costs = [row for row in samples if row['cost_complete'] and row['purchase_k'] is not None
                 and (quantity_basis == 'PURCHASE_K' or row['promised_bonus_k'] is not None)]
        if costs:
            delivery_at = {row['order_key']: max(_instant(record['trade_at']) for record in facts[row['order_key']][4])
                           for row in costs if row['order_key'] in facts and facts[row['order_key']][4]}
            recent_costs = sorted(costs, key=lambda row: (delivery_at[row['order_key']], row['order_key']), reverse=True)[:6]
            upper = max(recent_costs, key=lambda row: normalize_cost(row, quantity_basis)['unit_usd'])
            upper_basis = dict(source='up_to_six_latest_same_layer_ordinary_delivery_cost_max',
                               selected_count=len(recent_costs), basis=quantity_basis,
                               layer=dict(layer), order_cost_revision=(fact_evidence or {}).get('source_revision'),
                               sample_ref=hashlib.sha256(json.dumps([row['order_key'] for row in recent_costs]).encode()).hexdigest(),
                               earliest_delivery_at=min(delivery_at[row['order_key']] for row in recent_costs).isoformat(),
                               latest_delivery_at=max(delivery_at[row['order_key']] for row in recent_costs).isoformat())
        if current_cost and quantity_basis == 'PROMISED_DELIVERED_K' and rate is not None:
            checked = _instant(current_cost.get('checked_at'))
            trade = _instant(current_cost.get('trade_at'))
            price = _number(current_cost.get('cny_per_1k'))
            native_source = current_cost.get('source_platform', current_cost.get('platform'))
            if (current_cost.get('platform') == layer['platform'] and native_source == layer['platform']
                    and current_cost.get('status') == 'valid' and current_cost.get('game') == 'FC27'
                    and current_cost.get('product') == 'Game Coins' and current_cost.get('unit') == 'CNY/K'
                    and str(current_cost.get('genre')) == '1' and current_cost.get('record_id')
                    and checked and trade and trade <= checked <= as_of
                    and as_of - checked <= timedelta(hours=1) and as_of - trade <= timedelta(days=7) and price):
                current = dict(layer=layer, purchase_k='1', promised_bonus_k='0',
                               cost_usd=price, cost_kind='PER_BASIS_K', quantity_basis=quantity_basis)
                current_source = dict(source='current_same_platform_order_delivery_unit_cost',
                                      source_platform=native_source, record_id=str(current_cost['record_id']),
                                      checked_at=checked.isoformat(), trade_at=trade.isoformat(),
                                      cny_per_k=str(price), basis=quantity_basis)
                if upper is None or current['cost_usd'] > normalize_cost(upper, quantity_basis)['unit_usd']:
                    upper, upper_basis = current, current_source
        if upper is not None:
            # An observed ordinary shipment can raise an existing planning bound
            # without treating the order's unfinished cost as a complete sample.
            partials = [row for row in samples if not row['cost_complete'] and row['ordinary_cost_floor_verified']]
            if partials:
                floor = max(partials, key=lambda row: (normalize_cost(row, quantity_basis)['unit_usd'], row['order_key']))
                floor_rate = normalize_cost(floor, quantity_basis)['unit_usd']
                if floor_rate > normalize_cost(upper, quantity_basis)['unit_usd']:
                    upper = floor
                    records = facts[floor['order_key']][4]
                    upper_basis = dict(source='same_layer_ordinary_delivery_observed_partial_floor',
                        base_upper_source=upper_basis, basis=quantity_basis, layer=dict(layer),
                        order_cost_revision=(fact_evidence or {}).get('source_revision'),
                        sample_ref=fingerprint(dict(order=floor['order_key'], records=[r['cost_record_id'] for r in records])),
                        latest_delivery_at=max(_instant(record['trade_at']) for record in records).isoformat(),
                        cny_per_basis_k=str(floor_rate))
    estimate = estimate_layer(samples, layer, quantity_basis, upper=upper)
    if ordinary_forecast and not selected['ordinary_delivery_orders']:
        source_gaps.append('ordinary_delivery_cost_sample_missing')
    if ordinary_forecast and current_source and estimate['status'] == 'calculated':
        # A current same-platform quote can raise a completed cohort forecast.
        # It cannot lower an already observed comparable cost or partial floor.
        current_rate = _number(current_source['cny_per_k'])
        for kind in ('expected', 'safe', 'stress'):
            field = kind + '_unit_usd'
            estimate[field] = max(estimate[field], current_rate)
    if ordinary_forecast and rate is not None:
        for field in ('expected_unit_usd', 'safe_unit_usd', 'stress_unit_usd',
                      'known_partial_usd', 'unallocated_known_cost_usd'):
            if estimate[field] is not None:
                estimate[field] /= rate
    gaps = sorted(set(source_gaps) | set(estimate['gaps']) | selected['gap_counts'].keys())
    result = dict(status='calculated' if ordinary_forecast and not gaps else 'PROOF_INCOMPLETE',
                time_basis='payment_cohort',
                window_hours=72 if selected is recent else 7 * 24, selected_window=selected, recent_72h=recent,
                gaps=gaps,
                attachment_revision=revision, order_cost_source=fact_evidence, forecast_fx=fx_evidence,
                diagnostic_estimate=estimate)
    if ordinary_forecast:
        result['cost_basis'] = ORDINARY_COST_BASIS
        result['cost_upper_source'] = upper_basis
        result['current_cost_source'] = current_source
    if loss is not None:
        result['admin_loss_statistics'] = loss
    return result
