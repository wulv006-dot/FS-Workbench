"""Dashboard paid-order procurement profit; existing sessions, accounting and worker pool."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from decimal import Decimal
import copy,fcntl,hashlib,json,sys,time
from live_summary import query as summary_query
from rs_admin import SITES,SERVERS,CATEGORIES

CONTRACT='same-order-actual-profit-v1'

def selection(params,profiles):
    if params.get('mode')!=['actual-profit']:raise ValueError('actual_profit_mode')
    values={**params,'mode':['summary']}
    if values.get('refresh')==['1']:values['refresh']=['true']
    q=summary_query(values,profiles)
    # Admin summary metadata must not invalidate the independent profit archive.
    q.pop('admin_site',None)
    if q['profile']!='RS':q['site']='www.mmoexp.com'
    if q['profile']!='RS' and q['profit_category']!='-1':raise ValueError('shipping_category_is_not_actual_cost_scope')
    return q

def public(data,q):
    result=copy.deepcopy(data)
    if result.get('actualContract')!=CONTRACT:raise ValueError('actual_profit_contract')
    result['selection']={k:q[k] for k in ('profile','start','end','grain','rs_site','rs_server','rs_category','profit_site') if k in q}
    result['actualPeriod']=result.get('actualPeriod',q['period'])
    result['period']={k:q[k] for k in ('start','end')}
    return result

def main_scope(q):
    return q['grain']=='day' and (q['profile']!='RS' and q['profit_site']=='main' or
        q['profile']=='RS' and q['rs_site']=='mmoexp' and q['rs_server']=='all' and q['rs_category']=='all')

def order_rows(session,q,gid):
    """Native aid/cid joins may repeat an identical whole order; enumerate before deduplication."""
    from channel_source import search
    site=SITES[q['rs_site']][0] if q['profile']=='RS' else 266 if q['profit_site']=='main' else ''
    filters=[('pay_status','=',1)]
    if gid:filters.append(('gid','=',gid))
    if site!='':filters.append(('site_id','=',site))
    if q['profile']=='RS':
        if q['rs_server']!='all':filters.append(('aid','=',SERVERS[q['rs_server']][0]))
        if q['rs_category']!='all':filters.append(('cid','=',CATEGORIES[q['rs_category']][0]))
    lo,hi=(datetime.strptime(q['period'][k],'%Y-%m-%d %H:%M') for k in ('start','end'))
    rows=[];seen={};scanned=0;deadline=time.monotonic()+180
    while lo<hi:
        stop=min(lo+timedelta(days=28),hi);rules=filters+[('paytime','RANGE',lo.strftime('%Y-%m-%d %H:%M:%S')+','+(stop-timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S'))]
        received=0;expected=None;previous=float('inf')
        for page in range(1,501):
            if time.monotonic()>deadline:raise TimeoutError('actual_orders_deadline')
            status,value=session.get_admin('/admin/order.Order/index',page=page,limit=100,order='id,desc',**search(rules))
            if status in (301,302,401,403):raise PermissionError('actual_admin_denied')
            data=value.get('data') or {};batch=data.get('list');total=data.get('total')
            if status!=200 or value.get('code')!=1 or type(total)is not int or total<0 or not isinstance(batch,list) or len(batch)>100 or expected is not None and total!=expected:raise ValueError('actual_order_pagination')
            expected=total
            for row in batch:
                identity=row.get('id');when=row.get('paytime','');signature=json.dumps(row,sort_keys=True,ensure_ascii=False)
                if type(identity)is not int or identity<=0 or identity>previous or not lo.strftime('%Y-%m-%d %H:%M:%S')<=when<stop.strftime('%Y-%m-%d %H:%M:%S'):raise ValueError('actual_order_identity_time')
                previous=identity
                if gid and str(row.get('gid'))!=str(gid) or site!='' and str(row.get('site_id'))!=str(site) or str(row.get('pay_status')) not in ('1','2'):raise ValueError('actual_order_scope')
                if identity in seen:
                    if seen[identity]!=signature:raise ValueError('actual_order_conflict')
                else:seen[identity]=signature;rows.append(row)
            scanned+=len(batch);received+=len(batch)
            if received==expected:break
            if not batch or received>expected:raise ValueError('actual_orders_incomplete')
        else:raise ValueError('actual_order_page_budget')
        lo=stop
    if len({str(r.get('order_no') or '') for r in rows})!=len(rows) or any(not r.get('order_no') for r in rows):raise ValueError('actual_order_number_identity')
    return rows,dict(complete=True,sourceScanned=scanned,uniqueOrders=len(rows),duplicateJoinRows=scanned-len(rows),dateBasis='paytime',site=str(site) or 'all')

def normalized(rows,costs):
    from channel_effects import money,number,EMPTY_COST
    index=defaultdict(list);seen=set()
    for r in costs:
        if str(r.get('genre')) not in ('1','订单发货'):continue
        identity=str(r.get('delivery_id') or '')
        if not identity or identity in seen:raise ValueError('actual_delivery_identity')
        seen.add(identity);index[(r['source'],r['sn'])].append(r)
    result=[]
    for raw in rows:
        site=(raw.get('site') or {}).get('full_title')
        if not site:raise ValueError('actual_admin_site_label')
        deliveries=index.get((site,str(raw['order_no'])),[])
        numbers=[money(r.get('cost_total')) for r in deliveries]
        if any(v is None or v<0 for v in numbers):raise ValueError('actual_delivery_cost')
        cost=number(sum(numbers,Decimal(0))) if numbers else None
        usd=money(raw.get('amount_usd_format'));sale=money(raw.get('amount_rmb_format'))
        if usd is None or usd<0 or sale is not None and sale<0:raise ValueError('actual_admin_amount')
        result.append(dict(orderNo=str(raw['order_no']),gid=str(raw.get('gid')),game=str(raw.get('game_format') or ''),
            paidAt=raw['paytime'],day=raw['paytime'][:10],salesUsd=number(usd),adminSaleCny=number(sale),
            status=str(raw.get('status_format') or '状态未提供'),payStatus=str(raw.get('pay_status')),refunded=str(raw.get('pay_status'))=='2' or str(raw.get('status_format','')).startswith('已退款'),
            site=site,codeKey='',promoterUid='',coupons=[],attribution='未用于渠道归因',conflict=False,
            **{**EMPTY_COST,'costCny':cost,'deliveryRows':len(deliveries)}))
    return result

def scoped_accounting(data):
    from channel_source import apply_cost_overrides
    data=apply_cost_overrides(data)
    main={r['orderNo'] for r in data['orders'] if r.get('site')=='www.mmoexp.com'}
    for field in ('costOverrides','testOrders'):data[field]={sn:r for sn,r in data[field].items() if sn in main}
    return data

def collect_orders(q,profile,root):
    from channel_source import COLLECTOR
    sys.path.insert(0,COLLECTOR);import p2pah_auth as auth
    session=auth.Session();token,reason=auth.admin_token_from_service()
    if not token:raise OSError('actual_shared_admin_unavailable')
    session.bind_admin_token(token);del token
    try:rows,proof=order_rows(session,q,'' if q['profile']=='MMOEXP' else profile[3])
    finally:session.close()
    stamp=datetime.now(timezone.utc).isoformat()
    return scoped_accounting(dict(period={k:q[k] for k in ('start','end')},actualPeriod=q['period'],generatedAt=stamp,
        sources=dict(orders=dict(status='complete',source='Admin原生订单列表',generatedAt=stamp,coverage=proof),cost=dict(status='unavailable',generatedAt=None)),
        orders=normalized(rows,[]),rawMembership=rows))

def fill_costs(data,q,profile,root):
    from channel_source import COLLECTOR
    from channel_cost_source import collect
    sys.path.insert(0,COLLECTOR);import p2pah_auth as auth
    start=q['period']['start'][:10]
    from channel_effects import TZ
    cutoff=datetime.now(TZ).replace(second=0,microsecond=0)-timedelta(minutes=1)
    source=SITES[q['rs_site']][1] if q['profile']=='RS' and q['rs_site']!='all' else 'www.mmoexp.com' if q['profile']!='RS' and q['profit_site']=='main' else ''
    with (root/'order-deliveries.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        session=auth.Session()
        try:costs=collect(session,start,cutoff.date().isoformat(),until=cutoff.strftime('%Y-%m-%d %H:%M'),source=source,gid=str(profile[2]))
        finally:session.close()
    data['orders']=normalized(data.pop('rawMembership'),costs)
    stamp=datetime.now(timezone.utc).isoformat();data['sources']['cost']=dict(status='complete',source='Order订单发货记录，同网站及订单号实际成本',generatedAt=stamp,until=cutoff.isoformat(),unassignedSourceRows=sum(not r['source'] for r in costs))
    return scoped_accounting(data)

class ActualProfitService:
    def __init__(self,channels,profiles,reader=collect_orders,cost_reader=fill_costs,clock=time.monotonic):
        self.channels,self.profiles,self.reader,self.cost_reader,self.clock=channels,profiles,reader,cost_reader,clock
        self.root=channels.root/'actual-profit';self.jobs={};self.starts={};self.denied={}
        channels.actual_jobs=self.jobs
    def capture(self,key,target,q,previous):
        from channel_effects import profit_view
        stage='orders'
        try:
            self.root.mkdir(mode=0o700,parents=True,exist_ok=True)
            with (self.channels.root/'collector.lock').open('a+b') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                data=self.reader(q,self.profiles[q['profile']],self.channels.root)
            # Publish complete revenue membership first; missing cost remains unknown.
            if previous and previous.get('data'):
                old={r['orderNo']:r for r in previous['data']['orders']}
                for row in data['orders']:
                    p=old.get(row['orderNo'])
                    if p and p.get('site')==row.get('site'):row.update({k:p.get(k) for k in ('costCny','deliveryRows')})
                data['sources']['cost']=previous['data']['sources']['cost']
            snapshot={k:v for k,v in data.items() if k!='rawMembership'}
            self.channels.publish(dict(data=snapshot,query=q,capturedAt=time.time()),target)
            stage='cost'
            with self.channels.lock:self.jobs[key]='cost_pending'
            data=self.cost_reader(data,q,self.profiles[q['profile']],self.channels.root)
            profit_view(data,{'mode':'profit'})
            self.channels.publish(dict(data=data,query=q,capturedAt=time.time()),target)
            with self.channels.lock:self.jobs[key]='available';self.denied.pop(key,None)
        except Exception as error:
            with self.channels.lock:
                self.jobs[key]='denied' if isinstance(error,PermissionError) else 'deferred' if isinstance(error,BlockingIOError) else stage+'_failed'
                if isinstance(error,PermissionError):self.denied[key]=self.clock()
    def get(self,params,user):
        if not self.channels.authorizer(user):return 403,{'status':'denied','error':'admin_required'}
        q=selection(params,self.profiles)
        if main_scope(q):
            request={k:[q[k]] for k in ('start','end')};request.update(mode=['profit'],status=['valid'])
            gid=str(self.profiles[q['profile']][3])
            if gid and gid!='0':request['gid']=[gid]
            if q.get('refresh'):request['refresh']=['1']
            code,value=self.channels.get(request,user)
            return code,public(value,q) if code==200 else value
        key=hashlib.sha256(json.dumps({k:v for k,v in q.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
        target=self.root/(key+'.json')
        if any(p.is_symlink() for p in (target,self.root,*self.root.parents)):raise ValueError('actual_cache_link')
        old=json.loads(target.read_text('utf-8')) if target.is_file() else None
        with self.channels.lock:
            state=self.jobs.get(key);fresh=bool(old and 0<=time.time()-old['capturedAt']<600)
            denied=key in self.denied
            if denied and self.clock()-self.denied[key]<30:return 403,{'status':'denied','error':'actual_source_permission_denied'}
            if denied:fresh=False
            if (not fresh or q.get('refresh') or state in ('deferred','orders_failed','cost_failed')) and state not in ('pending','cost_pending') and self.clock()-self.starts.get(key,-1000)>=60:
                active=sum(v in ('pending','cost_pending') for v in self.jobs.values())+sum(v in ('pending','cost_pending') for v in self.channels.jobs.values())
                if active>=2:return 429,{'status':'busy','retryAfter':10}
                if len(self.jobs)>=256:
                    victim=next((k for k,v in self.jobs.items() if v not in ('pending','cost_pending')),None)
                    if victim is None:return 429,{'status':'busy','retryAfter':10}
                    self.jobs.pop(victim);self.starts.pop(victim,None);self.denied.pop(victim,None)
                self.starts[key]=self.clock();self.jobs[key]='pending';state='pending'
                self.channels.pool.submit(self.capture,key,target,copy.deepcopy(q),old)
        if not old or denied:return (503 if state in ('orders_failed','cost_failed') else 202),{'status':state or 'pending','retryAfter':3}
        from channel_effects import profit_view
        value=profit_view(old['data'],{'mode':'profit'});value.update(status='available',refreshing=state in ('pending','cost_pending','deferred'),costRefreshing=state=='cost_pending',costError=state=='cost_failed',sourceError=state=='orders_failed',stale=not fresh)
        return 200,public(value,q)
