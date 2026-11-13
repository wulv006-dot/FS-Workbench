"""Read-only bridge from native Admin rows and a pinned D0 private projection.

The caller owns authorization and source acquisition. Nothing here fetches an
export, writes a cache, or treats a shipment-time window as full order cost.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
import hashlib

from order_facts import build_order_facts


def _period(scope):
    start, end = date.fromisoformat(scope['start']), date.fromisoformat(scope['end'])
    if start > end:
        raise ValueError('order_facts_period')
    return start.isoformat(), end.isoformat()


def _sites(rows):
    sites = {}
    for row in rows:
        site = str(row.get('site_id') or '').strip()
        title = (row.get('site') or {}).get('full_title')
        if not site or not isinstance(title, str) or not title.strip():
            continue
        if site in sites and sites[site] != title:
            raise ValueError('order_facts_site_revision_conflict')
        sites[site] = title
    if len(set(sites.values())) != len(sites):
        raise ValueError('order_facts_site_mapping_ambiguous')
    return sites


def _identities(catalog, start, end):
    """Only the complete native paid all-site/all-game catalog proves uniqueness."""
    index = defaultdict(set)
    if catalog is None:
        return index, 'unavailable'
    span = catalog.get('scope') or {}
    if (not catalog.get('revision')
            or span.get('site') != 'all' or span.get('game') != 'all'
            or span.get('pay_status') != '1'
            or not span.get('start') or not span.get('end')):
        return index, 'coverage_unverified'
    lo, hi = _period(span)
    if not lo <= start <= end <= hi:
        return index, 'coverage_unverified'
    verified_days = set(catalog.get('verified_days', ()))
    if catalog.get('complete') is not True and not verified_days:
        return index, 'coverage_unverified'
    for row in catalog['rows']:
        site, sn = str(row.get('site_id') or '').strip(), str(row.get('order_no') or '').strip()
        if not site or not sn:
            return defaultdict(set), 'identity_missing'
        index[hashlib.sha256(sn.encode()).hexdigest()].add((site, sn))
    return index, 'complete' if catalog.get('complete') is True else 'partial'


def project_order_facts(admin_orders, dataset, deliveries, *, scope,
                        source_coverage, identity_catalog=None, complete_cost_orders=()):
    """Project selected native inputs; all proof arguments are server-owned.

    scope has inclusive ISO-day start/end. Admin rows are already scope-selected.
    identity_catalog is {rows, complete, revision, scope:{site:'all', game:'all',
    pay_status:'1', start,end}} from the native Admin paid list, not an all-status
    list. A single-site unique hash is not a
    verified bridge. D0 data must be produced by its publication-pinned reader;
    its existing hashes, publication/data revisions and source scope survive.
    """
    start, end = _period(scope)
    orders = list(admin_orders)
    sites = _sites(orders)
    if identity_catalog is not None:
        catalog_sites = _sites(identity_catalog.get('rows', []))
        if any(site in catalog_sites and catalog_sites[site] != title for site, title in sites.items()):
            raise ValueError('order_facts_site_revision_conflict')
    keys = {(str(r.get('site_id') or '').strip(), str(r.get('order_no') or '').strip()) for r in orders}
    statuses = defaultdict(set)
    for row in orders:
        key = (str(row.get('site_id') or '').strip(), str(row.get('order_no') or '').strip())
        status = str(row.get('status_format') or '').strip()
        if status:
            statuses[key].add(status)
    index, identity_status = _identities(identity_catalog, start, end)
    verified_days = set((identity_catalog or {}).get('verified_days', ()))
    coverage = deepcopy(source_coverage)
    attrs, excluded = [], 0
    bridge_counts = defaultdict(int)
    attribution_source = dict(status='unavailable', selected_scope={'start':start, 'end':end})
    if dataset is not None:
        if (dataset.get('_private_dataset') is not True
                or dataset.get('revision_selection') != 'published_pins'
                or not dataset.get('publication_id')
                or dataset.get('source_revision') != dataset.get('publication_id')
                or dataset.get('data_revision') is None):
            raise ValueError('order_facts_publication_required')
        original_scope = dataset.get('effective_scope') or {}
        lo, hi = _period(original_scope)
        if not lo <= start <= end <= hi:
            raise ValueError('order_facts_attribution_period')
        attribution_source.update({k:deepcopy(dataset.get(k)) for k in (
            'status','publication_id','source_revision','data_revision','available_at','captured_at',
            'hashes','revision_selection','effective_scope','revision_conflicts')})
        for row in dataset['rows']:
            try:
                paid = datetime.strptime(str(row.get('付款时间') or '').replace('/', '-'), '%Y-%m-%d %H:%M:%S')
            except ValueError:
                raise ValueError('order_facts_attribution_payment_time') from None
            if not start <= paid.date().isoformat() <= end:
                excluded += 1
                continue
            item = deepcopy(row)
            item.pop('site_id', None)
            item.pop('order_no', None)
            # D0's hash algorithm is retained; never reverse it or replace it in storage.
            matches = index.get(row.get('订单号'), set())
            if identity_status != 'complete' and not (identity_status == 'partial' and paid.date().isoformat() in verified_days):
                reason = 'identity_coverage_unverified'
            elif len(matches) > 1:
                reason = 'cross_site_ambiguous'
            elif not matches:
                reason = 'identity_unmatched'
            else:
                site, sn = next(iter(matches))
                if (site, sn) not in keys:
                    excluded += 1
                    continue
                if site not in sites:
                    reason = 'site_label_unverified'
                elif (str(row.get('订单状态') or '').strip() and statuses[(site,sn)]
                      and statuses[(site,sn)] != {str(row['订单状态']).strip()}):
                    reason = 'order_status_revision_mismatch'
                else:
                    item.update(site_id=site, order_no=sn)
                    reason = 'linked'
            item['_bridge_status'] = reason
            attrs.append(item)
            bridge_counts[reason] += 1
    attribution_source.update(identity_status=identity_status,
        identity_revision=identity_catalog.get('revision') if identity_catalog else None,
        identity_scope=deepcopy(identity_catalog.get('scope')) if identity_catalog else None,
        bridge_counts=dict(bridge_counts), excluded_source_rows=excluded)
    coverage['attribution'] = attribution_source
    result = build_order_facts(orders, attrs, deliveries, sites=sites, scope=scope,
        source_coverage=coverage, complete_cost_orders=complete_cost_orders)
    result['bridge_version'] = 'admin-es-order-bridge-20261113-v1'
    return result
