"""Fictional orders: one paid cohort, whole-order income, exact site and daily sums."""
import copy,json,os,sys,tempfile,threading,time,unittest
from datetime import datetime,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE));sys.path.append(str(Path(__file__).parent/'fixtures'))
if os.name=='nt':sys.modules['fcntl']=SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=lambda *args:None)
from actual_profit import ActualProfitService,selection,normalized,order_rows,main_scope
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
    def submit(self,fn,*args):self.jobs.append((fn,args))
    def drain(self):
        while self.jobs:
            fn,args=self.jobs.pop(0);fn(*args)

class ActualProfit(unittest.TestCase):
    def test_native_cost_reader_passes_distinct_order_game_and_exact_website(self):
        from channel_cost_source import collect
        cells=['','1','订单发货','www.rsorders.com','A','2026-10-20 12:00:00','RS','1','0','35','35','70','50%','','','','','','']
        html='<table class="table-list"><thead><tr><th>商户订单号</th></tr></thead><tbody><tr>'+''.join('<td>'+x+'</td>' for x in cells)+'</tr></tbody></table>'
        session=Mock();session.get_order.return_value=(200,html)
        self.assertEqual(collect(session,'2026-10-20','2026-10-20',source='www.rsorders.com',gid='506')[0]['cost_total'],'35')
        self.assertEqual(session.get_order.call_args.kwargs['source[]'],'www.rsorders.com');self.assertEqual(session.get_order.call_args.kwargs['gid'],'506')
        with self.assertRaises(ValueError):collect(session,'2026-10-20','2026-10-20',source='www.mmoexp.com')
        self.assertEqual(len(collect(session,'2026-10-20','2026-10-20',source='',gid='0')),1)
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
        self.service=ActualProfitService(self.channels,PROFILES,reader,lambda d,*args:d,clock=lambda:self.now)
    def test_async_same_scope_and_permission_no_public_order_leak(self):
        self.assertEqual(self.service.get(BASE,'guest')[0],403);self.assertEqual(len(self.pool.jobs),0)
        self.assertEqual(self.service.get(BASE,'admin')[0],202);self.service.get(BASE,'admin');self.assertEqual(len(self.pool.jobs),1);self.pool.drain()
        code,v=self.service.get(BASE,'admin');self.assertEqual(code,200);self.assertEqual(v['selection']['rs_site'],'rsorders');self.assertEqual(v['denominator']['profitCny'],35);self.assertNotIn('rawMembership',v)
        files=list((Path(self.tmp.name)/'actual-profit').glob('*.json'));self.assertEqual(len(files),1)
        if os.name!='nt':self.assertEqual(files[0].stat().st_mode&0o077,0)
        self.assertEqual(self.service.get({**BASE,'rs_site':['rsmalls']},'admin')[0],202)
    def test_denial_hides_previous_cache_and_can_recover_original_session(self):
        self.service.get(BASE,'admin');self.pool.drain();self.now=61
        self.service.cost_reader=Mock(side_effect=PermissionError('denied'));self.service.get({**BASE,'refresh':['1']},'admin');self.pool.drain();self.assertEqual(self.service.get(BASE,'admin')[0],403)
        self.now=122;self.service.cost_reader=lambda d,*args:d;self.service.get(BASE,'admin');self.pool.drain();self.assertEqual(self.service.get(BASE,'admin')[0],200)
    def test_combined_existing_worker_budget_preserved(self):
        self.channels.jobs={'one':'pending','two':'cost_pending'};self.assertEqual(self.service.get(BASE,'admin')[0],429);self.assertFalse(self.pool.jobs)
    def test_original_channel_request_obeys_actual_worker_admission(self):
        self.service.jobs={'one':'pending','two':'cost_pending'};self.channels.actual_jobs=self.service.jobs
        self.assertEqual(self.channels.get({'start':['2026-10-20'],'end':['2026-10-21']},'admin')[0],429)
    def test_cost_failure_preserves_known_values_and_error(self):
        self.service.get(BASE,'admin');self.pool.drain();self.now=61
        self.service.cost_reader=Mock(side_effect=OSError('failed'));self.service.get({**BASE,'refresh':['1']},'admin');self.pool.drain()
        code,v=self.service.get(BASE,'admin');self.assertEqual(code,200);self.assertTrue(v['costError']);self.assertEqual(v['denominator']['profitCny'],35)

if __name__=='__main__':unittest.main()
