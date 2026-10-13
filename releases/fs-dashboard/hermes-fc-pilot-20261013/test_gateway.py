"""No real identity, network, provider, ledger migration or runtime used."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from proxy_gateway import ModelGateway, ScopedTools, UnifiedBudget, schemas, request_body
from pilot import TaskStore
from runtime_contract import candidate, validate, clean_environment
from runs_contract import WIRE_TOOLS
from test_pilot import spec, book


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.tasks = TaskStore(self.root/'tasks.db')
        self.task = self.tasks.create('owner', spec())
        self.tasks.reserve_dispatch(self.task['id'], 'owner', 'lease')
        self.tasks.bind_run(self.task['id'], 'owner', 'lease', 'run_fixture')
        self.now = datetime(2026,10,13,15,tzinfo=timezone.utc)
        self.scope = ScopedTools(self.tasks,book(),lambda:self.now,self.now+timedelta(seconds=600))
        self.policy = {'id':'fixture-only','model':'fake-deepseek','price_version':'fake-v1',
                       'input_microcny':2,'output_microcny':4}
        with self.db() as db:
            db.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT NOT NULL,state TEXT NOT NULL,content TEXT)')
        self.budget = UnifiedBudget(self.db,self.policy,lambda:self.now)
        self.lock = threading.Lock()
        self.calls = 0
        self.provider = self.answer
        self.gateway = ModelGateway(self.scope,self.budget,self.slot,
                                    lambda req:self.provider(req),lambda req:100,lambda:0)

    def tearDown(self):
        self.tmp.cleanup()

    @contextmanager
    def db(self):
        conn=sqlite3.connect(self.root/'daily.sqlite3',timeout=5)
        conn.row_factory=sqlite3.Row
        try:
            with conn: yield conn
        finally: conn.close()

    @contextmanager
    def slot(self):
        with self.lock: yield True

    def answer(self, request):
        self.calls+=1
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM model_calls WHERE state='started'").fetchone()[0],1)
        return {'id':'fake_receipt_'+str(self.calls), 'usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60},
                'choices':[{'message':{'role':'assistant','content':'核对平台变化。'}}]}

    def call(self, turn=0, **overrides):
        args={'owner':'owner','task_id':self.task['id'],'lease':'lease','turn':turn,
              'body':{'messages':[{'role':'user','content':'分析聚合证据。'}],'max_tokens':50}}
        args.update(overrides)
        return self.gateway.call(**args)

    def test_same_ledger_reserve_before_provider_and_settle_actual_cost(self):
        result=self.call()
        self.assertEqual(result['cost_microcny'],140)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT state FROM model_calls').fetchone()[0],'succeeded')
            self.assertEqual([x[1] for x in db.execute('PRAGMA table_info(model_calls)')],['fingerprint','day','state','content'])

    def test_replay_has_no_second_provider_call(self):
        result=self.call()
        self.gateway.daily_limit=lambda:1
        self.assertEqual(self.call(),result)
        self.assertEqual(self.calls,1)

    def test_concurrent_same_turn_charges_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.call(),range(8)))
        self.assertTrue(all(x==results[0] for x in results)); self.assertEqual(self.calls,1)

    def test_changed_same_turn_rejected(self):
        self.call()
        with self.assertRaisesRegex(ValueError,'turn_conflict'):
            self.call(body={'messages':[{'role':'user','content':'changed'}],'max_tokens':50})
        self.assertEqual(self.calls,1)

    def test_user_rejected_pilot_quotas_are_not_enforced(self):
        self.scope.deadline = None
        self.now += timedelta(seconds=3600)
        for turn in range(20):
            result = self.call(turn)
            self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.calls, 20)

    def test_pilot_quota_fields_cannot_be_reintroduced(self):
        policy = dict(self.policy, task_microcny=1)
        with self.assertRaisesRegex(ValueError, 'policy_fields'):
            UnifiedBudget(self.db, policy, lambda:self.now)

    def test_unknown_provider_persists_across_adapter_restart(self):
        def fail(req): self.calls+=1; raise TimeoutError('untrusted details')
        self.provider=fail
        with self.assertRaisesRegex(ValueError,'provider_outcome_unknown'): self.call()
        self.gateway.budget=UnifiedBudget(self.db,self.policy,lambda:self.now)
        with self.assertRaisesRegex(ValueError,'unknown_previous_attempt'): self.call()
        with self.assertRaisesRegex(ValueError,'pilot_usage_hold'): self.call(1)
        self.assertEqual(self.calls,1)

    def test_missing_usage_holds_and_does_not_zero_bill(self):
        self.provider=lambda req:{'id':'fake','choices':[]}
        with self.assertRaisesRegex(ValueError,'unverified_provider_result'): self.call()
        with self.db() as db:
            row=db.execute('SELECT state,content FROM model_calls').fetchone()
            import json
            self.assertEqual(row['state'],'unknown');self.assertEqual(json.loads(row['content'])['status'],'unknown')
            self.assertNotIn('provider_usage',json.loads(row['content']))
        with self.assertRaisesRegex(ValueError,'pilot_usage_hold'): self.call(1)

    def test_provider_usage_extensions_and_empty_reasoning_are_supported(self):
        def extended(req):
            result=self.answer(req)
            result['usage']['prompt_tokens_details']={'cached_tokens':0}
            result['choices'][0]['message']['reasoning_content']=None
            return result
        self.provider=extended
        result=self.call()
        self.assertEqual(result['usage']['total_tokens'],60)
        self.assertNotIn('reasoning_content',result['message'])
        self.assertIn('not_account_invoice',result['cost_basis'])

    def test_excess_usage_holds(self):
        def over(req):
            result=self.answer(req); result['usage']={'prompt_tokens':101,'completion_tokens':10,'total_tokens':111}; return result
        self.provider=over
        with self.assertRaisesRegex(ValueError,'unverified_provider_result'): self.call()

    def test_invalid_response_retains_safe_usage_and_shape_without_private_content(self):
        def malformed(req):
            value=self.answer(req);value['model']=req['model']
            value['choices'][0]['message']['private_field']='password=secret; sk-SECRET'
            value['choices'][0]['message']['reasoning_content']='private reasoning must never reach diagnostics'
            return value
        self.provider=malformed
        with self.assertRaisesRegex(ValueError,'unverified_provider_result'):self.call()
        import json
        with self.db() as db:receipt=json.loads(db.execute('SELECT content FROM model_calls').fetchone()[0])
        self.assertEqual(receipt['reason'],'response_message_invalid')
        self.assertEqual(receipt['provider_usage']['total_tokens'],60)
        self.assertEqual(receipt['response_shape']['unknown_message_field_count'],1)
        self.assertNotIn('private reasoning',json.dumps(receipt));self.assertNotIn('sk-SECRET',json.dumps(receipt))
        self.assertEqual(receipt['status'],'invalid_response')
        self.assertEqual(receipt['usage']['total_tokens'],60);self.assertEqual(receipt['cost_microcny'],140)
        with self.assertRaisesRegex(ValueError,'unknown_previous_attempt'):self.call()
        with self.assertRaisesRegex(ValueError,'invalid_previous_result'):self.call(1)
        self.provider=self.answer
        newer=spec();newer['template_version']='after-invalid-response'
        task=self.tasks.create('owner',newer);self.tasks.reserve_dispatch(task['id'],'owner','newlease');self.tasks.bind_run(task['id'],'owner','newlease','run_after_invalid')
        gateway=ModelGateway(ScopedTools(self.tasks,book(),lambda:self.now),self.budget,self.slot,self.answer,lambda _:100,lambda:0)
        self.assertEqual(gateway.call('owner',task['id'],'newlease',0,{'messages':[{'role':'user','content':'new task'}],'max_tokens':50})['status'],'succeeded')

    def test_explicit_unknown_acceptance_only_allows_new_task_same_owner_exact_bound(self):
        def fail(req):raise TimeoutError('secret error body')
        self.provider=fail
        with self.assertRaisesRegex(ValueError,'provider_outcome_unknown'):self.call()
        with self.db() as db:row=db.execute('SELECT fingerprint,microcny FROM hermes_reservations').fetchone()
        newer=spec();newer['template_version']='new-approved-diagnostic'
        task=self.tasks.create('owner',newer);self.tasks.reserve_dispatch(task['id'],'owner','newlease');self.tasks.bind_run(task['id'],'owner','newlease','run_new')
        scope=ScopedTools(self.tasks,book(),lambda:self.now)
        budget=UnifiedBudget(self.db,self.policy,lambda:self.now,accepted_unknowns={row['fingerprint']:row['microcny']})
        gateway=ModelGateway(scope,budget,self.slot,self.answer,lambda _:100,lambda:0)
        result=gateway.call('owner',task['id'],'newlease',0,{'messages':[{'role':'user','content':'new task'}],'max_tokens':50})
        self.assertEqual(result['status'],'succeeded')
        self.gateway.budget=budget
        with self.assertRaisesRegex(ValueError,'unknown_previous_attempt'):self.call()
        with self.assertRaisesRegex(ValueError,'pilot_usage_hold'):self.call(1)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT state FROM model_calls WHERE fingerprint=?',(row['fingerprint'],)).fetchone()[0],'unknown')
        with self.assertRaisesRegex(ValueError,'pilot_usage_hold'):
            budget.reserve('other','other_task',0,request_body({'messages':[{'role':'user','content':'new'}],'max_tokens':50},self.policy['model']),100)
        wrong=UnifiedBudget(self.db,self.policy,lambda:self.now,accepted_unknowns={row['fingerprint']:row['microcny']+1})
        with self.assertRaisesRegex(ValueError,'pilot_usage_hold'):
            wrong.reserve('owner','third_task',0,request_body({'messages':[{'role':'user','content':'new'}],'max_tokens':50},self.policy['model']),100)

    def test_foreign_owner_cancel_and_deadline_refuse(self):
        with self.assertRaises(PermissionError): self.call(owner='other')
        self.now+=timedelta(seconds=601)
        with self.assertRaisesRegex(PermissionError,'inactive_task'): self.call()
        self.now-=timedelta(seconds=601)
        self.tasks.cancel(self.task['id'],'owner')
        with self.assertRaisesRegex(PermissionError,'inactive_task'): self.call()
        self.assertEqual(self.calls,0)

    def test_cancel_during_provider_accounts_but_withholds_result(self):
        def cancel(req):
            result=self.answer(req); self.tasks.cancel(self.task['id'],'owner'); return result
        self.provider=cancel
        with self.assertRaisesRegex(PermissionError,'inactive_task'): self.call()
        with self.db() as db: self.assertEqual(db.execute('SELECT state FROM model_calls').fetchone()[0],'succeeded')

    def test_original_global_limit_and_busy_lock_preserved(self):
        self.gateway.daily_limit=lambda:1
        with self.db() as db: db.execute("INSERT INTO model_calls VALUES('old','2026-10-13','succeeded','{}')")
        with self.assertRaisesRegex(ValueError,'daily_model_limit'): self.call()
        @contextmanager
        def busy(): yield False
        self.gateway.slot=busy
        with self.assertRaisesRegex(ValueError,'model_busy'): self.call()
        self.assertEqual(self.calls,0)

    def test_price_policy_cannot_change_mid_task(self):
        self.call(); self.budget.policy['price_version']='fake-v2'
        with self.assertRaisesRegex(ValueError,'task_policy_changed'): self.call(1)

    def test_body_cannot_override_provider_or_tools(self):
        for extra in ('model','tools','stream','api_key','base_url'):
            body={'messages':[{'role':'user','content':'x'}],'max_tokens':50,extra:'bad'}
            with self.assertRaisesRegex(ValueError,'request_fields'): self.call(body=body)
        self.assertEqual(self.calls,0)

    def test_five_tools_and_scope_enforced(self):
        self.assertEqual([x['function']['name'] for x in schemas()],list(WIRE_TOOLS))
        result=self.scope.call('owner',self.task['id'],'lease',WIRE_TOOLS[1],{'snapshot_id':spec()['snapshot_id'],'window':'target'})
        self.assertEqual(result['data']['orders'],12)
        for name,args in [('shell',{}),(WIRE_TOOLS[1],{'snapshot_id':'other','window':'target'})]:
            with self.assertRaises((PermissionError,ValueError)):
                self.scope.call('owner',self.task['id'],'lease',name,args)

    def test_tool_roundtrip_and_orphan_rejection(self):
        call={'id':'call1','type':'function','function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}
        messages=[{'role':'user','content':'x'},{'role':'assistant','content':None,'tool_calls':[call]},
                  {'role':'tool','tool_call_id':'call1','content':'{}'}]
        self.assertEqual(request_body({'messages':messages,'max_tokens':50},'fixed')['model'],'fixed')
        with self.assertRaisesRegex(ValueError,'tool_result_missing'):
            request_body({'messages':messages[:-1],'max_tokens':50},'fixed')

    def test_unapproved_model_tool_output_holds(self):
        def bad(req):
            result=self.answer(req)
            result['choices'][0]['message']['tool_calls']=[{'id':'a','type':'function','function':{'name':'shell','arguments':'{}'}}]
            return result
        self.provider=bad
        with self.assertRaisesRegex(ValueError,'unverified_provider_result'): self.call()

    def test_runtime_proposal_inert_and_environment_has_no_inherited_secrets(self):
        self.assertFalse(validate(candidate())['launch_allowed'])
        plan=candidate(); plan['network']['public_listeners']=['0.0.0.0:8080']
        with self.assertRaises(ValueError): validate(plan)
        self.assertEqual(set(clean_environment()),{'PATH','HOME','LANG','PYTHONDONTWRITEBYTECODE','PYTHONNOUSERSITE'})

    def test_existing_schema_required_no_alternative_usage_db(self):
        with self.db() as db: db.execute('ALTER TABLE model_calls ADD COLUMN unexpected TEXT')
        with self.assertRaisesRegex(ValueError,'existing_ledger_required'):
            UnifiedBudget(self.db,self.policy,lambda:self.now)

    def test_adaptive_tool_roundtrip_uses_scoped_evidence_and_two_receipts(self):
        call={'id':'call1','type':'function','function':{'name':WIRE_TOOLS[4],
              'arguments':'{"snapshot_id":"synthetic-capture-v1","window":"target","dimension":"platform"}'}}
        def choose(req):
            result=self.answer(req)
            if self.calls==1:
                result['choices'][0]['message']={'role':'assistant','content':None,'tool_calls':[call]}
            return result
        self.provider=choose
        first=self.call()
        import json
        evidence=self.scope.call('owner',self.task['id'],'lease',call['function']['name'],json.loads(call['function']['arguments']))
        second=self.call(1,body={'messages':[{'role':'user','content':'分析结构'},first['message'],
                         {'role':'tool','tool_call_id':'call1','content':json.dumps(evidence)}],'max_tokens':50})
        self.assertEqual(evidence['data'][0]['revenue_usd'],'120.00')
        self.assertEqual(second['status'],'succeeded'); self.assertEqual(self.calls,2)
        with self.db() as db: self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],2)


if __name__=='__main__': unittest.main()
