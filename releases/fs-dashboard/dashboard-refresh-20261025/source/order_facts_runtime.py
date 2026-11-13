"""Read existing Admin, pinned ES and delivery sources without publishing anything."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlencode

from order_facts_source import project_order_facts

DB = Path('/var/lib/fs-user-analytics/customers.sqlite3')
ARCHIVE = Path('/var/lib/fc27-es-exports')
COSTS = Path('/var/lib/fs-channel-effects/order-deliveries.json')
FIELDS = ('id','order_no','site_id','site','gid','game_format','paytime','pay_status',
          'status_format','amount_usd_format','amount_rmb_format')


def admin_orders(scope, request):
    """Enumerate all native identities first; derive selected site/game afterwards."""
    from channel_source import search
    lo, hi = scope['start']+' 00:00:00', scope['end']+' 23:59:59'
    # Omitting pay_status activates a narrower native default, not all statuses.
    rules = [('pay_status','=',1),('paytime','RANGE',lo+','+hi)]
    result, seen, expected, previous = [], {}, None, None
    deadline = time.monotonic()+180
    for page in range(1, 501):
        if time.monotonic() > deadline:raise TimeoutError('order_facts_admin_deadline')
        params = dict(page=page, limit=100, order='id,desc', **search(rules))
        status, raw = request('/admin/order.Order/index?'+urlencode(params), method='GET')
        if status in (301,302,401,403):raise PermissionError('order_facts_admin_denied')
        value = json.loads(raw)
        data = value.get('data') or {}
        rows, total = data.get('list'), data.get('total')
        if (status != 200 or value.get('code') != 1 or not isinstance(rows,list)
                or type(total) is not int or not 0 <= total <= 50000 or len(rows)>100
                or expected is not None and total != expected):
            raise ValueError('order_facts_admin_pagination')
        expected = total
        for row in rows:
            ident = row.get('id')
            if (type(ident) is not int or ident <= 0 or ident in seen
                    or previous is not None and ident >= previous
                    or not lo <= str(row.get('paytime') or '') <= hi
                    or str(row.get('pay_status')) not in ('1','2')
                    or not row.get('order_no') or not row.get('site_id')):
                raise ValueError('order_facts_admin_identity_scope')
            previous = ident
            selected = {k:row.get(k) for k in FIELDS}
            seen[ident] = True
            result.append(selected)
        if len(result) == expected:break
        if not rows or len(result)>expected:raise ValueError('order_facts_admin_incomplete')
    else:raise ValueError('order_facts_admin_page_budget')
    return result


def publication(db=DB):
    """No Store initialization, migrations, locks or replacement database creation."""
    db = Path(db)
    if not db.is_file():return None
    if any(p.is_symlink() for p in (db,*db.parents)):raise ValueError('order_facts_database_link')
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro', uri=True, timeout=2)) as connection:
        connection.execute('PRAGMA query_only=ON')
        row = connection.execute("SELECT value FROM meta WHERE key='weekly_publication'").fetchone()
    if row is None:return None
    if len(row[0].encode())>4*1024*1024:raise ValueError('order_facts_publication_size')
    return json.loads(row[0])


def existing_costs(path=COSTS):
    path = Path(path)
    if not path.is_file():return [], {'status':'unavailable'}
    if any(p.is_symlink() for p in (path,*path.parents)) or path.stat().st_size>128*1024*1024:
        raise ValueError('order_facts_cost_cache')
    raw = path.read_bytes()
    value = json.loads(raw)
    if value.get('contract')!='channel-order-deliveries-v1' or not isinstance(value.get('rows'),list):
        raise ValueError('order_facts_cost_contract')
    return value['rows'], dict(status='observed_only', source_revision=hashlib.sha256(raw).hexdigest(),
        generated_at=value.get('generatedAt'), period=value.get('period'),
        shipment_window_complete=value.get('complete') is True, order_cost_complete=False)


def collect(scope, *, request=None, db=DB, archive=ARCHIVE, costs=COSTS, dataset_reader=None):
    if request is None:
        from summary_bridge import dc_request
        request = dc_request
    if dataset_reader is None:
        from es_order_structure import archived_dataset
        dataset_reader = archived_dataset
    rows = admin_orders(scope, request)
    revision = hashlib.sha256(json.dumps(rows, sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    selected = [r for r in rows if str(r.get('pay_status')) in ('1','2')
        and (scope['site_id']=='all' or str(r['site_id'])==scope['site_id'])
        and (scope['gid']=='all' or str(r.get('gid'))==scope['gid'])]
    pin = publication(db)
    dataset, attribution_status = None, 'publication_unavailable'
    if pin is not None:
        cutoff = datetime.fromisoformat(pin['cutoff'])
        if datetime.fromisoformat(scope['end']).date() < cutoff.date():
            dataset = dataset_reader(dict(profile='ALL',start=scope['start'],end=scope['end']),
                                     root=Path(archive),publication=pin)
            attribution_status = 'published_pins'
        else:attribution_status = 'publication_does_not_cover_requested_end'
    deliveries, cost_proof = existing_costs(costs)
    order_keys = {((r.get('site') or {}).get('full_title'),str(r['order_no'])) for r in selected}
    deliveries = [r for r in deliveries if (r.get('source'),str(r.get('sn') or '')) in order_keys]
    coverage = dict(admin_complete=True,source_revision=revision,
        admin_date_basis='paytime',admin_snapshot=False,admin_source_rows=len(rows),
        admin_payment_membership='pay_status_1_or_2',cost=cost_proof,
        attribution_availability=attribution_status,
        captured_at=datetime.now(timezone.utc).isoformat())
    catalog = dict(rows=rows,complete=True,revision=revision,
        scope=dict(site='all',game='all',pay_status='1',start=scope['start'],end=scope['end']))
    return project_order_facts(selected,dataset,deliveries,scope=scope,source_coverage=coverage,
                               identity_catalog=catalog)
