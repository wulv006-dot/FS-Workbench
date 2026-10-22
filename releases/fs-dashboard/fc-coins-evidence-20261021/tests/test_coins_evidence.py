import ast,hashlib,json,sys,tempfile,unittest
import importlib.util
import threading,time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

HERE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(HERE/'source'))
for p in (HERE.parent/'fs_channel_dashboard_20261021/source',HERE.parent/'channel-effects-20261021/source'):
    if p.is_dir():sys.path.append(str(p));break
from coins_evidence import CoinsEvidence,checked_query,schema,baseline_identity

def row(key,**changes):
    return dict({'orderNo':key,'gid':'1327','game':'FC 27','day':'2026-10-20','status':'已完成','payStatus':'1','refunded':False,
      'salesUsd':10,'saleCny':70,'costCny':49,'profitCny':21,'deliveryRows':1,'coupons':[],
      'codeKey':'','promoterUid':'','attribution':'无推广归属','conflict':False,'customerType':'新客','project':'无推广归属'},**changes)

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        (self.root/'executions').mkdir()
        self.reader=CoinsEvidence(root=self.root)
        self.q={'profile':'FC27','kind':'order_costs','start':'2026-10-20','end':'2026-10-20'}
    def tearDown(self):self.tmp.cleanup()
    def fixture(self,rows,types=None):
        data={'period':{'start':'2026-10-20','end':'2026-10-20'},'generatedAt':'2026-10-21T00:00:00+08:00','orders':rows,
          'sources':{'orders':{'status':'complete'},'coupons':{'status':'complete'},'cost':{'generatedAt':'2026-10-21T00:01:00+08:00'}}}
        types=types or {r['orderNo']:'货币(Gold)' for r in rows}
        meta={hashlib.sha256(k.encode()).hexdigest():{'product':v,'discount_usd':'2'} for k,v in types.items()}
        return data,meta,{'complete':True,'captured_at':'2026-10-21T00:00:00+08:00'}
    def costs(self,fixture):
        data,meta,cov=fixture
        with patch.object(self.reader,'channel_data',return_value=deepcopy(data)),patch('coins_evidence.es_metadata',return_value=(meta,cov)):
            return self.reader(self.q)
    def test_closed_scope(self):
        for extra in ({'profile':'ALL'},{'kind':'write'},{'url':'https://example.com'},{'page':True},{'start':'2026-10-21','end':'2026-10-20'}):
            with self.assertRaises((ValueError,TypeError)):checked_query(self.q|extra)
    def test_admin_income_and_fraud_exclusion_reach_coins_consumer(self):
        v=self.costs(self.fixture([row('A',adminSaleCny=80),row('fraud',adminSaleCny=80,status='验证未通过')]))
        self.assertEqual(v['revenue_basis'],'admin_order_cny')
        self.assertEqual((v['summary']['saleCny'],v['summary']['profitCny']),(80,31))
        self.assertEqual(v['summary']['actual_discount_usd'],'2')
        self.assertEqual(v['status'],'available')
    def test_mixed_income_schema_never_mixes_methods(self):
        v=self.costs(self.fixture([row('A',adminSaleCny=80),row('B')]))
        self.assertEqual(v['revenue_basis'],'legacy_delivery')
        self.assertEqual((v['summary']['saleCny'],v['summary']['profitCny']),(140,42))
        self.assertEqual(v['status'],'partial')
    def test_completed_only_and_test_and_coin_scope(self):
        f=self.fixture([row('coin'),row('pending',status='发货中'),row('test'),row('voucher'),row('missing',costCny=None,profitCny=None)],{'coin':'货币(Gold)','pending':'货币(Gold)','test':'货币(Gold)','voucher':'物品(Items)','missing':'货币(Gold)'})
        f[0]['testOrders']={'test':{'gid':'1327','salesUsd':'10'}}
        v=self.costs(f);m=v['summary']
        self.assertEqual((m['orders'],m['completedOrders'],m['pendingOrders'],m['coveredOrders'],m['missingCostOrders'],m['testOrders']),(3,2,1,1,1,1))
        self.assertEqual((m['saleCny'],m['costCny'],m['profitCny']),(70,49,21))
        self.assertEqual(v['status'],'partial');self.assertTrue(all(v['quality_checks'].values()))
        self.assertNotIn('orderNo',json.dumps(v));self.assertNotIn('voucher',json.dumps(v))
    def test_coupon_code_overlap_and_discount_not_deducted_twice(self):
        v=self.costs(self.fixture([row('A',codeKey='secret-code',coupons=[{'templateId':'12'}]),row('B',coupons=[{'templateId':'12'},{'templateId':'13'}])]))
        self.assertEqual(v['coupon_orders']['orders'],2)
        self.assertEqual(v['code_or_referrer_orders']['orders'],1)
        self.assertEqual(v['coupon_and_code_overlap']['orders'],1)
        self.assertEqual(v['summary']['profitCny'],42)
        self.assertEqual(v['summary']['actual_discount_usd'],'4')
        self.assertNotIn('secret-code',json.dumps(v))
    def test_unknown_classification_is_excluded_and_partial(self):
        data,meta,cov=self.fixture([row('A')]);meta.clear()
        v=self.costs((data,meta,cov));self.assertEqual(v['summary']['orders'],0);self.assertEqual(v['status'],'partial')
        self.assertEqual(v['coverage']['excluded_product_orders']['missing_es_product'],1)
    def test_platform_only_from_existing_dataset(self):
        self.reader.dataset=lambda:{'as_of':'2026-10-21T00:00:00+08:00','orders':[{'id':'A','platform':'XBOX','site_group':'main'}]}
        v=self.costs(self.fixture([row('A'),row('B')]))
        self.assertEqual(v['coverage']['platform_unknown_orders'],1)
        self.assertEqual({g['label'] for g in v['groups']['platform']},{'XBOX','unknown'})
    def test_missing_cache_does_not_collect(self):
        with patch.object(self.reader,'channel_data',return_value=None):v=self.reader(self.q)
        self.assertEqual(v['status'],'not_available');self.assertFalse(v['collection_triggered'])
    def test_duplicate_and_wrong_day_rejected(self):
        for rows in ([row('A'),row('A')],[row('A',day='2026-10-19')]):
            with self.assertRaises(ValueError):self.costs(self.fixture(rows))
    def history_record(self,ident,**changes):
        v={'execution_id':ident,'run_id':ident,'created_at':'2026-10-19T16:00:00+00:00','status':'CONFIRMED','automatic':True,'changed':['PS'],'sync_confirmed':True,
           'before':{'rows':[{'expectedPlatform':'PS','b2c':'0.10'}]},'after':{'rows':[{'expectedPlatform':'PS','b2c':'0.09'}]},'targets':[],'operator_reason':'private@example.com'}|changes
        (self.root/'executions'/(ident+'.json')).write_text(json.dumps(v));return v
    def test_real_statuses_and_timezone_not_manual_actions(self):
        a='a'*8+'-'+'a'*4+'-'+'a'*4+'-'+'a'*4+'-'+'a'*12
        b=a.replace('a','b')
        self.history_record(a);self.history_record(b,status='UNKNOWN')
        v=self.reader(self.q|{'kind':'price_history'})
        self.assertEqual(v['pagination']['total_events'],2)
        self.assertEqual(v['status_counts'],{'CONFIRMED':1,'UNKNOWN':1})
        self.assertEqual(v['events'][0]['after_backend_usd_per_k'],{'PS':'0.09'})
        self.assertTrue(all(x['independent_public_after_readback'].startswith('not_proven') for x in v['events']))
        self.assertNotIn('private@',json.dumps(v))
    def test_bad_identity_retained_as_coverage_gap(self):
        a='a'*8+'-'+'a'*4+'-'+'a'*4+'-'+'a'*4+'-'+'a'*12
        self.history_record(a,execution_id='different')
        v=self.reader(self.q|{'kind':'price_history'});self.assertEqual(v['status'],'partial');self.assertEqual(v['coverage']['invalid_identity_or_time'],1)

    def v2_history(self,execution='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',**changes):
        run='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';preview='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        for folder in ('quotes','previews'):(self.root/folder).mkdir(exist_ok=True)
        (self.root/'quotes'/(run+'.json')).write_text(json.dumps({'run_id':run}))
        (self.root/'previews'/(preview+'.json')).write_text(json.dumps({'preview_id':preview,'run_id':run}))
        self.history_record(execution,run_id=run,preview_id=preview,**changes)
        return run,preview

    def test_v2_quote_and_execution_keep_distinct_verified_identities(self):
        run,preview=self.v2_history()
        v=self.reader(self.q|{'kind':'price_history'});self.assertEqual(v['status'],'available')
        self.assertEqual(v['pagination']['total_events'],1);event=v['events'][0]
        self.assertNotEqual(event['execution_id'],event['run_id']);self.assertEqual(event['run_id'],run)
        self.assertEqual(event['identity_check']['basis'],'execution_preview_quote_chain')
        self.assertEqual(event['identity_check']['preview_id'],preview)
        self.assertEqual(len(event['identity_check']['quote_sha256']),64)

    def test_v2_missing_or_wrong_quote_chain_stays_a_coverage_gap(self):
        run,preview=self.v2_history()
        for folder,ident,field in (('previews',preview,'run_id'),('quotes',run,'run_id')):
            path=self.root/folder/(ident+'.json');original=path.read_bytes();value=json.loads(original);value[field]='dddddddd-dddd-4ddd-8ddd-dddddddddddd';path.write_text(json.dumps(value))
            v=self.reader(self.q|{'kind':'price_history'});self.assertEqual(v['status'],'partial');self.assertEqual(v['pagination']['total_events'],0)
            path.write_bytes(original);path.unlink()
            self.assertEqual(self.reader(self.q|{'kind':'price_history'})['status'],'partial')
            path.write_bytes(original)

    def test_v2_same_quote_does_not_merge_distinct_execution_statuses(self):
        self.v2_history();self.v2_history('dddddddd-dddd-4ddd-8ddd-dddddddddddd',status='PARTIAL')
        v=self.reader(self.q|{'kind':'price_history'});self.assertEqual(v['pagination']['total_events'],2)
        self.assertEqual(v['status_counts'],{'CONFIRMED':1,'PARTIAL':1})

    def test_v2_original_failed_job_and_later_reconciliation_both_retained(self):
        self.v2_history();ident='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';(self.root/'jobs').mkdir()
        path=self.root/'jobs'/(ident+'.json')
        rec=dict(execution_id=ident,status='confirmed',completed_at='2026-10-20T01:46:00Z',original_job_status='failed',mmoexp_replayed=False,public_readback='verified',private='secret@example.com')
        path.write_text(json.dumps(dict(job_id=ident,status='failed',reconciliation=rec)))
        v=self.reader(self.q|{'kind':'price_history'});event=v['events'][0]
        self.assertEqual(event['status'],'CONFIRMED');self.assertEqual(event['job_status'],'failed')
        self.assertEqual(event['reconciliation']['completed_at'],'2026-10-20T01:46:00Z')
        self.assertIs(event['reconciliation']['mmoexp_replayed'],False);self.assertNotIn('secret@',json.dumps(v))
        rec['execution_id']='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        path.write_text(json.dumps(dict(job_id=ident,status='failed',reconciliation=rec)))
        self.assertEqual(self.reader(self.q|{'kind':'price_history'})['status'],'partial')

    def test_v2_non_uuid_run_cannot_reach_other_paths(self):
        self.v2_history();path=next((self.root/'executions').glob('*.json'));value=json.loads(path.read_text());value['run_id']='../../private';path.write_text(json.dumps(value))
        v=self.reader(self.q|{'kind':'price_history'});self.assertEqual(v['status'],'partial');self.assertEqual(v['pagination']['total_events'],0)
    def test_registry_wiring_and_current_baseline(self):
        v=(HERE/'source/research.py').read_text(encoding='utf8');tree=ast.parse(v)
        names=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='RESEARCH_NAMES' for x in n.targets))
        self.assertEqual(names.count('fc.query_pricing_evidence'),1)
        self.assertIn('coins_schema()',v);self.assertIn("self.config.get('enabled') is not True",v)
        wiring=(HERE/'source/fs_evidence.py').read_text(encoding='utf8')
        self.assertIn('book.coins_evidence=coins_read',wiring)
        self.assertIn("if not detail.config.get('enabled')",wiring)
        self.assertIn("args.get('kind')=='order_costs'",wiring)
        self.assertEqual(schema()['function']['name'],'mcp__fcro__fc_query_pricing_evidence')
        self.assertTrue(baseline_identity()['version'].endswith('-v7'))

    def test_freshest_es_per_day_does_not_overwrite_with_old_wide_export(self):
        archive=self.root/'es';archive.mkdir()
        old={'query':{'start':'2026-10-19','end':'2026-10-20'},'captured_at':'2026-10-20T00:00:00Z'}
        fresh={'query':{'start':'2026-10-20','end':'2026-10-20'},'captured_at':'2026-10-21T00:00:00Z'}
        for i,v in enumerate((old,fresh)):(archive/(str(i)+'.json')).write_text(json.dumps(v))
        def dataset(q,root):
            return {'rows':[{'订单号':'hash','游戏':'FC 27','付款时间':'2026-10-20 12:00:00','产品类型':'货币(Gold)' if q==fresh['query'] else '物品(Items)','折扣金额':'1'}],
              'parse_failures':0,'failed_files':0,'declared_files':1,'hashes':['a'*64],'captured_at':fresh['captured_at']}
        with patch.dict(sys.modules,es_order_structure=SimpleNamespace(archived_dataset=dataset)):
            from coins_evidence import es_metadata
            rows,cov=es_metadata('2026-10-19','2026-10-20',archive)
        self.assertTrue(cov['complete']);self.assertEqual(rows['hash']['product'],'货币(Gold)')

    def test_original_preparation_is_extended_without_new_schedule(self):
        from source_snapshots import prepare_supplements
        calls=[]
        def query(name,args):
            calls.append((name,args));return {'evidence_id':'e','data':{'status':'available'}}
        result=prepare_supplements(SimpleNamespace(research=query),'2026-10-14','2026-10-20')
        self.assertEqual(len(result),10)
        self.assertEqual([a['kind'] for n,a in calls if n=='fc.query_pricing_evidence'],['price_history','order_costs'])
        self.assertEqual(sum(n=='fc.query_marketing_snapshot' for n,a in calls),2)
        self.assertEqual(sum(n=='fc.query_discount_analysis' for n,a in calls),2)

    def test_release_only_five_exact_targets_no_business_or_timer_writes(self):
        spec=importlib.util.spec_from_file_location('coins_release',HERE/'deploy/release.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        m={'scope':module.SCOPE,'businessWrites':False,'timersChanged':False,'files':[dict(candidate=k,target=v,beforeSha256=None if k in module.NEW else 'a'*64,owner='0:0',mode='0o644') for k,v in module.TARGETS.items()]}
        self.assertEqual(len(module.checked_manifest(m)['files']),5)
        for field in ('businessWrites','timersChanged'):
            with self.assertRaises(ValueError):module.checked_manifest(m|{field:True})
        m['files'][0]['target']='/var/lib/fc27-cloud/config/automation.json'
        with self.assertRaises(ValueError):module.checked_manifest(m)

    def test_marketing_wait_returns_pending_once_then_polls_same_native_query(self):
        tree=ast.parse((HERE/'source/fs_evidence.py').read_text(encoding='utf8'))
        build=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='build_book')
        read=next(n for n in build.body if isinstance(n,ast.FunctionDef) and n.name=='marketing_read')
        async_class=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AsyncRead')
        entered=threading.Event();release=threading.Event();calls=[]
        def original(args):
            calls.append(dict(args));entered.set();release.wait(1)
            return {'status':'pending','reason':'exact_marketing_period_preparing'} if len(calls)==1 else {'status':'partial','actual':'terminal'}
        ns=dict(threading=threading,ThreadPoolExecutor=ThreadPoolExecutor,marketing_lock=threading.Lock(),marketing_jobs={},
          detail=SimpleNamespace(config={'enabled':True}),digest=lambda q:json.dumps(q,sort_keys=True),pinned_marketing=original)
        exec(compile(ast.Module(body=[async_class,read],type_ignores=[]),'<actual-marketing-adapter>','exec'),ns)
        q={'profile':'FC27','start':'2026-10-14','end':'2026-10-20'}
        try:
            with patch.dict(sys.modules,report_tracks=SimpleNamespace(fc27_marketing_view=lambda v:{'rule':'test'})):
                self.assertEqual(ns['marketing_read'](q)['status'],'pending');self.assertTrue(entered.wait(1))
                self.assertEqual(ns['marketing_read'](q)['reason'],'source_read_running');self.assertEqual(len(calls),1)
                release.set()
                until=time.monotonic()+2
                while time.monotonic()<until:
                    v=ns['marketing_read'](q)
                    if v['status']=='partial':break
                    time.sleep(.005)
                self.assertEqual(v['actual'],'terminal');self.assertEqual(calls,[q,q])
                ns['detail'].config['enabled']=False
                self.assertEqual(ns['marketing_read'](q)['reason'],'fc_detail_disabled')
        finally:
            release.set()
            for job in ns['marketing_jobs'].values():job.pool.shutdown(wait=True)

    def test_slow_source_cannot_block_other_family_and_same_query_stays_frozen(self):
        tree=ast.parse((HERE/'source/fs_evidence.py').read_text(encoding='utf8'))
        node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SourcePins')
        ns=dict(threading=threading,deepcopy=deepcopy,digest=lambda v:hashlib.sha256(json.dumps(v,sort_keys=True).encode()).hexdigest())
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-source-pins>','exec'),ns)
        pins=ns['SourcePins']();entered=threading.Event();release=threading.Event();calls=[]
        def slow(q):
            calls.append(q);entered.set();release.wait(2);return {'http_status':200,'status':'available','value':'first'}
        read=pins.wrap(slow,'slow');fast=pins.wrap(lambda q:{'http_status':200,'status':'available','value':'independent'},'fast')
        with ThreadPoolExecutor(max_workers=3) as pool:
            a=pool.submit(read,{});self.assertTrue(entered.wait(1));b=pool.submit(read,{})
            try:self.assertEqual(pool.submit(fast,{}).result(timeout=.5)['value'],'independent')
            finally:release.set()
            first=a.result(timeout=1);self.assertEqual(first,b.result(timeout=1));self.assertEqual(len(calls),1)

if __name__=='__main__':unittest.main()
