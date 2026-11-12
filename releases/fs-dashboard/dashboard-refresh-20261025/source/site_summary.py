"""MMOEXP-native aggregates through the existing direct Admin API."""
from datetime import datetime, timezone
import json

ENDPOINT='/admin/order.Order/orderStaticsDetailByEs'


def collect(q, definition, *, local_repeat=None):
    if q.get('profile')=='RS' or q.get('profit_site')!='main':
        raise ValueError('main_site_summary_scope')
    from summary_bridge import dc_request
    from supplement_fields import extract
    from rs_admin import native_rows,number
    payload=dict(order_status='',pay_status=1,game=definition[3],site=266,
            country_code=q.get('country_code',''),client='',date=[q['period']['start'],q['period']['end']],pay_type='',time_unit=1,cid='',discount_code='',product_type='')
    status,body=dc_request(ENDPOINT,data=payload)
    if status in (301,302,401,403):raise PermissionError('main_site_admin_denied')
    if status!=200 or len(body)>8*1024*1024:raise OSError('main_site_admin_read_failed')
    value=json.loads(body)
    if value.get('code')!=1:raise ValueError('main_site_admin_contract')
    raw=value['data']
    if isinstance(raw,dict) and isinstance(raw.get('data'),dict):raw=raw['data']
    mapped=extract(raw);rows=native_rows(raw,q['period'])
    channels=mapped['dimensions'].get('channels') or []
    if (number(raw['total'],True)>0 and len(channels)!=1) or any((r.get('code') or r.get('name'))!='www.mmoexp.com' for r in channels):
        raise ValueError('main_site_filter_not_applied')
    for metric in mapped['metrics'].values():metric['scope']='MMOEXP'
    from admin_scope import enrich
    result = dict(system='admin.p2pah.cn',endpoint=ENDPOINT,status='available',currency='USD',period=q['period'],
        normalisedScope='main-website',filters=payload,capturedAt=datetime.now(timezone.utc).isoformat(),
        sourceDataAsOf=None,asOfStatus='not_provided_by_upstream',rows=rows,seriesGranularity='day-or-hour',labelsVerified=True,**mapped)

    return enrich(result, raw, local_repeat)
