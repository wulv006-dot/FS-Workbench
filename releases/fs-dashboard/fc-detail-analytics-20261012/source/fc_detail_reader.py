"""Run the existing bounded reader through the shared direct Admin API client."""
import hashlib, json, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.error import URLError
from fc_detail_model import normalize, deduplicate

class FCContractError(ValueError):
    pass

def native_page_rows(batch, seen_ids):
    """Only adjacent, byte-equivalent native join rows within this page can repeat."""
    rows, ids, duplicates = [], set(), 0
    for row in batch:
        identity = int(row['id'])
        if identity in seen_ids: raise ValueError('fc_duplicate_page_records')
        if identity in ids:
            if rows and row == rows[-1]:
                duplicates += 1
                continue
            raise ValueError('fc_duplicate_page_records')
        ids.add(identity)
        rows.append(row)
    return rows, duplicates

def collect(request, query, config, shipping_reader=None):
    native_state = {'active':False,'requests':0,'deadline':None,'budget_exhausted':False}
    def read(path):
        if native_state['active']:
            if native_state['requests'] >= config.get('native_request_budget',400) or time.monotonic() >= native_state['deadline']:
                native_state['budget_exhausted'] = True
                raise TimeoutError('fc_native_relation_budget')
            native_state['requests'] += 1
        for attempt in range(3):
            try:
                status, raw = request(path)
                if status in (301,302,401,403): raise PermissionError('fc_source_denied')
                return status, raw
            except (TimeoutError, URLError):
                if attempt == 2: raise
                time.sleep(1)
    status, raw = read('/admin/site.Site/siteList?' + urlencode({'page': 1, 'initKey': 'id', 'initValue': '', 'select': 'true', 'quick_search': ''}))
    sites = json.loads(raw)
    if status != 200 or sites.get('code') != 1: raise ValueError('site_catalog_unavailable')
    site_ids = {int(row['id']) for row in sites['data']['list'] if int(row['id']) > 0}
    if config['main_site_id'] not in site_ids: raise ValueError('main_site_mapping_unavailable')
    observations = []
    def pages(filters, name):
        rows, expected, previous_id, seen_ids = [], None, float('inf'), set()
        received_source_rows, duplicates_dropped = 0, 0
        current = name.startswith('current-')
        for page in range(1, config['max_pages'] + 1):
            params = {'page': page, 'limit': config['page_size']}
            if not current: params['order'] = 'id,desc'
            for i, (field, value, operator) in enumerate(filters):
                params.update({'search[%s][field]' % i: field, 'search[%s][val]' % i: value, 'search[%s][operator]' % i: operator})
                if field == 'paytime': params['search[%s][render]' % i] = 'datetime'
            status, raw = read('/admin/order.Order/index?' + urlencode(params))
            data = json.loads(raw)
            if status in (401, 403): raise PermissionError('fc_orders_denied')
            if status != 200 or data.get('code') != 1: raise ValueError('fc_orders_unavailable')
            value = data.get('data') or {}; batch = value.get('list'); total = value.get('total')
            if __name__ == '__main__' and (page == 1 or page % 10 == 0): print('FC read %s page=%s total=%s' % (name, page, total), file=sys.stderr, flush=True)
            if not isinstance(batch, list) or not isinstance(total, int) or total < 0: raise ValueError('fc_pagination_contract')
            if expected is None: expected = total
            if total != expected: raise ValueError('fc_pagination_changed')
            if not batch and received_source_rows < expected: raise ValueError('fc_pagination_incomplete')
            if any(str(r.get('gid')) != str(config['game_id']) for r in batch): raise FCContractError('fc_filter_not_applied')
            received_source_rows += len(batch)
            if received_source_rows > expected: raise ValueError('fc_pagination_contract')
            if name.startswith('native-pid-'):
                batch, dropped = native_page_rows(batch, seen_ids)
                duplicates_dropped += dropped
            ids = [int(r['id']) for r in batch]
            if len(set(ids)) != len(ids) or seen_ids.intersection(ids): raise ValueError('fc_duplicate_page_records')
            if not current and ids and (ids != sorted(ids, reverse=True) or ids[0] >= previous_id): raise ValueError('fc_stable_sort_not_applied')
            seen_ids.update(ids)
            if ids: previous_id = ids[-1]
            rows.extend(batch)
            if received_source_rows == expected:
                observations.append({'dataset': name, 'pages': page, 'source_total': total, 'received': len(rows),
                                     'received_source_rows':received_source_rows, 'duplicatesDropped':duplicates_dropped})
                return rows
            time.sleep(0.1)
        raise ValueError('fc_page_budget_exceeded')
    base = [('gid', config['game_id'], '='), ('pay_status', 1, '=')]
    paid, missing_days = [], []
    cursor = datetime.strptime(query['period']['start'], '%Y-%m-%d %H:%M')
    stop = datetime.strptime(query['period']['end'], '%Y-%m-%d %H:%M')
    if cursor < stop:
        try:
            paid = pages(base + [('paytime', cursor.strftime('%Y-%m-%d %H:%M:%S') + ',' + stop.strftime('%Y-%m-%d %H:%M:%S'), 'RANGE')], 'paid')
            cursor = stop
        except (PermissionError, FCContractError): raise
        except (ValueError, OSError):
            if __name__ == '__main__': print('FC full range unavailable; retry by natural day', file=sys.stderr, flush=True)
    while cursor < stop:
        end = min(cursor.replace(hour=0,minute=0)+timedelta(days=1),stop)
        try:
            paid.extend(pages(base + [('paytime', cursor.strftime('%Y-%m-%d %H:%M:%S') + ',' + end.strftime('%Y-%m-%d %H:%M:%S'), 'RANGE')], 'paid-' + cursor.date().isoformat()))
        except (PermissionError, FCContractError): raise
        except (ValueError, OSError):
            missing_days.append(cursor.date().isoformat())
            if __name__ == '__main__': print('FC read missing day ' + cursor.date().isoformat(), file=sys.stderr, flush=True)
        cursor = end
    if missing_days and not paid: raise ValueError('fc_paid_days_unavailable')
    def native_relations(rows, period):
        from fc_dashboard import native_membership
        if native_state['deadline'] is None: native_state['deadline'] = time.monotonic()+config.get('native_seconds_budget',180)
        native_state['active'] = True
        try: return native_membership(read,pages,rows,period,config)
        finally: native_state['active'] = False
    native_coverage = {'status':'unavailable','reason':'native_product_relation_unavailable'}
    if shipping_reader is not None:
        try:
            paths, native_coverage = native_relations(paid, query['period'])
            config = {**config, '_category_paths':paths}
        except PermissionError: raise
        except Exception:
            # Partial PID joins are never published as a complete whole-order classification.
            for row in paid:
                row.pop('_fc_native_items', None); row.pop('_fc_items_complete', None)
    active, backlog_failed_groups = [], []
    for progress in range(1, 10):
        try: active.extend(pages(base + [('progress', progress, '=')], 'current-' + str(progress)))
        except PermissionError: raise
        except (ValueError, OSError): backlog_failed_groups.append(progress)
    def mapped(raw_rows):
        return deduplicate([row for row in (normalize(r, config, site_ids) for r in raw_rows) if row is not None])
    all_paid, all_active = mapped(paid), mapped(active)
    # The upstream RANGE includes its upper edge; our natural-day contract excludes it.
    lo, hi = query['period']['start'], query['period']['end']
    missing_time = sum(not r['paid_at'] for r in all_paid)
    in_period = [r for r in all_paid if r['paid_at'] and lo.replace(' ', 'T') <= r['paid_at'][:16] < hi.replace(' ', 'T')]
    backlog = [r for r in all_active if not r['terminal']]
    captured = datetime.now(timezone.utc).isoformat()
    content = {'orders': in_period, 'backlog': backlog, 'as_of': captured,
               'coverage': {'period': query['period'], 'backlog': 'all_authorized_open_fc_orders_no_paid_date_filter',
                            'site_rule': '266 main; all other configured website ids satellite; explicit distribution ids excluded',
                            'native_classification': native_coverage, 'site_count': len(site_ids), 'observations': observations, 'missing_payment_time': missing_time,
                            'unknown_scope_orders': sum(r['site_group'] == 'unknown' for r in in_period),
                            'excluded_distribution_orders': sum(r['site_group'] == 'distribution_group' for r in in_period),
                            'distribution_shop_verification': 'not_verified_no_shop_or_group_field',
                            'deduplicated_paid_records': len(paid) - len(all_paid)},
               'data_status': 'partial' if missing_time or missing_days or backlog_failed_groups else 'available'}
    content['coverage'].update(stable_sort='source_id_descending', backlog_sort='source_native_order_total_and_unique_verified', paid_complete=not missing_days and not missing_time and not any(r['site_group']=='unknown' for r in in_period), missing_days=missing_days, backlog_status='partial' if backlog_failed_groups else 'available', backlog_failed_groups=backlog_failed_groups)
    content['shipping'], content['shipping_orders'] = [], []
    content['shipping_coverage'] = {'status': 'unavailable', 'reason': 'shipping_reader_unavailable'}
    if shipping_reader is not None:
        shipping_read_complete, known = False, {}
        try:
            from fc_dashboard import shipping_membership
            shipping_payload = shipping_reader(query['period'])
            shipping = shipping_payload['rows'] if isinstance(shipping_payload,dict) else shipping_payload
            reconciliation = shipping_payload.get('coverage',{}) if isinstance(shipping_payload,dict) else {}
            if not isinstance(shipping,list) or not isinstance(reconciliation,dict): raise ValueError('shipping_source_contract')
            # Publish the independent Order read before optional Admin enrichment.
            # A later membership failure cannot invalidate its native reconciliation.
            content['shipping'] = shipping
            content['shipping_coverage'] = {'source': 'Order /order/admin_delivery/index.html', 'game_id':1322,
                'date_basis':'trade_at', 'period':query['period'],
                'reconciliation_status':'not_verified', 'native_summary_reconciled':False, **reconciliation,
                'status':'partial', 'membership_status':'pending'}
            shipping_read_complete = True
            # Payment membership is insufficient for transaction-time deliveries; resolve their exact whole orders.
            known = {(r.get('site'), r['id']): r for r in backlog + in_period if r.get('site') and r.get('category_status')=='verified'}
            missing = [r for r in shipping if (r['source'], r['sn']) not in known]
            raw_resolved = []
            resolved, failures = shipping_membership(request, missing, config, site_ids, normalize, raw_results=raw_resolved)
            # Shipping time and payment time are separate cohorts. Resolve older payments on their actual dates.
            groups = {}
            for row in raw_resolved:
                day = str(row.get('paytime') or '')[:10]
                groups.setdefault(day, []).append(row)
            classification_failures = 0
            for index, (day, batch) in enumerate(sorted(groups.items())):
                if index >= config.get('native_payment_date_budget',32):
                    classification_failures += len(batch); continue
                try:
                    end = (datetime.strptime(day,'%Y-%m-%d')+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
                    paths, proof = native_relations(batch, {'start':day+' 00:00','end':end})
                    resolved = [r for r in resolved if (str(r.get('site_id')),r['id']) not in {(str(v.get('site_id')),str(v['order_no'])) for v in batch}]
                    resolved.extend(normalize(r,{**config,'_category_paths':paths},site_ids) for r in batch)
                except PermissionError: raise
                except Exception: classification_failures += len(batch)
            known.update({(r.get('site'), r['id']): r for r in resolved})
            content['shipping'], content['shipping_orders'] = shipping, list(known.values())
            content['shipping_coverage'] = {'status': 'available' if not failures else 'partial',
                'membership_status': 'available' if not failures else 'partial',
                'source': 'Order /order/admin_delivery/index.html', 'game_id': 1322,
                'date_basis': 'trade_at', 'period': query['period'], 'membership_failures': failures,
                'reconciliation_status': 'not_verified', 'native_summary_reconciled': False,
                'outside_payment_classification_failures': classification_failures, **reconciliation}
        except PermissionError: raise
        except Exception:
            if shipping_read_complete:
                content['shipping_orders'] = list(known.values())
                content['shipping_coverage'].update(status='partial', membership_status='partial',
                    classification_status='partial', reason='shipping_membership_failed')
            else:
                content['shipping_coverage'] = {'status': 'unavailable', 'reason': 'shipping_source_failed'}
    if shipping_reader is not None:
        by_date = {}
        for row in active:
            day = str(row.get('paytime') or '')[:10]
            by_date.setdefault(day, []).append(row)
        for index, (day,batch) in enumerate(sorted(by_date.items())):
            if index >= config.get('native_payment_date_budget',32): continue
            try:
                end=(datetime.strptime(day,'%Y-%m-%d')+timedelta(days=1)).strftime('%Y-%m-%d %H:%M')
                paths, proof=native_relations(batch,{'start':day+' 00:00','end':end})
                config={**config,'_category_paths':paths}
            except PermissionError: raise
            except Exception: pass
    content['backlog'] = [r for r in mapped(active) if not r['terminal']]
    content['coverage']['native_relation_budget'] = {k:v for k,v in native_state.items() if k in ('requests','budget_exhausted')}
    content['snapshot_id'] = 'fc-detail-' + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:20]
    return content

if __name__ == '__main__':
    sys.path.insert(0, '/opt/sales-dashboard/collector')
    from p2pah_auth import Session
    args = json.loads(sys.argv[1]); session = Session()
    def request(path):
        status, value = session.get_admin(path)
        return status, json.dumps(value).encode('utf-8')
    def shipping_reader(period):
        from fc_dashboard import collect_shipping
        return collect_shipping(session, period)
    try:result = collect(request, args['query'], args['config'], shipping_reader=shipping_reader)
    except PermissionError:sys.exit(77)
    finally:session.close()
    print(json.dumps(result, ensure_ascii=False))
