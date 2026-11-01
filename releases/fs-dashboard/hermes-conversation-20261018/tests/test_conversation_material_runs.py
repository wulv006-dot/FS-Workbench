"""Real task/file databases and official-schema recovery; zero provider calls."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'source'),str(MODULE.parent/'hermes-v2-core-20261020/source'),
             str(MODULE.parent/'hermes-fc-pilot-20261013')]
from pilot import TaskStore
from conversation_store import ConversationStore
from conversation_files import ConversationFiles
from conversation_goals import ConversationGoals
from conversation_goal_tasks import ConversationGoalTasks
from conversation_material_runs import MaterialRunLedger,MaterialRuntime,MaterialService,readonly_official_run,official_fingerprint
from b2_goal_host import GoalHost
from material_execution import prepare_materials,freeze_execution,operation_guard,build_context_proof
from conversation_file_bindings import ExecutionBoundFiles


class MaterialRunsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=Path(self.temp.name)
        self.store=ConversationStore(root/'conversations');self.cid=self.store.create('alice')['conversation_id']
        self.tasks=TaskStore(root/'tasks.sqlite3');self.allowed=True
        self.auth=lambda *args:self.allowed
        self.queue=ConversationGoalTasks(self.tasks,'alice',self.cid,self.auth,expected_path=self.tasks.path)
        self.goals=ConversationGoals(self.store,'alice',self.cid,self.auth)
        self.ledger=MaterialRunLedger(self.queue)
        self.files=ConversationFiles(self.store)
        self.item=self.files.save('alice',self.cid,'small.csv',b'name,value\na,10\nb,25\n','upload-original-1')
        self.now=datetime.now(timezone.utc)
        self.scope='material-selection-synthetic'
        self.host=GoalHost(self.goals,owner='alice',cid=self.cid,authorize=self.auth,
                           dispatcher=self.queue,verify_receipt=self.queue.verify_receipt)

    def execution(self,revise=False,read_scope=None,items=None):
        items=items or [self.item]
        operation={'mode':'read'} if not revise else dict(mode='revise',file_id=self.item['file_id'],
            edits=[dict(sheet=0,row=2,column=1,value=30)],format='xlsx')
        facts=prepare_materials(owner='alice',cid=self.cid,scope_ref=self.scope,selection_revision=1,
                                files=items,operation=operation,now=self.now)
        constraints=['No business sources']
        if read_scope:
            from conversation_material_runs import READ_SCOPE_PREFIX,_json
            constraints.append(READ_SCOPE_PREFIX+_json(read_scope))
        self.host.create('material-goal',mutation_id='create-material',scope_ref=self.scope,objective='Read selected material',
            constraints=constraints,recheck_at=self.now+timedelta(minutes=10),now=self.now,explicit_goal=True)
        result=self.host.step('material-goal',mutation_id='prepare-material',request_id='material-request-1',
                              fact_version=facts['fact_version'],now=self.now)
        binding=self.host._binding(result['state'])
        with self.queue._db() as db:
            handoff=json.loads(db.execute('SELECT handoff_json FROM conversation_goal_outbox_v1').fetchone()[0])
        execution=freeze_execution(binding=binding,handoff=handoff,selection_revision=1,files=items,
                                   operation=operation,deadline_at=self.now+timedelta(minutes=10),now=self.now)
        return execution

    def concurrent_first_parts(self, service, live=None):
        from concurrent.futures import ThreadPoolExecutor
        constructor_barrier=threading.Barrier(2)
        constructed=[]
        def construct(*args,**kwargs):
            runtime=MaterialRuntime(*args,**kwargs)
            constructed.append(runtime)
            if live:runtime.live.update(live)
            # The old unlocked implementation admits both constructors here.
            # With the cache lock, the only constructor times out at this test
            # synchronization point; no DB/network operation is mocked.
            try:constructor_barrier.wait(timeout=1)
            except threading.BrokenBarrierError:pass
            return runtime
        with patch('conversation_material_runs.MaterialRuntime',side_effect=construct),ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(service._parts,'alice',self.cid) for _ in range(2)]
            runtimes=[future.result(timeout=5)[3] for future in futures]
        self.assertEqual(len(constructed),1)
        self.assertIs(runtimes[0],runtimes[1])
        self.assertIs(service.runtimes[('alice',self.cid)],runtimes[0])
        return runtimes[0]

    def test_concurrent_first_parts_constructs_one_runtime_with_real_databases(self):
        hermes=SimpleNamespace(root=Path(self.tasks.path).parent,tasks=self.tasks,authorizer=self.auth)
        service=MaterialService(hermes,SimpleNamespace(store=self.store))
        runtime=self.concurrent_first_parts(service)
        self.assertIs(service._parts('alice',self.cid)[3],runtime)

    def test_concurrent_first_parts_keeps_live_book_and_reconcile_does_not_fence_it(self):
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'policy')
        self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'6'*32)
        book=object();token='synthetic-existing-token'
        hermes=SimpleNamespace(root=Path(self.tasks.path).parent,tasks=self.tasks,authorizer=self.auth,
            grants=SimpleNamespace(renew=lambda *a:None,revoke=lambda *a:self.fail('live grant revoked')),
            lock=threading.RLock(),tokens={row['task_id']:token},books={row['task_id']:book},gateways={})
        service=MaterialService(hermes,SimpleNamespace(store=self.store))
        queue=service._queue('alice',self.cid)
        with queue._db() as db:
            db.execute('INSERT INTO conversation_material_selections_v1 VALUES(?,?,?,?,?,?)',
                ('alice',self.cid,binding['request_id'],self.scope,'synthetic-request-sha','{}'))
        live={row['task_id']:{'token':token,'gateway':object()}}
        runtime=self.concurrent_first_parts(service,live)
        calls=[]
        def rpc(method,path,*args):
            calls.append((method,path));self.assertEqual(method,'GET')
            return 200,dict(run_id='run_'+'6'*32,session_id=row['session_id'],status='running')
        runtime.rpc=rpc
        with patch.object(runtime,'_admission'):
            self.assertEqual(service._parts('alice',self.cid)[3].reconcile(binding)['status'],'running')
        self.assertIs(runtime.live[row['task_id']],live[row['task_id']])
        self.assertIs(hermes.books[row['task_id']],book)
        self.assertEqual(self.tasks.get(row['task_id'],'alice')['state'],'RUNNING')
        self.assertEqual(calls,[('GET','/v1/materials/'+row['session_id'])])

    def test_scope_selection_is_frozen_before_cas_conflicts_and_changes_fact_version(self):
        hermes=SimpleNamespace(root=Path(self.tasks.path).parent,tasks=self.tasks,authorizer=self.auth)
        conversation=SimpleNamespace(store=self.store,pool=SimpleNamespace(submit=lambda *a:None))
        service=MaterialService(hermes,conversation)
        body=dict(client_request_id='scoped-request-1',goal='Read explicit range',file_ids=[self.item['file_id']],operation={'mode':'read'},
                  read_scope=dict(file_id=self.item['file_id'],sheet=0,offset=1,limit=1))
        with patch.dict(sys.modules,{'direct_provider':SimpleNamespace(POLICY_ID='effective-policy')}):
            first=service.submit('alice',self.cid,body)
            self.assertEqual(service.submit('alice',self.cid,body)['task_id'],first['task_id'])
            changed=json.loads(json.dumps(body));changed['read_scope']['offset']=2
            with self.assertRaisesRegex(ValueError,'request_conflict'):service.submit('alice',self.cid,changed)
            changed['client_request_id']='scoped-request-2';service.submit('alice',self.cid,changed)
        with self.tasks.db() as db:
            executions=[json.loads(r[0]) for r in db.execute('SELECT execution FROM conversation_material_runs_v1 ORDER BY request_id')]
        self.assertEqual([e['selection_revision'] for e in executions],[1,2])
        self.assertNotEqual(executions[0]['fact_version'],executions[1]['fact_version'])
        self.assertNotEqual(executions[0]['binding']['intent_sha256'],executions[1]['binding']['intent_sha256'])
        from conversation_material_runs import READ_SCOPE_PREFIX,read_scope
        _,goals,_,_=service._parts('alice',self.cid)
        for e in executions:
            state=goals.load_goal(e['binding']['goal_id'])
            self.assertEqual(state['constraints'],e['handoff']['constraints'])
            self.assertTrue(any(v.startswith(READ_SCOPE_PREFIX) for v in state['constraints']))
            self.assertEqual(read_scope(e)['limit'],1)
        for key,value in [('offset',True),('sheet',False),('limit',True),('limit',201),('offset',4),('sheet',10)]:
            invalid=json.loads(json.dumps(body));invalid['client_request_id']='invalid-scope-'+key+str(value);invalid['read_scope'][key]=value
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):service.submit('alice',self.cid,invalid)

    def test_multiple_inputs_require_each_workbook_and_eof_has_real_read_proof(self):
        from conversation_material_runs import read_satisfied
        other=self.files.save('alice',self.cid,'second.csv',b'x\n2\n','upload-second-1')
        execution=self.execution(items=[self.item,other]);binding=execution['binding']
        self.ledger.create(execution,'policy');self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'2'*32)
        context=ExecutionBoundFiles(self.store,self.goals,self.ledger,binding,self.auth,
            lambda name,args:operation_guard(execution,name,args,now=datetime.now(timezone.utc)))
        context.read_table(self.item['file_id'],sheet=0,offset=0,limit=200)
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        context.read_table(other['file_id'],sheet=0,offset=0,limit=200)
        self.assertTrue(read_satisfied(self.ledger.get(binding)))

    def test_empty_workbook_and_explicit_eof_need_actual_zero_row_page(self):
        import io
        from openpyxl import Workbook
        from conversation_material_runs import read_satisfied
        book=Workbook();raw=io.BytesIO();book.save(raw);book.close()
        self.item=self.files.save('alice',self.cid,'empty.xlsx',raw.getvalue(),'upload-empty-1')
        execution=self.execution(read_scope=dict(file_id=self.item['file_id'],sheet=0,offset=0,limit=200))
        binding=execution['binding'];self.ledger.create(execution,'policy');self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'2'*32)
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        context=ExecutionBoundFiles(self.store,self.goals,self.ledger,binding,self.auth,
            lambda name,args:operation_guard(execution,name,args,now=datetime.now(timezone.utc)))
        page=context.read_table(self.item['file_id'],sheet=0,offset=0,limit=200)
        self.assertEqual(page['total_rows'],0);self.assertEqual(page['returned_rows'],0)
        self.assertTrue(read_satisfied(self.ledger.get(binding)))

    def test_known_run_answer_is_bounded_separate_from_receipt_and_current_owner_rechecked(self):
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'policy')
        self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'4'*32)
        calls=[];response=dict(run_id='run_'+'4'*32,session_id=row['session_id'],status='completed',output='<script>plain text</script>'+'字'*30000)
        def rpc(method,path,*a):calls.append((method,path));return 200,response
        runtime=MaterialRuntime(SimpleNamespace(tasks=self.tasks),SimpleNamespace(),self.ledger,self.goals,rpc=rpc)
        result=runtime.answer(binding);self.assertTrue(result['truncated']);self.assertLessEqual(len(result['text'].encode()),65536)
        self.assertTrue(result['text'].startswith('<script>'))
        self.assertEqual(calls,[('GET','/v1/runs/'+'run_'+'4'*32)])
        self.assertNotIn('plain text',json.dumps(runtime.receipt(binding)))
        response['session_id']='mg_'+'f'*64;self.assertEqual(runtime.answer(binding)['text'],'')
        self.allowed=False
        with self.assertRaises(PermissionError):runtime.answer(binding)

    def test_real_task_creation_and_exact_replay_keep_fc_spec_contract_unchanged(self):
        execution=self.execution();binding=execution['binding']
        row=self.ledger.create(execution,'actual-general-policy')
        self.assertTrue(row['fresh_created'])
        task=self.tasks.get(row['task_id'],'alice')
        self.assertEqual(task['state'],'QUEUED');self.assertIsNone(task['spec']['period'])
        self.assertEqual(task['spec']['snapshot_id'],execution['snapshot_id'])
        self.assertFalse(self.ledger.create(execution,'actual-general-policy')['fresh_created'])
        self.assertEqual(len(self.store.detail('alice',self.cid)['turns']),0)
        self.assertTrue(self.ledger.claim_post(binding));self.assertFalse(self.ledger.claim_post(binding))
        self.assertEqual(self.tasks.get(row['task_id'],'alice')['state'],'DISPATCH_UNKNOWN')
        with self.tasks.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
            self.assertEqual(tuple(db.execute('SELECT task_id,lease,run_id FROM conversation_goal_outbox_v1').fetchone()),(None,None,None))

    def test_execution_files_page_revision_owner_expiry_and_stop_without_fake_turn(self):
        execution=self.execution(revise=True);binding=execution['binding'];row=self.ledger.create(execution,'actual-general-policy')
        self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'1'*32)
        context=ExecutionBoundFiles(self.store,self.goals,self.ledger,binding,lambda _:self.allowed,
            lambda name,args:operation_guard(execution,name,args,now=datetime.now(timezone.utc)))
        page=context.read_table(self.item['file_id'],sheet=0,offset=0,limit=200)
        self.assertEqual(page['returned_rows'],3)
        operation=execution['operation']
        item=context.revise(operation['file_id'],operation['edits'],operation['format'],operation['revision_request_id'])
        self.assertEqual(item['parent_id'],self.item['file_id']);self.assertEqual(item['version'],2)
        self.assertEqual(self.files.parsed('alice',self.cid,item['file_id'])['sheets'][0]['rows'][2][1],30)
        self.assertEqual(len(self.store.detail('alice',self.cid)['turns']),0)
        self.allowed=False
        with self.assertRaises(PermissionError):context.catalog()
        self.allowed=True;self.ledger.stop(binding)
        with self.assertRaises(PermissionError):context.catalog()

    def official(self,status='running',session=None,updated=None):
        path=Path(self.temp.name)/'official.db'
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('CREATE TABLE run_idempotency(scope TEXT,idempotency_key TEXT,fingerprint TEXT,run_id TEXT,status_json TEXT,owner_pid INTEGER,owner_started INTEGER,updated_at REAL,retention_until REAL,acknowledged_at REAL,PRIMARY KEY(scope,idempotency_key))')
            body={'input':'selected files','session_id':session or 'mg_'+'a'*64}
            fp=official_fingerprint(body)
            db.execute('INSERT INTO run_idempotency VALUES(?,?,?,?,?,?,?,?,?,?)',('authenticated-scope','original-key',fp,
                'run_'+'b'*32,json.dumps(dict(status=status,session_id=body['session_id'],output='must never leave resolver')),
                123,456,updated or self.now.timestamp(),0,None))
        return path,fp,body['session_id']

    def test_official_resolver_select_only_recovers_accepted_run_and_filters_body(self):
        path,fp,session=self.official();before=path.read_bytes()
        result=readonly_official_run(path,scope='authenticated-scope',key='original-key',fingerprint=fp,
            session_id=session,owner_alive=lambda *args:True,now=self.now.timestamp())
        self.assertEqual(result,dict(status='running',session_id=session,run_id='run_'+'b'*32))
        self.assertEqual(path.read_bytes(),before)
        for scope,key in [('other-scope','original-key'),('authenticated-scope','missing')]:
            result=readonly_official_run(path,scope=scope,key=key,fingerprint=fp,session_id=session,owner_alive=lambda *args:True)
            self.assertEqual(result['status'],'unknown');self.assertNotIn('run_id',result)
        with self.assertRaises(PermissionError):
            readonly_official_run(path,scope='authenticated-scope',key='original-key',fingerprint='wrong',session_id=session,owner_alive=lambda *args:True)

    def test_official_resolver_stale_owner_and_expired_terminal_never_reserve_or_prune(self):
        path,fp,session=self.official(status='completed',updated=self.now.timestamp()-90000)
        before=path.read_bytes()
        result=readonly_official_run(path,scope='authenticated-scope',key='original-key',fingerprint=fp,session_id=session,
                                     owner_alive=lambda *args:False,now=self.now.timestamp())
        self.assertEqual(result['status'],'unknown');self.assertEqual(path.read_bytes(),before)
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('UPDATE run_idempotency SET status_json=?',(json.dumps(dict(status='running',session_id=session)),))
        before=path.read_bytes()
        result=readonly_official_run(path,scope='authenticated-scope',key='original-key',fingerprint=fp,session_id=session,
                                     owner_alive=lambda *args:False,now=self.now.timestamp())
        self.assertEqual(result['status'],'interrupted');self.assertEqual(path.read_bytes(),before)

    def test_authenticated_http_material_creates_real_task_without_human_turn_and_reuses_original(self):
        from conversation_http import handle
        from urllib.parse import urlsplit
        pool=SimpleNamespace(submit=lambda *args:None)
        hermes=SimpleNamespace(root=Path(self.tasks.path).parent,tasks=self.tasks,authorizer=lambda user:user=='alice',
            grants=SimpleNamespace(revoke=lambda token:None),lock=threading.RLock(),tokens={},books={},gateways={})
        conversation=SimpleNamespace(store=self.store,pool=pool,run_root=Path(self.temp.name)/'run')
        service=MaterialService(hermes,conversation);conversation.materials=service
        outer=self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):handle(self,'POST',urlsplit(self.path),'alice',conversation,hermes.authorizer)
            def do_GET(self):handle(self,'GET',urlsplit(self.path),'alice',conversation,hermes.authorizer)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/api/hermes/conversations/'+self.cid+'/materials'
            body=dict(client_request_id='actual-material-http-1',goal='Read selected CSV',file_ids=[self.item['file_id']],operation={'mode':'read'})
            with patch.dict(sys.modules,{'direct_provider':SimpleNamespace(POLICY_ID='test-effective-policy')}):
                request=Request(url,data=json.dumps(body).encode(),method='POST',headers={
                    'Content-Type':'application/json','X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'})
                with urlopen(request) as response:result=json.load(response)
                with urlopen(request) as response:again=json.load(response)
            self.assertEqual(result['task_id'],again['task_id']);self.assertEqual(result['status'],'queued')
            self.assertIsNone(result['run_id']);self.assertEqual(self.store.detail('alice',self.cid)['turns'],[])
            with self.tasks.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0],1)
            original=url+'/'+body['client_request_id']
            with urlopen(original+'/result') as response:answer=json.load(response)
            self.assertEqual(answer['text'],'');self.assertEqual(answer['status'],'unknown')
            stop=Request(original+'/stop',data=b'{}',method='POST',headers={
                'Content-Type':'application/json','X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin'})
            with urlopen(stop) as response:stopped=json.load(response)
            self.assertEqual(stopped['status'],'cancelled');self.assertEqual(stopped['task_id'],result['task_id'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_lost_202_recovers_only_original_official_record_without_second_post(self):
        # Real local HTTP + official-shaped SQLite reservation. No SDK agent or
        # provider is constructed; the fixture deliberately drops the HTTP202.
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'actual-general-policy')
        self.assertTrue(self.ledger.claim_post(binding))
        official=Path(self.temp.name)/'accepted-official.db'
        with closing(sqlite3.connect(official)) as db:
            db.execute('CREATE TABLE run_idempotency(scope TEXT,idempotency_key TEXT,fingerprint TEXT,run_id TEXT,status_json TEXT,owner_pid INTEGER,owner_started INTEGER,updated_at REAL,retention_until REAL,acknowledged_at REAL)')
        posts=[];outer=self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                posts.append(body)
                with closing(sqlite3.connect(official)) as db,db:
                    db.execute('INSERT INTO run_idempotency VALUES(?,?,?,?,?,?,?,?,?,?)',
                        ('current-auth',self.headers['Idempotency-Key'],official_fingerprint(body),'run_'+'d'*32,
                         json.dumps(dict(status='queued',session_id=body['session_id'])),123,456,outer.now.timestamp(),0,None))
                self.close_connection=True  # Lost 202 after durable reserve.
            def do_GET(self):
                result=readonly_official_run(official,scope='current-auth',key=row['runtime_key'],
                    fingerprint=row['body_sha'],session_id=row['session_id'],owner_alive=lambda *args:True)
                raw=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with self.assertRaises(OSError):
                urlopen(Request(base+'/v1/runs',data=row['body'].encode(),method='POST',headers={'Idempotency-Key':row['runtime_key']}))
            with urlopen(base+'/v1/materials/'+row['session_id']) as response:found=json.load(response)
            self.ledger.bind_run(binding,found['run_id'])
            self.assertEqual(self.tasks.get(row['task_id'],'alice')['run_id'],found['run_id'])
            self.assertFalse(self.ledger.claim_post(binding));self.assertEqual(len(posts),1)
            self.assertEqual(MaterialRunLedger(self.queue).get(binding)['run_id'],found['run_id'])
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)

    def test_runtime_single_attempt_executes_real_files_and_completed_receipt_is_not_goal_achievement(self):
        # Runs protocol fixture, not a claim to have started the real SDK/model.
        # Exercise the production MaterialRuntime and real lease/file tool chain.
        from test_conversation_file_loop import WorkerFileLoop
        WorkerFileLoop.setUpClass()
        execution=self.execution(revise=True);binding=execution['binding'];row=self.ledger.create(execution,'actual-general-policy')
        run_id='run_'+'e'*32;posts=[];observations=[]
        admissions=Path(self.temp.name)/'runtime'/'admissions';admissions.mkdir(parents=True)
        lock=threading.RLock()
        grants=SimpleNamespace(mint=lambda *a,**k:'t'*48,renew=lambda *a:None,revoke=lambda *a:None)
        hermes=SimpleNamespace(tasks=self.tasks,daily=object(),authorizer=lambda _:True,
                              grants=grants,lock=lock,tokens={},books={},gateways={})
        conversation=SimpleNamespace(store=self.store,run_root=admissions.parent)
        def atomic(path,value):path.write_text(json.dumps(value),encoding='utf-8')
        def gateway(*args,**kwargs):
            self.assertTrue(kwargs['material_execution'])
            return SimpleNamespace(budget=SimpleNamespace(policy={'id':'actual-general-policy','model':'deepseek-flash'}))
        official_status=dict(status='queued',session_id=row['session_id'],run_id=run_id)
        from conversation_file_tools import WIRE_NAMES
        def rpc(method,path,body=None,key=None):
            if path=='/v1/capabilities':return 200,{'fs_materials':{'verified_pin':True,'readonly_original_lookup':True,'single_post':True}}
            if method=='POST' and path=='/v1/runs':
                self.assertEqual(key,row['runtime_key']);posts.append(body)
                raise OSError('accepted but HTTP202 lost')
            if method=='GET' and path.startswith('/v1/materials/'):
                admitted=json.loads((admissions/(row['session_id']+'.json')).read_text())
                if admitted['ready'] and official_status['status']=='queued':
                    book=hermes.books[row['task_id']]
                    scope=WorkerFileLoop.deployed_gateway.ScopedTools(self.tasks,book,lambda:datetime.now(timezone.utc))
                    page=scope.call('alice',row['task_id'],row['lease'],WIRE_NAMES[1],
                        dict(file_id=self.item['file_id'],sheet=0,offset=0,limit=200))
                    observations.append(page)
                    op=execution['operation']
                    artifact=scope.call('alice',row['task_id'],row['lease'],WIRE_NAMES[2],
                        dict(file_id=op['file_id'],edits=op['edits'],format=op['format'],request_id=op['revision_request_id']))
                    observations.append(artifact)
                    proof=build_context_proof(execution,session_id=row['session_id'],run_id=run_id,
                        actual_system_prompt='SDK fixture base\n'+admitted['prompt'],actual_input=posts[0]['input'],
                        actual_tool_names=list(WIRE_NAMES),native_memory_skipped=True)
                    official_status.update(status='completed',context_receipt=proof)
                return 200,dict(official_status)
            if path.endswith('/stop'):return 200,{'status':'stopping'}
            raise AssertionError((method,path))
        runtime=MaterialRuntime(hermes,conversation,self.ledger,self.goals,rpc=rpc)
        with patch.dict(sys.modules,{'controller':SimpleNamespace(atomic=atomic),
                'fs_inprocess':SimpleNamespace(gateway=gateway,spending_hold=lambda *args:None),
                'strategy_tools':WorkerFileLoop.strategies}):
            self.assertEqual(runtime.start(binding,fresh=True)['status'],'unknown')
            self.assertEqual(runtime.reconcile(binding)['status'],'queued')
            self.assertEqual(runtime.reconcile(binding)['status'],'completed')
            self.assertEqual(runtime.start(binding)['status'],'completed')
        self.assertEqual(len(posts),1)
        self.assertEqual(self.tasks.get(row['task_id'],'alice')['state'],'SUCCEEDED')
        receipt=runtime.receipt(binding);self.assertTrue(runtime.verify_receipt(receipt,binding))
        self.host.verify_receipt=runtime.verify_receipt
        self.host.observe('material-goal',receipt=receipt,now=datetime.now(timezone.utc))
        self.assertEqual(self.goals.load_goal('material-goal')['status'],'active')
        self.assertEqual(self.goals.load_goal('material-goal')['work']['status'],'completed')
        artifact=self.ledger.get(binding)['generated'][0]
        self.assertEqual(self.files.parsed('alice',self.cid,artifact['file_id'])['sheets'][0]['rows'][2][1],30)
        self.assertEqual(self.store.detail('alice',self.cid)['turns'],[])

    def test_read_completion_requires_requested_range_and_reuses_b_partial_evidence(self):
        from conversation_material_runs import read_satisfied
        raw=b'name,value\n'+b'a,10\n'*450
        self.item=self.files.save('alice',self.cid,'large.csv',raw,'upload-large-1')
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'policy')
        self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'2'*32)
        context=ExecutionBoundFiles(self.store,self.goals,self.ledger,binding,self.auth,
            lambda name,args:operation_guard(execution,name,args,now=datetime.now(timezone.utc)))
        context.read_table(self.item['file_id'],sheet=0,offset=0,limit=200)
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        context.read_table(self.item['file_id'],sheet=0,offset=400,limit=200)
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        context.read_table(self.item['file_id'],sheet=0,offset=200,limit=200)
        self.assertTrue(read_satisfied(self.ledger.get(binding)))
        summary=self.ledger.get(binding)['coverage'][-1]['analysis_coverage']
        self.assertEqual(summary['observed_sheets'][0]['total_rows'],451)
        self.assertTrue(summary['workbook_complete'])
        references=self.ledger.get(binding)['coverage'][-1]['evidence']
        self.assertIn('business_data_not_read',references[0]['missing'])
        self.assertIn('long_term_goal_not_assessed',references[0]['missing'])

    def test_explicit_partial_read_completes_only_its_frozen_range(self):
        from conversation_material_runs import read_satisfied
        self.item=self.files.save('alice',self.cid,'large.csv',b'x\n'+b'1\n'*450,'upload-large-2')
        selected=dict(file_id=self.item['file_id'],sheet=0,offset=200,limit=100)
        execution=self.execution(read_scope=selected);binding=execution['binding']
        self.ledger.create(execution,'policy');self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'2'*32)
        context=ExecutionBoundFiles(self.store,self.goals,self.ledger,binding,self.auth,
            lambda name,args:operation_guard(execution,name,args,now=datetime.now(timezone.utc)))
        with self.assertRaises(PermissionError):context.read_table(self.item['file_id'],sheet=0,offset=0,limit=100)
        context.read_table(self.item['file_id'],sheet=0,offset=250,limit=50)
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        context.read_table(self.item['file_id'],sheet=0,offset=200,limit=25)
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        context.read_table(self.item['file_id'],sheet=0,offset=225,limit=25)
        self.assertTrue(read_satisfied(self.ledger.get(binding)))
        self.assertFalse(self.ledger.get(binding)['coverage'][-1]['analysis_coverage']['workbook_complete'])

    def test_explicit_nonempty_eof_is_not_full_workbook_coverage(self):
        from conversation_material_runs import read_satisfied
        execution=self.execution(read_scope=dict(file_id=self.item['file_id'],sheet=0,offset=3,limit=10))
        binding=execution['binding'];self.ledger.create(execution,'policy');self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'2'*32)
        context=ExecutionBoundFiles(self.store,self.goals,self.ledger,binding,self.auth,
            lambda name,args:operation_guard(execution,name,args,now=datetime.now(timezone.utc)))
        self.assertFalse(read_satisfied(self.ledger.get(binding)))
        page=context.read_table(self.item['file_id'],sheet=0,offset=3,limit=10)
        self.assertEqual(page['total_rows'],3);self.assertEqual(page['returned_rows'],0)
        self.assertTrue(read_satisfied(self.ledger.get(binding)))
        self.assertFalse(self.ledger.get(binding)['coverage'][-1]['analysis_coverage']['workbook_complete'])

    def test_restart_and_revocation_fence_original_run_without_repost_or_new_grant(self):
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'policy')
        self.ledger.claim_post(binding)
        calls=[]
        def rpc(method,path,*args):
            calls.append((method,path))
            if method=='GET':return 200,dict(session_id=row['session_id'],run_id='run_'+'3'*32,status='running')
            self.assertTrue(path.endswith('/stop'));return 200,{'status':'stopping'}
        hermes=SimpleNamespace(root=Path(self.tasks.path).parent,tasks=self.tasks,authorizer=lambda user:False,
            grants=SimpleNamespace(revoke=lambda token:None),lock=threading.RLock(),tokens={},books={},gateways={})
        conversation=SimpleNamespace(store=self.store)
        runtime=MaterialRuntime(hermes,conversation,self.ledger,self.goals,rpc=rpc)
        self.assertEqual(runtime.start(binding)['status'],'unknown')
        self.assertEqual(self.tasks.get(row['task_id'],'alice')['state'],'CANCEL_REQUESTED')
        self.assertEqual([method for method,path in calls if path=='/v1/runs'],[])
        self.allowed=False;calls.clear()
        with patch.object(MaterialRuntime,'_rpc',side_effect=rpc):MaterialService(hermes,conversation).recover()
        self.assertTrue(any(path.endswith('/stop') for method,path in calls))
        self.assertFalse(any(path=='/v1/runs' for method,path in calls))

    def test_only_one_concurrent_durable_claim_can_attempt_post(self):
        from concurrent.futures import ThreadPoolExecutor
        execution=self.execution();binding=execution['binding'];self.ledger.create(execution,'policy')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda _:MaterialRunLedger(self.queue).claim_post(binding),range(4)))
        self.assertEqual(results.count(True),1)
        self.assertEqual(self.ledger.get(binding)['attempted'],1)

    def test_pause_winning_between_runtime_read_and_claim_prevents_post(self):
        from b2_goal_state import configure_goal
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'policy')
        hermes=SimpleNamespace(tasks=self.tasks,daily=object(),authorizer=self.auth)
        conversation=SimpleNamespace(store=self.store)
        def rpc(method,path,*args):
            self.assertEqual((method,path),('GET','/v1/capabilities'))
            return 200,{'fs_materials':{'verified_pin':True,'readonly_original_lookup':True,'single_post':True}}
        runtime=MaterialRuntime(hermes,conversation,self.ledger,self.goals,rpc=rpc)
        original=self.goals.load_goal;reads=[]
        def load(goal_id):
            state=original(goal_id);reads.append(True)
            if len(reads)==2:
                paused=configure_goal(state,expected_revision=state['revision'],now=datetime.now(timezone.utc),authorize=self.auth,status='paused')['state']
                self.goals.cas_goal(goal_id,expected_revision=state['revision'],mutation_id='pause-wins-runtime',state=paused)
            return state
        with patch.object(self.goals,'load_goal',side_effect=load),patch.dict(sys.modules,{'fs_inprocess':SimpleNamespace(
                gateway=lambda *a,**k:SimpleNamespace(budget=SimpleNamespace(policy={'id':'policy'})),spending_hold=lambda *a:None)}):
            with self.assertRaisesRegex(PermissionError,'goal_claim_conflict'):runtime.start(binding,fresh=True)
        self.assertEqual(self.ledger.get(binding)['attempted'],0)
        self.assertEqual(self.tasks.get(row['task_id'],'alice')['state'],'QUEUED')

    def test_actual_worker_constructor_measures_file_only_context_and_refuses_tool_drift(self):
        from material_execution import verify_context_proof
        from test_conversation_file_loop import WorkerEnvironmentTests
        execution=self.execution()
        fixture=WorkerEnvironmentTests()
        with fixture.runtime(execution=execution) as (worker,adapter,calls,modules):
            agent=adapter._create_agent(session_id='mg_'+'a'*64)
            proof=agent._hermes_api_runtime['fs_material_context']
            self.assertTrue(verify_context_proof(execution,proof,session_id='mg_'+'a'*64,run_id='run_'+'d'*32))
            self.assertEqual(calls['agent']['enabled_toolsets'],['fs_materials'])
            self.assertEqual(calls['dotenv_reads'],0)
            self.assertIsNone(calls['agent']['fallback_model'])
        with fixture.runtime(execution=execution,extra_tool=True) as (worker,adapter,calls,modules):
            with self.assertRaises(PermissionError):adapter._create_agent(session_id='mg_'+'a'*64)
            self.assertTrue(calls['closed'])

    def test_worker_refuses_material_post_without_pin_and_durable_store(self):
        import asyncio
        from test_conversation_file_loop import WorkerEnvironmentTests
        from conversation_material_runs import runtime_pin_verified
        root=Path(self.temp.name)/'pin';root.mkdir()
        pins={name:hashlib.sha256(name.encode()).hexdigest() for name in ('a.py','b.py','c.py')}
        for name in pins:(root/name).write_bytes(name.encode())
        with patch('conversation_material_runs.PIN_FILES',pins):
            self.assertTrue(runtime_pin_verified(root));(root/'b.py').write_bytes(b'drift')
            self.assertFalse(runtime_pin_verified(root))
        execution=self.execution()
        with WorkerEnvironmentTests().runtime(execution=execution) as (worker,adapter,calls,modules):
            modules['gateway.platforms.api_server_runs'].__file__=str(root/'api_server_runs.py')
            modules['aiohttp'].web.json_response=lambda value,status=200:SimpleNamespace(status=status,body=json.dumps(value).encode())
            adapter._run_idempotency_store=SimpleNamespace(durable=False)
            request=SimpleNamespace(method='POST',path='/v1/runs',headers={})
            async def body():return {'input':execution['input'],'session_id':'mg_'+'a'*64}
            request.json=body
            async def handler(request):self.fail('unverified material POST reached official admission')
            middleware=adapter._make_profile_prefix_middleware()
            for pinned in (False,True):
                with patch('conversation_material_runs.runtime_pin_verified',return_value=pinned):
                    self.assertEqual(asyncio.run(middleware(request,handler)).status,403)

    def test_material_gateway_limits_schemas_strategies_lane_and_transport_retries(self):
        from test_conversation_file_loop import WorkerFileLoop,load,PACKAGES
        from conversation_file_tools import WIRE_NAMES
        from contextlib import nullcontext
        policy_id='no-pilot-quotas-deepseek-direct-stream-tokens-only-v2'
        WorkerFileLoop.setUpClass();proxy=WorkerFileLoop.deployed_gateway
        execution=self.execution();binding=execution['binding'];row=self.ledger.create(execution,'effective-policy')
        self.ledger.claim_post(binding);self.ledger.bind_run(binding,'run_'+'5'*32)
        book=SimpleNamespace(capture_id=execution['snapshot_id'],material_execution=True,
                             authorize_execution=lambda:True,call=lambda *a:self.fail('non-file book bypass'))
        schemas=proxy.task_schemas(book)
        self.assertEqual([s['function']['name'] for s in schemas],list(WIRE_NAMES))
        request=proxy.request_body(dict(messages=[dict(role='user',content='synthetic')],max_tokens=20),
                                   'deepseek-flash',tool_schemas=schemas)
        self.assertEqual(request['tools'],schemas)
        scope=proxy.ScopedTools(self.tasks,book,lambda:datetime.now(timezone.utc))
        nonfile='mcp__fcro__fs_pricing_control'
        with patch.object(proxy,'WIRE_TOOLS',tuple(proxy.WIRE_TOOLS)+(nonfile,)),patch.object(proxy,'SEMANTIC_TOOLS',tuple(proxy.SEMANTIC_TOOLS)+('fs.pricing.control',)):
            with self.assertRaisesRegex(PermissionError,'material_tool_denied'):scope.call('alice',row['task_id'],row['lease'],nonfile,{})
        modules={'proxy_gateway':proxy,'background':SimpleNamespace(import_background=None),
            'source_projection':SimpleNamespace(project_capture=None),
            'fc_daily':SimpleNamespace(provider_slot=lambda root:nullcontext(True),model_daily_limit=lambda:0),
            'direct_provider':SimpleNamespace(MODEL='deepseek-flash',POLICY_ID=policy_id,
                request_model=lambda *a,**k:self.fail('no provider call'),prepare_request=lambda *a,**k:None)}
        with patch.dict(sys.modules,modules):
            source=load('material_actual_inprocess',PACKAGES.parent/'fc-coins/fc-review-channel-20261026/source/fs_inprocess.py')
            with self.tasks.db() as db:db.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
            daily=SimpleNamespace(root=Path(self.temp.name)/'daily',db=self.tasks.db)
            gateway=source.gateway(daily,self.tasks,book,material_execution=True)
            self.assertEqual(gateway.transport_retries,0);self.assertEqual(gateway.budget.policy['id'],policy_id)
            with self.assertRaises(PermissionError):source.gateway(daily,self.tasks,book,material_execution=True,provider_lane='pricing')
