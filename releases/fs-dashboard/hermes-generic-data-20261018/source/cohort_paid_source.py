"""Main-site Admin paid orders for ES cohort linkage; no raw identity leaves the session service."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
import time
from urllib.parse import urlencode

GAME_IDS={'FC27':1327,'D4':456,'AION2':891,'POE2':552,'NBA2K27':1329,
    'NFL27':1309,'MLB26':927,'CFB27':1307,'RS':506,'ARC_RAIDERS':925,
    'MAPLESTORY_CLASSIC':1333,'DARK_AND_DARKER':589,'WOW_FOREVER':1367,
    'ARENA_BREAKOUT_INFINITE':897,'COD_BO7':859}
SHANGHAI=timezone(timedelta(hours=8))


def checked_query(args):
    if not isinstance(args,dict) or set(args)!={'profile','start','end'} or args['profile'] not in GAME_IDS:
        raise ValueError('cohort_paid_query')
    lo,hi=(date.fromisoformat(args[k]) for k in ('start','end'))
    if lo.isoformat()!=args['start'] or hi.isoformat()!=args['end'] or not 0<=(hi-lo).days<=60 or hi>=datetime.now(SHANGHAI).date():
        raise ValueError('cohort_paid_period')
    return args


def collect(request,args):
    """Return only SHA-256 order/site-customer pseudonyms and exact paid timestamps."""
    q=checked_query(args);gid=GAME_IDS[q['profile']]
    out={'kind':'cohort_paid_orders','status':'unavailable','query':q,'orders':[],
         'coverage':{'paid_complete':False,'period':{'start':q['start']+' 00:00','end':
            (date.fromisoformat(q['end'])+timedelta(days=1)).isoformat()+' 00:00'}}}
    bounds=[(q['start']+' 00:00:00',q['end']+' 23:59:59')]
    if (date.fromisoformat(q['end'])-date.fromisoformat(q['start'])).days>=28:
        from channel_source import windows
        bounds=list(windows(q))
    deadline=time.monotonic()+850;seen={};order_ids={};observed=[];page_budget=300
    segments=[dict(start=lower,end=upper,source_total=None,received=0,complete=False) for lower,upper in bounds]
    for segment in segments:
        lower,upper=segment['start'],segment['end']
        expected=None;received=0;previous_id=float('inf');segment_seen=set()
        for page in range(1,page_budget+1):
            if deadline-time.monotonic()<=0:break
            page_budget-=1
            filters=[('gid',gid,'='),('site_id',266,'='),('pay_status',1,'='),
                ('paytime',lower+','+upper,'RANGE')]
            params={'page':page,'limit':100,'order':'id,desc'}
            for i,(field,value,operator) in enumerate(filters):
                params.update({f'search[{i}][field]':field,f'search[{i}][val]':value,
                    f'search[{i}][operator]':operator})
                if operator=='RANGE':params[f'search[{i}][render]']='datetime'
            code,raw=request('/admin/order.Order/index?'+urlencode(params),min(30,deadline-time.monotonic()))
            if code in (401,403):raise PermissionError('cohort_paid_denied')
            if code!=200 or len(raw)>8*1024*1024:raise ValueError('cohort_paid_source')
            value=json.loads(raw)
            data=value.get('data') if value.get('code')==1 else None
            if not isinstance(data,dict) or type(data.get('total')) is not int or not isinstance(data.get('list'),list):
                raise ValueError('cohort_paid_contract')
            batch=data['list'];total=data['total']
            if total<0 or len(batch)>100 or expected is not None and total!=expected:
                raise ValueError('cohort_paid_pagination_changed')
            if expected is None:
                expected=total;segment['source_total']=total
                if sum(s['source_total'] or 0 for s in segments)>30000:raise ValueError('cohort_paid_row_budget')
            ids=[]
            for row in batch:
                if str(row.get('gid'))!=str(gid) or str(row.get('site_id'))!='266' or str(row.get('pay_status'))!='1':
                    raise ValueError('cohort_paid_scope')
                ident=row.get('order_no');uid=row.get('uid');raw_id=row.get('id')
                if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) or not str(raw_id).isdigit():
                    raise ValueError('cohort_paid_identity')
                identity=int(raw_id);ids.append(identity)
                when=datetime.strptime(row.get('paytime',''),'%Y-%m-%d %H:%M:%S')
                signature=hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
                if (identity in seen and seen[identity]!=signature) or (ident in order_ids and order_ids[ident]!=identity):
                    raise ValueError('cohort_paid_duplicate_conflict')
                if not lower<=row['paytime']<=upper:raise ValueError('cohort_paid_time')
                if identity in seen:continue
                seen[identity]=signature;order_ids[ident]=identity
                customer_key=hashlib.sha256(('266:'+str(uid)).encode()).hexdigest()[:24] if str(uid).isdigit() and int(uid)>0 else None
                out['orders'].append({'id':hashlib.sha256(ident.encode()).hexdigest(),
                    'id_is_hashed':True,'customer_key':customer_key,'paid_at':when.replace(tzinfo=SHANGHAI).isoformat(),
                    'site_group':'main','platform':'all'})
            if ids!=sorted(ids,reverse=True) or ids and ids[0]>=previous_id or len(set(ids))!=len(ids) or segment_seen.intersection(ids):
                raise ValueError('cohort_paid_sort_or_duplicate')
            if ids:previous_id=ids[-1]
            segment_seen.update(ids);received+=len(batch);segment['received']=received
            observed.append({'page':page,'rows':len(batch),'total':total,'start':lower,'end':upper})
            if received>total:raise ValueError('cohort_paid_pagination_changed')
            if received==total:
                segment['complete']=True
                break
            if not batch:raise ValueError('cohort_paid_empty_page')
        if not segment['complete']:break
    complete=all(s['complete'] for s in segments)
    expected=sum(s['source_total'] for s in segments) if all(s['source_total'] is not None for s in segments) else None
    out.update(status='available' if complete else 'partial',coverage={**out['coverage'],
        'paid_complete':complete,'source_total':expected,'received':len(seen),
        'pages':observed,'windows':segments,'source_scope':'Admin paid orders; exact gid + main site 266; site-local UID',
        'missing_payment_time':0,'missing_days':[],
        'missing_windows':[dict(start=s['start'],end=s['end']) for s in segments if not s['complete']]},
        snapshot_id='cohort-paid-'+hashlib.sha256(json.dumps(out['orders'],sort_keys=True).encode()).hexdigest()[:20],
        as_of=datetime.now(timezone.utc).isoformat())
    return out


def read_service(args):
    import sys
    sys.path.insert(0,'/opt/sales-dashboard/collector')
    import p2pah_auth as auth
    q=checked_query(args)
    client=auth.Session()
    def request(path,timeout):
        response=client.admin.get(auth.ADMIN_API+path,timeout=timeout)
        return response.status_code,response.content
    try:value=collect(request,q)
    finally:client.close()
    if len(json.dumps(value).encode())>16*1024*1024:raise ValueError('cohort_paid_response_size')
    if value.get('kind')!='cohort_paid_orders' or value.get('query')!=q:
        raise ValueError('cohort_paid_response_contract')
    return value
