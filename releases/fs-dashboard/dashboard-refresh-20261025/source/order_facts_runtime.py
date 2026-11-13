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
CHANNEL_ARCHIVE = COSTS.parent
FIELDS = ('id','order_no','site_id','site','gid','game_format','paytime','pay_status',
          'status_format','amount_usd_format','amount_rmb_format')
MARKETING_FIELDS = ('discount_code','recommend_uid','country_code','country','paytype_display','paytype')
PROMOTION_CHANNELS = {'seo':'SEO','谷歌广告':'PPC','kol':'Referral','tiktok':'Referral','tt':'Referral'}
ATTRIBUTION_RULE = 'order-channel-priority-20261113-v1'


def admin_orders(scope, request, *, marketing=False):
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
            if marketing:
                selected.update((k,row[k]) for k in MARKETING_FIELDS if k in row)
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


def collect(scope, **kwargs):
    return collect_many([scope], **kwargs)[0]


def dashboard_evidence(period, root):
    """Read matched main-site evidence from the existing completed daily cache."""
    from channel_cache import CONTRACT, days
    records, revisions = {}, {}
    for day in days(period):
        path = Path(root)/'days'/f'{day}.json'
        try:
            if any(item.is_symlink() for item in (path,*path.parents)) or path.stat().st_size > 16*1024*1024:
                continue
            raw = path.read_bytes()
            value = json.loads(raw)
            sources = value['sources']
            if (value['contract'] != CONTRACT or value['period'] != {'start':day,'end':day}
                    or sources['orders']['status'] != 'complete' or sources['orders'].get('site') != 'MMOEXP'
                    or sources['coupons']['status'] != 'complete'):
                continue
            rows = value['orders']
            index = {(day,r['orderNo'],r['gid'],r['paidAt']):r for r in rows
                     if r['day']==day and isinstance(r['coupons'],list)}
            if len(index) != len(rows):
                continue
        except (OSError, ValueError, KeyError, TypeError):
            # A missing or unusable auxiliary day cannot certify zero coupon use.
            continue
        records.update(index)
        revisions[day] = hashlib.sha256(raw).hexdigest()
    return records, revisions


def dashboard_mapping():
    from channel_effects import Attribution
    from channel_source import SALES, __file__ as channel_source_file
    raw = Path(channel_source_file).with_name('channel_mapping.json').read_bytes()
    directory_path = SALES/'promoter_dir.json'
    directory = directory_path.read_bytes() if directory_path.is_file() else b'{}'
    return Attribution(json.loads(raw), [], json.loads(directory)), hashlib.sha256(raw+b'\0'+directory).hexdigest()


def tracked_channel(source):
    # Existing 2026-10-22 exact PMax campaign identity. A generic Google tag is ambiguous.
    if isinstance(source,str) and source.strip().casefold() == 'google-fc27-pmax-coins-us':
        return 'PPC'
    return None


def effective_attribution(order, native, archived, mapping):
    from channel_effects import clean, positive_id
    fact = order['marketing_attribution']
    observed = archived or {}
    archive_source = observed.get('sourceRaw') if observed.get('sourceStatus')=='available' else None
    pinned_source = order.get('pinned_order_source')
    source = pinned_source or archive_source
    native_conflict = fact.get('status')=='conflict'
    source_conflict = order.get('pinned_order_source_conflict') is True or (not pinned_source and observed.get('sourceStatus')=='conflict')
    native_code = native.get('discount_code')
    code = native_code if isinstance(native_code,str) else observed.get('code')
    native_uid = native.get('recommend_uid')
    uid = positive_id(native_uid) or positive_id(observed.get('promoterUid'))
    project, promoter_name = None, observed.get('promoter')
    if order['site_id']=='266' and (isinstance(code,str) or uid or archived is not None):
        resolved = mapping.resolve(dict(discount_code=code,recommend_uid=uid,gid=order['gid']))
        if resolved.get('promoterUid'):
            promoter_name = resolved.get('promoter')
        if not resolved['conflict']:
            project = resolved['project']
            # The existing same-order projection may include verified configuration owners.
            archived_project = observed.get('project')
            if (project in ('未归类','推荐人渠道待核','无推广归属') and archived_project
                    and not observed.get('conflict') and (native_code is None or code==observed.get('code'))):
                project = archived_project
    promotion_channel = PROMOTION_CHANNELS.get((project or '').casefold())
    source_channel = tracked_channel(source)
    native_channel = order['channel'] if order['channel']!='unknown' else None
    if native_conflict:
        channel, basis, detail = 'unknown', 'native_conflict', None
    elif native_channel:
        channel, basis, detail = native_channel, 'native_channel', (fact.get('raw') or {}).get('source_raw')
    elif source_conflict:
        channel, basis, detail = 'unknown', 'order_source_conflict', None
    elif source_channel:
        channel, basis, detail = source_channel, 'order_source', source
    elif promotion_channel:
        channel, basis, detail = promotion_channel, 'promotion', project
    else:
        channel, basis, detail = 'unknown', 'unknown', None
    coupons = observed.get('coupons')
    return dict(channel=channel, basis=basis, detail=detail, order_source=source,
        conflict=native_conflict or source_conflict or len({c for c in (native_channel,source_channel,promotion_channel) if c})>1,
        discount_code=bool(code.strip()) if isinstance(code,str) else None,
        promoter=True if uid else False if native_uid is not None or archived is not None else None,
        coupon=bool(coupons) if coupons is not None else None,
        coupon_templates=[item['title'] for item in coupons or () if isinstance(item,dict) and isinstance(item.get('title'),str)],
        promotion_project=project if project not in (None,'未归类','推荐人渠道待核','无推广归属') else None,
        filter_row=dict(orderNo=order['order_no'],gid=order['gid'],
            refunded=order['pay_status']=='2' or order['status'].startswith('已退款'),
            country=clean(native.get('country_code') or native.get('country') or observed.get('country')) or None,
            payment=clean(native.get('paytype_display') or native.get('paytype') or observed.get('payment')) or None,
            project=project, code=code, codeKey=code.strip().casefold() if isinstance(code,str) else None,
            promoter=promoter_name, coupons=coupons))


def collect_dashboard(scope, *, channel_archive=CHANNEL_ARCHIVE, **kwargs):
    return collect_many([scope], channel_archive=channel_archive, **kwargs)[0]


def collect_many(scopes, *, request=None, db=DB, archive=ARCHIVE, costs=COSTS, dataset_reader=None,
                 channel_archive=None):
    """One source revision for same-period consumers; no persistent private cache."""
    if not scopes or any((s['start'], s['end']) != (scopes[0]['start'], scopes[0]['end']) for s in scopes):
        raise ValueError('order_facts_batch_period')
    scope = scopes[0]
    if request is None:
        from summary_bridge import dc_request
        request = dc_request
    if dataset_reader is None:
        from es_order_structure import archived_dataset
        dataset_reader = archived_dataset
    dashboard = channel_archive is not None
    rows = admin_orders(scope, request, marketing=dashboard)
    revision_rows = [{k:r[k] for k in FIELDS} for r in rows] if dashboard else rows
    revision = hashlib.sha256(json.dumps(revision_rows, sort_keys=True,ensure_ascii=False).encode()).hexdigest()
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
    coverage = dict(admin_complete=True,source_revision=revision,
        admin_date_basis='paytime',admin_snapshot=False,admin_source_rows=len(rows),
        admin_payment_membership='pay_status_1_or_2',cost=cost_proof,
        attribution_availability=attribution_status,
        captured_at=datetime.now(timezone.utc).isoformat())
    catalog = dict(rows=rows,complete=True,revision=revision,
        scope=dict(site='all',game='all',pay_status='1',start=scope['start'],end=scope['end']))
    result = []
    if dashboard:
        evidence, archive_revisions = dashboard_evidence(scope, channel_archive)
        mapping, mapping_revision = dashboard_mapping()
    for scope in scopes:
        selected = [r for r in rows if str(r.get('pay_status')) in ('1','2')
            and (scope['site_id']=='all' or str(r['site_id'])==scope['site_id'])
            and (scope['gid']=='all' or str(r.get('gid'))==scope['gid'])]
        order_keys = {((r.get('site') or {}).get('full_title'),str(r['order_no'])) for r in selected}
        selected_deliveries = [r for r in deliveries if (r.get('source'),str(r.get('sn') or '')) in order_keys]
        value = project_order_facts(selected,dataset,selected_deliveries,scope=scope,
            source_coverage=coverage,identity_catalog=catalog)
        if dashboard:
            native = {(str(r['site_id']),str(r['order_no'])):r for r in selected}
            for order in value['orders']:
                raw = native[(order['site_id'],order['order_no'])]
                paid = order['paid_at']
                key = (paid[:10],order['order_no'],order['gid'],paid)
                archived = evidence.get(key) if order['site_id']=='266' else None
                order['effective_attribution'] = effective_attribution(order,raw,archived,mapping)
            value['source_coverage']['effective_attribution'] = dict(rule=ATTRIBUTION_RULE,
                mapping_revision=mapping_revision, day_revisions=archive_revisions)
        result.append(value)
    return result
