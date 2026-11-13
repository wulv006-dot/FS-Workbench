"""Private, in-memory D2 projection of already authorized and revision-selected inputs.

No fetching, persistence, publication, FX conversion or source-scope inference.
Sites and complete_cost_orders must come from the caller's verified source evidence.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal

from channel_effects import money, accounting_row
from order_attribution import HEADERS, CHANNELS, VERSION as ATTRIBUTION_VERSION, normalize_order_attribution

VERSION = 'same-order-facts-20261113-v1'
BASIS = 'same_order_admin_cny'


def amount(value):
    value = money(value)
    if value is None:return None
    text = format(value, 'f')
    return '0' if value == 0 else text.rstrip('0').rstrip('.') if '.' in text else text


def identity(row, sites, order_field='order_no'):
    site, sn = str(row.get('site_id') or '').strip(), str(row.get(order_field) or '').strip()
    return (site, sn) if site in sites and sn else None


def summarize(rows):
    def total(field):
        return format(sum((Decimal(r[field]) for r in rows if r[field] is not None), Decimal(0)), 'f')
    covered = [r for r in rows if r['actual_cost_cny'] is not None and r['admin_paid_cny'] is not None]
    uncovered = [r for r in rows if r['actual_cost_cny'] is None and r['admin_paid_cny'] is not None]
    gross = [r for r in rows if r['procurement_gross_cny'] is not None]
    return dict(orders=len(rows), admin_paid_usd=total('admin_paid_usd'), admin_paid_cny=total('admin_paid_cny'),
                missing_admin_usd_orders=sum(r['admin_paid_usd'] is None for r in rows),
                missing_admin_cny_orders=sum(r['admin_paid_cny'] is None for r in rows),
                observed_cost_cny=total('observed_cost_cny'), cost_records=sum(len(r['cost_records']) for r in rows),
                cost_covered_orders=sum(r['actual_cost_cny'] is not None for r in rows),
                missing_cost_orders=sum(r['actual_cost_cny'] is None for r in rows),
                covered_revenue_cny=format(sum((Decimal(r['admin_paid_cny']) for r in covered),Decimal(0)),'f'),
                missing_cost_revenue_cny=format(sum((Decimal(r['admin_paid_cny']) for r in uncovered),Decimal(0)),'f'),
                procurement_gross_cny=total('procurement_gross_cny') if gross else None,
                gross_covered_orders=len(gross),
                gross_covered_revenue_cny=format(sum((Decimal(r['admin_paid_cny']) for r in gross),Decimal(0)),'f'),
                unknown_channel_orders=sum(r['channel']=='unknown' for r in rows),
                attributed_revenue_cny=format(sum((Decimal(r['admin_paid_cny']) for r in rows if r['channel']!='unknown' and r['admin_paid_cny'] is not None),Decimal(0)),'f'),
                accounting_basis=BASIS, fee_coverage='unknown', known_fee_contribution_cny=None,
                amount_semantics='known subtotals; missing counts and cost coverage are not zero-imputation')


def build_order_facts(admin_orders, attribution_rows, deliveries, *, sites, scope,
                      source_coverage, complete_cost_orders=()):
    """sites maps verified Admin site_id to exact Order source/full_title.

    Admin fields are order-level native amounts (not product-line amounts).
    Attribution bridges require original order_no and verified site_id, never a
    guessed site or a reversed D0 hash. Missing bridges stay explicitly unlinked.
    complete_cost_orders contains (site_id, original_order_no) pairs whose entire
    actual procurement set is proven complete; seeing a delivery is not that proof.
    """
    sites = {str(k):v for k,v in sites.items()}
    if any(not k or not isinstance(v,str) or not v for k,v in sites.items()) or len(set(sites.values()))!=len(sites):
        raise ValueError('ambiguous_site_mapping')
    source_sites = {name:site for site,name in sites.items()}
    complete = set(complete_cost_orders)
    orders, attrs, costs = {}, defaultdict(list), defaultdict(list)
    unlinked_admin, unlinked_attrs, unlinked_costs = [], [], []
    duplicate_admin = duplicate_cost = 0
    for raw in admin_orders:
        key = identity(raw,sites)
        if key is None:
            unlinked_admin.append(deepcopy(raw));continue
        row = dict(site_id=key[0],order_no=key[1],admin_paid_usd=amount(raw.get('amount_usd_format')),
                   admin_paid_cny=amount(raw.get('amount_rmb_format')),status=str(raw.get('status_format') or ''),
                   pay_status=str(raw.get('pay_status') or ''),paid_at=raw.get('paytime'),
                   gid=str(raw.get('gid') or ''),game=str(raw.get('game_format') or ''))
        if key in orders:
            if orders[key]!=row:raise ValueError('admin_order_revision_conflict')
            duplicate_admin += 1
        else:orders[key]=row
    for raw in attribution_rows:
        key = identity(raw,sites)
        if key not in orders:
            unlinked_attrs.append(deepcopy(raw));continue
        fact = deepcopy(raw.get('marketing_attribution'))
        if fact is None:fact=normalize_order_attribution(raw,set(raw),{'fields':HEADERS})
        context = (fact, raw.get('订单来源'))
        if context not in attrs[key]:attrs[key].append(context)
    seen, incomplete = {}, set()
    for raw in deliveries:
        site = source_sites.get(raw.get('source'))
        sn, did = str(raw.get('sn') or '').strip(), str(raw.get('delivery_id') or '').strip()
        key = (site,sn)
        if key not in orders or not did or str(raw.get('genre')) not in ('1','订单发货'):
            unlinked_costs.append(deepcopy(raw))
            if key in orders:incomplete.add(key)
            continue
        record = dict(cost_record_id=did,site_id=site,order_no=sn,source=raw.get('source'),
                      cost_cny=amount(raw.get('cost_total')),order_sale_cny=amount(raw.get('sale_total')),
                      cost_unit_cny=amount(raw.get('cost_unit')),trade_at=raw.get('trade_at'),
                      trade_amended_at=raw.get('trade_amended_at'),quantity=raw.get('qty'),gift=raw.get('gift'),
                      source_quantity_basis='ACTUAL_SHIPPED_K' if raw.get('quantity_unit')=='K' else 'unverified',
                      component='order_delivery',status=raw.get('settle_status'))
        token = (site,did)
        if token in seen:
            if seen[token]!=record:raise ValueError('cost_record_revision_conflict')
            duplicate_cost += 1;continue
        seen[token]=record;costs[key].append(record)
    result=[]
    for key, row in orders.items():
        contexts=attrs[key]
        choices=[]
        for choice, _ in contexts:
            if choice not in choices:choices.append(choice)
        fact=(choices[0] if len(choices)==1 else normalize_order_attribution({},set(),{'fields':HEADERS}))
        if len(choices)>1:fact.update(status='conflict',variants=choices)
        channel=fact.get('channel') if fact.get('status')=='available' and fact.get('channel') in CHANNELS.values() else 'unknown'
        records=costs[key];valid=[r for r in records if r['cost_cny'] is not None and Decimal(r['cost_cny'])>=0]
        observed=sum((Decimal(r['cost_cny']) for r in valid),Decimal(0))
        is_complete=bool(records) and len(valid)==len(records) and key in complete and key not in incomplete
        actual=format(observed,'f') if is_complete else None
        # Preserve the existing completed/non-refunded same-Admin-order accounting policy.
        accounting=accounting_row(dict(orderNo=row['order_no'],gid=row['gid'],game=row['game'],
            status=row['status'],refunded=row['pay_status']=='2' or row['status'].startswith('已退款'),
            salesUsd=row['admin_paid_usd'],adminSaleCny=row['admin_paid_cny'],saleCny=None,costCny=actual),{})
        row.update(channel=channel,marketing_attribution=fact,cost_records=records,
                   observed_cost_cny=format(observed,'f'),actual_cost_cny=actual,
                   cost_coverage='complete' if is_complete else 'missing' if not records else 'partial',
                   procurement_gross_cny=amount(accounting.get('profitCny')),
                   accounting_status=accounting['costStatus'],accounting_basis=BASIS,
                   fee_coverage='unknown',known_fee_contribution_cny=None)
        sources = {source.strip() for _, source in contexts if isinstance(source,str) and source.strip()}
        row['pinned_order_source'] = next(iter(sources)) if len(sources)==1 else None
        row['pinned_order_source_conflict'] = len(sources)>1
        if row['pinned_order_source']:
            row['pinned_order_source_revision'] = source_coverage.get('attribution',{}).get('source_revision')
            observed = {choice.get('source_captured_at') for choice,source in contexts
                        if isinstance(source,str) and source.strip()==row['pinned_order_source']}
            row['pinned_order_source_at'] = next(iter(observed)) if len(observed)==1 else None
        result.append(row)
    groups=defaultdict(list)
    for row in result:groups[row['channel']].append(row)
    return dict(version=VERSION,attribution_version=ATTRIBUTION_VERSION,private=True,
                status='available' if source_coverage.get('admin_complete') is True and not unlinked_admin else 'partial',
                input_scope=deepcopy(scope),site_mapping=deepcopy(sites),source_coverage=deepcopy(source_coverage),orders=result,
                totals=summarize(result),channels=[dict(channel=k,**summarize(v)) for k,v in sorted(groups.items())],
                unlinked_admin_rows=unlinked_admin,unlinked_attribution_rows=unlinked_attrs,unlinked_cost_records=unlinked_costs,
                coverage=dict(linked_orders=len(result),unlinked_admin_rows=len(unlinked_admin),
                              unlinked_attribution_rows=len(unlinked_attrs),unlinked_cost_records=len(unlinked_costs),
                              duplicate_admin_rows=duplicate_admin,duplicate_cost_rows=duplicate_cost))
