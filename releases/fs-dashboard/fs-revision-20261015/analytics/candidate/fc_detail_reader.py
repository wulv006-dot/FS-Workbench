"""Runs inside the existing Admin session container, using its existing auth helper."""
import hashlib, json, sys, time
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode
from urllib.error import URLError
sys.path.insert(0, '/usr/local/bin')
from p2pah_session_service import SessionManager, read_private_config
from fc_detail_model import normalize, deduplicate

class FCContractError(ValueError):
    pass

def collect(request, query, config):
    def read(path):
        for attempt in range(3):
            try: return request(path)
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
            if not batch and len(rows) < expected: raise ValueError('fc_pagination_incomplete')
            if any(str(r.get('gid')) != str(config['game_id']) for r in batch): raise FCContractError('fc_filter_not_applied')
            ids = [int(r['id']) for r in batch]
            if len(set(ids)) != len(ids) or seen_ids.intersection(ids): raise ValueError('fc_duplicate_page_records')
            if not current and ids and (ids != sorted(ids, reverse=True) or ids[0] >= previous_id): raise ValueError('fc_stable_sort_not_applied')
            seen_ids.update(ids)
            if ids: previous_id = ids[-1]
            rows.extend(batch)
            if len(rows) >= expected:
                observations.append({'dataset': name, 'pages': page, 'source_total': total, 'received': len(rows)})
                return rows
            time.sleep(0.1)
        raise ValueError('fc_page_budget_exceeded')
    base = [('gid', config['game_id'], '='), ('pay_status', 1, '=')]
    paid, missing_days = [], []
    cursor = datetime.strptime(query['period']['start'], '%Y-%m-%d %H:%M')
    stop = datetime.strptime(query['period']['end'], '%Y-%m-%d %H:%M')
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
    active, backlog_failed_groups = [], []
    for progress in range(1, 10):
        try: active.extend(pages(base + [('progress', progress, '=')], 'current-' + str(progress)))
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
                            'site_count': len(site_ids), 'observations': observations, 'missing_payment_time': missing_time,
                            'unknown_scope_orders': sum(r['site_group'] == 'unknown' for r in in_period),
                            'excluded_distribution_orders': sum(r['site_group'] == 'distribution_group' for r in in_period),
                            'distribution_shop_verification': 'not_verified_no_shop_or_group_field',
                            'deduplicated_paid_records': len(paid) - len(all_paid)},
               'data_status': 'partial' if missing_time or missing_days or backlog_failed_groups else 'available'}
    content['coverage'].update(stable_sort='source_id_descending', backlog_sort='source_native_order_total_and_unique_verified', paid_complete=not missing_days, missing_days=missing_days, backlog_status='partial' if backlog_failed_groups else 'available', backlog_failed_groups=backlog_failed_groups)
    content['snapshot_id'] = 'fc-detail-' + hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()[:20]
    return content

if __name__ == '__main__':
    args = json.loads(sys.argv[1]); manager = SessionManager(read_private_config())
    if not manager.ensure(): raise RuntimeError('existing_auth_unavailable')
    with manager.lock:
        result = collect(lambda path: manager.request(path, token=manager.token), args['query'], args['config'])
    print(json.dumps(result, ensure_ascii=False))
