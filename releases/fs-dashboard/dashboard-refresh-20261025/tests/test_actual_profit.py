"""Fictional orders: one paid cohort, whole-order income, exact site and daily sums."""
import copy,hashlib,json,os,sys,tempfile,threading,time,unittest
from contextlib import nullcontext
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE));sys.path.append(str(Path(__file__).parent/'fixtures'))
if os.name=='nt':sys.modules['fcntl']=SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *args:None)
from actual_profit import ActualProfitService,selection,normalized,order_rows,main_scope,_closed_complete
from channel_effects import profit_view,view,Attribution,normalize,ChannelService
from live_summary import SummaryCache,query,key_of
from daily_archive import complete_summary,summary_key

PROFILES={'RS':(None,'RS','506','506'),'FC27':(None,'FC27','1322','1327'),'MMOEXP':(None,'MMOEXP','0','')}
BASE={'mode':['actual-profit'],'profile':['RS'],'start':['2026-10-20'],'end':['2026-10-21'],'rs_site':['rsorders']}
def raw(sn='A',**fields):
    return dict(dict(id=5,order_no=sn,gid=506,site_id=320,site={'full_title':'www.rsorders.com'},amount_usd_format='$ 10',amount_rmb_format='¥ 70',paytime='2026-10-20 12:00:00',status_format='已完成',pay_status=1),**fields)
def delivery(sn='A',**fields):
    return dict(dict(delivery_id='one',source='www.rsorders.com',sn=sn,genre='1',cost_total='35'),**fields)
def data(rows=None,costs=None):
    return dict(period={'start':'2026-10-20','end':'2026-10-21'},generatedAt=datetime.now(timezone.utc).isoformat(),orders=normalized(rows if rows is not None else [raw()],costs if costs is not None else [delivery()]),sources={'orders':{'status':'complete'},'cost':{'status':'complete'}},costOverrides={},testOrders={})
class Pool:
    def __init__(self):self.jobs=[]
    def submit(self,fn,*args,**kwargs):self.jobs.append((fn,args,kwargs))
    def drain(self):
        while self.jobs:
            fn,args,kwargs=self.jobs.pop(0);fn(*args,**kwargs)

class ActualProfit(unittest.TestCase):
    def test_native_cost_reader_passes_distinct_order_game_and_exact_website(self):
        from channel_cost_source import collect
        cells=['','1','订单发货','www.rsorders.com','A','2026-10-20 12:00:00 改2026-10-20 12:01:00',
               'RS','1','0','35','35','70','50%','','','','','已结算','']
        html='<table class="table-list"><thead><tr><th>商户订单号</th></tr></thead><tbody><tr>'+''.join('<td>'+x+'</td>' for x in cells)+'</tr></tbody></table>'
        session=Mock();session.get_order.return_value=(200,html)
        native = collect(session,'2026-10-20','2026-10-20',source='www.rsorders.com',gid='506')[0]
        self.assertEqual(native['cost_total'],'35')
        self.assertEqual(native['trade_at'],'2026-10-20 12:00:00')
        self.assertEqual(native['trade_amended_at'],'2026-10-20 12:01:00')
        self.assertEqual(native['settle_status'],'已结算')
        self.assertNotIn('completed_at', native)
        self.assertEqual(session.get_order.call_args.kwargs['source[]'],'www.rsorders.com');self.assertEqual(session.get_order.call_args.kwargs['gid'],'506')
        with self.assertRaises(ValueError):collect(session,'2026-10-20','2026-10-20',source='www.mmoexp.com')
        self.assertEqual(len(collect(session,'2026-10-20','2026-10-20',source='',gid='0')),1)
        session.get_order.return_value=(200,html.replace('<td>www.rsorders.com</td>','<td></td>'))
        unassigned=collect(session,'2026-10-20','2026-10-20',source='',gid='0')
        self.assertEqual(profit_view(data(costs=unassigned),{})['denominator']['coveredOrders'],0)
        with self.assertRaises(ValueError):collect(session,'2026-10-20','2026-10-20',source='www.rsorders.com',gid='506')
        session.get_order.return_value=(403,'denied')
        with self.assertRaises(PermissionError):collect(session,'2026-10-20','2026-10-20')
    def test_same_order_income_once_multiple_deliveries_and_daily_sum(self):
        d=data([raw(),raw('B',id=4,paytime='2026-10-21 02:00:00',amount_rmb_format='¥ 200')],[delivery(),delivery(delivery_id='two',cost_total='15'),delivery('B',delivery_id='three',cost_total='100')])
        v=profit_view(d,{});m=v['denominator']
        self.assertEqual((m['saleCny'],m['costCny'],m['profitCny']),(270,150,120))
        self.assertAlmostEqual(m['margin'],120/270)
        for key in ('orders','coveredOrders','saleCny','costCny','profitCny'):self.assertEqual(sum(x[key] for x in v['trend']),m[key])
        self.assertNotIn('orders',v);self.assertNotIn('orderNo',json.dumps(v))
    def test_paid_membership_refund_fraud_test_and_no_code(self):
        d=data([raw(),raw('unpaid',id=4,pay_status=0),raw('refund',id=3,pay_status=2),raw('fraud',id=2,status_format='验证·未通过'),raw('test',id=1)],[])
        d['testOrders']={'test':dict(gid='506',salesUsd=10)}
        m=profit_view(d,{})['denominator'];self.assertEqual((m['orders'],m['completedOrders'],m['missingCostOrders'],m['fraudOrders'],m['testOrders']),(1,1,1,1,1))
        self.assertEqual(m['codedOrders'],0)
    def test_pending_and_missing_income_never_extrapolated(self):
        d=data([raw(),raw('pending',status_format='待发货'),raw('missing',amount_rmb_format=None)],[])
        m=profit_view(d,{})['denominator'];self.assertEqual((m['orders'],m['completedOrders'],m['pendingOrders'],m['coveredOrders'],m['missingCostOrders']),(3,2,1,0,2))
        self.assertIsNone(m['profitCny']);self.assertIsNone(m['margin']);self.assertEqual(m['coverageStatus'],'partial')
    def test_zero_empty_zero_income_and_loss(self):
        m=profit_view(data([],[]),{})['denominator'];self.assertEqual(m['profitCny'],0);self.assertIsNone(m['margin'])
        m=profit_view(data([raw(amount_rmb_format='0')]),{})['denominator'];self.assertEqual(m['profitCny'],-35);self.assertIsNone(m['margin'])
        m=profit_view(data(costs=[delivery(cost_total='100')]),{})['denominator'];self.assertEqual(m['profitCny'],-30)
    def test_only_closed_complete_sources_can_freeze(self):
        old={'data':data()};q={'end':'2026-10-21'}
        self.assertTrue(_closed_complete(old,q))
        for source in ('orders','cost'):
            partial=copy.deepcopy(old);partial['data']['sources'][source]['status']='pending'
            self.assertFalse(_closed_complete(partial,q))
        self.assertTrue(_closed_complete({'data':data([],[])},q))
        from channel_effects import TZ
        self.assertFalse(_closed_complete(old,{'end':datetime.now(TZ).date().isoformat()}))
    def test_closed_cache_needs_persisted_terminal_states_not_runtime_denominator(self):
        q={'end':'2026-10-21'}
        for status in ('问题订单','暂停发货','待发货','发货中','处理中','失败','状态未提供'):
            with self.subTest(status=status):
                old={'data':data([raw(status_format=status)],[]),'denominator':{'pendingOrders':0}}
                self.assertFalse(_closed_complete(old,q))
        for field in ('orders','status','refunded'):
            with self.subTest(missing=field):
                old={'data':data()}
                if field=='orders':old['data'].pop(field)
                else:old['data']['orders'][0].pop(field)
                self.assertFalse(_closed_complete(old,q))
        for status,pay in (('已完成',1),('已退款',2),('验证·未通过',1)):
            with self.subTest(existing_terminal=status):
                self.assertTrue(_closed_complete({'data':data([raw(status_format=status,pay_status=pay)],[])},q))
    def test_only_matching_site_and_order_cost_can_join(self):
        m=profit_view(data(costs=[delivery(source='www.mmoexp.com')]),{})['denominator'];self.assertEqual(m['coveredOrders'],0)
        with self.assertRaises(ValueError):normalized([raw()],[delivery(),delivery()])
    def test_incomplete_source_missing_revenue_contract_and_outside_day_fail(self):
        for change in ('incomplete','legacy','day'):
            d=data()
            if change=='incomplete':d['sources']['orders']['status']='partial'
            if change=='legacy':d['orders'][0].pop('adminSaleCny')
            if change=='day':d['orders'][0]['day']='2026-10-19'
            with self.assertRaises(ValueError):profit_view(d,{})
    def test_approved_zero_cost_stays_exact_order_gid_usd(self):
        d=data(costs=[]);d['costOverrides']={'A':dict(gid='506',salesUsd=10,saleCny=70,productTitle='confirmed')}
        self.assertEqual(profit_view(d,{})['denominator']['profitCny'],70)
        d['costOverrides']['A']['gid']='507';self.assertEqual(profit_view(d,{})['denominator']['coveredOrders'],0)
    def test_original_channel_modes_unchanged_and_new_mode_includes_no_code(self):
        d=data();d['orders'][0].update(country='US',payment='PayPal',code='',project='',promoter='',promoterUid='',attributionSource='none',device='',isNew=None)
        d['mapping']={}
        self.assertEqual(view(d,{'mode':'profit'})['denominator']['orders'],1)
        self.assertEqual(view(d,{'mode':'code'})['denominator']['profitCny'],35)
        self.assertEqual(sum(x['orders'] for x in view(d,{'mode':'code'})['trend']),0)
    def test_scope_validation_and_server_profile_mapping(self):
        q=selection(BASE,PROFILES);self.assertFalse(main_scope(q));self.assertEqual(q['rs_site'],'rsorders')
        main=selection({**BASE,'rs_site':['mmoexp']},PROFILES);self.assertTrue(main_scope(main))
        for values in ({'rs_site':['bad']},{'start':['2020-01-01']},{'rs_site':['all','all']}):
            with self.assertRaises(ValueError):selection({**BASE,**values},PROFILES)
        with self.assertRaises(ValueError):selection({'mode':['actual-profit'],'profile':['FC27'],'start':['2026-10-20'],'end':['2026-10-21'],'profit_category':['2']},PROFILES)
    def test_rs_identical_join_duplicates_count_whole_order_once(self):
        q=selection({**BASE,'rs_category':['items'],'rs_server':['oldschool']},PROFILES);session=Mock();session.get_admin.return_value=(200,{'code':1,'data':{'total':2,'list':[raw(),raw()]}})
        rows,proof=order_rows(session,q,'506');self.assertEqual(len(rows),1);self.assertEqual(proof['duplicateJoinRows'],1)
        args=session.get_admin.call_args.kwargs;fields={v for k,v in args.items() if k.endswith('[field]')};self.assertTrue({'aid','cid','site_id','gid','paytime'}<=fields)
        session.get_admin.return_value=(200,{'code':1,'data':{'total':2,'list':[raw(),raw(amount_rmb_format='80')]}})
        with self.assertRaises(ValueError):order_rows(session,q,'506')
    def test_scope_leak_date_incomplete_pagination_and_permission_fail(self):
        q=selection(BASE,PROFILES)
        for row in (raw(site_id=266),raw(gid=7),raw(paytime='2026-10-19 00:00:00')):
            session=Mock();session.get_admin.return_value=(200,{'code':1,'data':{'total':1,'list':[row]}})
            with self.assertRaises(ValueError):order_rows(session,q,'506')
        session=Mock();session.get_admin.return_value=(403,{})
        with self.assertRaises(PermissionError):order_rows(session,q,'506')
    def test_summary_actual_suppresses_only_shipping_reads_and_cache_isolated(self):
        for key,expected in [('RS',{'Admin'}),('FC27',{'Admin','Order'})]:
            calls=[]
            def read(name):
                def run(q):
                    calls.append(name);return dict(status='available',period=q['period'],capturedAt=datetime.now(timezone.utc).isoformat(),metrics={})
                return run
            c=SummaryCache(read('Admin'),read('Order'),PROFILES,shipping_read=read('Shipping'));c.close();pool=Pool();c.pools={k:pool for k in c.readers}
            params={'mode':['summary'],'profile':[key],'start':['2026-10-20'],'end':['2026-10-20']}
            q=query({**params,'profit_basis':['actual']},PROFILES);old=query(params,PROFILES)
            self.assertNotEqual(key_of(q),key_of(old));self.assertNotEqual(summary_key(q),summary_key(old))
            c.get_live(q);pool.drain();code,v=c.get_live(q);self.assertEqual(set(calls),expected);self.assertEqual(code,200);self.assertTrue(complete_summary(v))
            self.assertEqual(v['sources']['Order']['status'],'not_requested' if key=='RS' else 'available')
            calls.clear();c.get_live(old);pool.drain();self.assertEqual(set(calls),{'Admin','Order'} if key=='RS' else {'Admin','Order','Shipping'})

class Service(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.channels=ChannelService(Path(self.tmp.name),lambda user:user=='admin',source=lambda p:data());self.channels.pool.shutdown();self.pool=Pool();self.channels.pool=self.pool
        self.now=0
        def reader(q,p,root):return dict(data(),actualPeriod=q['period'])
        def costs(d,*args):
            d['sources']['cost']['status']='complete';return d
        self.service=ActualProfitService(self.channels,PROFILES,reader,costs,clock=lambda:self.now)
    def test_distinct_actual_cold_admin_scopes_do_not_take_global_collector_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        started=[threading.Event(),threading.Event()];release=threading.Event()
        def reader(q,profile,root):
            started[0 if q['rs_site']=='rsorders' else 1].set()
            if not release.wait(2):raise TimeoutError('fixture deadline')
            return dict(data(),actualPeriod=q['period'])
        self.service.reader=reader
        self.service.get(BASE,'admin');self.service.get({**BASE,'rs_site':['rsmalls']},'admin')
        global_lock=Path(self.tmp.name)/'collector.lock';global_lock.touch();identity=global_lock.stat().st_ino
        def fence(fd,operation):
            if os.fstat(fd).st_ino==identity:raise BlockingIOError('global collector owned by another task')
        pool=ThreadPoolExecutor(max_workers=2)
        held=global_lock.open('a+b')
        if os.name=='posix':
            import fcntl
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            with patch('actual_profit.fcntl.flock',side_effect=fence) if os.name=='nt' else nullcontext():
                futures=[pool.submit(fn,*args,**kw) for fn,args,kw in self.pool.jobs]
                self.assertTrue(all(event.wait(1) for event in started),'cold Admin reads still depend on the global collector')
                release.set()
                for future in futures:future.result(2)
            self.assertEqual(set(self.service.jobs.values()),{'available'})
        finally:release.set();held.close();pool.shutdown()

    def test_main_scope_cold_periods_do_not_take_global_collector_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        started=[threading.Event(),threading.Event()];release=threading.Event()
        def reader(period):
            started[0 if period['start']=='2026-10-20' else 1].set()
            if not release.wait(2):raise TimeoutError('fixture deadline')
            return dict(data(),period=period)
        self.channels.source=reader
        for day in ('2026-10-20','2026-10-21'):
            self.service.get({**BASE,'rs_site':['mmoexp'],'start':[day],'end':[day]},'admin')
        global_lock=Path(self.tmp.name)/'collector.lock';global_lock.touch();identity=global_lock.stat().st_ino
        def fence(fd,operation):
            if os.fstat(fd).st_ino==identity:raise BlockingIOError('global collector owned by another task')
        pool=ThreadPoolExecutor(max_workers=2)
        held=global_lock.open('a+b')
        if os.name=='posix':
            import fcntl
            fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            with patch('actual_profit.fcntl.flock',side_effect=fence) if os.name=='nt' else nullcontext():
                futures=[pool.submit(fn,*args,**kw) for fn,args,kw in self.pool.jobs]
                self.assertTrue(all(event.wait(1) for event in started),'main-scope Admin reads still hold the global collector')
                release.set()
                for future in futures:future.result(2)
            self.assertEqual(set(self.channels.jobs.values()),{'available'})
        finally:release.set();held.close();pool.shutdown()

    def test_main_scope_warm_projection_does_not_hold_other_scope_metadata_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        entered=threading.Event();release=threading.Event();second_done=threading.Event()
        def cached(period,*args):
            value=dict(data(),period=period)
            for row in value['orders']:row.update(day=period['start'],paidAt=period['start']+' 12:00:00')
            value['sources']['cost']['generatedAt']=value['generatedAt']
            return value
        def delivery(value,*args):
            if value['period']['start']=='2026-10-20':
                entered.set();release.wait(2)
            return value
        self.channels.source=None
        def read(day):return self.channels.get(dict(mode=['profit'],start=[day],end=[day]),'admin')
        def other():
            result=read('2026-10-21');second_done.set();return result
        pool=ThreadPoolExecutor(max_workers=2)
        try:
            with patch('channel_cache.compose',side_effect=cached),patch('channel_cache.apply_delivery_cache',side_effect=delivery),patch('channel_source.apply_customer_types',side_effect=lambda value:value),patch('channel_source.apply_cost_overrides',side_effect=lambda value:value):
                first=pool.submit(read,'2026-10-20');self.assertTrue(entered.wait(1));second=pool.submit(other)
                self.assertTrue(second_done.wait(.5),'one warm projection holds the shared job metadata lock')
                release.set();self.assertEqual(first.result(2)[0],200);self.assertEqual(second.result(2)[0],200)
        finally:release.set();pool.shutdown()

    def test_async_same_scope_and_permission_no_public_order_leak(self):
        self.assertEqual(self.service.get(BASE,'guest')[0],403);self.assertEqual(len(self.pool.jobs),0)
        self.assertEqual(self.service.get(BASE,'admin')[0],202);self.service.get(BASE,'admin');self.assertEqual(len(self.pool.jobs),1);self.pool.drain()
        code,v=self.service.get(BASE,'admin');self.assertEqual(code,200);self.assertEqual(v['selection']['rs_site'],'rsorders');self.assertEqual(v['denominator']['profitCny'],35);self.assertNotIn('rawMembership',v)
        files=list((Path(self.tmp.name)/'actual-profit').glob('*.json'));self.assertEqual(len(files),1)
        if os.name!='nt':self.assertEqual(files[0].stat().st_mode&0o077,0)
        self.assertEqual(self.service.get({**BASE,'rs_site':['rsmalls']},'admin')[0],202)
    def test_summary_contract_change_reuses_original_actual_profit_cache_target(self):
        q=selection(BASE,PROFILES);legacy=dict(q,contractId='admin-main-order-labelled-supplement-v1')
        key=hashlib.sha256(json.dumps({k:v for k,v in legacy.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
        self.service.root.mkdir();target=self.service.root/(key+'.json')
        self.channels.publish(dict(data=dict(data(),actualPeriod=q['period']),query=legacy,capturedAt=time.time()-3600),target)
        with patch('live_summary.CONTRACT','summary-version-next'):
            self.assertEqual(selection(BASE,PROFILES),q)
            self.assertEqual(self.service.get(BASE,'admin')[1]['denominator']['profitCny'],35)
            self.assertFalse(self.pool.jobs)
            self.service.get({**BASE,'refresh':['1']},'admin')
        self.assertEqual(self.pool.jobs[0][1][:2],(key,target));self.assertEqual(len(list(self.service.root.glob('*.json'))),1)
        with self.assertRaises(ValueError):self.service.get({**BASE,'contractId':['caller-contract']},'admin')
    def test_summary_ttl_change_preserves_existing_aion_actual_profit_key(self):
        params=dict(mode=['actual-profit'],profile=['AION2'],start=['2026-10-27'],end=['2026-10-27'],profit_site=['all'])
        profiles={'AION2':('AION2','Aion2',826,891,'rpg')}
        q=selection(params,profiles)
        self.assertEqual(q['cacheSeconds'],7200)
        key=hashlib.sha256(json.dumps({k:v for k,v in q.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
        self.assertEqual(key,'713f952ac22296a114c937edd05298c8d4a036ed8d6508242da42abd05d8e6c0')
        with patch('live_summary.HISTORY_TTL',604801):self.assertEqual(selection(params,profiles),q)
    def test_closed_zero_order_cache_reuses_complete_sources_but_retries_unavailable_cost(self):
        q=selection(BASE,PROFILES)
        key=hashlib.sha256(json.dumps({k:v for k,v in q.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
        self.service.root.mkdir();target=self.service.root/(key+'.json')
        empty=dict(data([],[]),actualPeriod=q['period'])
        self.channels.publish(dict(data=empty,query=q,capturedAt=time.time()-3600),target)
        value=self.service.get(BASE,'admin')[1]
        self.assertEqual(value['denominator']['orders'],0);self.assertFalse(value['stale']);self.assertFalse(self.pool.jobs)
        empty['sources']['cost']['status']='unavailable'
        self.channels.publish(dict(data=empty,query=q,capturedAt=time.time()-3600),target)
        value=self.service.get(BASE,'admin')[1]
        self.assertTrue(value['refreshing']);self.assertTrue(value['stale']);self.assertEqual(len(self.pool.jobs),1)
    def test_existing_all_site_unfinished_cache_reuses_values_then_refreshes_same_target(self):
        params={'mode':['actual-profit'],'profile':['FC27'],'start':['2026-10-20'],'end':['2026-10-21'],'profit_site':['all']}
        q=selection(params,PROFILES)
        legacy=dict(q,contractId='admin-main-order-labelled-supplement-v1')
        key=hashlib.sha256(json.dumps({k:v for k,v in legacy.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
        self.service.root.mkdir();target=self.service.root/(key+'.json')
        rows=[raw(str(i),id=i,gid=1327) for i in range(189)]+[raw('p'+str(i),id=200+i,gid=1327,status_format='问题订单') for i in range(3)]
        d=dict(data(rows,[]),actualPeriod=q['period'])
        captured=time.time()
        self.channels.publish(dict(data=d,query=legacy,capturedAt=captured),target)
        with patch('actual_profit.time.time',return_value=captured+599):
            value=self.service.get(params,'admin')[1]
        self.assertFalse(value['stale']);self.assertFalse(self.pool.jobs)
        self.assertEqual((value['denominator']['completedOrders'],value['denominator']['pendingOrders']),(189,3))
        with patch('actual_profit.time.time',return_value=captured+601):
            value=self.service.get(params,'admin')[1]
            self.service.get(params,'admin')
        self.assertTrue(value['stale']);self.assertTrue(value['refreshing']);self.assertEqual(len(self.pool.jobs),1)
        self.assertEqual(self.pool.jobs[0][1][:2],(key,target))
        self.assertEqual(len(list(self.service.root.glob('*.json'))),1)
        persisted=json.loads(target.read_text('utf-8'))
        self.assertNotIn('denominator',persisted['data']);self.assertEqual(len(persisted['data']['orders']),192)
    def test_actual_today_keeps_600_second_ttl_and_explicit_refresh(self):
        from channel_effects import TZ
        today=datetime.now(TZ).date().isoformat()
        params={**BASE,'start':[today],'end':[today]};q=selection(params,PROFILES)
        key=hashlib.sha256(json.dumps({k:v for k,v in q.items() if k not in ('period','refresh')},sort_keys=True).encode()).hexdigest()
        self.service.root.mkdir();target=self.service.root/(key+'.json')
        d=data([raw(paytime=today+' 00:00:00')]);d.update(period={'start':today,'end':today},actualPeriod=q['period'])
        captured=time.time();self.channels.publish(dict(data=d,query=q,capturedAt=captured),target)
        with patch('actual_profit.time.time',return_value=captured+599):
            self.assertFalse(self.service.get(params,'admin')[1]['refreshing'])
            self.service.get({**params,'refresh':['1']},'admin')
        self.assertEqual(len(self.pool.jobs),1)
        self.pool.jobs.clear();self.service.jobs.clear();self.service.starts.clear()
        with patch('actual_profit.time.time',return_value=captured+601):
            self.assertTrue(self.service.get(params,'admin')[1]['refreshing'])
        self.assertEqual(len(self.pool.jobs),1)
    def test_denial_hides_previous_cache_and_can_recover_original_session(self):
        self.service.get(BASE,'admin');self.pool.drain();self.now=61
        self.service.cost_reader=Mock(side_effect=PermissionError('denied'));self.service.get({**BASE,'refresh':['1']},'admin');self.pool.drain();self.assertEqual(self.service.get(BASE,'admin')[0],403)
        self.now=122;self.service.cost_reader=lambda d,*args:d;self.service.get(BASE,'admin');self.pool.drain();self.assertEqual(self.service.get(BASE,'admin')[0],200)
    def test_combined_existing_worker_budget_preserved(self):
        self.channels.jobs={'one':'pending','two':'cost_pending'};self.assertEqual(self.service.get(BASE,'admin')[0],429);self.assertFalse(self.pool.jobs)
    def test_original_channel_request_obeys_actual_worker_admission(self):
        self.service.jobs={'one':'pending','two':'cost_pending'};self.channels.actual_jobs=self.service.jobs
        self.assertEqual(self.channels.get({'start':['2026-10-20'],'end':['2026-10-21']},'admin')[0],429)
    def test_cost_lock_deferral_retries_after_original_cooldown_even_with_revenue_snapshot(self):
        self.service.cost_reader=Mock(side_effect=BlockingIOError('shared cost reader busy'))
        self.service.get(BASE,'admin');self.pool.drain();self.assertEqual(set(self.service.jobs.values()),{'deferred'})
        self.service.get(BASE,'admin');self.assertFalse(self.pool.jobs)
        self.now=61;self.service.cost_reader=lambda d,*args:d
        self.service.get(BASE,'admin');self.assertEqual(len(self.pool.jobs),1)
        self.pool.drain();code,v=self.service.get(BASE,'admin');self.assertEqual(code,200);self.assertFalse(v['refreshing'])
    def test_cost_failure_preserves_known_values_and_error(self):
        self.service.get(BASE,'admin');self.pool.drain();self.now=61
        self.service.cost_reader=Mock(side_effect=OSError('failed'));self.service.get({**BASE,'refresh':['1']},'admin');self.pool.drain()
        code,v=self.service.get(BASE,'admin');self.assertEqual(code,200);self.assertTrue(v['costError']);self.assertEqual(v['denominator']['profitCny'],35)
    def test_interrupted_new_cohort_does_not_inherit_complete_cost_source(self):
        self.service.get(BASE,'admin');self.pool.drain();self.now=61
        self.service.reader=lambda q,*args:dict(data([raw(),raw('B',id=4)],[]),actualPeriod=q['period'])
        self.service.cost_reader=Mock(side_effect=OSError('cost interrupted'))
        self.service.get({**BASE,'refresh':['1']},'admin');self.pool.drain()
        target=next(self.service.root.glob('*.json'));stored=json.loads(target.read_text('utf-8'))
        self.assertEqual(stored['data']['sources']['cost']['status'],'pending')
        self.assertFalse(_closed_complete(stored,selection(BASE,PROFILES)))
        self.assertEqual([r['costCny'] for r in stored['data']['orders']],[35,None])
        self.service.jobs.clear();self.now=122
        with patch('actual_profit.time.time',return_value=stored['capturedAt']+601):self.service.get(BASE,'admin')
        self.assertEqual(len(self.pool.jobs),1)
    def test_closed_channel_cost_gap_reuses_orders_and_retries_only_cost(self):
        d=data();stamp=datetime.fromtimestamp(time.time()-3600,timezone.utc).isoformat()
        d['generatedAt']=stamp;d['sources']['cost']={'status':'unavailable','generatedAt':stamp}
        self.channels.source=None
        request={k:[v] for k,v in d['period'].items()};request['mode']=['profit']
        def enrich(value,force=False):value['sources']['cost']['status']='complete';return value
        with patch('channel_cache.compose',return_value=d),patch('channel_cache.collect_period') as orders,patch('channel_cache.store_days'),patch('channel_source.enrich',side_effect=enrich) as costs,patch('channel_cache.apply_delivery_cache',side_effect=lambda value,*args:value),patch('channel_source.apply_customer_types',side_effect=lambda value:value),patch('channel_source.apply_cost_overrides',side_effect=lambda value:value):
            code,value=self.channels.get(request,'admin')
            self.assertEqual(code,200);self.assertTrue(value['refreshing']);self.assertTrue(self.pool.jobs[0][2]['cost_only'])
            costs.side_effect=OSError('Order temporarily unavailable');self.pool.drain()
            self.assertEqual(set(self.channels.jobs.values()),{'cost_failed'})
            self.channels.starts.clear();self.channels.get(request,'admin')
            self.assertTrue(self.pool.jobs[0][2]['cost_only']);costs.side_effect=enrich;self.pool.drain()
            orders.assert_not_called();self.assertEqual(costs.call_count,2)
            self.assertFalse(self.channels.get(request,'admin')[1]['refreshing']);self.assertFalse(self.pool.jobs)
            self.channels.get({**request,'refresh':['1']},'admin')
            # Explicit refresh keeps the original cooldown and then refreshes membership too.
            self.channels.starts.clear();self.channels.get({**request,'refresh':['1']},'admin')
            self.assertFalse(self.pool.jobs[0][2]['cost_only'])
    def test_existing_complete_delivery_day_proof_keeps_closed_cache_fresh(self):
        from channel_cache import compose,cache_day
        d=data(costs=[]);stamp=datetime.fromtimestamp(time.time()-3600,timezone.utc).isoformat()
        day='2026-10-20';d.update(period={'start':day,'end':day},generatedAt=stamp,mapping={},contract='channel-day-v1')
        d['sources'].update(cost={'status':'unavailable','generatedAt':None},coupons={'status':'complete'},customer={'status':'complete'})
        root=self.channels.root;target=root/'days'/f'{day}.json';target.parent.mkdir();target.write_text(json.dumps(d),encoding='utf-8')
        receipt=root/'delivery-days'/f'{day}.json';receipt.parent.mkdir()
        cost=dict(contract='channel-order-deliveries-v1',complete=True,period=d['period'],generatedAt=stamp,rows=[])
        receipt.write_text(json.dumps(cost),encoding='utf-8');self.channels.source=None
        with patch.dict(sys.modules,{'p2pah_auth':SimpleNamespace()}):cache_day(day,root)
        persisted=json.loads(target.read_text('utf-8'));self.assertEqual(persisted['sources']['cost']['status'],'complete')
        self.assertEqual(persisted['sources']['cost']['generatedAt'],stamp)
        request={k:[v] for k,v in d['period'].items()};request['mode']=['profit']
        with patch('channel_cache.apply_delivery_cache',side_effect=lambda value,*args:value),patch('channel_source.apply_customer_types',side_effect=lambda value:value),patch('channel_source.apply_cost_overrides',side_effect=lambda value:value):
            value=self.channels.get(request,'admin')[1]
            self.assertFalse(value['refreshing']);self.assertFalse(value['stale']);self.assertFalse(self.pool.jobs)
            self.assertEqual(value['denominator']['missingCostOrders'],1);self.assertIsNone(value['denominator']['profitCny'])
        cost['complete']=False;receipt.write_text(json.dumps(cost),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'invalid_delivery_day_cache'):compose(d['period'],root)
        cost.update(complete=True,period={'start':'2026-10-19','end':'2026-10-19'});receipt.write_text(json.dumps(cost),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'invalid_delivery_day_cache'):compose(d['period'],root)
    def test_composed_cost_source_cannot_inherit_last_day_completeness(self):
        from channel_cache import compose
        root=self.channels.root;folder=root/'days';folder.mkdir()
        for day,status in (('2026-10-20','unavailable'),('2026-10-21','complete')):
            d=data();d.update(period={'start':day,'end':day},mapping={},contract='channel-day-v1')
            for row in d['orders']:row.update(day=day,orderNo=day)
            d['sources'].update(coupons={'status':'complete'},cost={'status':status,'generatedAt':d['generatedAt']})
            (folder/f'{day}.json').write_text(json.dumps(d),encoding='utf-8')
        source=compose({'start':'2026-10-20','end':'2026-10-21'},root)['sources']['cost']
        self.assertEqual(source['status'],'partial');self.assertEqual(source['coverage']['completeDays'],1)
    def test_today_channel_cache_expires_at_600_seconds(self):
        from channel_effects import TZ
        today=datetime.now(TZ).date().isoformat();d=data();d['period']={'start':today,'end':today}
        for row in d['orders']:row['day']=today
        request={'start':[today],'end':[today],'mode':['profit']}
        self.channels.get(request,'admin');target=self.pool.jobs.pop()[1][2]
        self.channels.jobs.clear();self.channels.starts.clear()
        d['generatedAt']=datetime.fromtimestamp(time.time()-599,timezone.utc).isoformat();self.channels.publish(d,target)
        self.assertFalse(self.channels.get(request,'admin')[1]['refreshing']);self.assertFalse(self.pool.jobs)
        d['generatedAt']=datetime.fromtimestamp(time.time()-601,timezone.utc).isoformat();self.channels.publish(d,target)
        self.assertTrue(self.channels.get(request,'admin')[1]['refreshing']);self.assertEqual(len(self.pool.jobs),1)
    def test_default_reader_applies_site_scoped_test_and_zero_rules_before_cost_failure(self):
        from actual_profit import collect_orders
        rows=[raw('A',id=3,site_id=266,site={'full_title':'www.mmoexp.com'}),raw('B',id=2),raw('C',id=1,site_id=266,site={'full_title':'www.mmoexp.com'})]
        session=Mock();session.get_admin.return_value=(200,{'code':1,'data':{'total':3,'list':rows}})
        auth=SimpleNamespace(Session=lambda:session,admin_token_from_service=lambda:('fictional',''))
        def rules(d):
            d.update(testOrders={sn:dict(gid='506',salesUsd=10) for sn in ('A','B')},costOverrides={'C':dict(gid='506',salesUsd=10,saleCny=70,productTitle='confirmed')});return d
        q=selection({**BASE,'rs_site':['all']},PROFILES);target=Path(self.tmp.name)/'actual-profit/fixed.json'
        previous=dict(data=data(rows,[delivery('A',source='www.mmoexp.com'),delivery('B',delivery_id='two')]))
        self.service.reader=collect_orders;self.service.cost_reader=Mock(side_effect=OSError('Order unavailable'))
        with patch.dict(sys.modules,{'p2pah_auth':auth}),patch('channel_source.apply_cost_overrides',side_effect=rules):self.service.capture('fixed',target,q,previous)
        stored=json.loads(target.read_text('utf-8'));v=profit_view(stored['data'],{})['denominator']
        self.assertEqual((v['orders'],v['testOrders'],v['coveredOrders'],v['zeroCostOrders'],v['profitCny']),(2,1,2,1,105))
        self.assertEqual(self.service.jobs['fixed'],'cost_failed');self.assertEqual(set(stored['data']['testOrders']),{'A'})

if __name__=='__main__':unittest.main()
