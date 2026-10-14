"""No real identity, network, provider, ledger migration or runtime used."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from proxy_gateway import MAX_PROVIDER_WIRE_BYTES, MAX_PROVIDER_CONTEXT_TOKENS, conservative_input_bound, ModelGateway, ScopedTools, UnifiedBudget, schemas, request_body
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

    def test_large_hermes_context_and_many_rows_preserve_originals(self):
        messages=[{'role':'user' if i%2==0 else 'assistant','content':'capacity '+str(i)+' '+'x'*2000} for i in range(80)]
        result=request_body({'messages':messages,'max_tokens':50},self.policy['model'])
        self.assertEqual(result['messages'],messages)
        self.assertGreater(len(str(messages)),128000)
        self.assertEqual(len(result['messages']),80)

    def test_official_tool_task_marker_is_not_a_secret_prefix(self):
        messages=[{'role':'user','content':'Check the readonly sample.'},
                  {'role':'assistant','content':None,'tool_calls':[{'id':'fixture_call','type':'function','function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}]},
                  {'role':'tool','tool_call_id':'fixture_call','content':'Tool response: {"identity":"task-scoped HMAC pseudonyms for order/event/item IDs"}'}]
        body={'messages':messages,'max_tokens':50}
        self.assertEqual(request_body(body,self.policy['model'])['messages'],messages)
        self.call(body=body)
        self.assertEqual(self.calls,1)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT state FROM model_calls').fetchone()[0],'succeeded')

    def test_sk_text_is_allowed_in_user_tool_and_native_reasoning(self):
        markers=('sk-SYNTHETIC','task-scoped','risk-based','Use "task-scoped." evidence.',
                 r'{"identity":"task-scoped.AAAA"}')
        for marker in markers:
            for field in ('user','tool','reasoning'):
                messages=[{'role':'user','content':marker if field=='user' else 'Check the readonly sample.'}]
                if field=='tool':
                    messages.extend([{'role':'assistant','content':None,'tool_calls':[{'id':'fixture_sk','type':'function','function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}]},
                                     {'role':'tool','tool_call_id':'fixture_sk','content':json.dumps({'note':marker})}])
                if field=='reasoning':messages.append({'role':'assistant','content':'Safe public text.','reasoning_content':marker})
                with self.subTest(marker=marker,field=field):
                    self.assertEqual(request_body({'messages':messages,'max_tokens':50,'reasoning_effort':'max'},self.policy['model'])['messages'],messages)
        self.call(body={'messages':messages,'max_tokens':50,'reasoning_effort':'max'})
        self.assertEqual(self.calls,1)

    def test_other_credential_markers_remain_blocked_before_spend(self):
        for marker in ('Bearer fixture-only','Cookie: fixture-only','password=fixture-only',
                       '\nBearer fixture-only','\tCookie: fixture-only','\rpassword=fixture-only',
                       'Tool response: {"note":"password=fixture-only"}'):
            for field in ('user','tool','reasoning'):
                messages=[{'role':'user','content':marker if field=='user' else 'Check the readonly sample.'}]
                if field=='tool':
                    messages.extend([{'role':'assistant','content':None,'tool_calls':[{'id':'fixture_secret','type':'function','function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}]},
                                     {'role':'tool','tool_call_id':'fixture_secret','content':marker}])
                if field=='reasoning':messages.append({'role':'assistant','content':'Safe public text.','reasoning_content':marker})
                with self.subTest(marker=marker,field=field):
                    with self.assertRaisesRegex(ValueError,'context_rejected'):
                        self.call(body={'messages':messages,'max_tokens':50,'reasoning_effort':'max'})
        self.assertEqual(self.calls,0)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM hermes_reservations').fetchone()[0],0)

    def test_oversized_wire_rejected_before_any_reservation_or_provider(self):
        body={'messages':[{'role':'user','content':'x'*MAX_PROVIDER_WIRE_BYTES}],'max_tokens':50}
        with self.assertRaisesRegex(ValueError,'context_rejected'):
            self.call(body=body)
        self.assertEqual(self.calls,0)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM hermes_reservations').fetchone()[0],0)

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

    def test_documented_bailian_index_and_tool_roundtrip_preserved(self):
        call={'id':'call_indexed','type':'function','index':0,'function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}
        def indexed(req):
            value=self.answer(req)
            if self.calls==1:value['choices'][0]['message']={'role':'assistant','content':None,'tool_calls':[call],'refusal':None,'audio':None,'function_call':None}
            else:
                self.assertEqual(req['messages'][1]['tool_calls'][0]['index'],0)
                value['choices'][0]['message']['tool_calls']=None
            return value
        self.provider=indexed
        first=self.call();self.assertEqual(first['message']['tool_calls'][0]['index'],0);self.assertNotIn('refusal',first['message'])
        replay=__import__('copy').deepcopy(first['message']);replay['tool_calls'][0].pop('index')
        result=self.call(1,body={'messages':[{'role':'user','content':'query'},replay,{'role':'tool','tool_call_id':'call_indexed','content':'{}'}],'max_tokens':50})
        self.assertNotIn('index',replay['tool_calls'][0])
        self.assertEqual(result['status'],'succeeded');self.assertEqual(self.calls,2)
        self.assertIn('index',call)  # Original provider object is never mutated.

    def test_paid_index_cannot_be_attached_to_changed_tool_history_or_other_task(self):
        def indexed(req):
            value=self.answer(req);value['choices'][0]['message']['tool_calls']=[{'id':'call_bound','type':'function','index':2,'function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}]
            return value
        self.provider=indexed;first=self.call()
        import copy
        for mutate in ('arguments','name','index'):
            message=copy.deepcopy(first['message'])
            if mutate=='arguments':message['tool_calls'][0]['function']['arguments']='{"changed":true}'
            if mutate=='name':message['tool_calls'][0]['function']['name']=WIRE_TOOLS[1]
            if mutate=='index':message['tool_calls'][0]['index']=1
            with self.assertRaisesRegex(ValueError,'provider_tool_history_changed'):
                self.call(1,body={'messages':[{'role':'user','content':'query'},message,{'role':'tool','tool_call_id':'call_bound','content':'{}'}],'max_tokens':50})
        request=request_body({'messages':[{'role':'user','content':'query'},first['message'],{'role':'tool','tool_call_id':'call_bound','content':'{}'}],'max_tokens':50},self.policy['model'])
        request['messages'][1]['tool_calls'][0].pop('index')
        self.budget.restore_tool_indexes('other','different',1,request)
        self.assertNotIn('index',request['messages'][1]['tool_calls'][0]);self.assertEqual(self.calls,1)

    def test_index_extension_never_accepts_unknown_fields_or_invalid_metadata(self):
        for patch in ({'index':True},{'index':-1},{'index':'0'},{'extra':'private secret'}, {'index':0,'extra':'private secret'}):
            def invalid(req,patch=patch):
                value=self.answer(req);value['model']=req['model']
                value['choices'][0]['message']['tool_calls']=[{'id':'invalid','type':'function','function':{'name':WIRE_TOOLS[0],'arguments':'{}'},**patch}]
                return value
            self.provider=invalid
            newer=spec();newer['template_version']='invalid-index-'+str(len(patch))+str(patch.get('index'))+str('extra' in patch)
            task=self.tasks.create('owner',newer);self.tasks.reserve_dispatch(task['id'],'owner','lease');self.tasks.bind_run(task['id'],'owner','lease','run_'+task['id'])
            gateway=ModelGateway(ScopedTools(self.tasks,book(),lambda:self.now),self.budget,self.slot,invalid,lambda _:100,lambda:0)
            with self.assertRaisesRegex(ValueError,'unverified_provider_result'):gateway.call('owner',task['id'],'lease',0,{'messages':[{'role':'user','content':'new'}],'max_tokens':50})
        import json
        with self.db() as db:receipts=[json.loads(r[0]) for r in db.execute('SELECT content FROM model_calls')]
        self.assertTrue(all('private secret' not in json.dumps(r) for r in receipts))
        self.assertTrue(any(r['response_shape']['tool_shapes'][0]['unknown_field_count']==1 for r in receipts))

    def test_research_turn_supports_more_than_legacy_five_readonly_calls(self):
        def parallel(req):
            value=self.answer(req)
            value['choices'][0]['finish_reason']='tool_calls'
            value['choices'][0]['message']['tool_calls']=[{'id':'call_'+str(i),'type':'function',
                'function':{'name':name,'arguments':'{}'}} for i,name in enumerate(WIRE_TOOLS[:6])]
            return value
        self.provider=parallel
        self.assertEqual(len(self.call()['message']['tool_calls']),6)

    def test_restored_index_bytes_rejected_before_slot_and_new_reservation(self):
        import json
        def indexed(req):
            value=self.answer(req)
            value['choices'][0]['message']={'role':'assistant','content':None,'tool_calls':[{'id':'call_size','type':'function','index':100000,'function':{'name':WIRE_TOOLS[0],'arguments':'{}'}}]}
            return value
        self.provider=indexed;first=self.call()
        message=deepcopy(first['message']);message['tool_calls'][0].pop('index')
        body={'messages':[{'role':'user','content':''},message,{'role':'tool','tool_call_id':'call_size','content':'{}'}],'max_tokens':50}
        base=request_body(body,self.policy['model'])
        body['messages'][0]['content']='x'*(MAX_PROVIDER_CONTEXT_TOKENS-5-body['max_tokens']-conservative_input_bound(base))
        self.assertEqual(conservative_input_bound(request_body(body,self.policy['model']))+body['max_tokens'],MAX_PROVIDER_CONTEXT_TOKENS-5)
        with self.assertRaisesRegex(ValueError,'context_window_exceeded'):self.call(1,body=body)
        self.assertEqual(self.calls,1)
        with self.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM model_calls').fetchone()[0],1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM model_calls WHERE state='unknown'").fetchone()[0],0)

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
