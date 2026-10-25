import ast,asyncio,hashlib,importlib.util,json,os,re,sqlite3,stat,sys,tempfile,threading,time,types,unittest
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(Path(__file__).parent))
import reader_contract as contract


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def functions(path,names,scope):
    tree=ast.parse(path.read_text(encoding='utf-8'));nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(path),'exec'),scope);return types.SimpleNamespace(**scope)


class Knowledge(unittest.TestCase):
    def test_publisher_only_accepts_the_existing_exact_readonly_group_boundary(self):
        m=functions(SOURCE.parent/'release_adapter.py',{'approved_boundary'},dict(stat=stat))
        original=lambda *args:False;scope={'scope':'fc-review-u4gm-recovery-20261025'}
        path=Path('/opt/fs-sports-outbound');info=types.SimpleNamespace(st_uid=0,st_gid=11028,st_mode=0o40750)
        self.assertTrue(m.approved_boundary(original,scope,Path('/'),path,info))
        for changed in ({'st_uid':1},{'st_gid':1},{'st_mode':0o40770}):
            bad=types.SimpleNamespace(**(vars(info)|changed))
            self.assertFalse(m.approved_boundary(original,scope,Path('/'),path,bad))
        self.assertFalse(m.approved_boundary(original,{},Path('/'),path,info))
        self.assertFalse(m.approved_boundary(original,scope,Path('/'),Path('/opt/other'),info))

    def test_full_sources_and_hashes_retained_near_original_limit(self):
        b=load(SOURCE/'business_context.py','context_candidate')
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);skills=root/'skills';skills.mkdir();source=root/'runtime';source.mkdir();(source/'business_context.py').touch()
            b.__file__=str(source/'business_context.py');b.FILES=tuple('method-'+str(i)+'.md' for i in range(16))
            for name in b.FILES:(skills/name).write_text('full approved method '+name+'\n'+'X'*1000)
            for name in ('business-baseline.md','learning-loop.md','data-archive-first.md'):(source/name).write_text('full '+name+'\n'+'Y'*1000)
            selection={'entries':[]};catalog='selected approved knowledge\n'+'K'*10000
            with patch.dict(sys.modules,knowledge_catalog=types.SimpleNamespace(context=lambda s:catalog)):
                initial=b.learning_bundle(root,skills,selection=selection)[0]
                extra=b.MAX_TOTAL-500-len(initial.encode());self.assertGreater(extra,0)
                for i in range(3):
                    p=skills/b.FILES[i];p.write_text(p.read_text()+'Z'*(extra//3+(1 if i<extra%3 else 0)))
                text,sha,rows=b.learning_bundle(root,skills,selection=selection)
                self.assertLess(len(text.encode()),b.MAX_TOTAL);self.assertEqual(b.MAX_TOTAL,262144)
                manifest=text.split('本次已冻结学习资料清单：',1)[1].split('\n',1)[0]
                legacy=json.dumps({'version':'desktop-learning-v2','files':rows},ensure_ascii=False,sort_keys=True,separators=(',',':'))
                self.assertGreater(len(text.replace(manifest,legacy).encode()),b.MAX_TOTAL)
                documents=re.findall(r'<owner_learning_document path="([^"]+)" sha256="([a-f0-9]{64})">\n([\s\S]*?)\n</owner_learning_document>',text)
                self.assertEqual(len(documents),len(rows));self.assertIn(catalog,text)
                for path,digest,body in documents:
                    p=skills/path[7:] if path.startswith('skills/') else source/('data-archive-first.md' if path=='runtime/data-archive-first/SKILL.md' else path[8:])
                    self.assertEqual(body,p.read_bytes().decode().strip());self.assertEqual(digest,hashlib.sha256(p.read_bytes()).hexdigest())
                p=skills/b.FILES[0];p.write_text(p.read_text()+'too large'*1000)
                with self.assertRaisesRegex(ValueError,'bundle_too_large'):b.learning_bundle(root,skills,selection=selection)

    def test_dispatch_error_is_durable_sanitized_and_never_replays(self):
        def atomic(p,value,mode):p.write_text(json.dumps(value));os.chmod(p,mode)
        m=functions(SOURCE/'conversation_service.py',{'dispatch_failure'},dict(Path=Path,re=re,atomic=atomic))
        with tempfile.TemporaryDirectory() as d:
            with self.assertLogs(level='ERROR'):
                m.dispatch_failure(d,'wulv','c','t','r','learning_bundle',ValueError('desktop_learning_bundle_too_large'))
                m.dispatch_failure(d,'wulv','c','other','r','runtime_submit',ValueError('secret token=abc URL=private'))
            v=json.loads((Path(d)/'contexts/t-dispatch-error.json').read_text())
            self.assertEqual(v['reason_code'],'desktop_learning_bundle_too_large');self.assertTrue(v['do_not_replay'])
            self.assertNotIn('secret',(Path(d)/'contexts/other-dispatch-error.json').read_text())

    def test_bridge_reads_only_same_original_failure_and_survives_bad_diagnostic(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'conversations').mkdir();(root/'contexts').mkdir()
            with closing(sqlite3.connect(root/'conversations/conversations.db')) as db,db:
                db.execute('create table turns(id, state, task_id,run_id,conversation_id,request_id)');db.execute('create table conversations(id,owner)')
                db.execute("insert into conversations values('c','wulv')");db.execute("insert into turns values('t','failed',NULL,NULL,'c','r')")
            b=functions(SOURCE/'hermes_pricing_bridge.py',{'turn_state'},dict(FS=root,closing=closing,sqlite3=sqlite3,json=json))
            p=root/'contexts/t-dispatch-error.json';v=dict(owner='wulv',conversation_id='c',turn_id='t',request_id='r',stage='learning_bundle',reason_code='desktop_learning_bundle_too_large',do_not_replay=True)
            p.write_text(json.dumps(v));self.assertEqual(b.turn_state('c','r','wulv')['dispatch_failure']['stage'],'learning_bundle')
            v['request_id']='another';p.write_text(json.dumps(v));self.assertNotIn('dispatch_failure',b.turn_state('c','r','wulv'))
            p.write_text('bad json');self.assertEqual(b.turn_state('c','r','wulv')['state'],'failed')

    def test_diagnostic_write_failure_does_not_interrupt_original_cleanup(self):
        def atomic(*args,**kwargs):raise ValueError('linked_result')
        m=functions(SOURCE/'conversation_service.py',{'dispatch_failure'},dict(Path=Path,re=re,atomic=atomic))
        with tempfile.TemporaryDirectory() as d,self.assertLogs(level='ERROR') as logs:
            m.dispatch_failure(d,'wulv','c','t','r','learning_bundle',ValueError('desktop_learning_bundle_too_large'))
        self.assertTrue(any('persist_failed' in line for line in logs.output))


class Page:
    def __init__(self,platform):self.platform=platform;self.closed=False
    def goto(self,*a,**k):return types.SimpleNamespace(status=200)
    def wait_for_timeout(self,*a):pass
    def evaluate(self,script,*args):
        if 'document.title' in script:return False
        return dict(ready=True,platformText={'PS':'PS 4/5','XBOX':'Xbox One/Series','PC':'PC'}[self.platform],price={'PS':'8.50','XBOX':'8.50','PC':'8.60'}[self.platform],bonus='5',label='100K + 5K')
    def locator(self,*a):return types.SimpleNamespace(click=lambda **k:None)
    def close(self):self.closed=True


class AsyncPage(Page):
    async def goto(self,*a,**k):return super().goto(*a,**k)
    async def wait_for_timeout(self,*a):pass
    async def evaluate(self,script,*args):return super().evaluate(script)
    def locator(self,*a):
        async def click(**kwargs):pass
        return types.SimpleNamespace(click=click)
    async def close(self):super().close()


class U4GM(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.transport=types.SimpleNamespace(fetch=lambda *a,**k:b'public bytes')
        modules={'collect_competitor_browser':contract,'sports_outbound':self.transport,'playwright.async_api':types.SimpleNamespace(async_playwright=lambda:None,TimeoutError=TimeoutError)}
        with patch.dict(sys.modules,modules):self.m=load(SOURCE/'collect_fc_u4gm.py','u4gm_candidate')

    async def test_original_three_platform_price_contract_and_cleanup_unchanged(self):
        original_pages=[Page(p) for p in contract.PLATFORMS];iterator=iter(original_pages)
        old=contract.collect_u4gm(types.SimpleNamespace(new_page=lambda:next(iterator)))
        pages=[AsyncPage(p) for p in contract.PLATFORMS];iterator=iter(pages)
        async def new_page():return next(iterator)
        new=await self.m.collect(types.SimpleNamespace(new_page=new_page),time.monotonic()+90,{})
        for a,b in zip(old,new):
            a.pop('captured_at');b.pop('captured_at');self.assertEqual(a,b)
        self.assertTrue(all(p.closed for p in original_pages+pages))

    async def test_network_reads_yield_and_are_bounded_at_four_without_credentials(self):
        active=maximum=0;guard=threading.Lock();release=threading.Event();seen=[]
        def fetch(url,data,headers,timeout):
            nonlocal active,maximum
            with guard:active+=1;maximum=max(maximum,active);seen.append(headers)
            release.wait(2)
            with guard:active-=1
            return b'bounded public bytes'
        self.transport.fetch=fetch
        class Route:
            request=types.SimpleNamespace(resource_type='script',url='https://www.u4gm.com/public.js',post_data_buffer=None,headers={'cookie':'private','authorization':'private','accept':'*/*'})
            async def fulfill(self,**kwargs):self.result=kwargs
            async def continue_(self):self.result='continued'
            async def abort(self,*a):self.result='aborted'
        routes=[Route() for _ in range(8)];failures=[];semaphore=asyncio.Semaphore(4)
        with ThreadPoolExecutor(max_workers=4) as executor:
            tasks=[asyncio.create_task(self.m.route_public(r,time.monotonic()+90,failures,semaphore,executor)) for r in routes]
            for _ in range(100):
                if maximum==4:break
                await asyncio.sleep(.005)
            self.assertEqual(maximum,4);release.set();await asyncio.gather(*tasks)
        self.assertEqual(failures,[]);self.assertTrue(all('cookie' not in h and 'authorization' not in h for h in seen))

    async def test_failed_route_is_recorded_without_url_or_secret(self):
        self.transport.fetch=lambda *a,**k:(_ for _ in ()).throw(TimeoutError('private proxy URL key=secret'))
        class Route:
            request=types.SimpleNamespace(resource_type='document',url='https://www.u4gm.com/fc-27/coins',post_data_buffer=None,headers={})
            async def abort(self,*a):self.aborted=True
        route=Route();failures=[]
        with ThreadPoolExecutor(max_workers=4) as executor:await self.m.route_public(route,time.monotonic()+90,failures,asyncio.Semaphore(4),executor)
        self.assertTrue(route.aborted);self.assertEqual(failures[0]['error_type'],'TimeoutError');self.assertNotIn('secret',json.dumps(failures))

    def test_expired_deadline_never_becomes_infinite_timeout(self):
        with self.assertRaisesRegex(ValueError,'source_deadline'):self.m.remaining_timeout(time.monotonic()-1,35000)

    async def test_timeout_retry_releases_each_context_and_returns_only_complete_new_rows(self):
        contexts=[];calls=[]
        class Context:
            async def route(self,*args):pass
            async def close(self):self.closed=True
        class Browser:
            async def new_context(self,**kwargs):
                context=Context();context.closed=False;contexts.append(context);return context
        class Playwright:
            async def __aenter__(self):return types.SimpleNamespace(chromium=self)
            async def __aexit__(self,*args):pass
            async def connect_over_cdp(self,*args,**kwargs):
                self_test.assertTrue(kwargs['no_defaults']);return Browser()
        self_test=self
        async def collect(context,deadline,diagnostic):
            calls.append(context);diagnostic.update(platform='PC',phase='stable_price')
            if len(calls)==1:raise TimeoutError('original partial platform timeout')
            return [dict(platform=p) for p in contract.PLATFORMS]
        self.m.async_playwright=Playwright;self.m.collect=collect
        result=await self.m.run()
        self.assertEqual(result['status'],'valid');self.assertEqual(len(result['read_retries']),1)
        self.assertEqual(len(calls),2);self.assertTrue(all(c.closed for c in contexts))
        async def failed(*args):raise TimeoutError('all attempts fail')
        self.m.collect=failed
        result=await self.m.run()
        self.assertEqual(result['status'],'missing');self.assertNotIn('offers',result)
        self.assertEqual(len(contexts),4);self.assertTrue(all(c.closed for c in contexts))


if __name__=='__main__':unittest.main()
