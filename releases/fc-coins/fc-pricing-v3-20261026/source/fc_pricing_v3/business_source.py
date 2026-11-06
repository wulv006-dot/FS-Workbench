"""Real Coins evidence; private historical rows stay behind aggregate API projections."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import html
import json
import re

from .financial import fingerprint

TZ = timezone(timedelta(hours=8))
POINTS_PER_USD = Decimal('100')
POINTS_CAP = Decimal('.10')
PLATFORMS = {'PS': 'PlayStation 4|5', 'XBOX': 'Xbox One|X|S', 'PC': 'PC Platform'}
PLATFORM_AIDS = {'21587': 'PS', '21585': 'XBOX', '21589': 'PC'}


def amount(value):
    if value is None or isinstance(value, bool) or str(value).strip() in ('', '-', '—'):
        return None
    try:
        n = Decimal(re.sub(r'[$￥¥,\s]', '', str(value)))
    except InvalidOperation:
        return None
    return n if n.is_finite() else None


def _period_population(period):
    from coins_evidence import CoinsEvidence, es_metadata, GOLD
    from channel_effects import accounting_row, fraud
    reader = CoinsEvidence()
    data = reader.channel_data(period)
    if not data:
        return None, dict(status='unavailable', period=period, reason='canonical_period_cache_missing')
    meta, coverage = es_metadata(period['start'], period['end'], reader.archive)
    selected = {}
    missing = 0
    missing_usd = Decimal(0)
    for raw in data['orders']:
        if str(raw.get('gid')) != '1327':
            continue
        row = accounting_row(raw, data.get('costOverrides', {}), data.get('testOrders', {}), admin_revenue=True)
        if row.get('testOrder') or fraud(row) or row.get('refunded') or str(row.get('payStatus')) != '1':
            continue
        info = meta.get(hashlib.sha256(raw['orderNo'].encode()).hexdigest())
        if not info:
            missing += 1
            missing_usd += amount(row.get('salesUsd')) or Decimal(0)
            continue
        if info['product'] != GOLD:
            continue
        selected[raw['orderNo']] = (row, info)
    provenance = dict(status='complete' if coverage['complete'] and not missing else 'partial', period=period,
        canonical_archive_sha256=fingerprint(data), ES_source_sha256=coverage['source_sha256'],
        ES_complete=coverage['complete'], missing_product_identity=missing,
        unclassified_paid_FC_usd=str(missing_usd),
        eligible_count=len(selected), source_generated_at=data.get('generatedAt'))
    return selected, provenance


def summarize(selected):
    counts = Counter()
    totals = defaultdict(Decimal)
    for row, es in selected.values():
        counts['orders'] += 1
        net = amount(row.get('salesUsd'))
        discount = amount(es.get('discount_usd'))
        if net is not None:
            totals['net_paid_usd'] += net
            counts['net_usd_known'] += 1
        if discount is not None:
            totals['actual_discount_usd'] += discount
            counts['discount_known'] += 1
        if row.get('customerType') in ('新客', '老客'):
            counts['customer_type_known'] += 1
            counts['new_customer_orders' if row['customerType'] == '新客' else 'returning_customer_orders'] += 1
        if row.get('status') == '已完成':
            counts['completed'] += 1
            cost, revenue = amount(row.get('costCny')), amount(row.get('saleCny'))
            if cost is not None and revenue is not None:
                counts['covered_cost_orders'] += 1
                totals['covered_cost_cny'] += cost
                totals['covered_revenue_cny'] += revenue
                totals['covered_gross_profit_cny'] += revenue - cost
        else:
            counts['not_completed'] += 1
    total = counts['orders']
    result = dict(orders=total, **{k: str(v) for k, v in totals.items()}, coverage=dict(counts))
    result['new_customer_order_ratio'] = str(Decimal(counts['new_customer_orders']) / total) if total and counts['customer_type_known'] == total else None
    result['effective_new_customers'] = None
    result['net_paid_usd'] = str(totals['net_paid_usd']) if counts['net_usd_known'] == total else None
    return result


def _coupon_path(template):
    values = {k: amount(template.get(k)) for k in ('reduce', 'attain', 'max_reduce')}
    if any(v is None or v < 0 for v in values.values()):
        raise ValueError('history_coupon_terms_missing')
    path = dict(threshold_usd=str(values['attain']), cap_usd=str(values['max_reduce']) if values['max_reduce'] else None)
    if str(template.get('mode_type')) == '2':
        if values['reduce'] > 100:
            raise ValueError('history_coupon_ratio_invalid')
        return dict(path, kind='ratio', retained_ratio=str(values['reduce'] / 100))
    if str(template.get('mode_type')) in ('1', '3'):
        return dict(path, kind='fixed', discount_usd=str(values['reduce']))
    raise ValueError('history_coupon_mode_unknown')


def promotion_path(order, es_discount, coupon_logs, templates):
    """Check historical amount layers; project the observed eligibility under current terms."""
    before, percent, discount = (amount(order.get('before_discount')), amount(order.get('discount')), amount(es_discount))
    points = amount(order.get('points'))
    if before is None or before <= 0 or percent is None or not 0 < percent <= 100 or discount is None or discount < 0 or points is None or points < 0:
        raise ValueError('history_price_layer_fields_missing')
    coupon_amounts = [amount(log.get('discount_amount')) for log in coupon_logs]
    if any(v is None or v < 0 for v in coupon_amounts):
        raise ValueError('history_coupon_log_amount_missing')
    actual_coupon = sum(coupon_amounts, Decimal(0))
    code_discount = before * (1 - percent / 100)
    credit = points / POINTS_PER_USD
    if abs(code_discount + actual_coupon + credit - discount) > Decimal('.02'):
        raise ValueError('history_discount_layer_mismatch')
    if points:
        if coupon_logs or percent != 100 or credit > before * POINTS_CAP + Decimal('.02'):
            raise ValueError('history_points_exclusivity_or_cap')
        return dict(kind='points', credit_usd=str(credit), cap_ratio=str(POINTS_CAP))
    paths = []
    if percent != 100:
        paths.append(dict(kind='ratio', retained_ratio=str(percent / 100), threshold_usd='0', cap_usd=None))
    for log in coupon_logs:
        template = templates.get(str(log.get('coupon_id')))
        if not template:
            raise ValueError('history_coupon_template_missing')
        if template.get('_current_active') is False:
            continue  # Current availability follows the original active() contract, not an expired historical offer.
        if paths and str(template.get('is_open')) == '0':
            raise ValueError('history_exclusive_promotions_overlap')
        paths.append(_coupon_path(template))
    if not paths:
        return dict(kind='none')
    return paths[0] if len(paths) == 1 else dict(kind='sequence', paths=paths)


def _used_coupon_template_ids(selected,logs):
    identities=set()
    for archived,_ in selected.values():
        for coupon in archived.get('coupons',[]):
            log=logs.get(str(coupon['id']))
            if not log or not log.get('coupon_id'):
                raise ValueError('history_coupon_log_amount_missing')
            identities.add(str(log['coupon_id']))
    return identities


def read_used_templates(session,pages,identities):
    """Complete original template rows for observed coupon IDs; inactive rows matter."""
    wanted=sorted(set(str(identity) for identity in identities))
    if any(not identity.isdigit() for identity in wanted):
        raise ValueError('selective_current_coupon_template_identity')
    result={}
    for offset in range(0,len(wanted),100):
        group=wanted[offset:offset+100]
        for row in pages(session,'/admin/market.Coupon/index',[('id','IN',','.join(group))]):
            identity=str(row.get('id'))
            if identity not in group or identity in result:
                raise ValueError('selective_current_coupon_template_scope')
            result[identity]=row
    if set(result)!=set(wanted):
        raise ValueError('selective_current_coupon_template_missing')
    return result


def _live_traces(session, pages, period, selected, *, reconcile_population=False, used_templates_only=False):
    rows = pages(session, '/admin/order.Order/index', [('site_id', '=', '266'), ('gid', '=', '1327'),
                 ('paytime', 'RANGE', period['start'] + ' 00:00:00,' + period['end'] + ' 23:59:59')], 100)
    def changed_population():
        error=ValueError('history_order_state_changed_since_archive')
        # In-process handoff only; the accounting rebuild rechecks the original scope.
        error.native_rows=tuple(rows)
        raise error
    if reconcile_population:
        new_paid = [row for row in rows if str(row.get('order_no')) not in selected
                    and str(row.get('site_id')) == '266' and str(row.get('gid')) == '1327'
                    and str(row.get('pay_status')) == '1']
        if new_paid:
            from coins_evidence import CoinsEvidence, es_metadata, GOLD
            metadata, _ = es_metadata(period['start'], period['end'], CoinsEvidence().archive)
            for row in new_paid:
                info = metadata.get(hashlib.sha256(str(row['order_no']).encode()).hexdigest())
                if not info or info.get('product') in (None, '', 'unknown', 'ambiguous'):
                    raise ValueError('history_new_paid_product_identity_missing')
                if info['product'] == GOLD:
                    changed_population()
    orders = {}
    for row in rows:
        sn = str(row.get('order_no'))
        if sn not in selected:
            continue
        if str(row.get('site_id')) != '266' or str(row.get('gid')) != '1327' or sn in orders:
            raise ValueError('history_live_order_scope')
        if str(row.get('pay_status')) != '1':
            changed_population()
        orders[sn] = row
    if set(orders) != set(selected):
        raise ValueError('history_live_order_coverage')
    # Only original used-coupon orders need the existing complete log lookup.
    coupon_orders = sorted(sn for sn, (r, _) in selected.items() if r.get('coupons'))
    logs = {}
    for offset in range(0, len(coupon_orders), 100):
        group = coupon_orders[offset:offset + 100]
        for log in pages(session, '/admin/user.MemberCouponLog/index', [('site_id', '=', '266'), ('order_no', 'IN', ','.join(group))]):
            if str(log.get('site_id')) != '266' or str(log.get('order_no')) not in group or str(log['id']) in logs:
                raise ValueError('history_coupon_log_scope')
            logs[str(log['id'])] = log
    templates = (read_used_templates(session,pages,_used_coupon_template_ids(selected,logs)) if used_templates_only
                 else {str(t['id']): t for t in pages(session, '/admin/market.Coupon/index')})
    return orders, logs, templates


def _historical_paid_lower_bound(order, coupon_logs):
    """Replay the original amount only; historical coupon amounts are not future fixed coupons."""
    from .engine import replay_promotion
    before = amount(order['before_discount'])
    retained = amount(order['discount']) / 100
    paths = []
    if retained != 1:
        paths.append(dict(kind='ratio', retained_ratio=str(retained)))
    coupon = sum((amount(log['discount_amount']) for log in coupon_logs), Decimal(0))
    if coupon:
        paths.append(dict(kind='fixed', discount_usd=str(coupon)))
    credit = (amount(order.get('points')) or Decimal(0)) / POINTS_PER_USD
    if credit:
        paths.append(dict(kind='points', credit_usd=str(credit), cap_ratio=str(POINTS_CAP)))
    path = paths[0] if len(paths) == 1 else dict(kind='sequence', paths=paths) if paths else dict(kind='none')
    return replay_promotion(before, path)


def build_replay(selected, orders, logs, templates, provenance, *, include_regions=True):
    grouped = {}
    counts, failures, old_factors = Counter(), Counter(), Counter()
    gross = net = discount = residual_total = Decimal(0)
    trace = []
    negative_groups = {}
    residual_min = None
    negative_sum = Decimal(0)
    for sn, (archived, es) in selected.items():
        order = orders[sn]
        used = [logs.get(str(c['id'])) for c in archived.get('coupons', [])]
        current_net, es_discount = amount(order.get('amount_usd_format')), amount(es.get('discount_usd'))
        try:
            if any(log is None for log in used):
                raise ValueError('history_coupon_log_missing')
            if current_net is None or current_net < 0 or es_discount is None or es_discount < 0:
                raise ValueError('history_amount_missing')
            if current_net != amount(archived.get('salesUsd')):
                raise ValueError('history_net_changed_since_archive')
            region = str(order.get('is_region_price')) == '1'
            factor = amount(order.get('region_price_factor')) if region else Decimal(1)
            if factor is None or factor <= 0:
                raise ValueError('history_region_factor_missing')
            path = promotion_path(order, es_discount, used, templates)
            weight = current_net + es_discount
            if weight <= 0:
                # Zero-revenue observations have zero influence on the original amount-weighted formula.
                counts['zero_weight_orders'] += 1
                continue
            coupon_terms = [{k: templates[str(log['coupon_id'])].get(k) for k in
                ('mode_type', 'reduce', 'attain', 'max_reduce', 'is_open', 'type', 'time_effect', 'start_time', 'end_time', 'days', 'fetch_scene', 'product_type', 'site_id', 'game_id', '_current_active')} for log in used]
            counts['historical_coupon_currently_inactive'] += sum(t['_current_active'] is False for t in coupon_terms)
            identity = dict(denominator_basis='regional_regular', promotion_path_excludes_region=True,
                            promotion_path=path, coupon_eligibility_terms=coupon_terms)
            key = fingerprint(identity)
            sample = grouped.setdefault(key, dict(identity, weight_usd='0', orders=0))
            sample['weight_usd'] = str(Decimal(sample['weight_usd']) + weight)
            sample['orders'] += 1
            counts['matched'] += 1
            counts['points' if amount(order.get('points')) else 'coupon' if used else 'code' if order.get('discount_code') else 'automatic_or_none'] += 1
            if region:
                counts['region_matched'] += 1
            old_factors[str(factor)] += 1
            net += current_net
            discount += es_discount
            gross += weight
            before = amount(order.get('before_discount'))
            historical_paid = _historical_paid_lower_bound(order, used)
            residual = current_net - historical_paid
            residual_total += residual
            residual_min = residual if residual_min is None else min(residual_min, residual)
            if residual >= 0:
                counts['net_residual_nonnegative'] += 1
            else:
                counts['net_residual_negative'] += 1
                negative_sum += residual
                if residual < Decimal('-.02'):
                    counts['negative_residual_over_2c'] += 1
                if residual < Decimal('-.05'):
                    counts['negative_residual_over_5c'] += 1
                label = dict(currency=str(order.get('currency_code') or 'unknown'),
                    payment=str(order.get('paytype_display') or order.get('paytype') or 'unknown'),
                    promotion=path['kind'], status=str(order.get('status_format') or 'unknown'),
                    pay_status=str(order.get('pay_status') or 'unknown'))
                label = {k: v if len(v) <= 100 and not re.search(r'[@<>\r\n]|https?://', v) else 'unknown' for k, v in label.items()}
                group = negative_groups.setdefault(fingerprint(label), dict(label, orders=0, total_usd='0', minimum_usd='0'))
                group['orders'] += 1
                group['total_usd'] = str(Decimal(group['total_usd']) + residual)
                group['minimum_usd'] = str(min(Decimal(group['minimum_usd']), residual))
            trace.append({k: order.get(k) for k in ('order_no', 'pay_status', 'amount_usd_format', 'before_discount', 'discount', 'points', 'is_region_price', 'region_price_factor', 'region_price_lang_region_id')})
        except (ValueError, KeyError, InvalidOperation) as error:
            failures[str(error) if isinstance(error, ValueError) else type(error).__name__] += 1
    paths = [grouped[k] for k in sorted(grouped)]
    source = dict(provenance, live_trace_sha256=fingerprint(trace), coupon_logs_sha256=fingerprint(logs),
                  current_coupon_terms_sha256=fingerprint(templates), eligible_count=len(selected))
    complete = provenance.get('status') == 'complete' and not failures and counts['matched'] + counts['zero_weight_orders'] == len(selected) and gross > 0
    result = dict(status='verified' if complete else 'partial', period=provenance['period'], source_sha256=fingerprint(source),
        provenance=source, eligible_count=len(selected), coverage=dict(counts), failures=dict(failures),
        paths=paths, paths_sha256=fingerprint(paths), original_amount_weight_usd=str(gross),
        original_net_usd=str(net), original_discount_usd=str(discount),
        original_retained_ratio=str(net / gross) if gross else None,
        old_region_factor_counts=dict(old_factors), source_scope='global_pooled_actual_mix',
        application_scope='each_candidate_region_and_tier', projection='historical_eligibility_current_terms_projected',
        residual_semantics='Admin_net_minus_original_ROUND_UP_promotion_cash_lower_bound; not_assumed_payment_fees',
        original_net_amount_residual_usd=str(residual_total),
        residual_minimum_usd=str(residual_min) if residual_min is not None else None, negative_residual_total_usd=str(negative_sum),
        negative_residual_groups=[negative_groups[k] for k in sorted(negative_groups)],
        sufficient_promotion_lower_bound=complete and counts['net_residual_negative'] == 0,
        basis_lower_bound_sufficient=complete and counts['net_residual_negative'] == 0,
        observed_negative_residual_within_2c=complete and counts['negative_residual_over_2c'] == 0,
        original_basis_reconciliation='Original v15 N/(N+ES_discount) is preserved separately. Original historical paths use actual code percentage, actual coupon-log USD amount and actual points credit with engine ROUND_UP deduction; current expired-template none projection is never used to validate old N. Every historical replay cash amount must be <= original Admin N. Differences are explicit cash lower bounds, not invented fee functions.',
        points_contract=dict(points_per_usd='100', cap_ratio='.10', basis='actual_closed_seven_day_points_identity_and_existing_cart_cap'),
        promotion_paths_exclude_region=True, no_customer_or_order_identity_returned=True)
    if include_regions:
        regions = defaultdict(dict)
        for sn, pair in selected.items():
            if str(orders[sn].get('is_region_price')) == '1':
                regions[str(orders[sn].get('region_price_lang_region_id'))][sn] = pair
        result['region_layers'] = {region: build_replay(entries, orders, logs, templates,
            dict(provenance, eligible_count=len(entries), source_scope='actual_region_' + region), include_regions=False)
            for region, entries in regions.items()}
        for region, layer in result['region_layers'].items():
            layer.update(source_scope='actual_region_' + region, application_scope='same_region_or_explicit_projection')
    return result


def _customer_assignments(selected, orders):
    identities = {}
    assigned = {}
    known_flags = 0
    for sn in sorted(selected, key=lambda key: (str(selected[key][0].get('paidAt') or ''), key)):
        row = selected[sn][0]
        email = str(orders[sn].get('email') or '').strip().casefold()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            continue
        identity = hashlib.sha256(email.encode()).hexdigest()
        identities[sn] = identity
        if row.get('customerType') in ('新客', '老客'):
            known_flags += 1
        if row.get('customerType') == '新客' and identity not in assigned:
            assigned[identity] = sn
    complete = len(identities) == len(selected) and known_flags == len(selected)
    return identities, assigned, dict(status='complete' if complete else 'partial',
        identity_known_orders=len(identities), backend_customer_flag_known_orders=known_flags,
        eligible_orders=len(selected), known_unique_customers=len(set(identities.values())),
        known_unique_new_customers=len(assigned), effective_new_customers=len(assigned) if complete else None,
        source_sha256=fingerprint(dict(identities=identities, assignments=assigned)),
        identity_basis='Admin_customer_email; payer_email_not_substituted; UID0_included',
        attribution='first_backend_flagged_new_order_per_email_in_this_window')


def _platform(order):
    if str(order.get('aid')) in PLATFORM_AIDS:
        return PLATFORM_AIDS[str(order['aid'])]
    # Old Xbox label was checked against native product pid163329277/aid21585.
    text = str(order.get('content') or '') + ' ' + str(order.get('show_game_pro') or '')
    found = [p for p, label in PLATFORMS.items() if label in text]
    # Earlier native orders used this server label before the PlayStation 4|5 rename.
    if '[PlayStation 5]' in html.unescape(re.sub(r'<[^>]*>', '', text)):
        found.append('PS')
    if 'Xbox Series X|S' in text:
        found.append('XBOX')
    found = list(set(found))
    return found[0] if len(found) == 1 else None


def _quantity(order):
    """Strict native K-coins item titles, checked against getOrderAdd.quantity (gift included)."""
    text = html.unescape(str(order.get('content') or ''))
    items = re.findall(r'<span\s+class=[\"\']?item[\"\']?\s*>(.*?)</span>', text, re.I | re.S)
    items = [line for item in items for line in re.split(r'<br\s*/?>', item, flags=re.I)
             if re.sub(r'<[^>]*>', '', line).strip()]
    if not items:
        return None
    totals = dict(purchase_k=Decimal(0), bonus_k=Decimal(0), delivered_k=Decimal(0))
    lines = []
    for item in items:
        title = re.sub(r'<[^>]*>', '', item).strip()
        match = re.fullmatch(r'[\s☑]*([\d,]+(?:\.\d+)?)\s*K\s+coins(?:\s*\+\s*([\d,]+(?:\.\d+)?)\s*K\s+Free)?\s*[x×]\s*(\d+)\s*=[^=]*', title, re.I)
        if not match:
            return None
        purchase = amount(match[1])
        bonus = amount(match[2]) if match[2] is not None else Decimal(0)
        count = int(match[3])
        if purchase is None or purchase <= 0 or bonus is None or count <= 0:
            return None
        line = dict(purchase_k=purchase * count, bonus_k=bonus * count, delivered_k=(purchase + bonus) * count)
        for key in totals:
            totals[key] += line[key]
        lines.append(dict(multiplier=count, **{k: str(v) for k, v in line.items()}))
    return dict(**{k: str(v) for k, v in totals.items()}, lines=lines,
                basis='native_historical_K_coins_title_times_num; gift_included_in_delivered_K')


def marketing_context(period):
    """Existing published data only; no range refresh, credentials, account rows or causal CAC."""
    try:
        from marketing_snapshot import PUBLISHED, projection
        # Published local model is currently 12.1 MB; the HTTP reply cap is not its file contract.
        raw = PUBLISHED.read_bytes()
        value = projection(json.loads(raw), dict(profile='FC27', **period), hashlib.sha256(raw).hexdigest())
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        return dict(status='unavailable', reason=type(error).__name__, attribution='cannot_allocate_incremental_CAC')
    project = cross_game = Decimal(0)
    complete = bool(value.get('ads_accounts'))
    for account in value.get('ads_accounts', []):
        campaigns = account.get('campaigns') or {}
        complete = complete and campaigns.get('calculation_complete') is True and campaigns.get('rejected_rows') == 0 and account.get('coverage', {}).get('query_range_complete') is True
        for row in campaigns.get('rows', []):
            cost = amount((row.get('metrics') or {}).get('cost'))
            if row.get('game_target') == 'FC27' and row.get('campaign_scope') == 'project':
                if cost is None:
                    complete = False
                else:
                    project += cost
            elif row.get('project_game') == 'FC27' and row.get('metric_scope') == 'cross_game':
                if cost is None:
                    complete = False
                else:
                    cross_game += cost
    return dict(status='fixed_context_available' if complete else 'partial_or_unavailable', period=period,
        fc_project_name_scoped_cost_usd=str(project) if complete else None,
        fc_project_cross_game_cost_usd=str(cross_game) if complete else None,
        fc_project_total_cost_usd=str(project + cross_game) if complete else None,
        Coins_attributed_cost_usd=None, incremental_CAC_usd=None, attribution='cannot_allocate_incremental_CAC',
        cost_scope='FC project fixed context; includes user-confirmed cross-game PMax; not allocated to Coins or region',
        source_sha256=value.get('source_sha256'), captured_at=value.get('captured_at'),
        source_rule_version=value.get('source_rule_version'), reason=value.get('reason'),
        traffic_context={key: {field: source.get(field) for field in ('status', 'coverage', 'metrics')} for key, source in value.get('sources', {}).items()},
        traffic_scope='whole-site background; GA newUsers are not effective new buyers')


def fulfillment_context(selected, orders, provenance):
    """Actual cached delivery rows for this paid cohort; measured throughput is not a capacity promise."""
    try:
        from channel_source import load_costs
        rows, source = load_costs()
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        return dict(status='unavailable', reason=type(error).__name__, promised_capacity_k_per_block=None)
    period = provenance['period']
    hours = Decimal((datetime.fromisoformat(period['end']) - datetime.fromisoformat(period['start'])).days + 1) * 24
    total = Decimal(0)
    matched = known = 0
    for row in rows:
        if str(row.get('sn')) not in selected or not period['start'] <= str(row.get('trade_at'))[:10] <= period['end']:
            continue
        matched += 1
        qty, gift = amount(row.get('qty')), amount(row.get('gift'))
        if qty is not None and gift is not None and qty >= 0 and gift >= 0:
            total += qty + gift
            known += 1
    return dict(status='observed_paid_cohort_throughput', period=period, rate_window_hours=6,
        observed_delivery_rows=matched, quantity_known_rows=known,
        observed_delivered_k=str(total) if known == matched and matched else None,
        observed_delivered_k_per_block=str(total / (hours / 6)) if known == matched and matched else None,
        promised_capacity_k_per_block=None, exact_remaining_backlog_k=None,
        outstanding_paid_orders=sum(pair[0].get('status') != '已完成' for pair in selected.values()),
        scope='same seven-day paid Coins cohort, actual delivery trade dates in period; excludes older-paid cohorts, not global capacity',
        source_generated_at=source.get('generatedAt'), source_period=source.get('period'), source_sha256=fingerprint(rows))


def _normal_order_queue(session):
    """Read only native Order status1/2, FC27 gid1322, main site; raw rows never leave memory."""
    from lxml import html as lxml_html
    normal = set()
    source_hashes = []
    counts = Counter()
    seen = set()
    for state, label in (('1', '新订单'), ('2', '交易中')):
        page = 1
        total_pages = None
        while True:
            status, text = session.get_order('/order/admin_order/index.html', status=state, page=str(page),
                start='', end='', **{'gid[]': '1322', 'source[]': 'www.mmoexp.com'})
            doc = lxml_html.fromstring(text)
            if status != 200 or doc.xpath('//input[@name="password"]'):
                raise ValueError('normal_Order_shared_session_unavailable')
            if not doc.xpath('//select[@name="gid[]"]/option[@value="1322"][@selected]'):
                raise ValueError('normal_Order_game_filter_unverified')
            tables = doc.xpath('//table[contains(@class,"table-list")]')
            if len(tables) != 1:
                raise ValueError('normal_Order_table_changed')
            page_numbers = [int(n) for link in doc.xpath('//*[contains(@class,"pagination")]//a/@href') for n in re.findall(r'[?&]page=(\d+)', link)]
            declared = max(page_numbers + [page])
            if total_pages is None:
                total_pages = declared
            if declared != total_pages:
                raise ValueError('normal_Order_pagination_changed')
            count = 0
            for tr in tables[0].xpath('.//tbody/tr'):
                cells = tr.xpath('./td')
                if tr.xpath('./td[@colspan]') or not cells:
                    continue
                if len(cells) != 13:
                    raise ValueError('normal_Order_columns_changed')
                merchant = ' '.join(cells[2].itertext())
                names = set(re.findall(r'D\d{18}', merchant))
                game = ' '.join(cells[3].itertext())
                labels = set(re.findall('新订单|交易中|问题单|再次发货|已完成|已暂停|已取消', ' '.join(cells[11].itertext())))
                identities = tr.xpath('.//input[@name="ids[]"]/@value')
                if len(names) != 1 or 'www.mmoexp.com' not in merchant or not re.search(r'FC\s*27', game, re.I) or labels != {label} or len(identities) != 1:
                    raise ValueError('normal_Order_scope_unverified')
                if identities[0] in seen:
                    raise ValueError('normal_Order_duplicate_page')
                seen.add(identities[0])
                normal.update(names)
                counts[label] += 1
                count += 1
            source_hashes.append(hashlib.sha256(text.encode()).hexdigest())
            if page == total_pages:
                break
            if not count or page >= 100:
                raise ValueError('normal_Order_incomplete_pages')
            page += 1
    return normal, dict(status='native_Order_status_1_2_verified', status_counts=dict(counts),
        scope='Order_gid1322_main_site_status1_new_and2_trading_only; excludes4_paused6_problem22_redelivery',
        source_sha256=fingerprint(source_hashes))


def active_backlog_context(session, pages):
    """User's normal-delivery queue only, across all payment dates; no problem-order investigation."""
    included = {'11': '已支付', '21': '验证·通过', '31': '发货·发货中'}
    excluded = {'12': 'Pending/未核正常交付', '22': '验证·未通过', '32': '联系买家/待客户动作',
                '33': '部分发货/非用户白名单', '34': '已交付', '4~8': '争议/调查/退款', '91': '问题订单', '11x/19x': '欺诈/删除'}
    try:
        from channel_source import apply_cost_overrides
        settings = apply_cost_overrides(dict(sources={}))
        rows = []
        for progress in (1, 2, 3):
            batch = pages(session, '/admin/order.Order/index', [('site_id', '=', '266'), ('gid', '=', '1327'),
                          ('progress', '=', str(progress))], 200)
            # Native index omits progress; verify via the shipped status enum, not a missing field.
            if any(str(r.get('site_id')) != '266' or str(r.get('gid')) != '1327' or int(r['status']) // 10 != progress for r in batch):
                raise ValueError('active_backlog_scope_invalid')
            rows.extend(batch)
        normal_order_names, order_source = _normal_order_queue(session)
    except (ImportError, OSError, ValueError, KeyError, TypeError) as error:
        return dict(status='unavailable', reason=str(error) if isinstance(error, ValueError) else type(error).__name__, gross_ordered_delivery_k=None,
                    included_statuses=included, excluded_statuses=excluded)
    counts = Counter()
    total = Decimal(0)
    by_status = {}
    for row in rows:
        if str(row.get('pay_status')) != '1' or str(row.get('status')) not in included:
            continue
        if str(row.get('order_no')) not in normal_order_names:
            counts['excluded_not_Order_normal_1_2'] += 1
            continue
        test = settings.get('testOrders', {}).get(str(row.get('order_no')))
        if test and str(test.get('gid')) == '1327' and amount(test.get('salesUsd')) == amount(row.get('amount_usd_format')):
            counts['excluded_test'] += 1
            continue
        quantity = _quantity(row)
        if quantity is None:
            counts['unmapped_Coins_title' if 'coins' in str(row.get('content')).lower() else 'non_Coins_product'] += 1
            continue
        counts['active_Coins_orders'] += 1
        delivered = Decimal(quantity['delivered_k'])
        total += delivered
        group = by_status.setdefault(str(row['status']), dict(orders=0, gross_ordered_delivery_k='0'))
        group['orders'] += 1
        group['gross_ordered_delivery_k'] = str(Decimal(group['gross_ordered_delivery_k']) + delivered)
    return dict(status='normal_delivery_gross_quantity_upper_estimate', checked_at=datetime.now(timezone.utc).isoformat(),
        gross_ordered_delivery_k=str(total), exact_remaining_backlog_k=None, counts=dict(counts), by_status=by_status,
        included_statuses=included, excluded_statuses=excluded,
        scope='all_dates_site266_FC27_paid_normal_delivery_K_coins; historical_order_gifts_included',
        order_status_intersection=order_source, pause_filter='native_Order_only1_new2_trading;4_paused6_problem_not_in_normal_queue',
        partial_delivery='not_subtracted; gross_order_K_is_initial_remaining_upper_estimate',
        source_sha256=fingerprint(dict(rows=rows, test_source=settings.get('sources', {}).get('accounting'), included=included)))


def demand_snapshot(selected, orders, storefront, provenance):
    period = provenance['period']
    start = datetime.fromisoformat(period['start'])
    end = datetime.fromisoformat(period['end']) + timedelta(days=1)
    window_hours = Decimal(str((end - start).total_seconds())) / 3600
    rate_window_hours = Decimal(6)
    if window_hours <= 0:
        raise ValueError('business_rate_window_invalid')
    blocks = window_hours / rate_window_hours
    buckets = defaultdict(dict)
    region_buckets = defaultdict(dict)
    known_platform = known_quantity = 0
    quantities = {sn: _quantity(orders[sn]) for sn in selected}
    known_quantity = sum(q is not None for q in quantities.values())
    identities, new_assignments, customer_coverage = _customer_assignments(selected, orders)
    for sn, pair in selected.items():
        order = orders[sn]
        platform = _platform(order)
        if not platform:
            continue
        known_platform += 1
        if str(order.get('is_region_price')) == '1':
            region_buckets[(str(order.get('region_price_lang_region_id')), platform)][sn] = pair
        else:
            buckets['pc' if platform == 'PC' else 'console'][sn] = pair
    groups = {}
    for group, entries in buckets.items():
        metrics = summarize(entries)
        platform = 'PC' if group == 'pc' else 'PS'
        complete_quantity = all(quantities[sn] is not None for sn in entries)
        quantity_totals = {key: sum((Decimal(quantities[sn][key]) for sn in entries if quantities[sn] is not None), Decimal(0)) for key in ('purchase_k', 'bonus_k', 'delivered_k')}
        groups[group] = dict(observed_orders_per_block=str(Decimal(len(entries)) / blocks),
            orders_per_block=str(Decimal(len(entries)) / blocks) if complete_quantity else None,
            rate_window_hours=6, observed_window_hours=str(window_hours),
            reference_regular_usd=str(storefront['rows'][platform]['package_usd']),
            observed_net_usd_per_order=str(Decimal(metrics['net_paid_usd']) / len(entries)) if metrics['net_paid_usd'] is not None else None,
            delivered_k_per_order=str(quantity_totals['delivered_k'] / len(entries)) if complete_quantity else None,
            target_revenue_per_order_usd=str(Decimal(metrics['net_paid_usd']) / len(entries)) if complete_quantity and metrics['net_paid_usd'] is not None else None,
            quantity_totals={k: str(v) for k, v in quantity_totals.items()}, quantity_known_orders=sum(quantities[sn] is not None for sn in entries),
            new_customer_ratio=str(Decimal(sum(sn in entries for sn in new_assignments.values())) / len(entries)) if customer_coverage['status'] == 'complete' else None,
            new_customer_order_ratio=metrics['new_customer_order_ratio'], metrics=metrics,
            new_customer_ratio_basis='unique_backend_flagged_new_email_first_order_per_window',
            forecast_status='observed_rate_AOV_quantity_with_central_elasticity_prior' if complete_quantity else 'quantity_projection_not_available')
    observed_segments = []
    for (region, platform), entries in sorted(region_buckets.items()):
        metrics = summarize(entries)
        complete_quantity = all(quantities[sn] is not None for sn in entries)
        delivered = sum((Decimal(quantities[sn]['delivered_k']) for sn in entries if quantities[sn]), Decimal(0))
        factors = {str(orders[sn].get('region_price_factor')) for sn in entries}
        net = amount(metrics['net_paid_usd'])
        discount = amount(metrics.get('actual_discount_usd'))
        observed_segments.append(dict(region_id=int(region), platform=platform,
            observed_orders_per_block=str(Decimal(len(entries)) / blocks),
            orders_per_block=str(Decimal(len(entries)) / blocks) if complete_quantity else None,
            target_revenue_per_order_usd=str(net / len(entries)) if net is not None else None,
            delivered_k_per_order=str(delivered / len(entries)) if complete_quantity else None,
            retained_ratio=str(net / (net + discount)) if net is not None and discount is not None and net + discount > 0 else None,
            reference_coefficient=next(iter(factors)) if len(factors) == 1 else None,
            reference_basis='current_regional_public_100K_reference_must_be_attached_by_sources; historical_factor_for_crosscheck_only',
            rate_window_hours=6, observed_window_hours=str(window_hours),
            new_customer_ratio=str(Decimal(sum(sn in entries for sn in new_assignments.values())) / len(entries)) if customer_coverage['status'] == 'complete' else None,
            metrics=metrics))
    return dict(status='observed_rate_quantity_partial_platform' if known_platform < len(selected) else 'observed_rate_quantity_available', version='fc27-real-business-source-v1',
        rate_window_hours=6, observed_window_hours=str(window_hours), period=period,
        groups=groups, segments=[], observed_segments=observed_segments, summary=dict(summarize(selected), **customer_coverage),
        coverage=dict(eligible_orders=len(selected), platform_known_orders=known_platform, quantity_known_orders=known_quantity,
                      advertising='not_loaded_not_assumed_zero', customer_identity=customer_coverage),
        source_sha256=fingerprint(dict(provenance=provenance, quantities=quantities, customer_source=customer_coverage['source_sha256'])), missing_context=(['verified_historical_delivery_quantity'] if known_quantity < len(selected) else []) + ['causal_elasticity', 'same_scope_advertising_attribution'],
        scope='groups_exclude_observed_region_orders; observed_segments_are_disjoint; no platform apportionment',
        allocation=dict(global_group_orders=sum(len(entries) for entries in buckets.values()),
            regional_segment_orders=sum(len(entries) for entries in region_buckets.values()),
            platform_unallocated_orders=len(selected) - known_platform),
        forecast_basis='actual_paid_order_rate_and_mixed_order_AOV_plus_delivery_K; current_100K_price_anchor; elasticity_prior_not_causal_fit')


def historical_mix(selected, provenance, *, history_window_contract=None):
    pairs = [(amount(r.get('salesUsd')), amount(es.get('discount_usd'))) for r, es in selected.values()]
    known = [(n, d) for n, d in pairs if n is not None and d is not None and n >= 0 and d >= 0]
    net, discount = (sum((p[i] for p in known), Decimal(0)) for i in (0, 1))
    gross = net + discount
    body = dict(status='available' if provenance.get('status') == 'complete' and len(known) == len(selected) else 'partial',
        observed_orders=len(known), eligible_orders=len(selected), net_order_usd=str(net), actual_discount_usd=str(discount),
        undiscounted_order_usd=str(gross), retained_ratio=str(net / gross) if gross else None,
        period=provenance['period'], source_times=dict(orders=provenance.get('source_generated_at')),
        source_coverage=dict(ES_complete=provenance.get('ES_complete'), missing_product_identity=provenance.get('missing_product_identity')),
        population='identified main-site Coins paid nonrefund nonfraud nontest orders; all platforms combined',
        formula='sum(Admin order USD) / sum(Admin order USD + matched ES actual discount USD)',
        canonical_archive_sha256=provenance.get('canonical_archive_sha256'), ES_source_sha256=provenance.get('ES_source_sha256'))
    if history_window_contract is not None:body['history_window_contract']=history_window_contract
    return dict(body, sha256=fingerprint(body))


def historical_attachment(selected, orders, logs, provenance, observed_at):
    """Private snapshot attachment only. Never print or expose these anonymous order rows."""
    from .financial import instant
    rows, counts, gaps = [], Counter(), Counter()
    totals = defaultdict(Decimal)
    for sn, (archived, es) in selected.items():
        order = orders.get(sn) or {}
        coverage = []
        quantity = _quantity(order)
        platform = _platform(order)
        before, paid = amount(order.get('before_discount')), amount(order.get('amount_usd_format'))
        if paid != amount(archived.get('salesUsd')):
            coverage.append('Admin_archive_paid_amount_mismatch')
            paid = None
        try:
            paid_at = instant(archived['paidAt']).isoformat()
        except (KeyError, ValueError):
            paid_at = None
            coverage.append('historical_paid_time_missing')
        try:
            created_at = _native_created_at(order).isoformat()
        except ValueError:
            created_at = None
            coverage.append('native_creation_epoch_display_missing_or_mismatch')
        regional = str(order.get('is_region_price')) == '1'
        factor = amount(order.get('region_price_factor')) if regional else Decimal(1)
        region = amount(order.get('region_price_lang_region_id')) if regional else Decimal(0)
        region_id = int(region) if region is not None and region >= 0 and region == int(region) else None
        if regional and (not region_id or factor is None or factor <= 0):
            coverage.append('historical_region_identity_or_factor_missing')
            region_id = None
        revenue_cny = amount(order.get('amount_rmb_format'))
        cost_cny = amount(archived.get('costCny'))
        delivery_rows = amount(archived.get('deliveryRows')) or Decimal(0)
        actual_cost = (archived.get('status') == '已完成' and cost_cny is not None and cost_cny >= 0
                       and (delivery_rows > 0 or archived.get('zeroCost') is True))
        if not actual_cost:
            cost_cny = None
            coverage.append('historical_actual_Order_cost_CNY_missing_or_not_completed')
        if revenue_cny is None or revenue_cny < 0:
            revenue_cny = None
            coverage.append('current_Admin_CNY_revenue_snapshot_missing')
        # These are actual historical deductions, never invented fixed-coupon terms.
        used = [logs.get(str(c['id'])) for c in archived.get('coupons', [])]
        coupon_values = [amount(log.get('discount_amount')) if log else None for log in used]
        coupon = sum(coupon_values, Decimal(0)) if all(v is not None and v >= 0 for v in coupon_values) else None
        percent, points, discount = amount(order.get('discount')), amount(order.get('points')), amount(es.get('discount_usd'))
        no_promotion = percent == 100 and points == 0 and coupon == 0 and discount == 0
        path = dict(kind='none') if no_promotion else None
        if path is None:
            coverage.append('historical_counterfactual_promotion_terms_version_missing')
        if not quantity:coverage.append('historical_native_quantity_missing')
        if not platform:coverage.append('historical_platform_identity_missing')
        if before is None or before < 0:coverage.append('historical_regional_regular_USD_missing')
        coverage.extend(('historical_USD_CNY_FX_missing_cost_USD_unknown','historical_price_version_and_window_missing'))
        original = dict(regular_usd=str(before) if before is not None else None,
            retained_percent=str(percent) if percent is not None else None,
            actual_coupon_discount_usd=str(coupon) if coupon is not None else None,
            actual_points_credit_usd=str(points / POINTS_PER_USD) if points is not None else None,
            actual_ES_discount_usd=str(discount) if discount is not None else None,
            basis='observed_original_amount_deductions_only; not_counterfactual_coupon_or_points_terms')
        row = dict(order_key=hashlib.sha256(('site266:FC27:Coins:' + sn).encode()).hexdigest(),
            paid_at=paid_at, created_at=created_at, available_at=observed_at.isoformat(),
            base_k=quantity['purchase_k'] if quantity else None, bonus_k=quantity['bonus_k'] if quantity else None,
            delivered_k=quantity['delivered_k'] if quantity else None, platform=platform, region_id=region_id,
            original_region_factor=str(factor) if factor is not None else None,
            regular_usd=str(before) if before is not None else None, paid_usd=str(paid) if paid is not None else None,
            regular_price_basis='actual_Admin_before_discount_regional_regular_USD; region_already_included',
            revenue_cny=str(revenue_cny) if revenue_cny is not None else None,
            cost_cny=str(cost_cny) if cost_cny is not None else None,
            actual_cny_gross=str(revenue_cny - cost_cny) if revenue_cny is not None and cost_cny is not None else None,
            cost_usd=None, historical_fx=None,
            cny_basis='current_Admin_amount_rmb_format_snapshot_minus_same_order_Order_historical_actual_cost_CNY; not_USD_settlement',
            promotion_path=path, actual_promotion_reconstruction=original,
            price_version=None, price_window_id=None, package_retained_ratio=None,
            refund_usd='0', paid_is_net_of_refunds=False, status=archived.get('status'),
            coverage=coverage, source_sha256=fingerprint(dict(canonical=provenance['canonical_archive_sha256'],
                ES=provenance['ES_source_sha256'], original=original, paid_usd=str(paid), revenue_cny=str(revenue_cny),
                cost_cny=str(cost_cny), quantity=quantity, platform=platform, region_id=region_id)))
        rows.append(row)
        counts['orders'] += 1
        for field in ('paid_at','created_at','base_k','platform','regular_usd','paid_usd','revenue_cny','cost_cny','actual_cny_gross','promotion_path'):
            counts[field + '_known'] += row[field] is not None
        gaps.update(coverage)
        if paid is not None:totals['net_paid_usd'] += paid
        if revenue_cny is not None and cost_cny is not None:
            totals['covered_Admin_snapshot_revenue_cny'] += revenue_cny
            totals['covered_historical_Order_cost_cny'] += cost_cny
            totals['covered_actual_cny_gross'] += revenue_cny - cost_cny
    metadata = dict(status='partial', period=provenance['period'], coverage=dict(counts), gaps=dict(gaps),
        totals={key:str(value) for key,value in totals.items()}, available_at=observed_at.isoformat(),
        availability_basis='these_Admin_and_cost_facts_verified_at_current_collection; never_backdated_to_payment_time',
        longer_window_coverage='only_this_exact_period; 14d_28d_month_require_additional_original_archives_and_traces',
        original_mix_sha256=historical_mix(selected, provenance)['sha256'],
        canonical_archive_sha256=provenance['canonical_archive_sha256'], ES_source_sha256=provenance['ES_source_sha256'],
        privacy='anonymous_rows_for_private_snapshot_only; no_customer_identifiers_or_raw_order_numbers')
    metadata['source_sha256'] = fingerprint(dict(rows=rows, provenance=provenance))
    return rows, metadata


def _today_summary(session, pages, now):
    from coins_evidence import CoinsEvidence, es_metadata, GOLD
    from channel_source import apply_cost_overrides
    today = now.astimezone(TZ).date().isoformat()
    period = dict(start=today, end=today)
    reader = CoinsEvidence()
    meta, coverage = es_metadata(today, today, reader.archive)
    if not meta:
        return dict(status='unavailable', period=period, net_paid_usd=None, reason='today_exact_Coins_identity_archive_missing',
                    source_sha256=coverage.get('source_sha256'))
    rows = pages(session, '/admin/order.Order/index', [('site_id', '=', '266'), ('gid', '=', '1327'),
                 ('paytime', 'RANGE', today + ' 00:00:00,' + now.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S'))], 100)
    settings = apply_cost_overrides(dict(sources={}))
    selected, missing = {}, 0
    for row in rows:
        if str(row.get('site_id')) != '266' or str(row.get('gid')) != '1327':
            raise ValueError('today_native_scope_invalid')
        if str(row.get('pay_status')) != '1' or str(row.get('status_format') or '').startswith('已退款') or str(row.get('status_format') or '').replace(' ', '').replace('·', '') == '验证未通过':
            continue
        sn = str(row.get('order_no'))
        test = settings.get('testOrders', {}).get(sn)
        if test and str(test.get('gid')) == '1327' and amount(test.get('salesUsd')) == amount(row.get('amount_usd_format')):
            continue
        info = meta.get(hashlib.sha256(sn.encode()).hexdigest())
        if not info:
            missing += 1
            continue
        if info['product'] == GOLD:
            selected[sn] = (dict(salesUsd=row.get('amount_usd_format'), status=row.get('status_format')), info)
    result = summarize(selected)
    complete = coverage['complete'] and missing == 0
    return dict(status='complete' if complete else 'partial', period=period,
        net_paid_usd=result['net_paid_usd'] if complete else None, known_net_paid_usd=result['net_paid_usd'],
        eligible_known_orders=len(selected), missing_product_identity=missing,
        source_sha256=fingerprint(dict(Admin_rows=rows, ES_source_sha256=coverage['source_sha256'])))


def _native_created_at(order):
    """Require independent native epoch/display agreement; payment time is never creation time."""
    epoch = amount(order.get('timestamp'))
    display = re.sub(r'<[^>]*>', '', str(order.get('timestamp_format') or '')).strip()
    if epoch is None or epoch < 1000000000 or epoch > 100000000000:
        raise ValueError('native_created_epoch_missing')
    created = datetime.fromtimestamp(float(epoch), timezone.utc)
    formatted = None
    for pattern in ('%Y-%m-%d %H:%M:%S', '%y-%m-%d %H:%M:%S'):
        try:
            formatted = datetime.strptime(display, pattern).replace(tzinfo=TZ)
            break
        except ValueError:
            pass
    if formatted is None or abs((created - formatted).total_seconds()) > 1:
        raise ValueError('native_created_epoch_display_mismatch')
    return created


def _window_instant(value):
    instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if instant.tzinfo is None:
        raise ValueError('price_window_timezone_missing')
    return instant


def _window_group(window, order, platform):
    group = 'pc' if platform == 'PC' else 'console'
    region = str(order.get('region_price_lang_region_id')) if str(order.get('is_region_price')) == '1' else None
    mutable = window.get('mutable_resources') or []
    key = region + ':' + platform if region else group
    if platform not in window.get('platforms', []) or not ('base:' + group in mutable or region and 'region:' + key in mutable):
        return None
    return key


def _window_end(window, group, windows, now):
    base_group = group if group in ('console', 'pc') else 'pc' if group.endswith(':PC') else 'console'
    dependencies = {'base:' + base_group}
    if ':' in group:
        dependencies.add('region:' + group)
    ends = [now]
    resource_closures = window.get('resource_closed_at')
    if resource_closures is not None:
        ends += [_window_instant(value) for key, value in resource_closures.items() if key in dependencies and value]
    elif window.get('closed_at'):
        ends.append(_window_instant(window['closed_at']))
    # A later price change affects the group's effective price even when it owns another dependency.
    opened = _window_instant(window['opened_at'])
    ends += [_window_instant(other['opened_at']) for other in windows
             if _window_instant(other['opened_at']) > opened and dependencies.intersection(other.get('mutable_resources', []))]
    return min(ends)


def _window_regular(window, action, order, platform, quantity):
    from .engine import render
    group = 'pc' if platform == 'PC' else 'console'
    region = str(order.get('region_price_lang_region_id')) if str(order.get('is_region_price')) == '1' else None
    coefficient = action.get('region_coefficients', {}).get(region + ':' + platform) if region else '1'
    if coefficient is None:
        raise ValueError('window_region_price_trace_missing')
    tiers = window['catalog'][platform]['tiers']
    total = Decimal(0)
    for line in quantity['lines']:
        count = Decimal(line['multiplier'])
        purchase, bonus = Decimal(line['purchase_k']) / count, Decimal(line['bonus_k']) / count
        matches = [tier for tier in tiers if amount(tier.get('base_k')) == purchase and amount(tier.get('bonus_k')) == bonus]
        if len(matches) != 1:
            # Current shipped blur() uses the next tier's rounded derived unit, max with regional unit.
            # Only the verified all-100%-retained catalog is reconstructed here; other terms stay explicit gaps.
            ordered = sorted(tiers, key=lambda tier: Decimal(tier['base_k']))
            if bonus != 0 or purchase != purchase.to_integral_value() or purchase < Decimal(window['catalog'][platform].get('min_custom_k', ordered[0]['base_k'])) or purchase > Decimal(ordered[-1]['base_k']) * 100 or any(Decimal(t['base_k']) == purchase for t in ordered) or any(Decimal(t['retained_ratio']) != 1 for t in ordered):
                raise ValueError('native_custom_or_historical_tier_price_trace_pending')
            next_tier = next((tier for tier in ordered if Decimal(tier['base_k']) > purchase), ordered[-1])
            unit = Decimal(action['base_prices'][group]) / 100
            regional_unit = unit * Decimal(coefficient)
            derived = (Decimal(render(unit, next_tier, coefficient)['exact_regular_usd']) / Decimal(next_tier['base_k'])).quantize(Decimal('.00001'), rounding=ROUND_HALF_UP)
            total += (max(regional_unit, derived) * purchase).quantize(Decimal('.01'), rounding=ROUND_HALF_UP) * count
        else:
            total += Decimal(render(Decimal(action['base_prices'][group]) / 100, matches[0], coefficient)['regular_usd']) * count
    return total


def bind_price_windows(orders, windows, now, *, archived=None, coupon_logs=None, query_complete=True):
    """Server-local anonymous settlement records and window aggregates, never customer identities."""
    from .engine import replay_promotion
    archived, coupon_logs = archived or {}, coupon_logs or {}
    orders_by_id = {str(o['order_no']): o for o in orders if o.get('order_no')}
    bound_customers = {}
    valid = [w for w in windows if w.get('origin') == 'confirmed_public_price_window' and w.get('mode') == 'production']
    coverage = Counter()
    failures = Counter()
    blocked_windows = set()
    unscoped_time_gaps = False
    blocked_groups = set()
    gap_events = []
    counts = Counter()
    settlements = []
    actual_outcomes = []
    source = fingerprint(dict(orders=orders, windows=valid, coupon_logs=coupon_logs, as_of=now.isoformat()))
    for order in orders:
        quantity = _quantity(order)
        if quantity is None:
            if 'coins' not in str(order.get('content') or '').lower():
                continue
            failures['native_Coins_quantity_missing'] += 1
        try:
            created = _native_created_at(order)
        except ValueError as error:
            failures[str(error)] += 1
            unscoped_time_gaps = True
            blocked_windows.update(w['operation_id'] for w in valid)
            continue
        active = [w for w in valid if _window_instant(w['opened_at']) <= created < now
                  and (not w.get('closed_at') or created < _window_instant(w['closed_at']))]
        if not active:
            coverage['created_outside_price_windows'] += 1
            continue
        gap_amount = amount(order.get('amount_usd_format'))
        gap_usd = str(gap_amount) if gap_amount is not None and gap_amount >= 0 else None
        platform = _platform(order)
        matches = []
        for window in active:
            if not platform:
                blocked_windows.add(window['operation_id'])
                gap_events.append(dict(price_window_id=window['operation_id'], group=None, occurred_at=created.isoformat(), reason='unknown_platform', amount_usd=gap_usd))
                continue
            group = _window_group(window, order, platform)
            if group is None or created >= _window_end(window, group, valid, now):
                continue
            if quantity is None:
                blocked_groups.add((window['operation_id'], group))
                gap_events.append(dict(price_window_id=window['operation_id'], group=group, occurred_at=created.isoformat(), reason='unknown_quantity', amount_usd=gap_usd))
                continue
            try:
                regular = _window_regular(window, window['action'], order, platform, quantity)
                if abs(regular - amount(order.get('before_discount'))) <= Decimal('.01'):
                    matches.append((window, group, regular))
                else:
                    failures['actual_regular_price_not_window_price'] += 1
                    blocked_groups.add((window['operation_id'],group))
                    gap_events.append(dict(price_window_id=window['operation_id'], group=group, occurred_at=created.isoformat(), reason='price_mismatch', amount_usd=gap_usd))
            except (ValueError, KeyError, TypeError, InvalidOperation) as error:
                failures[str(error) if isinstance(error, ValueError) else type(error).__name__] += 1
                blocked_groups.add((window['operation_id'],group))
                gap_events.append(dict(price_window_id=window['operation_id'], group=group, occurred_at=created.isoformat(), reason='price_trace_unknown', amount_usd=gap_usd))
        if quantity is None:
            continue
        if len(matches) != 1:
            coverage['unbound_or_ambiguous_orders'] += 1
            blocked_groups.update((w['operation_id'],group) for w,group,_ in matches)
            gap_events.extend(dict(price_window_id=w['operation_id'], group=group, occurred_at=created.isoformat(), reason='ambiguous_binding', amount_usd=gap_usd) for w,group,_ in matches)
            continue
        window, group, regular = matches[0]
        if str(order.get('pay_status')) != '1' or str(order.get('status_format') or '').startswith('已退款'):
            failures['refund_or_unpaid_requires_native_USD_reconciliation'] += 1
            gap_events.append(dict(price_window_id=window['operation_id'], group=group, occurred_at=created.isoformat(), reason='refund_or_unpaid', amount_usd=gap_usd))
            continue
        coverage['created_and_actual_price_uniquely_bound'] += 1
        counts[(window['operation_id'], group)] += 1
        sn = str(order['order_no'])
        net = amount(order.get('amount_usd_format'))
        old = (archived.get(sn) or [None])[0]
        contribution = None
        if old and net is not None:
            cost, cny = amount(old.get('costCny')), amount(old.get('saleCny'))
            # Order shipping CNY margin is authoritative; Admin display CNY can use another FX rounding.
            if old.get('status') == '已完成' and cost is not None and cost >= 0 and cny is not None and cny > 0 and amount(old.get('salesUsd')) == net:
                contribution = str((cny - cost) * net / cny)
        actual_outcomes.append(dict(order_key=hashlib.sha256(('FC27:266:' + sn).encode()).hexdigest(),
            price_window_id=window['operation_id'], group=group, platform=platform, occurred_at=created.isoformat(),
            actual_net_usd=str(net) if net is not None else None, actual_contribution_usd=contribution,
            coupon_present=bool(coupon_logs.get(sn)), cost_status='same_order_confirmed' if contribution is not None else 'pending',
            cost_basis='same_order_Order_shipping_CNY_margin_at_actual_USD_receipt' if contribution is not None else None))
        bound_customers[sn]=len(actual_outcomes)-1
        if coupon_logs.get(sn):
            failures['budget_reference_historical_coupon_terms_pending'] += 1
            continue
        percent, points, net = amount(order.get('discount')), amount(order.get('points')), amount(order.get('amount_usd_format'))
        if percent is None or points is None or net is None or not 0 < percent <= 100 or points < 0:
            failures['budget_actual_promotion_fields_missing'] += 1
            continue
        if points and (percent != 100 or points / POINTS_PER_USD > regular * POINTS_CAP + Decimal('.02')):
            failures['budget_points_exclusivity_or_cap'] += 1
            continue
        path = dict(kind='points', credit_usd=str(points / POINTS_PER_USD), cap_ratio=str(POINTS_CAP)) if points else dict(kind='ratio', retained_ratio=str(percent / 100))
        actual_cash = replay_promotion(regular, path)
        if abs(actual_cash - net) > Decimal('.01'):
            failures['budget_reference_cash_residual_unresolved'] += 1
            continue
        try:
            reference_regular = _window_regular(window, window['budget_reference'], order, platform, quantity)
        except (ValueError, KeyError, TypeError, InvalidOperation):
            failures['budget_reference_price_trace_missing'] += 1
            continue
        budget_source = fingerprint(dict(
            order={key: order.get(key) for key in ('order_no', 'timestamp', 'timestamp_format', 'before_discount', 'discount', 'points', 'amount_usd_format', 'amount_rmb_format', 'status', 'pay_status', 'is_region_price', 'region_price_factor', 'region_price_lang_region_id', 'content')},
            accounting={key: old.get(key) for key in ('costCny', 'saleCny', 'salesUsd', 'status')} if old else None,
            window={key: window.get(key) for key in ('operation_id', 'action', 'budget_reference', 'catalog')}))
        settlements.append(dict(order_key=hashlib.sha256(('FC27:266:' + sn).encode()).hexdigest(),
            origin='actual_bound_order', mode='production', operation_id=window['operation_id'], price_window_id=window['operation_id'],
            group='pc' if platform == 'PC' else 'console', price_group=group, platform=platform,
            occurred_at=created.isoformat(), reference_net_usd=str(replay_promotion(reference_regular, path)),
            actual_net_usd=str(net), actual_contribution_usd=contribution, source_sha256=budget_source,
            refund=False, status=str(order.get('status_format') or ''),
            coverage=dict(created_epoch_display_verified=True, unique_regular_price_window=True,
                          cost='same_order_Order_shipping_CNY_margin_at_actual_USD_receipt' if contribution is not None else 'pending; reservation_retained',
                          reference='same_realized_code_or_points_path; cash_residual_within_one_cent')))
    customer_rows = {sn: archived[sn] for sn in bound_customers if archived.get(sn)}
    identities, new_assignments, customer_coverage = _customer_assignments(customer_rows, orders_by_id)
    if len(customer_rows) != len(bound_customers):
        customer_coverage['status'] = 'partial'
        customer_coverage['missing_archive_orders'] = len(bound_customers) - len(customer_rows)
    for sn,index in bound_customers.items():
        old=(archived.get(sn) or [None])[0]
        actual_outcomes[index].update(customer_key=identities.get(sn),
            new_customer=(new_assignments.get(identities[sn]) == sn) if sn in identities and old and old.get('customerType') in ('新客','老客') else None)
    training = []
    for window in valid:
        operation = window['operation_id']
        if not query_complete or operation in blocked_windows:
            continue
        if window.get('assignment_probability') is None:
            continue
        groups = set()
        for resource in window.get('mutable_resources', []):
            if resource.startswith('base:'):
                groups.add(resource.split(':', 1)[1])
            elif resource.startswith('region:'):
                groups.add(resource.split(':', 1)[1])
        for key in window['action'].get('region_coefficients', {}):
            platform = key.split(':')[-1]
            base_group = 'pc' if platform == 'PC' else 'console'
            regional_identity=(Decimal(window['action']['region_coefficients'][key])!=1 or
                               'region:'+key in window.get('mutable_resources',[]) or counts[(operation,key)]>0)
            if regional_identity and platform in window.get('platforms', []) and 'base:' + base_group in window.get('mutable_resources', []):
                groups.add(key)
        for group in sorted(groups):
            if (operation,group) in blocked_groups:
                continue
            end = _window_end(window, group, valid, now)
            hours = Decimal(str((end - _window_instant(window['opened_at'])).total_seconds())) / 3600
            if hours <= 0:
                continue
            base_group = group if group in ('console', 'pc') else 'pc' if group.endswith(':PC') else 'console'
            price = Decimal(window['action']['base_prices'][base_group])
            if ':' in group:
                price *= Decimal(window['action']['region_coefficients'][group])
            training.append(dict(mode='production', origin='actual_order_and_price_window', price_window_id=operation,
                price_group=group, offset_kind='effective_hours', exposure=str(hours), paid_orders=counts[(operation, group)],
                effective_price_usd=str(price), assignment_probability=window['assignment_probability'],
                randomization_verified=window.get('randomization_verified') is True,
                inference='randomized' if window.get('randomization_verified') is True else 'observational; not_causal',
                as_of=now.isoformat(), source_sha256=source))
    return dict(budget_settlements=settlements, actual_outcomes=actual_outcomes, training_observations=training,
        learning_coverage=dict(status='available' if training else 'price_binding_coverage_pending',
            price_windows=len(valid), counts=dict(coverage), gaps=dict(failures), source_sha256=source,
            observed_at=now.isoformat(),blocked_price_groups=[dict(price_window_id=op,price_group=group) for op,group in sorted(blocked_groups)],
            gap_events=gap_events, unscoped_time_gaps=unscoped_time_gaps,
            query_complete=query_complete, customer_coverage=customer_coverage, binding='native_creation_epoch_and_display plus actual_regular_price; never payment_time_assignment',
            source_rows_returned=False, customer_identifiers_returned=False))


def online_window_context(session, pages, windows, now, archived):
    if not windows:
        return dict(budget_settlements=[], training_observations=[], learning_coverage=dict(status='await_first_confirmed_exposure', price_windows=0))
    try:
        valid = [w for w in windows if w.get('origin') == 'confirmed_public_price_window' and w.get('mode') == 'production']
        if not valid:
            raise ValueError('no_confirmed_public_price_window')
        start = min(_window_instant(w['opened_at']) for w in valid).astimezone(TZ)
        # Payment time only bounds candidate retrieval; actual assignment below uses independent creation time.
        from channel_source import windows as range_windows
        begin, end = start.strftime('%Y-%m-%d %H:%M:%S'), now.astimezone(TZ).strftime('%Y-%m-%d %H:%M:%S')
        rows, seen = [], {}
        for lower, upper in range_windows(dict(start=begin[:10], end=end[:10])):
            lower, upper = max(lower, begin), min(upper, end)
            batch = pages(session, '/admin/order.Order/index', [('site_id', '=', '266'), ('gid', '=', '1327'),
                          ('paytime', 'RANGE', lower + ',' + upper)], 100)
            for row in batch:
                identity = str(row.get('id') or '')
                if not identity or not lower <= str(row.get('paytime')) <= upper:
                    raise ValueError('window_candidate_range_invalid')
                if identity in seen:
                    if seen[identity] != row: raise ValueError('window_candidate_conflict')
                    continue
                seen[identity] = row
                rows.append(row)
        if any(str(r.get('site_id')) != '266' or str(r.get('gid')) != '1327' for r in rows):
            raise ValueError('window_candidate_scope_invalid')
        from channel_source import apply_cost_overrides
        settings = apply_cost_overrides(dict(sources={}))
        filtered = []
        for row in rows:
            test = settings.get('testOrders', {}).get(str(row.get('order_no')))
            if test and str(test.get('gid')) == '1327' and amount(test.get('salesUsd')) == amount(row.get('amount_usd_format')):
                continue
            if str(row.get('status')) in ('22', '111', '112', '191'):
                continue
            filtered.append(row)
        rows = filtered
        logs = defaultdict(list)
        names = sorted(str(r['order_no']) for r in rows if _quantity(r))
        for offset in range(0, len(names), 100):
            group = names[offset:offset + 100]
            for log in pages(session, '/admin/user.MemberCouponLog/index', [('site_id', '=', '266'), ('order_no', 'IN', ','.join(group))]):
                if str(log.get('order_no')) not in group or str(log.get('site_id')) != '266':
                    raise ValueError('window_coupon_log_scope_invalid')
                logs[str(log['order_no'])].append(log)
        return bind_price_windows(rows, valid, now, archived=archived, coupon_logs=logs)
    except (ValueError, OSError, KeyError, TypeError) as error:
        return dict(budget_settlements=[], training_observations=[], learning_coverage=dict(status='price_binding_coverage_pending',
            price_windows=len(windows), reason=str(error) if isinstance(error, ValueError) else type(error).__name__, query_complete=False))


def collect(session, pages, storefront, products, price_windows=None):
    now = datetime.now(timezone.utc)
    today = now.astimezone(TZ).date()
    last = today - timedelta(days=1)
    period = dict(start=(today - timedelta(days=7)).isoformat(), end=last.isoformat())
    selected, provenance = _period_population(period)
    if selected is None or provenance.get('status') != 'complete' or not selected:
        raise ValueError('pricing_v3_business_history_source_incomplete')
    orders, logs, templates = _live_traces(session, pages, period, selected)
    from pricing_sources import active
    templates = {key: dict(value, _current_active=active(value, now, coupon=True)) for key, value in templates.items()}
    replay = build_replay(selected, orders, logs, templates, provenance)
    mix = historical_mix(selected, provenance)
    replay['original_mix_sha256'] = mix['sha256']
    model = demand_snapshot(selected, orders, storefront, replay['provenance'])
    model['advertising_context'] = marketing_context(period)
    model['fulfillment_context'] = fulfillment_context(selected, orders, provenance)
    model['coverage']['advertising'] = model['advertising_context']['status']
    backlog = active_backlog_context(session, pages)
    fulfillment_estimates = dict(estimated=True, rate_window_hours=6,
        capacity_k_per_block=model['fulfillment_context'].get('observed_delivered_k_per_block'),
        backlog_k=backlog.get('gross_ordered_delivery_k'),
        capacity_basis='initial_capacity_estimate_from_observed_recent_paid_cohort_throughput; not_promised_capacity',
        backlog_basis='initial_backlog_upper_estimate_from_all_dates_normal_delivery_gross_order_K; partial_delivery_unknown',
        observed_capacity_source=model['fulfillment_context'], current_backlog_source=backlog)
    month_period = dict(start=today.replace(day=1).isoformat(), end=last.isoformat())
    month_rows, month_source = _period_population(month_period)
    closed = summarize(month_rows) if month_rows is not None else None
    try:
        current_day = _today_summary(session, pages, now)
    except (ValueError, OSError) as error:
        current_day = dict(status='unavailable', net_paid_usd=None, reason=str(error) if isinstance(error, ValueError) else type(error).__name__)
    closed_net = closed['net_paid_usd'] if closed and month_source.get('status') == 'complete' else None
    full_mtd = closed_net is not None and current_day.get('status') == 'complete'
    known_closed = closed['net_paid_usd'] if closed else None
    partial_closed = known_closed is not None and month_source.get('ES_complete') is True
    mtd = str(Decimal(closed_net) + Decimal(current_day['net_paid_usd'])) if full_mtd else known_closed
    upper = str(Decimal(known_closed) + Decimal(month_source.get('unclassified_paid_FC_usd', '0'))) if partial_closed else None
    monthly = dict(amount=None, mtd=mtd, mtd_exact=mtd if full_mtd or closed_net is not None else None,
        mtd_lower_bound=mtd, mtd_upper_bound=mtd if full_mtd else upper,
        target_basis='net_paid_USD', target_scope='site266_FC27_Coins',
        status='target_not_configured', mtd_status='complete_through_current_read' if full_mtd else 'closed_days_only' if closed_net is not None else 'partial_closed_day_interval' if partial_closed else 'unavailable',
        through_date=today.isoformat() if full_mtd else last.isoformat() if partial_closed else None,
        period=dict(start=month_period['start'], end=today.isoformat() if full_mtd else month_period['end']),
        closed_day_metrics=closed, today=current_day, coverage=month_source,
        known_closed_day_net_usd=closed['net_paid_usd'] if closed else None,
        source_sha256=fingerprint(dict(closed=month_source, today=current_day)))
    online = online_window_context(session, pages, price_windows, now, selected)
    historical, historical_coverage = historical_attachment(selected, orders, logs, provenance, datetime.now(timezone.utc))
    return dict(monthly_target=monthly, demand_model=model, history_replay=replay, historical_discount_mix=mix,
        historical_orders=historical, historical_orders_coverage=historical_coverage,
        fulfillment_estimates=fulfillment_estimates, **online)


# Append-only candidate adapters. Existing collect() remains unchanged until owner switches caller.

def history_ES_blocker(period, *, ES_root=None, receipt_root=None):
    """Observe existing export evidence before collection; never requests an export."""
    from pathlib import Path
    ES_root=Path(ES_root or '/var/lib/fc27-es-exports')
    receipt_root=Path(receipt_root or '/var/lib/fs-hermes-fc/fs/es-structures')
    if not receipt_root.is_dir():return None
    manifests=[]
    for path in ES_root.glob('*.json'):
        if path.stat().st_size>2*1024*1024:continue
        value=json.loads(path.read_text());query=value.get('query') if isinstance(value,dict) else None
        if isinstance(query,dict) and query.get('start') and query.get('end'):manifests.append(query)
    missing=[];day=datetime.fromisoformat(period['start']).date();stop=datetime.fromisoformat(period['end']).date()
    while day<=stop:
        text=day.isoformat()
        if not any(q['start']<=text<=q['end'] for q in manifests):missing.append(text)
        day+=timedelta(days=1)
    if not missing:return None
    # Any original in-flight/unknown window is reconciled separately, never called a permission refusal.
    for path in receipt_root.glob('*.attempt'):
        value=json.loads(path.read_text());query=value.get('query') or {}
        if any(query.get('start','')<=day<=query.get('end','') for day in missing):
            return dict(reason='es_export_previous_attempt_unknown_requires_reconcile',period=period,missing_days=missing,original_attempt=str(path))
    import sys
    sys.path.insert(0,'/opt/fs-hermes-fc')
    from es_order_structure import checked_query,RULE_VERSION
    for day in missing:
        for profile in ('ALL','FC27'):
            query=checked_query(dict(profile=profile,start=day,end=day))
            key=hashlib.sha256(json.dumps(dict(query=query,rule=RULE_VERSION),sort_keys=True).encode()).hexdigest()
            path=receipt_root/(key+'.json')
            if not path.is_file():continue
            value=json.loads(path.read_text());result=value.get('value') or {}
            unknown=('es_export_previous_attempt_unknown_requires_reconcile','es_export_result_unknown_poll_only','es_export_request_failed_or_unknown','es_export_manifest_invalid','es_archive_not_saved_capacity_or_io')
            if result.get('stage')=='export_sent' or result.get('reason') in unknown or value.get('last_attempt') in unknown:
                return dict(reason='es_export_previous_attempt_unknown_requires_reconcile',period=period,missing_days=missing,original_receipt=str(path))
            if result.get('reason')=='es_export_permission_denied' and result.get('stage')=='not_generated' and not path.with_suffix('.attempt').exists():
                return dict(reason='selective_history_ES_permission_denied',period=period,missing_days=missing,original_receipt=str(path),stage='not_generated')
    return None


def selective_history_signature(period, *, channel_root=None, ES_root=None):
    """Cheap change detector; it never asserts a new content hash or reads order payloads."""
    from pathlib import Path
    channel_root=Path(channel_root or '/var/lib/fs-channel-effects')
    ES_root=Path(ES_root or '/var/lib/fc27-es-exports')
    paths=[channel_root/'accounting-overrides.json']
    day=datetime.fromisoformat(period['start']).date()
    stop=datetime.fromisoformat(period['end']).date()
    manifests=[]
    for path in ES_root.glob('*.json'):
        if path.stat().st_size>2*1024*1024:continue
        value=json.loads(path.read_text())
        query=value.get('query') if isinstance(value,dict) else None
        if isinstance(query,dict) and query.get('start') and query.get('end'):
            manifests.append((path,value))
    chosen={}
    while day<=stop:
        text=day.isoformat();paths.append(channel_root/'days'/(text+'.json'))
        options=[item for item in manifests if item[1]['query']['start']<=text<=item[1]['query']['end']]
        if not options:raise ValueError('selective_history_ES_manifest_missing')
        path,value=max(options,key=lambda item:(item[1].get('captured_at') or '',item[1]['query']['end']))
        chosen[path]=value
        day+=timedelta(days=1)
    for path,value in chosen.items():
        paths.append(path)
        for digest in value.get('file_sha256',[]):
            if not re.fullmatch('[a-f0-9]{64}',str(digest)):raise ValueError('selective_history_ES_digest_invalid')
            paths.append(ES_root/(digest+'.xlsx'))
    signature=[]
    for path in sorted(set(paths)):
        if not path.exists():
            if path.name=='accounting-overrides.json':signature.append([str(path),'absent']);continue
            raise ValueError('selective_history_source_file_missing')
        stat=path.stat()
        signature.append([str(path),stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns])
    # Delivery costs are deliberately excluded: v15 N/D does not change merely because an old cost arrives.
    return fingerprint(dict(period=period,files=signature,contract='amount_and_discount_sources_v3_d9_d2_eight_days_native_multiline_quantity'))


def build_shared_history_cache(session,pages,storefront,products,source_signature,now,*,include_fulfillment=False,used_templates_only=False,prior_cache=None):
    from copy import deepcopy
    from .selective_sources import history_period,seal_history_cache,HISTORY_WINDOW_CONTRACT
    period=history_period(now)
    selected,provenance=_period_population(period)
    if selected is None or provenance.get('status')!='complete' or not selected:
        raise ValueError('pricing_v3_business_history_source_incomplete')
    try:
        orders,logs,templates=_live_traces(session,pages,period,selected,reconcile_population=True,
            **(dict(used_templates_only=True) if used_templates_only else {}))
    except ValueError as error:
        if str(error)!='history_order_state_changed_since_archive':raise
        archived_source=provenance['canonical_archive_sha256']
        selected,provenance,orders,logs=_historical_native_population(period,session,pages,
            **(dict(pricing_only=True) if used_templates_only else {}),
            **(dict(native_rows=error.native_rows) if hasattr(error,'native_rows') else {}))
        if provenance.get('status')!='complete' or not selected:
            raise ValueError('pricing_history_payment_reconciliation_incomplete')
        provenance=dict(provenance,reconciliation='current_Admin_payment_state',prior_archive_sha256=archived_source)
        templates=(read_used_templates(session,pages,_used_coupon_template_ids(selected,logs)) if used_templates_only
                   else {str(t['id']):t for t in pages(session,'/admin/market.Coupon/index')})
    from pricing_sources import active
    templates={key:dict(value,_current_active=active(value,now,coupon=True)) for key,value in templates.items()}
    replay=build_replay(selected,orders,logs,templates,provenance)
    replay['points_contract']['basis']='actual_d9_d2_eight_day_points_identity_and_existing_cart_cap'
    replay['history_window_contract']=HISTORY_WINDOW_CONTRACT
    mix=historical_mix(selected,provenance,history_window_contract=HISTORY_WINDOW_CONTRACT);replay['original_mix_sha256']=mix['sha256']
    grouped={}
    for identity,(archived,es) in selected.items():
        order=orders[identity]
        used=[logs[str(c['id'])] for c in archived.get('coupons',[])]
        scenario=dict(code_retained_ratio=str(amount(order['discount'])/100),
            points_credit_usd=str(amount(order['points'])/POINTS_PER_USD),
            coupon_template_ids=[str(log['coupon_id']) for log in used],
            region_id=int(order['region_price_lang_region_id']) if str(order.get('is_region_price'))=='1' else 0)
        key=fingerprint(scenario)
        item=grouped.setdefault(key,dict(scenario,weight_usd='0',orders=0))
        item['weight_usd']=str(Decimal(item['weight_usd'])+amount(archived['salesUsd'])+amount(es['discount_usd']))
        item['orders']+=1
    # The new financial window does not redefine the independent seven-day demand baseline.
    old_model=None
    if isinstance(prior_cache,dict) and prior_cache.get('cache_sha256')==fingerprint({k:v for k,v in prior_cache.items() if k!='cache_sha256'}):
        old_model=(prior_cache.get('daily_rollups') or {}).get('demand_model')
    if old_model:
        model=deepcopy(old_model);model.setdefault('history_observed_at',prior_cache['created_at'])
    else:
        model=dict(status='not_collected_for_pricing',groups={},segments=[],observed_segments=[],history_observed_at=None,
                   missing_context=['seven_day_demand_baseline_not_collected'],forecast_basis='relative_100k_price_prior_not_observed_orders')
    rollups=dict(demand_model=model)
    if include_fulfillment:rollups['observed_fulfillment']=fulfillment_context(selected,orders,provenance)
    return seal_history_cache(mix,replay,[grouped[k] for k in sorted(grouped)],rollups,source_signature,now),templates


def _selective_closed_month_rollup(now):
    today=now.astimezone(TZ).date()
    period=dict(start=today.replace(day=1).isoformat(),end=(today-timedelta(days=1)).isoformat())
    if period['end']<period['start']:return dict(status='no_closed_days_this_month',period=period,lower_bound=None,upper_bound=None)
    rows,source=_period_population(period)
    metrics=summarize(rows) if rows is not None else None
    known=(metrics or {}).get('net_paid_usd')
    upper=str(Decimal(known)+Decimal(source.get('unclassified_paid_FC_usd','0'))) if known is not None and source.get('ES_complete') else None
    return dict(status=source.get('status','unavailable'),period=period,lower_bound=known,upper_bound=upper,
        metrics=metrics,source_sha256=fingerprint(source),as_of=now.isoformat())


def collect_selective_business(session,pages,storefront,products,*,active_mode,scope=None,history_cache=None,
                               source_signature=None,current_templates=None,online_context=None,now=None):
    from .selective_sources import source_plan,history_period,checked_history_cache,context_from_cache,seal_history_cache
    now=now or datetime.now(timezone.utc)
    plan=source_plan(active_mode,scope)
    core_only=(scope or {}).get('catalog_only') is True
    signature=selective_history_signature(history_period(now))
    if source_signature is not None and source_signature!=signature:
        raise ValueError('selective_history_source_signature_changed')
    update=None
    try:cache=checked_history_cache(history_cache,signature,now)
    except ValueError:
        cache,current_templates=build_shared_history_cache(session,pages,storefront,products,signature,now,
            **(dict(used_templates_only=True) if core_only else {}),**(dict(prior_cache=history_cache) if history_cache is not None else {}))
        update=cache
    if current_templates is None:
        current_templates=(read_used_templates(session,pages,
            [identity for scenario in cache['promotion_scenarios'] for identity in scenario['coupon_template_ids']]) if core_only
            else {str(row['id']):row for row in pages(session,'/admin/market.Coupon/index')})
    from pricing_sources import active
    current_templates={str(key):dict(row,_current_active=active(row,now,coupon=True)) for key,row in current_templates.items()}
    monthly=None
    if plan['refresh_monthly_target']:
        closed=cache['daily_rollups'].get('closed_month')
        today=now.astimezone(TZ).date()
        expected=dict(start=today.replace(day=1).isoformat(),end=(today-timedelta(days=1)).isoformat())
        if not closed or closed['period']!=expected:
            closed=_selective_closed_month_rollup(now)
            rollups=dict(cache['daily_rollups'],closed_month=closed)
            cache=seal_history_cache(cache['historical_discount_mix'],cache['original_history_replay'],cache['promotion_scenarios'],rollups,signature,datetime.fromisoformat(cache['created_at']))
            update=cache
        try:current=_today_summary(session,pages,now)
        except (ValueError,OSError) as error:current=dict(status='unavailable',net_paid_usd=None,reason=type(error).__name__)
        lower,upper=closed.get('lower_bound'),closed.get('upper_bound')
        complete_today=current.get('status')=='complete' and current.get('net_paid_usd') is not None
        mtd=str(Decimal(lower)+Decimal(current['net_paid_usd'])) if lower is not None and complete_today else lower
        monthly=dict(amount=None,mtd=mtd,mtd_exact=mtd if closed['status']=='complete' and complete_today else None,
            mtd_lower_bound=mtd,mtd_upper_bound=str(Decimal(upper)+Decimal(current['net_paid_usd'])) if upper is not None and complete_today else upper,
            through_date=today.isoformat() if complete_today else expected['end'],today=current,closed_day_rollup=closed,
            target_scope='site266_FC27_Coins',target_basis='net_paid_USD',status='target_not_configured')
    context=context_from_cache(cache,plan,current_templates,now,monthly=monthly,online=online_context)
    return dict(context=context,private_updates=dict(history_cache=update) if update else {},source_plan=plan)

def _historical_provider_now():
    return datetime.now(timezone.utc)


def historical_period(period, *, now=None):
    """Resolve a closed payment window in the existing business timezone."""
    from datetime import date
    reference = now or _historical_provider_now()
    if reference.tzinfo is None:
        raise ValueError('historical_provider_timezone_missing')
    today = reference.astimezone(TZ).date()
    aliases = {'7d_closed': '7d', '14d_closed': '14d', '28d_closed': '28d',
               'previous_calendar_month': 'last_complete_month', 'month': 'last_complete_month'}
    selector = str(period) + 'd' if type(period) is int and period in (7, 14, 28) else period
    if isinstance(selector, str):
        selector = aliases.get(selector, selector)
        if selector in ('7d', '14d', '28d'):
            end_exclusive = today
            start = today - timedelta(days=int(selector[:-1]))
        elif selector == 'last_complete_month':
            end_exclusive = today.replace(day=1)
            start = (end_exclusive - timedelta(days=1)).replace(day=1)
        else:
            raise ValueError('historical_provider_period_invalid')
    elif isinstance(period, dict) and set(period) == {'start', 'end'}:
        start, end = (date.fromisoformat(period[key]) for key in ('start', 'end'))
        if start.isoformat() != period['start'] or end.isoformat() != period['end']:
            raise ValueError('historical_provider_period_invalid')
        end_exclusive, selector = end + timedelta(days=1), 'explicit_closed_period'
    else:
        raise ValueError('historical_provider_period_invalid')
    if not 1 <= (end_exclusive - start).days <= 31 or end_exclusive > today:
        raise ValueError('historical_provider_period_not_closed_or_too_large')
    lower = datetime.combine(start, datetime.min.time(), TZ)
    upper = datetime.combine(end_exclusive, datetime.min.time(), TZ)
    return dict(period_selector=selector, period=dict(start=start.isoformat(), end=(end_exclusive - timedelta(days=1)).isoformat()),
                paid_window=dict(start=start.isoformat(), end_exclusive=end_exclusive.isoformat(), timezone='Asia/Shanghai'),
                paid_window_start=lower.isoformat(), paid_window_end_exclusive=upper.isoformat(), timezone='Asia/Shanghai')


def _historical_existing_day_blocks(period):
    """File existence only; original reader remains responsible for archive validation."""
    from pathlib import Path
    from coins_evidence import CoinsEvidence
    root = Path(CoinsEvidence().channel_root) / 'days'
    current = datetime.fromisoformat(period['start']).date()
    stop = datetime.fromisoformat(period['end']).date()
    blocks, missing, begin, previous = [], [], None, None
    while current <= stop:
        if (root / (current.isoformat() + '.json')).is_file():
            if begin is None:begin = current
            previous = current
        else:
            missing.append(current.isoformat())
            if begin is not None:
                blocks.append(dict(start=begin.isoformat(), end=previous.isoformat()))
                begin = None
        current += timedelta(days=1)
    if begin is not None:blocks.append(dict(start=begin.isoformat(), end=previous.isoformat()))
    return blocks, missing


def _historical_existing_ES_coverage(period):
    """Existing manifests/XLSX only; never launches an export or an Admin request."""
    from coins_evidence import CoinsEvidence, es_metadata, GOLD
    reader = CoinsEvidence()
    metadata, coverage = es_metadata(period['start'], period['end'], reader.archive)
    return dict(status='complete' if coverage.get('complete') else 'partial',
        source_sha256=coverage.get('source_sha256'), captured_at=coverage.get('captured_at'),
        parsed_files=coverage.get('files'), identified_Gold_orders=sum(value.get('product') == GOLD for value in metadata.values()),
        scope='ES product identity coverage, not Admin-qualified eligible orders or proof that missing canonical days have zero orders')


def _historical_provider_reason(error):
    reason = str(error)
    prefixes = ('historical_', 'history_', 'canonical_', 'coins_', 'admin_', 'invalid_', 'incomplete_', 'duplicate_', 'day_', 'native_', 'pricing_')
    return reason if reason.startswith(prefixes) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}', reason) else type(error).__name__


def _historical_native_population(period, session, pages, *, pricing_only=False, native_rows=None):
    """Fill only explicitly requested missing days using the original accounting and ES identity."""
    from pathlib import Path
    import channel_source as channel
    from channel_effects import accounting_row, fraud
    from coins_evidence import CoinsEvidence, es_metadata, GOLD
    start, end = period['start']+' 00:00:00', period['end']+' 23:59:59'
    native = list(native_rows) if native_rows is not None else pages(session, '/admin/order.Order/index', [('site_id','=','266'), ('gid','=','1327'),
                   ('paytime','RANGE',start+','+end)], 100)
    if any(str(r.get('site_id'))!='266' or str(r.get('gid'))!='1327' or not start<=str(r.get('paytime'))<=end for r in native):
        raise ValueError('historical_native_paid_scope_not_honored')
    reader = CoinsEvidence()
    meta, ES = es_metadata(period['start'], period['end'], reader.archive)
    normalized, logs, accounting = [], [], channel.apply_cost_overrides(dict(sources={}))
    cost_source = None
    if native:
        discounts = [] if pricing_only else pages(session, '/admin/market.Discount/index')
        templates = [] if pricing_only else pages(session, '/admin/market.Coupon/index')
        names = sorted({str(r['order_no']) for r in native})
        for offset in range(0,len(names),100):
            group = names[offset:offset+100]
            batch = pages(session, '/admin/user.MemberCouponLog/index', [('site_id','=','266'), ('order_no','IN',','.join(group))])
            if any(str(r.get('site_id'))!='266' or str(r.get('order_no')) not in group for r in batch):
                raise ValueError('historical_native_coupon_scope_not_honored')
            logs.extend(batch)
        if pricing_only:
            # These lookups only label attribution/cost coverage in the original
            # normalizer. Paid USD, status and real coupon-log identities remain
            # original; actual discount USD comes from the matched ES row below.
            deliveries,directory,mapping=[],{},dict(entries=[])
            cost_source=dict(status='not_collected',reason='historical_CNY_cost_and_attribution_not_required_for_pricing_USD_mix')
        else:
            deliveries, cost_source = channel.load_costs()
            mapping = json.loads(Path(channel.__file__).with_name('channel_mapping.json').read_text('utf-8'))
            directory_path = channel.SALES/'promoter_dir.json'
            directory = json.loads(directory_path.read_text('utf-8')) if directory_path.is_file() else {}
        normalized = channel.normalize(native,discounts,logs,templates,deliveries,directory,mapping)
        if pricing_only:
            for row in normalized:row['marketingDefinitionStatus']='not_collected_for_pricing'
    selected, missing, missing_usd = {}, 0, Decimal(0)
    for raw in normalized:
        row = accounting_row(raw,accounting.get('costOverrides',{}),accounting.get('testOrders',{}),admin_revenue=True)
        if row.get('testOrder') or fraud(row) or row.get('refunded') or str(row.get('payStatus'))!='1':
            continue
        info = meta.get(hashlib.sha256(raw['orderNo'].encode()).hexdigest())
        if info is None:
            missing += 1
            missing_usd += amount(row.get('salesUsd')) or Decimal(0)
        elif info['product']==GOLD:
            selected[raw['orderNo']] = (row,info)
    proof = dict(period=period,status='complete' if ES['complete'] and not missing else 'partial',
        canonical_archive_sha256=fingerprint(dict(native=native,normalized=normalized,cost_source=cost_source,accounting=accounting['sources']['accounting'])),
        ES_source_sha256=ES['source_sha256'],ES_complete=ES['complete'],missing_product_identity=missing,
        unclassified_paid_FC_usd=str(missing_usd),source_generated_at=_historical_provider_now().isoformat(),
        source_kind='native_Admin_backfill_original_accounting_existing_ES_no_shared_archive_write',native_rows=len(native))
    return selected, proof, {r['order_no']:r for r in native if r['order_no'] in selected}, {str(r['id']):r for r in logs}


def collect_historical_attachment(period, session, pages, *, observed_at=None):
    """One explicit private historical input; no writes, retries, public rows or live collect hook.

    observed_at is a source-controlled clock hint, never a user's historical as-of.
    It cannot backdate facts read by this invocation. Preserve each returned version
    in the private input store; consumers select versions by available_at.
    """
    from .financial import instant
    started = _historical_provider_now()
    clock_hint = observed_at or started
    if not isinstance(clock_hint, datetime) or clock_hint.tzinfo is None:
        raise ValueError('historical_provider_timezone_missing')
    window = historical_period(period, now=started)
    target = window['period']
    lower, upper = instant(window['paid_window_start']), instant(window['paid_window_end_exclusive'])
    source_parts, selected, gaps, selection = [], {}, Counter(), Counter()
    missing_days, failed_periods, ES = [], [], None
    preloaded_orders, preloaded_logs, native_backfills = {}, {}, []
    try:
        initial, provenance = _period_population(target)
    except (ValueError, OSError) as error:
        initial, provenance = None, dict(status='unavailable', reason=_historical_provider_reason(error))
        gaps['canonical_source_read_failed'] += 1
    if initial is not None:
        candidates = [(target, initial, provenance)]
        ES = dict(status='complete' if provenance.get('ES_complete') else 'partial',
                  source_sha256=provenance.get('ES_source_sha256'), scope='same-period ES join already checked by original population reader')
    else:
        try:
            blocks, missing_days = _historical_existing_day_blocks(target)
        except (ValueError, OSError) as error:
            blocks, missing_days = [], None
            gaps['canonical_day_inventory_unavailable'] += 1
        candidates = []
        for block in blocks:
            if block == target:
                population, proof = None, provenance  # Do not repeat the same failed exact-range read.
            else:
                try:
                    population, proof = _period_population(block)
                except (ValueError, OSError) as error:
                    population, proof = None, dict(status='unavailable', reason=_historical_provider_reason(error))
            if population is None:
                failed_periods.append(dict(period=block, reason=proof.get('reason', 'canonical_period_cache_missing')))
            else:
                candidates.append((block, population, proof))
        try:
            ES = _historical_existing_ES_coverage(target)
        except (ValueError, OSError) as error:
            ES = dict(status='unavailable', reason=_historical_provider_reason(error))
            gaps['existing_ES_read_failed'] += 1
        blocks = []
        for day in missing_days or []:
            previous = datetime.fromisoformat(blocks[-1]['end']).date() if blocks else None
            current = datetime.fromisoformat(day).date()
            if previous and current==previous+timedelta(days=1) and (current-datetime.fromisoformat(blocks[-1]['start']).date()).days<28:
                blocks[-1]['end'] = day
            else:
                blocks.append(dict(start=day,end=day))
        for block in blocks:
            try:
                population, proof, native, used = _historical_native_population(block,session,pages)
                candidates.append((block,population,proof))
                preloaded_orders.update(native);preloaded_logs.update(used)
                native_backfills.append(dict(period=block,source_sha256=proof['canonical_archive_sha256'],status=proof['status']))
            except (ValueError,OSError,KeyError,TypeError) as error:
                failed_periods.append(dict(period=block,reason=_historical_provider_reason(error)))
                gaps['native_population_backfill_failed'] += 1
    unresolved_days = [day for day in missing_days or [] if not any(b['period']['start']<=day<=b['period']['end'] for b in native_backfills)]
    if unresolved_days:gaps['canonical_days_missing'] += len(unresolved_days)
    if failed_periods:gaps['canonical_periods_unavailable'] += len(failed_periods)
    for block, population, proof in candidates:
        source_parts.append(dict(period=block, **{key:proof.get(key) for key in
            ('status', 'canonical_archive_sha256', 'ES_source_sha256', 'source_generated_at', 'ES_complete', 'missing_product_identity', 'source_kind', 'unclassified_paid_FC_usd')}))
        for identity, pair in population.items():
            selection['canonical_eligible_observations'] += 1
            try:
                paid = instant(pair[0]['paidAt'])
            except (KeyError, ValueError):
                gaps['canonical_paid_at_unknown'] += 1
                continue
            if not lower <= paid < upper:
                selection['excluded_outside_paid_window'] += 1
                continue
            if identity in selected:
                raise ValueError('historical_provider_duplicate_canonical_identity')
            selected[identity] = pair
    selection['eligible_known_in_paid_window'] = len(selected)
    if selection['excluded_outside_paid_window']:gaps['canonical_paid_window_disagreement'] += selection['excluded_outside_paid_window']
    if any(part['status'] != 'complete' for part in source_parts):gaps['canonical_or_ES_population_partial'] += 1
    orders, logs = dict(preloaded_orders), dict(preloaded_logs)
    trace_failures = []
    current = datetime.fromisoformat(target['start']).date()
    stop = datetime.fromisoformat(target['end']).date()
    while current <= stop:
        end = min(current + timedelta(days=27), stop)
        part = dict(start=current.isoformat(), end=end.isoformat())
        part_lower = datetime.combine(current, datetime.min.time(), TZ)
        part_upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), TZ)
        needed = {key:pair for key,pair in selected.items() if key not in orders and part_lower <= instant(pair[0]['paidAt']) < part_upper}
        if needed:
            try:
                native, used, _ = _live_traces(session, pages, part, needed)
                orders.update(native)
                for key, value in used.items():
                    if key in logs and logs[key] != value:raise ValueError('historical_provider_coupon_trace_conflict')
                    logs[key] = value
            except (ValueError, OSError) as error:
                trace_failures.append(dict(period=part, reason=_historical_provider_reason(error)))
                gaps['native_trace_read_failed'] += 1
                break  # No retry or repeated full scan on the same failure.
        current = end + timedelta(days=1)
    ready = {key:pair for key,pair in selected.items() if key in orders}
    selection['eligible_with_native_traces'] = len(ready)
    selection['eligible_without_native_traces'] = len(selected) - len(ready)
    if len(ready) < len(selected):gaps['eligible_native_trace_missing'] += len(selected) - len(ready)
    complete = (bool(source_parts) and missing_days is not None and not unresolved_days and not failed_periods and not trace_failures
                and all(part['status'] == 'complete' for part in source_parts) and ES.get('status') == 'complete'
                and not gaps['canonical_paid_at_unknown'] and not gaps['canonical_paid_window_disagreement'] and len(ready) == len(selected))
    aggregate_proof = dict(period=target, status='complete' if complete else 'partial', eligible_count=len(ready),
        canonical_archive_sha256=source_parts[0]['canonical_archive_sha256'] if len(source_parts) == 1 else fingerprint(source_parts),
        ES_source_sha256=ES.get('source_sha256') or fingerprint(ES), ES_complete=ES.get('status') == 'complete',
        source_generated_at=min((part['source_generated_at'] for part in source_parts if part.get('source_generated_at')), default=None),
        missing_product_identity=sum(part.get('missing_product_identity') or 0 for part in source_parts))
    verified_at = max(_historical_provider_now(), clock_hint)
    rows, metadata = historical_attachment(ready, orders, logs, aggregate_proof, verified_at)
    metadata.update(window)
    metadata.update(as_of=verified_at.isoformat(), available_at=verified_at.isoformat(),
        population_status='complete' if complete else 'partial' if source_parts else 'unavailable', window_complete=complete,
        population_selection=dict(selection), canonical_missing_days=missing_days,
        unresolved_population_days=unresolved_days,native_backfills=native_backfills,
        canonical_failed_periods=failed_periods, native_trace_failures=trace_failures, source_parts=source_parts,
        existing_ES_coverage=ES, request_is_independent_of_production_collect=True,
        population_scope='original Admin-qualified paid nonrefund nonfraud nontest site266 FC27 Coins cohort',
        refund_revision_coverage='not_collected_by_original_population_reader; later refunded orders are excluded, not fabricated as zero refund reversals',
        version_policy='append immutable source versions in private historical_inputs; latest available_at<=asof wins, never overwrite old revisions',
        longer_window_coverage='this exact paid window only; no relabelling another-period attachment')
    metadata['gaps'] = dict(Counter(metadata.get('gaps') or {}) + gaps)
    metadata['gaps']['historical_refund_revision_chain_not_collected'] = 1
    metadata['status'] = 'unavailable' if not source_parts else 'partial' if metadata['gaps'] or not complete else 'complete'
    metadata['source_sha256'] = fingerprint(dict(rows=rows, coverage={key:value for key,value in metadata.items() if key != 'source_sha256'}))
    return dict(period_selector=window['period_selector'], period=target, paid_window=window['paid_window'],
        as_of=verified_at.isoformat(), available_at=verified_at.isoformat(), source_sha256=metadata['source_sha256'],
        historical_orders=rows, historical_orders_coverage=metadata)


def historical_attachment_summary(private_input):
    """Only this aggregate projection may cross the public/API boundary."""
    return json.loads(json.dumps(private_input['historical_orders_coverage']))
