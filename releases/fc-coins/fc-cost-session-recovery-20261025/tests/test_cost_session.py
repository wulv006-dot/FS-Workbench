import ast,hashlib,importlib.util,json,re,sys,types,unittest
from contextlib import nullcontext
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


class CostSession(unittest.TestCase):
    def setUp(self):
        self.calls=0;self.closed=0;self.page_number=0;self.fail_first=False
        self.context=types.SimpleNamespace()
        self.browser=types.SimpleNamespace(contexts=[self.context])
        owner=self
        class Page:
            context=owner.context
            def goto(self,url,**kwargs):
                owner.page_number=int(__import__('urllib.parse',fromlist=['parse_qs']).parse_qs(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(url).query)['page'][0]);return types.SimpleNamespace(status=200)
            def evaluate(self,script):
                traded=(datetime.now(timezone.utc)-timedelta(minutes=1)).astimezone(owner.m.SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
                return dict(login=False,page=str(owner.page_number),game='1322',product='1',genre='1',typeHeader='交货类型',table=True,hasDataRows=owner.page_number==1,empty=owner.page_number>1,
                            rows=[dict(platform=p,record_id=str(100+i),delivery_type='订单发货',trade_at=traded,cny_per_1k='0.50') for i,p in enumerate(('PS','XBOX','PC'))] if owner.page_number==1 else [])
            def wait_for_timeout(self,*args):pass
        self.context.new_page=Page
        def apply(context):
            self.calls+=1
            if self.fail_first or self.calls>1:raise RuntimeError('global_order_unavailable:order_probe_unavailable')
        def open_backend(playwright):
            try:apply(self.context);return self.browser
            except BaseException:self.closed+=1;raise
        def close_backend(page):self.closed+=1
        modules={'isolated_backend':types.SimpleNamespace(open_backend=open_backend,close_backend=close_backend),
                 'playwright.sync_api':types.SimpleNamespace(sync_playwright=lambda:nullcontext(object()),TimeoutError=TimeoutError)}
        with patch.dict(sys.modules,modules):
            try:self.m=load(ROOT/'source/collect_p2pah_cost.py','candidate_cost')
            except __import__('zoneinfo').ZoneInfoNotFoundError:
                # Windows fixture only; Linux CI uses its real IANA database.
                with patch('zoneinfo.ZoneInfo',lambda name:timezone(timedelta(hours=8))):
                    self.m=load(ROOT/'source/collect_p2pah_cost.py','candidate_cost')
        self.login=lambda page,config:apply(page.context)

    def test_old_duplicate_cookie_fetch_reproduces_same_failure_before_any_cost_read(self):
        tree=ast.parse((ROOT/'tests/original_collect.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef))
        namespace=dict(vars(self.m),login=self.login)
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'frozen_original_collect','exec'),namespace)
        with self.assertRaisesRegex(RuntimeError,'global_order_unavailable:order_probe_unavailable') as caught:namespace['collect']()
        self.assertEqual(self.calls,2);self.assertEqual(self.page_number,0);self.assertEqual(self.closed,1)
        self.assertEqual(type(caught.exception).__name__,'RuntimeError')

    def test_verified_context_is_used_once_and_three_platform_costs_stay_valid(self):
        result=self.m.collect()
        self.assertEqual(self.calls,1);self.assertEqual(self.closed,1)
        self.assertEqual(result['status'],'valid');self.assertEqual([r['platform'] for r in result['costs']],['PS','XBOX','PC'])
        self.assertTrue(all(r['genre']=='1' and r['delivery_type']=='订单发货' and r['status']=='valid' for r in result['costs']))
        self.assertEqual([r['requested_page'] for r in result['page_observations']],[1,2])

    def test_initial_session_failure_still_blocks_without_costs_or_relogin(self):
        self.fail_first=True
        with self.assertRaises(RuntimeError) as caught:self.m.collect()
        result=self.m.failure_result(caught.exception)
        self.assertEqual(self.calls,1);self.assertEqual(self.closed,1);self.assertEqual(self.page_number,0)
        self.assertEqual(result['reason'],'global_order_unavailable:order_probe_unavailable')
        self.assertEqual(result['diagnostic']['stage'],'shared_order_session');self.assertNotIn('costs',result)

    def test_unknown_runtime_exception_does_not_expose_secrets(self):
        result=self.m.failure_result(RuntimeError('cookie: session=private token=private'))
        self.assertEqual(result['reason'],'RuntimeError');self.assertNotIn('private',json.dumps(result))

    def test_page_validation_and_timeout_diagnostics_are_preserved(self):
        result=self.m.failure_result(self.m.CostPageError('filter_or_rows_unverified:2',{'requested_page':2,'http_status':200,'observed':{'game':'wrong'}}))
        self.assertEqual(result['reason'],'filter_or_rows_unverified:2');self.assertEqual(result['diagnostic']['observed']['game'],'wrong')
        result=self.m.failure_result(TimeoutError('Page.goto: timeout'))
        self.assertEqual(result['reason'],'page_navigation_timeout');self.assertEqual(result['diagnostic']['api_method'],'Page.goto')

    def test_source_contract_still_selects_latest_real_cost_and_rejects_other_delivery_types(self):
        now=(datetime.now(timezone.utc)-timedelta(minutes=1)).astimezone(self.m.SHANGHAI).strftime('%Y-%m-%d %H:%M:%S')
        raw=dict(platform='PS',record_id='123',delivery_type='订单发货',trade_at=now,cny_per_1k='0.50')
        self.assertEqual(self.m.valid_record(raw)[1]['unit'],'CNY/K')
        self.assertIsNone(self.m.valid_record(dict(raw,delivery_type='采购打款')))
        with self.assertRaisesRegex(ValueError,'cost_delivery_type_unverified'):self.m.valid_record(dict(raw,delivery_type='unknown'))

    def test_launcher_preserves_original_resource_identity_and_timeout_boundaries(self):
        shell=(ROOT/'source/collect_p2pah_cost.sh').read_text()
        self.assertIn('timeout 180s docker run --rm --init --memory 2g --memory-swap 2g',shell)
        self.assertIn('src=/run/fs-order-session',shell);self.assertIn('src=/opt/fs-order-session',shell)
        self.assertNotIn('P2PAH_PASSWORD',shell);self.assertIn("'stage','exception_type','api_method'",shell)
        self.assertIn("['PS','XBOX','PC']",shell.replace(' ',''));self.assertIn("exit 1",shell)

    def test_original_publisher_adapter_is_exactly_two_cold_targets_without_restarts(self):
        calls=[];base=types.SimpleNamespace(restart_for=lambda m,f=None:calls.append(m['scope']))
        adapter=types.SimpleNamespace(load_base=lambda:base)
        loader=types.SimpleNamespace(exec_module=lambda m:None)
        util=types.SimpleNamespace(spec_from_file_location=lambda *a:types.SimpleNamespace(loader=loader),module_from_spec=lambda s:adapter)
        scope=dict(Path=Path,HERE=ROOT,SCOPE='fc-cost-session-recovery-20261025',importlib=types.SimpleNamespace(util=util))
        tree=ast.parse((ROOT/'release_adapter.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'cost_publisher_contract','exec'),scope)
        selected=scope['load_base']();self.assertIs(selected,base)
        self.assertEqual(set(adapter.TARGETS.values()),{'/opt/fc27-cloud-browser/collect_p2pah_cost.py','/opt/fc27-cloud-browser/collect_p2pah_cost.sh'})
        self.assertFalse(adapter.RESTART_FC);self.assertEqual(adapter.NEW,frozenset())
        selected.restart_for({'scope':'fc-cost-session-recovery-20261025'});self.assertEqual(calls,[])
        selected.restart_for({'scope':'other'});self.assertEqual(calls,['other'])


if __name__=='__main__':unittest.main()
