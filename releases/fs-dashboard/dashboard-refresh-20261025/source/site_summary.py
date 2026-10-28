"""MMOEXP-native aggregates through the existing shared Admin session, without login or renewal."""
from datetime import datetime, timezone
import sys

ENDPOINT='/admin/order.Order/orderStaticsDetailByEs'


def collect(q, definition):
    if q.get('profile')=='RS' or q.get('profit_site')!='main':
        raise ValueError('main_site_summary_scope')
    sys.path.insert(0,'/opt/sales-dashboard/collector')
    sys.path.insert(0,'/opt/fs-transaction-snapshot')
    import p2pah_auth as auth
    from supplement_fields import extract
    from rs_admin import native_rows,number
    session=auth.Session()
    try:
        token,error=auth.admin_token_from_service()
        if error:raise OSError(error)
        session.bind_admin_token(token);del token
        payload=dict(order_status='',pay_status=1,game=definition[3],site=266,
            country_code='',client='',date=[q['period']['start'],q['period']['end']],pay_type='',time_unit=1,cid='',discount_code='',product_type='')
        response=session.admin.request('POST',auth.ADMIN_API+ENDPOINT,json=payload,headers={'batoken':session.token},timeout=85,allow_redirects=False)
        if response.status_code in (301,302,401,403):raise PermissionError('main_site_admin_denied')
        if response.status_code!=200 or len(response.content)>8*1024*1024:raise OSError('main_site_admin_read_failed')
        value=response.json()
        if value.get('code')!=1:raise ValueError('main_site_admin_contract')
        raw=value['data']
        if isinstance(raw,dict) and isinstance(raw.get('data'),dict):raw=raw['data']
        mapped=extract(raw);rows=native_rows(raw,q['period'])
        channels=mapped['dimensions'].get('channels') or []
        if (number(raw['total'],True)>0 and len(channels)!=1) or any((r.get('code') or r.get('name'))!='www.mmoexp.com' for r in channels):
            raise ValueError('main_site_filter_not_applied')
        for metric in mapped['metrics'].values():metric['scope']='MMOEXP'
        return dict(system='admin.p2pah.cn',endpoint=ENDPOINT,status='available',currency='USD',period=q['period'],
            normalisedScope='main-website',filters=payload,capturedAt=datetime.now(timezone.utc).isoformat(),
            sourceDataAsOf=None,asOfStatus='not_provided_by_upstream',rows=rows,seriesGranularity='day-or-hour',labelsVerified=True,**mapped)
    finally:session.close()
