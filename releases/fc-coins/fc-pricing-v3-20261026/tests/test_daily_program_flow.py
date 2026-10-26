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

    def test_daily_context_does_not_attribute_pretrial_day_to_V3(self):
        window=dict(origin='confirmed_public_price_window',mode='production',opened_at='2026-10-26T14:36:00+00:00',operation_id='original',mutable_resources=['base:console'])
        result=daily.exposure_scope([window],'2026-10-26')
        self.assertEqual(result['first_exposure_at'],'2026-10-26T14:36:00+00:00')
        self.assertEqual(result['confirmed_operation_count'],1)
        self.assertEqual(daily.exposure_scope([window],'2026-10-25')['status'],'no_confirmed_exposure')

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
        service=ns['ConversationService'](Mock(),Path('fs/conversations'),Path('runtime'))
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
            self.assertEqual(set(first['periods'][0]['results']),set(('daily','acquisition','backlog','flash_sale','revenue_sprint')))
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


if __name__=='__main__':unittest.main()
