import copy,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source'),str(Path(__file__).parent/'fixtures')]
from rs_backlog import RSBacklog,project,CONTRACT
from live_summary import SummaryCache

Q=dict(rs_site='rsorders',rs_server='oldschool',rs_category='items')
class Pool:
    def __init__(self):self.calls=[]
    def submit(self,*args,**kw):self.calls.append((args,kw))

class RSCurrent(unittest.TestCase):
    def raw(self,**kw):return dict(id=1,gid=506,pay_status=1,status=91,status_format='问题订单',site_id=320,**kw)
    def test_distinct_whole_orders_and_native_filters_no_date(self):
        calls=[]
        def read(params):
            calls.append(params);fields=[v for k,v in params.items() if k.endswith('[field]')]
            unpaid=any(v=='pay_status' and params[k.replace('[field]','[val]')]==0 for k,v in params.items() if k.endswith('[field]'))
            row=self.raw();row.update(pay_status=0,status=1,status_format='待支付') if unpaid else None
            self.assertFalse('paytime' in fields);self.assertTrue(set(['gid','site_id','aid','cid','pay_status']).issubset(fields))
            return {'total':2,'list':[row,row]}
        result=project(read,Q)
        self.assertEqual([result['metrics'][k]['value'] for k in ('issues','unpaid')],[1,1])
        self.assertEqual(result['basis'],'current_no_payment_date_filter')
        self.assertNotIn('orders',result)
    def test_false_unpaid_totals_never_published(self):
        result=project(lambda _:dict(total=1,list=[self.raw()]),Q)
        self.assertEqual(result['metrics']['issues']['value'],1)
        self.assertIsNone(result['metrics']['unpaid']['value'])
    def test_partial_pagination_unknown_permission_propagates(self):
        value=project(lambda _:dict(total=2,list=[]),Q)
        self.assertIsNone(value['metrics']['issues']['value'])
        with self.assertRaises(PermissionError):project(lambda _:(_ for _ in ()).throw(PermissionError()),Q)
    def test_wrong_game_site_and_conflicts_rejected(self):
        for row in [dict(self.raw(),gid=1322),dict(self.raw(),site_id=266)]:
            value=project(lambda _:dict(total=1,list=[row]),Q)
            self.assertIsNone(value['metrics']['issues']['value'])
        value=project(lambda _:dict(total=2,list=[self.raw(),dict(self.raw(),status_format='changed')]),Q)
        self.assertIsNone(value['metrics']['issues']['value'])
    def test_cache_retains_exact_scope_and_deduplicates_jobs(self):
        pool=Pool();now=[100.];c=RSBacklog(pool,clock=lambda:now[0]);params={k:[v] for k,v in dict(mode='rs-backlog',profile='RS',**Q).items()}
        self.assertEqual(c.get(params)[0],202);self.assertEqual(c.get(params)[0],202);self.assertEqual(len(pool.calls),1)
        entry=next(iter(c.entries.values()));entry.update(state='available',at=100.,data=dict(contractId=CONTRACT,selection=Q,metrics={}))
        self.assertEqual(c.get(params)[0],200);now[0]=401
        code,data=c.get(params);self.assertEqual(code,200);self.assertTrue(data['refreshing']);self.assertEqual(data['selection'],Q)
        with self.assertRaises(ValueError):c.get(dict(params,start=['2026-10-23']))
        entry.update(state='denied',at=401.,data=None);self.assertEqual(c.get(params)[0],403)

class History(unittest.TestCase):
    def setUp(self):
        self.c=SummaryCache(None,None,{});self.addCleanup(self.c.close)
        self.q=dict(profile='RS',period={},cacheSeconds=7200,profit_basis='actual')
        self.old={'generatedAt':'2020-01-01T00:00:00+00:00','sources':{'Admin':{'status':'available'}},'profile':{'value':17}}
    def test_expired_history_shows_last_snapshot_while_revalidating(self):
        original=copy.deepcopy(self.old)
        with patch('daily_archive.summary_key',return_value={}),patch('daily_archive.read',return_value=self.old),patch('daily_archive.derive_summary',return_value=None),patch.object(self.c,'get_live',return_value=(202,{'status':'pending'})) as native:
            code,value=self.c.get(self.q)
            self.assertEqual(code,200);self.assertEqual(value['profile']['value'],17);self.assertTrue(value['refreshing']);self.assertEqual(value['sources']['Admin']['status'],'pending');native.assert_called_once()
        self.assertEqual(original['profile'],value['profile'])
    def test_denial_does_not_retain_archive(self):
        with patch('daily_archive.summary_key',return_value={}),patch('daily_archive.read',return_value=self.old),patch('daily_archive.derive_summary',return_value=None),patch.object(self.c,'get_live',return_value=(403,{'status':'denied'})):
            self.assertEqual(self.c.get(self.q)[0],403)
    def test_derived_history_announces_pending_native_range(self):
        self.old['archive']={}
        with patch('daily_archive.summary_key',return_value={}),patch('daily_archive.read',return_value=None),patch('daily_archive.derive_summary',return_value=self.old),patch.object(self.c,'get_live',return_value=(202,{'status':'pending'})):
            code,value=self.c.get(self.q);self.assertEqual(code,200);self.assertTrue(value['refreshing']);self.assertEqual(value['sources']['Admin']['status'],'pending');self.assertEqual(value['expiresInSeconds'],0)
    def test_current_facts_within_history_bound_reused(self):
        self.old['generatedAt']=__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
        with patch('daily_archive.summary_key',return_value={}),patch('daily_archive.read',return_value=self.old),patch.object(self.c,'get_live') as native:
            code,value=self.c.get(self.q);self.assertEqual(code,200);self.assertGreater(value['expiresInSeconds'],7100);native.assert_not_called()

if __name__=='__main__':unittest.main()
