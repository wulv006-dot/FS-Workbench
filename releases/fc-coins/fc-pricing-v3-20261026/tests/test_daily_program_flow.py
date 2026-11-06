import ast
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from email.message import Message
import io,json,sqlite3,sys,tempfile,threading
import subprocess
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from urllib.parse import urlsplit

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import daily,runtime,scheduler,shadow_worker
from fc_pricing_v3.ledger import Ledger
from fixtures import fixture,NOW
import automation_policy,conversation_http,hermes_pricing_bridge,pricing_operations


class DailyProgramFlow(unittest.TestCase):
    def test_normal_quote_calculates_only_current_strategy_without_model(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db')
            data=fixture()[0];data['run_id']='00000000-0000-4000-8000-000000000099'
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',Path(folder)),patch.object(runtime,'clock',return_value=NOW),patch.object(runtime,'evaluate',wraps=runtime.evaluate) as evaluate:
                result=runtime.calculate(data)
            self.assertEqual([call.args[1] for call in evaluate.call_args_list],['revenue_sprint'])
            self.assertEqual(set(db.get('strategy_decisions',data['run_id'])),{'revenue_sprint'})
            receipt=result['decision_receipt']
            self.assertFalse(receipt['per_cycle_model_required'])
            self.assertEqual(receipt['hermes_role'],'daily_effect_review_and_strategy_suggestions')
            self.assertTrue(receipt['financial_proof']['pass_all'])

    def test_backend_preview_accepts_only_current_sources_and_still_rejects_missing_cost_or_market(self):
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db');evidence=fixture()[0]
            evidence['run_id']='00000000-0000-4000-8000-000000000099'
            for cost in evidence['costs'].values():cost['cny_per_1k']=str(runtime.number(cost['cny_per_1k']))
            evidence['storefront']['status']='ok'
            for platform,row in evidence['storefront']['rows'].items():row.update(status='ok',platform=platform,base_k='100',checked_at=NOW.isoformat())
            evidence['offers']={p:{'Lootbar':rows['Lootbar']} for p,rows in evidence['offers'].items()}
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',Path(folder)),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate(evidence)
            payload=dict(evidence=evidence,result=result)
            script="const fs=require('node:fs'),logic=require(process.argv[1]),data=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(logic.buildPreview(data.payload,Date.parse(data.now))));"
            def preview(value):
                return subprocess.run(['node','-e',script,str(SOURCE/'repricing_logic.js')],input=json.dumps(dict(payload=value,now=NOW.isoformat())),text=True,encoding='utf-8',capture_output=True,timeout=15)
            valid=preview(payload)
            self.assertEqual(valid.returncode,0,valid.stderr+valid.stdout)
            self.assertEqual([r['platform'] for r in json.loads(valid.stdout)['targets']],['PS','XBOX','PC'])
            for change in ('market','cost'):
                invalid=json.loads(json.dumps(payload))
                if change=='market':invalid['evidence']['offers']['PS']={}
                else:invalid['result']['rows'][0]['raw_cost_cny']='999'
                self.assertNotEqual(preview(invalid).returncode,0)

    def test_configurable_interval_does_not_resume_paused_plan_or_change_switches(self):
        from fc_pricing_v3 import api
        policy=automation_policy.initial_policy();policy.update(system_enabled=False,mode='manual')
        updated=dict(policy,interval_minutes=180,revision=1,updated_at=NOW.isoformat())
        fake=Mock();fake.active_plan.return_value=dict(state='SUSPENDED')
        with patch.object(automation_policy,'load_policy',return_value=policy),patch.object(automation_policy,'save_policy',return_value=updated) as save,patch.object(api,'ledger',return_value=fake):
            result=api.post('interval',dict(interval_minutes=180,expected_revision=0),'wulv')
        sent=save.call_args.args[0]
        self.assertFalse(sent['system_enabled']);self.assertEqual(sent['mode'],'manual')
        self.assertEqual(result['plan_state'],'SUSPENDED');self.assertFalse(result['write_performed'])
        plan=dict(plan_id='p',starts_at=NOW.isoformat(),last_cycle_at=NOW.isoformat(),resumed_at=(NOW+timedelta(hours=8)).isoformat())
        self.assertEqual(scheduler.next_cycle_at(fake,plan,updated),NOW+timedelta(hours=11))

    def test_daily_cutoff_and_actual_peak_come_from_paid_hours(self):
        before=datetime(2026,10,26,18,19,tzinfo=timezone.utc)
        self.assertIsNone(daily.due_date(before))
        self.assertEqual(daily.due_date(before+timedelta(minutes=1)),'2026-10-26')
        selected={'a':(dict(paidAt='2026-10-26T12:10:00+00:00',salesUsd='10'),{}),
            'b':(dict(paidAt='2026-10-26T13:10:00+00:00',salesUsd='20'),{})}
        result=daily.hourly_actual(selected,dict(status='complete'),'2026-10-26')
        self.assertEqual(result['high_demand_period']['start_hour'],18)
        self.assertEqual(result['high_demand_period']['net_paid_usd'],'30')
        gap=daily.hourly_actual(selected,dict(status='partial'),'2026-10-26')
        self.assertFalse(gap['missing_hours_are_zero']);self.assertIsNone(gap['low_demand_period'])

    def test_daily_grant_cannot_recommend_execute_or_switch_strategy(self):
        scope=Mock();scope.clock.return_value=NOW
        for action,args in [('recommend',dict(run_id='x',bundle_sha256='x',action_sha256='x',request_key='x',reason='x',evidence_refs=[])),('plan_propose',dict(request_key='x',mode='daily')),('plan_execute_authorized',dict(request_key='x',plan_id='x'))]:
            with patch.object(pricing_operations,'authorization',return_value=dict(mode='daily_review')):
                with self.assertRaises(PermissionError):pricing_operations.call(scope,'wulv','t','l',dict(action=action,**args),Mock())
        prompt=hermes_pricing_bridge.daily_review_text(dict(daily_report={'actual':{'status':'partial'}}))
        self.assertIn('每日一次',prompt)
        self.assertIn('不调用recommend',prompt);self.assertLess(len(prompt),12000)

    def test_daily_capabilities_use_saved_review_instead_of_wrong_run_compare(self):
        scope=Mock();scope.clock.return_value=NOW
        with patch.object(pricing_operations,'authorization',return_value=dict(mode='daily_review',runs=['daily-id'])):
            result=pricing_operations.call(scope,'wulv','t','l',dict(action='capabilities'),Mock())
        self.assertIn('state',result['allowed_actions'])
        self.assertNotIn('compare_strategies',result['allowed_actions'])

    def test_daily_failed_model_records_original_incident_and_exposes_prepared_context(self):
        from fc_pricing_v3 import history
        with tempfile.TemporaryDirectory() as folder:
            db=Ledger(Path(folder)/'control.db');date='2026-10-26'
            db.put('metadata','daily:'+date,dict(local_date=date,request_id='original',phase='created',actual={'status':'partial'},decision_basis={}))
            def model(*args,**kwargs):
                self.assertEqual(db.get('metadata','latest_daily_review')['phase'],'review_prepared')
                return dict(phase='failed')
            with patch.object(runtime,'ledger',return_value=db),patch.object(scheduler,'export_shadow_snapshot'),patch.object(history,'ensure_shadow',return_value=dict(status='completed',result={})),patch.object(hermes_pricing_bridge,'review',side_effect=model):
                result=daily.run(dict(local_date=date))
            self.assertEqual(result['phase'],'failed')
            self.assertEqual(db.all('incidents')[0]['error'],'original_request_id:original')

    def test_daily_effects_include_reviewed_day_cost_and_customer_rows(self):
        from fc_pricing_v3 import business_source, selective_sources
        current = {'today-order': [{'costCny':'20', 'customerType':'新客'}, {}]}
        historical = {'older-order': [{'costCny':'10'}, {}]}
        session = Mock()
        auth = SimpleNamespace(Session=Mock(return_value=session), admin_token_from_service=lambda:('token',None))
        channel = SimpleNamespace(pages=Mock(), COLLECTOR='unused-test-path')
        def online(session_arg, pages, windows, now, rows):
            self.assertEqual(rows['today-order'][0]['costCny'], '20')
            self.assertEqual(rows['today-order'][0]['customerType'], '新客')
            self.assertIn('older-order', rows)
            return {'actual_outcomes':[]}
        with patch.dict(sys.modules, {'p2pah_auth':auth, 'channel_source':channel}), patch.object(business_source, '_period_population', side_effect=[(current,{}),(historical,{})]), patch.object(business_source, 'online_window_context', side_effect=online), patch.object(daily, 'hourly_actual', return_value={}), patch.object(selective_sources, 'history_period', return_value={}):
            daily.collect_outcomes('2026-11-05', [])
        session.close.assert_called_once()

    def test_daily_context_does_not_attribute_pretrial_day_to_V3(self):
        window=dict(origin='confirmed_public_price_window',mode='production',opened_at='2026-10-26T14:36:00+00:00',operation_id='original',mutable_resources=['base:console'])
        result=daily.exposure_scope([window],'2026-10-26')
        self.assertEqual(result['first_exposure_at'],'2026-10-26T14:36:00+00:00')
        self.assertEqual(result['confirmed_operation_count'],1)
        self.assertEqual(daily.exposure_scope([window],'2026-10-25')['status'],'no_confirmed_exposure')

    def test_active_http_adapter_preserves_pricing_route(self):
        import importlib.util
        path = SOURCE.parents[2] / 'fs-dashboard/hermes-conversation-20261018/source/conversation_http.py'
        spec = importlib.util.spec_from_file_location('active_conversation_http', path)
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        headers = Message()
        for key, value in {'X-FS-Advisor-Action':'submit', 'Sec-Fetch-Site':'same-origin', 'Content-Length':'2', 'Content-Type':'application/json'}.items():
            headers[key] = value
        handler = SimpleNamespace(headers=headers, connection=Mock(), rfile=io.BytesIO(b'{}'), wfile=io.BytesIO(), send_response=Mock(), send_header=Mock(), end_headers=Mock())
        service = Mock()
        service.pricing.create.return_value = {'conversation_id':'a'*32}
        adapter.handle(handler, 'POST', urlsplit(adapter.PREFIX+'/pricing-reviews'), 'wulv', service, lambda _:True)
        handler.send_response.assert_called_once_with(201)
        service.pricing.create.assert_called_once_with('wulv')
        service.create.assert_not_called()

    def test_pricing_turn_route_validates_real_id_not_literal_turns(self):
        body=dict(text='daily',client_request_id='fc_pricing_daily',run_id='00000000-0000-4000-8000-000000000099')
        raw=json.dumps(body).encode();headers=Message()
        for k,v in {'X-FS-Advisor-Action':'submit','Sec-Fetch-Site':'same-origin','Content-Type':'application/json','Content-Length':str(len(raw))}.items():headers[k]=v
        handler=SimpleNamespace(headers=headers,rfile=io.BytesIO(raw),wfile=io.BytesIO(),connection=Mock(),send_response=Mock(),send_header=Mock(),end_headers=Mock())
        service=Mock();service.pricing.submit_pricing.return_value=dict(state='queued')
        conversation_http.handle(handler,'POST',urlsplit(conversation_http.PREFIX+'/pricing-reviews/'+'a'*32+'/turns'),'wulv',service,lambda _:True)
        handler.send_response.assert_called_once_with(202)
        service.pricing.submit_pricing.assert_called_once_with('wulv','a'*32,'daily','fc_pricing_daily',body['run_id'])

    def test_pricing_store_and_queue_do_not_block_ordinary_conversations(self):
        tree=ast.parse((SOURCE/'conversation_service.py').read_text(encoding='utf-8'))
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='ConversationService')
        class Store:
            def __init__(self,root):self.root=Path(root)
            def active(self):return []
        ns=dict(Path=Path,ConversationStore=Store,ThreadPoolExecutor=ThreadPoolExecutor,threading=threading)
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'conversation_service.py','exec'),ns)
        native=Mock(side_effect=lambda service:SimpleNamespace(service=service))
        # This AST fixture tests queue/store separation, not the native runtime.
        # Supply its constructor dependency just like the synthetic Store above.
        with patch.dict(sys.modules,{'conversation_native':SimpleNamespace(NativeConversation=native)}):
            service=ns['ConversationService'](Mock(),Path('fs/conversations'),Path('runtime'))
        self.assertEqual([call.args[0] for call in native.call_args_list],[service,service.pricing])
        self.assertIs(service.native.service,service)
        self.assertIs(service.pricing.native.service,service.pricing)
        gate=threading.Event()
        try:
            occupied=service.pricing.pool.submit(gate.wait,3)
            self.assertEqual(service.pool.submit(lambda:'ordinary').result(timeout=1),'ordinary')
            self.assertNotEqual(service.store.root,service.pricing.store.root)
            self.assertIsNot(service.pool,service.pricing.pool)
        finally:
            gate.set();service.pool.shutdown();service.pricing_pool.shutdown();service.pricing.pool.shutdown()

    def test_shadow_daily_worker_is_oneshot_and_keeps_network_and_writer_isolation(self):
        unit=(SOURCE/'systemd/fc-pricing-v3-shadow.service').read_text()
        for item in ('Type=oneshot','--once','Restart=no','PrivateNetwork=yes','User=nobody','ReadOnlyDirectories=/var/lib/fc27-cloud'):
            self.assertIn(item,unit)

    def test_pricing_only_uses_native_runtime_in_original_review_queue(self):
        tree=ast.parse((SOURCE/'conversation_service.py').read_text(encoding='utf-8'))
        cls=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=='ConversationService')
        class Store:
            def __init__(self,root):self.root=Path(root)
            def active(self):return []
        ns=dict(Path=Path,ConversationStore=Store,ThreadPoolExecutor=ThreadPoolExecutor,threading=threading)
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'conversation_service.py','exec'),ns)
        native=Mock()
        with patch.dict(sys.modules,{'conversation_native':SimpleNamespace(NativeConversation=native)}):
            service=ns['ConversationService'](Mock(),Path('fs/pricing-reviews'),Path('runtime'),pricing_only=True)
        try:
            native.assert_called_once_with(service)
            self.assertIs(service.native,native.return_value)
            self.assertIsNone(service.pricing)
            self.assertIs(service.pool,service.pricing_pool)
        finally:
            service.pool.shutdown()

    def test_daily_shadow_restarts_once_and_leaves_next_day_snapshot_for_next_run(self):
        from test_shadow_worker import evidence,evaluate
        from fc_pricing_v3 import simulation
        at=datetime(2020,1,1,12,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);production=root/'production.db';shadow=root/'shadow.db'
            with closing(sqlite3.connect(production)) as conn,conn:
                conn.executescript('CREATE TABLE event_outbox(id INTEGER PRIMARY KEY,kind TEXT,body TEXT);CREATE TABLE pricing_snapshots(id TEXT PRIMARY KEY,body TEXT);')
                for index,stamp in enumerate((at,at+timedelta(days=1)),1):
                    ident=str(index)
                    conn.execute('INSERT INTO pricing_snapshots VALUES (?,?)',(ident,json.dumps(dict(snapshot_id=ident,created_at=stamp.isoformat(),evidence=evidence(stamp)))))
                    conn.execute('INSERT INTO event_outbox VALUES (?,?,?)',(index,'snapshot_ready',json.dumps(dict(snapshot_id=ident))))
            with patch.object(simulation,'evaluate',side_effect=evaluate):
                first=shadow_worker.run_daily(production,shadow,'2020-01-01')
                repeated=shadow_worker.run_daily(production,shadow,'2020-01-01')
            self.assertEqual(first,repeated);self.assertEqual(first['cursor'],1)
            self.assertFalse(first['production_write_performed']);self.assertFalse(first['external_collection_performed'])
            self.assertEqual(len(first['periods']),4)
            self.assertEqual(set(first['periods'][0]['results']),set(('daily','revenue_sprint')))
            with closing(sqlite3.connect(production)) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM event_outbox').fetchone()[0],2)

    def test_page_interaction_contract(self):
        subprocess.run(['node',str(Path(__file__).with_name('test_ui_contract.cjs'))],check=True,capture_output=True,timeout=20)

    def test_paused_plan_keeps_last_real_source_timestamp_without_new_collection(self):
        from fc_pricing_v3 import monitoring
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'v3/control.sqlite3')
            plan=dict(plan_id='p',state='SUSPENDED',mode='daily',resources=['base:pc'],starts_at=NOW.isoformat())
            db.put('pricing_plans','p',plan)
            db.put('metadata','latest_snapshot:p',dict(snapshot_id='snapshot'))
            db.put('pricing_snapshots','snapshot',dict(snapshot_id='snapshot',created_at=NOW.isoformat(),evidence=dict(checked_at=NOW.isoformat())))
            (root/'config').mkdir();(root/'config/v3-control.json').write_text('{"enabled":true}')
            (root/'v3/heartbeat.json').write_text(json.dumps(dict(checked_at=NOW.isoformat())))
            state=monitoring.projection(root,NOW)
            self.assertEqual(state['schedule']['last_source_checked_at'],NOW.isoformat())
            self.assertIsNone(state['schedule']['next_cycle_at'])
            self.assertEqual(state['source_coverage']['status'],'not_required_without_active_plan')


class SavedDailyComparison(unittest.TestCase):
    def producer(self, folder, *, missing=False):
        import importlib.util
        releases=Path(__file__).resolve().parents[3]
        sys.path.insert(0,str(releases/'fs-dashboard/hermes-conversation-20261018/source'))
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,path)
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            return module
        pilot=load('saved_daily_pilot',releases/'fs-dashboard/hermes-fc-pilot-20261013/pilot.py')
        store_module=load('saved_daily_store',releases/'fs-dashboard/hermes-conversation-20261018/source/conversation_store.py')
        from fc_pricing_v3 import api,history
        root=Path(folder);(root/'evidence').mkdir()
        db=Ledger(root/'control.db');tasks=pilot.TaskStore(root/'tasks.sqlite3')
        store=store_module.ConversationStore(root/'pricing-reviews')
        source='00000000-0000-4000-8000-000000000002'
        snapshot=dict(snapshot_id=source,origin='live_collector',policy_version='fc-pricing-v3-20261026',evidence={'original':'evidence'},result={})
        db.put('pricing_snapshots',source,snapshot)
        if not missing:db.put('strategy_decisions',source,dict(daily=dict(status='READY',candidates=[])))
        day='2026-11-04'
        db.put('metadata','daily:'+day,dict(local_date=day,request_id='00000000-0000-4000-8000-000000000001',phase='created',actual={'status':'partial'}))
        made={};native_calls=[]
        def native(path,owner,body=None):
            native_calls.append((path,owner,body))
            self.assertIsNone(body,'Saved daily comparison must never POST')
            with patch.object(api,'ledger',return_value=db):return api.read(path.removeprefix('/pricing/v3/'))
        def http(owner,path,body=None,timeout=30):
            if path=='/api/hermes/conversations/pricing-reviews':
                made.update(store.create(owner));return made
            self.assertTrue(path.endswith('/turns'))
            turn=store.reserve_turn(owner,made['conversation_id'],body['text'],body['client_request_id'],native=True)
            store.bind_task(owner,made['conversation_id'],turn['turn_id'],turn['turn_id'],'a'*32)
            made.update(turn);return turn
        def save(path,value):path.write_text(json.dumps(value),encoding='utf-8')
        with patch.object(runtime,'ledger',return_value=db),patch.object(scheduler,'export_shadow_snapshot'), \
             patch.object(history,'ensure_shadow',return_value=dict(status='completed',result={})), \
             patch.object(hermes_pricing_bridge,'ROOT',root),patch.object(hermes_pricing_bridge,'FS',root), \
             patch.object(hermes_pricing_bridge,'request',side_effect=http),patch.object(hermes_pricing_bridge,'save',side_effect=save), \
             patch.object(hermes_pricing_bridge.os,'chown',create=True),patch.object(pricing_operations,'native',side_effect=native):
            try:record=daily.run(dict(local_date=day))
            except ValueError as error:
                if str(error)!='pricing_daily_hermes_pending':raise
                record=db.get('metadata','daily:'+day)
        def context(owner,task,lease):
            if owner!='wulv' or task!=made['turn_id'] or lease!='a'*32:raise PermissionError('test_owned_lease')
        scope=SimpleNamespace(tasks=tasks,clock=lambda:datetime.now(timezone.utc),context=context)
        return SimpleNamespace(record=record,store=store,db=db,scope=scope,made=made,source=source,snapshot=snapshot,native=native,calls=native_calls,root=root)

    def test_saved_daily_real_producer_binds_snapshot_hash_and_gets_original_comparison(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder)
            basis=p.record['decision_basis']
            self.assertEqual(basis.get('snapshot_sha256'),runtime.fingerprint(p.snapshot['evidence']))
            auth=pricing_operations.authorization(p.scope,'wulv',p.made['turn_id'],p.scope.clock())
            self.assertEqual(auth['runs'],[p.record['request_id']])
            self.assertEqual(auth.get('source_quote_run'),p.source)
            self.assertEqual(auth.get('source_quote_sha256'),basis['snapshot_sha256'])
            self.assertEqual(p.record['hermes'].get('source_quote_run'),p.source)
            result=pricing_operations.call(p.scope,'wulv',p.made['turn_id'],'a'*32,dict(action='compare_strategies',mode='daily'),request=p.native)
            self.assertEqual(result['snapshot_id'],p.source)
            self.assertEqual(result['snapshot_sha256'],basis['snapshot_sha256'])
            self.assertFalse(result['execution_authorized'])
            self.assertTrue(all(call[0]=='/pricing/v3/strategy-decisions/'+p.source and call[2] is None for call in p.calls))

    def test_saved_daily_missing_decision_still_submits_review_without_compare(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder,missing=True)
            self.assertEqual(p.record['hermes']['phase'],'submitted')
            self.assertIn('compare_basis_gap',p.record['hermes'])
            caps=pricing_operations.call(p.scope,'wulv',p.made['turn_id'],'a'*32,dict(action='capabilities'),request=p.native)
            self.assertNotIn('compare_strategies',caps['allowed_actions'])
            with self.assertRaisesRegex(ValueError,'pricing_daily_compare_basis_unavailable'):
                pricing_operations.call(p.scope,'wulv',p.made['turn_id'],'a'*32,dict(action='compare_strategies',mode='daily'),request=p.native)

    def test_saved_daily_rejects_changed_hash_missing_mode_and_expired_or_wrong_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder)
            p.db.put('pricing_snapshots',p.source,dict(p.snapshot,evidence={'changed':True}))
            try:
                with self.assertRaisesRegex(ValueError,'pricing_review_run_basis_changed'):
                    pricing_operations.call(p.scope,'wulv',p.made['turn_id'],'a'*32,dict(action='compare_strategies',mode='daily'),request=p.native)
            except PermissionError as error:self.fail('Saved basis is not connected: '+str(error))
            p.db.put('pricing_snapshots',p.source,p.snapshot)
            with self.assertRaisesRegex(ValueError,'pricing_review_run_basis_changed'):
                pricing_operations.call(p.scope,'wulv',p.made['turn_id'],'a'*32,dict(action='compare_strategies',mode='revenue_sprint'),request=p.native)
            with self.assertRaises(PermissionError):
                pricing_operations.call(p.scope,'other',p.made['turn_id'],'a'*32,dict(action='compare_strategies',mode='daily'),request=p.native)
            with p.scope.tasks.db() as conn:conn.execute("UPDATE pricing_grants SET expires_at='2000-01-01T00:00:00+00:00'")
            with self.assertRaises(PermissionError):
                pricing_operations.call(p.scope,'wulv',p.made['turn_id'],'a'*32,dict(action='compare_strategies',mode='daily'),request=p.native)
            self.assertTrue(all(call[2] is None for call in p.calls))

    def test_saved_daily_old_grant_columns_migrate_without_upgrading_scope(self):
        with closing(sqlite3.connect(':memory:')) as conn,conn:
            conn.execute('CREATE TABLE pricing_grants(conversation TEXT PRIMARY KEY,owner TEXT NOT NULL,mode TEXT NOT NULL,runs TEXT NOT NULL,expires_at TEXT NOT NULL,source TEXT NOT NULL,restore_sources TEXT NOT NULL)')
            old=('a'*32,'wulv','daily_review','["daily"]','2099-01-01T00:00:00+00:00','old-source','[]')
            conn.execute('INSERT INTO pricing_grants VALUES(?,?,?,?,?,?,?)',old)
            pricing_operations.tables(conn)
            row=conn.execute('SELECT * FROM pricing_grants').fetchone()
            self.assertEqual(row,old);self.assertEqual(pricing_operations.quote_reference(conn,'a'*32),(None,None))

    def test_saved_daily_bound_intent_rejects_changed_producer_basis_without_resubmit(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder)
            report={k:p.record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis','price_exposure')}
            report['decision_basis']=dict(report['decision_basis'],snapshot_id='00000000-0000-4000-8000-000000000003')
            with patch.object(hermes_pricing_bridge,'ROOT',p.root),patch.object(hermes_pricing_bridge,'FS',p.root), \
                 patch.object(pricing_operations,'native',side_effect=p.native),patch.object(hermes_pricing_bridge,'request') as submit, \
                 patch.object(hermes_pricing_bridge,'save',side_effect=lambda path,value:path.write_text(json.dumps(value),encoding='utf-8')):
                with self.assertRaisesRegex(ValueError,'pricing_hermes_intent_conflict'):
                    hermes_pricing_bridge.review(dict(job_id=p.record['request_id']),dict(run_id=p.record['request_id'],daily_report=report),mode='daily_review',wait_seconds=0)
            submit.assert_not_called()

    def test_saved_daily_bridge_does_not_hide_unexpected_api_errors(self):
        quote=dict(daily_report=dict(decision_basis=dict(snapshot_id='00000000-0000-4000-8000-000000000002',snapshot_sha256='a'*64)))
        with patch.object(pricing_operations,'native',side_effect=ValueError('unexpected_parser_failure')):
            with self.assertRaisesRegex(ValueError,'unexpected_parser_failure'):
                hermes_pricing_bridge.source_quote_basis(quote,'wulv')

    def test_saved_daily_original_unbound_intent_is_not_upgraded_on_reconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder)
            path=p.root/'evidence'/('hermes-pricing-'+p.record['request_id']+'.json')
            old=json.loads(path.read_text('utf-8'))
            old.pop('source_quote_run');old.pop('source_quote_sha256')
            path.write_text(json.dumps(old),encoding='utf-8')
            with p.scope.tasks.db() as conn:conn.execute('UPDATE pricing_grant_sources SET source_quote_run=NULL,source_quote_sha256=NULL')
            report={k:p.record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis','price_exposure')}
            with patch.object(hermes_pricing_bridge,'ROOT',p.root),patch.object(hermes_pricing_bridge,'FS',p.root), \
                 patch.object(pricing_operations,'native') as reads,patch.object(hermes_pricing_bridge,'request') as submit, \
                 patch.object(hermes_pricing_bridge,'save',side_effect=lambda path,value:path.write_text(json.dumps(value),encoding='utf-8')):
                result=hermes_pricing_bridge.review(dict(job_id=p.record['request_id']),dict(run_id=p.record['request_id'],daily_report=report),mode='daily_review',wait_seconds=0)
            reads.assert_not_called();submit.assert_not_called()
            self.assertNotIn('source_quote_run',result)
            auth=pricing_operations.authorization(p.scope,'wulv',p.made['turn_id'],p.scope.clock())
            self.assertIsNone(auth['source_quote_run']);self.assertIsNone(auth['source_quote_sha256'])

    def test_saved_daily_existing_automatic_and_operator_compare_contracts_remain(self):
        scope=Mock();scope.clock.return_value=NOW
        response=dict(snapshot_id='original',results=dict(daily={'status':'READY'}))
        request=Mock(return_value=response)
        with patch.object(pricing_operations,'authorization',return_value=dict(mode='automatic_review',runs=['original'])):
            result=pricing_operations.call(scope,'wulv','task','lease',dict(action='compare_strategies',mode='daily'),request=request)
        self.assertEqual(result['snapshot_id'],'original')
        request.assert_called_once_with('/pricing/v3/strategy-decisions/original','wulv')
        request.reset_mock()
        with patch.object(pricing_operations,'authorization',return_value=dict(mode='operator_workflow',runs=[])):
            self.assertEqual(pricing_operations.call(scope,'wulv','task','lease',dict(action='compare_strategies',mode='daily'),request=request),response)
        request.assert_called_once_with('/pricing/v3/evaluate','wulv',dict(mode='daily'))


    def test_saved_daily_terminal_receipt_needs_no_new_api_or_submission(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder)
            path=p.root/'evidence'/('hermes-pricing-'+p.record['request_id']+'.json')
            original=json.loads(path.read_text('utf-8'))
            report={k:p.record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis','price_exposure')}
            for phase in ('completed','failed','timeout','unknown'):
                with self.subTest(phase=phase):
                    receipt=dict(original,phase=phase)
                    path.write_text(json.dumps(receipt),encoding='utf-8')
                    with patch.object(hermes_pricing_bridge,'ROOT',p.root), \
                         patch.object(pricing_operations,'native',side_effect=AssertionError('terminal_receipt_must_not_requery')) as reads, \
                         patch.object(hermes_pricing_bridge,'request') as submits:
                        result=hermes_pricing_bridge.review(dict(job_id=p.record['request_id']),
                            dict(run_id=p.record['request_id'],daily_report=report),mode='daily_review',wait_seconds=0)
                    self.assertEqual(result,receipt)
                    reads.assert_not_called();submits.assert_not_called()


    def test_saved_daily_submitted_turn_reconciles_when_comparison_api_is_unavailable(self):
        with tempfile.TemporaryDirectory() as folder:
            p=self.producer(folder)
            p.store.set_state('wulv',p.made['conversation_id'],p.made['turn_id'],'completed')
            report={k:p.record.get(k) for k in ('local_date','actual','learning_coverage','shadow','decision_basis','price_exposure')}
            with patch.object(hermes_pricing_bridge,'ROOT',p.root),patch.object(hermes_pricing_bridge,'FS',p.root), \
                 patch.object(pricing_operations,'native',side_effect=OSError('comparison_temporarily_unavailable')) as comparisons, \
                 patch.object(hermes_pricing_bridge,'turn_state',wraps=hermes_pricing_bridge.turn_state) as reads, \
                 patch.object(hermes_pricing_bridge,'request',return_value={'state':'completed'}) as request, \
                 patch.object(hermes_pricing_bridge,'save',side_effect=lambda path,value:path.write_text(json.dumps(value),encoding='utf-8')):
                try:
                    result=hermes_pricing_bridge.review(dict(job_id=p.record['request_id']),
                        dict(run_id=p.record['request_id'],daily_report=report),mode='daily_review',wait_seconds=0)
                except ValueError as error:
                    self.fail('Original turn reconciliation blocked: '+str(error))
            self.assertEqual(result['phase'],'completed')
            self.assertEqual(result['turn']['id'],p.made['turn_id'])
            reads.assert_called_once()
            comparisons.assert_not_called()
            request.assert_called_once_with('wulv','/api/hermes/conversations/pricing-reviews/'+p.made['conversation_id'])

    def test_source_reference_table_initializes_concurrently_without_changing_old_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.db'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE pricing_grants(conversation TEXT PRIMARY KEY,owner TEXT NOT NULL,mode TEXT NOT NULL,runs TEXT NOT NULL,expires_at TEXT NOT NULL,source TEXT NOT NULL,restore_sources TEXT NOT NULL)')
            barrier=threading.Barrier(2)
            def initialize():
                with closing(sqlite3.connect(path,timeout=5)) as connection:
                    barrier.wait(timeout=5)
                    pricing_operations.tables(connection)
            with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:initialize(),range(2)))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(len(list(db.execute('PRAGMA table_info(pricing_grants)'))),7)
                columns={r[1]:r[2] for r in db.execute('PRAGMA table_info(pricing_grant_sources)')}
            self.assertEqual(columns['source_quote_run'],'TEXT')
            self.assertEqual(columns['source_quote_sha256'],'TEXT')

    def test_source_reference_storage_keeps_other_database_errors_visible(self):
        with closing(sqlite3.connect(':memory:')) as connection:
            class FailedSourceTable:
                def execute(self,sql,*args):
                    if sql.startswith('CREATE TABLE IF NOT EXISTS pricing_grant_sources'):
                        raise sqlite3.OperationalError('database is locked')
                    return connection.execute(sql,*args)
            with self.assertRaisesRegex(sqlite3.OperationalError,'database is locked'):
                pricing_operations.tables(FailedSourceTable())


class DailyReviewBoundary(unittest.TestCase):
    def quote(self):
        # Equal six-hour totals hide the different hourly demand peaks.
        hourly = [dict(hour=h, orders=6 if h in (2, 9, 13, 23) else 0,
                       net_paid_usd='60' if h in (2, 9, 13, 23) else '0')
                  for h in range(24)]
        return dict(daily_report=dict(
            local_date='2026-11-04',
            actual=dict(status='complete', hourly=hourly,
                        periods=[dict(start_hour=h, end_hour=h+6, orders=6, net_paid_usd='60')
                                 for h in range(0, 24, 6)],
                        missing_hours_are_zero=True),
            decision_basis=dict(mode='smart'),
            learning_coverage=dict(status='partial'),
            price_exposure=dict(attribution='bound_orders_only'),
            shadow=dict(status='estimate')))

    def test_review_retains_original_hourly_and_coverage_evidence(self):
        quote = self.quote()
        before = json.loads(json.dumps(quote))
        prompt = hermes_pricing_bridge.daily_review_text(quote)
        report = json.loads(prompt.split('实际及影子摘要：', 1)[1])
        self.assertEqual(report, before['daily_report'])
        self.assertEqual(quote, before)

    def test_review_leaves_analysis_window_and_structure_to_model(self):
        prompt = hermes_pricing_bridge.daily_review_text(self.quote())
        self.assertNotIn('按附带真实六小时时段订单与收入分布比较低估期和高峰期', prompt)
        self.assertNotIn('输出一次简明中文复盘：效果判断、分时段比较、基数与假设、建议及次日观察', prompt)

    def test_review_keeps_readonly_and_effect_evidence_boundaries(self):
        prompt = hermes_pricing_bridge.daily_review_text(self.quote())
        for boundary in ('本任务只读', '不调用recommend', '不创建/执行/切换计划',
                         '曝光开始前的成交不能归给V3', '双20%', '不能豁免',
                         '模拟收益不能叫真实增收'):
            self.assertIn(boundary, prompt)

    def test_review_keeps_existing_prompt_size_limit(self):
        quote = self.quote()
        quote['daily_report']['large'] = 'x' * 12000
        with self.assertRaisesRegex(ValueError, '^pricing_daily_prompt_too_long$'):
            hermes_pricing_bridge.daily_review_text(quote)

if __name__=='__main__':unittest.main()
