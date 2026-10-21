from contextlib import contextmanager,closing
from datetime import datetime,timedelta
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_pricing_v2 import fixture,NOW
import pricing_v2 as p
import pricing_operations as ops
import pricing_state
import fc27_quote_engine as engine

RUN='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
CONVERSATION='a'*32


def quoted():
    evidence,rows,_=fixture()
    with patch.object(p,'datetime',wraps=datetime) as clock:
        clock.now.return_value=NOW
        result=engine.calculate(evidence,{'minimum_gross_margin_pct':'10','pricing_rules':{'invalid_legacy':'ignored'}})
    return dict(run_id=RUN,created_at=NOW.isoformat(),evidence=evidence,edits={'minimum_gross_margin_pct':'10'},result=result)


class Tasks:
    def __init__(self,root):self.path=root/'tasks.sqlite3'
    @contextmanager
    def db(self):
        connection=sqlite3.connect(self.path)
        try:
            with connection:yield connection
        finally:connection.close()


class Control(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'conversations').mkdir()
        with closing(sqlite3.connect(self.root/'conversations/conversations.db')) as db:
            db.execute('CREATE TABLE conversations(id TEXT,owner TEXT)')
            db.execute('CREATE TABLE turns(task_id TEXT,conversation_id TEXT)')
            db.execute('INSERT INTO conversations VALUES(?,?)',(CONVERSATION,'wulv'))
            db.execute('INSERT INTO turns VALUES(?,?)',('task1',CONVERSATION))
            db.commit()
        self.tasks=Tasks(self.root)
        self.scope=SimpleNamespace(tasks=self.tasks,clock=lambda:NOW,context=lambda *a:None,
                                   book=SimpleNamespace(evidence={'e1':{}}))
        self.quote=quoted();self.calls=[]

    def grant(self,mode='operator_workflow',owner='wulv',expires=None,restore_sources=()):
        with self.tasks.db() as db:
            ops.grant(db,owner,CONVERSATION,RUN,mode,(expires or NOW+timedelta(hours=1)).isoformat(),'test',restore_sources)

    def request(self,path,owner,body=None):
        self.calls.append((path,owner,body))
        if path=='/pricing/state':return {'quote':copy.deepcopy(self.quote),'quote_usable':True}
        if path=='/automation':return {'platforms':['PS','XBOX','PC'],'minimum_gross_margin_pct':'10'}
        if path=='/monitor':return {'publication':{'status':'matched','execution_id':'original_execution'}}
        if body:return {'job_id':body['client_event_id'],'accepted':True}
        raise AssertionError(path)

    def call(self,args,owner='wulv',task='task1',request=None):
        return ops.call(self.scope,owner,task,'lease',args,request or self.request)

    def recommend(self,**overrides):
        args=dict(action='recommend',request_key='r1',run_id=RUN,console_choice='baseline',pc_choice='hold',
                  reason='本轮只调整到可比位置',counterexample='同口径采购毛利持续下降则复核',evidence_refs=['e1'])
        args.update(overrides);return self.call(args)

    def test_ungranted_and_cross_owner_tasks_cannot_write(self):
        self.grant()
        for owner,task in [('DY','task1'),('wulv','task2')]:
            with self.subTest(owner=owner,task=task),self.assertRaises(PermissionError):
                self.call({'action':'collect','request_key':'c1'},owner,task)
        self.assertFalse(self.calls)

    def test_expired_grant_cannot_write(self):
        self.grant(expires=NOW-timedelta(seconds=1))
        with self.assertRaises(PermissionError):self.recommend()

    def test_model_state_retains_original_publication_receipt(self):
        result=self.call({'action':'state'})
        self.assertEqual(result['monitor']['publication']['execution_id'],'original_execution')
        self.assertEqual(result['quote_sha256'],p.fingerprint(self.quote))
        self.assertEqual(result['quote_evidence_ref'],'pricing:'+p.fingerprint(self.quote))
        self.assertTrue(all(body is None for _,_,body in self.calls))

    def test_auto_review_cannot_deadlock_worker_with_another_queue(self):
        self.grant('automatic_review')
        self.assertIn('recommend',self.call({'action':'capabilities'})['allowed_actions'])
        with self.assertRaises(PermissionError):self.call({'action':'collect','request_key':'c1'})

    def test_unusable_quote_is_history_not_current_model_fact(self):
        original=self.request
        def request(path,owner,body=None):
            if path=='/pricing/state':return {'quote':copy.deepcopy(self.quote),'quote_usable':False}
            return original(path,owner,body)
        result=self.call({'action':'state'},request=request)
        self.assertIsNone(result['current_quote']);self.assertIsNone(result['quote_sha256'])
        self.assertEqual(result['historical_quote'],ops.quote_view(self.quote))
        self.assertEqual(result['historical_quote_sha256'],p.fingerprint(self.quote))
        self.assertIsNone(result['quote_evidence_ref'])

    def test_quote_fragments_preserve_complete_source_and_original_sha(self):
        def request(path,owner,body=None):
            if path=='/quotes/'+RUN:return copy.deepcopy(self.quote)
            return self.request(path,owner,body)
        result=self.call(dict(action='read_quote',run_id=RUN,path='/evidence/promotion_envelope/packages/PS'),request=request)
        self.assertTrue(result['complete']);self.assertEqual(result['value'],self.quote['evidence']['promotion_envelope']['packages']['PS'])
        self.assertEqual(result['quote_sha256'],p.fingerprint(self.quote))
        self.quote['edits']['large']={'one':'a'*11000}
        result=self.call(dict(action='read_quote',run_id=RUN,path='/edits'),request=request)
        self.assertFalse(result['complete']);self.assertNotIn('value',result)
        self.assertIn('/edits/large',result['read_subpaths'])

    def test_failed_job_exposes_original_partial_write_and_stops_new_intent(self):
        self.grant();jid='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        def request(path,owner,body=None):
            if path=='/jobs/'+jid:return dict(job_id=jid,kind='execute',status='failed',writer_result={'status':'FAILED'})
            if path=='/audits/'+jid:return dict(execution_id=jid,status='PARTIAL',changed=['PS','XBOX','PC'],sync_confirmed=True,after={'rows':[dict(platform='PS',b2c='.12')]})
            if path=='/monitor':return {'health':{'incomplete_executions':1}}
            return self.request(path,owner,body)
        result=self.call(dict(action='read_job',job_id=jid),request=request)
        self.assertTrue(result['price_write_observed']);self.assertTrue(result['reconciliation_required']);self.assertTrue(result['do_not_replay'])
        self.assertEqual(result['execution_audit']['after'][0]['b2c'],'.12')
        result=self.call(dict(action='execute',request_key='new-key',preview_id=jid),request=request)
        self.assertEqual(result['state'],'rejected');self.assertEqual(result['result']['error'],'pricing_execution_reconciliation_required')
        self.assertFalse(any(body for _,_,body in self.calls))

    def test_rejected_tool_calls_explain_fields_and_exact_evidence(self):
        self.grant()
        result=self.call(dict(action='collect',request_key='bad-fields',run_id=RUN))
        self.assertEqual(result['result']['expected_fields'],['action','request_key'])
        result=self.recommend(evidence_refs=['invented'])
        self.assertEqual(result['result']['expected_evidence_ref'],'pricing:'+p.fingerprint(self.quote))
        self.assertEqual(self.call({'action':'capabilities'})['action_fields']['collect'],['action','request_key'])

    def test_native_rejection_retains_machine_reason_without_replay(self):
        import io
        from urllib.error import HTTPError
        self.grant()
        def rejected(*args,**kwargs):raise HTTPError('native',400,'bad',{},io.BytesIO(b'{"error":"pricing_newer_run_exists"}'))
        result=self.call(dict(action='collect',request_key='http-reject'),request=rejected)
        self.assertEqual(result['state'],'rejected')
        self.assertEqual(result['result']['native_error'],'pricing_newer_run_exists')
        self.assertFalse(result['do_not_replay'])

    def test_lease_is_required_before_any_api_or_database_mutation(self):
        def denied(*args):raise PermissionError('lease lost')
        self.scope.context=denied
        with self.assertRaises(PermissionError):self.call({'action':'state'})
        self.assertFalse(self.calls)

    def test_recommendation_is_generated_and_has_counterexample_and_evidence(self):
        self.grant();result=self.recommend()
        self.assertEqual(result['state'],'accepted')
        self.assertFalse(result['queue_write_performed']);self.assertFalse(result['price_write_confirmed'])
        self.assertEqual(result['result']['console_usd'],self.quote['result']['decision_receipt']['decisions'][0]['candidates']['baseline'])
        self.assertTrue(all(body is None for _,_,body in self.calls))

    def test_recommendation_cannot_invent_evidence_or_candidate(self):
        self.grant()
        self.assertEqual(self.recommend(evidence_refs=['invented'])['state'],'rejected')
        self.assertEqual(self.recommend(request_key='r2',console_choice='invented')['state'],'rejected')

    def test_recommendation_rechecks_current_authorized_run(self):
        self.grant();self.quote['run_id']='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        self.assertEqual(self.recommend()['state'],'rejected')

    def test_unknown_write_is_never_replayed_even_with_same_request_key(self):
        self.grant()
        posts=[]
        def timeout(path,owner,body=None):
            posts.append(body);raise TimeoutError()
        args={'action':'collect','request_key':'once'}
        first=self.call(args,request=timeout);second=self.call(args,request=timeout)
        self.assertEqual(len(posts),1);self.assertEqual(first['state'],'unknown')
        self.assertTrue(second['reused']);self.assertTrue(second['do_not_replay'])
        self.assertEqual(first['job_id'],second['job_id'])

    def test_request_key_cannot_change_payload(self):
        self.grant();self.call({'action':'collect','request_key':'once'})
        with self.assertRaisesRegex(ValueError,'payload_conflict'):
            self.call({'action':'preview','request_key':'once','run_id':RUN})

    def test_apply_recommendation_uses_owned_program_prices(self):
        self.grant();rec=self.recommend()['result']
        result=self.call(dict(action='apply_recommendation',request_key='apply1',recommendation_id=rec['operation_id']))
        self.assertEqual(result['state'],'accepted')
        path,_,body=self.calls[-1]
        self.assertEqual(path,'/pricing/recalculate')
        self.assertEqual(body['edits']['quotes']['PS'],body['edits']['quotes']['XBOX'])
        self.assertFalse(result['price_write_confirmed'])

    def test_grant_cannot_be_replaced_with_wider_authority(self):
        self.grant('automatic_review')
        with self.assertRaisesRegex(ValueError,'grant_conflict'):self.grant('operator_workflow')

    def test_apply_rejects_changed_quote_even_in_same_run(self):
        self.grant();rec=self.recommend()['result'];self.quote['created_at']='changed'
        result=self.call(dict(action='apply_recommendation',request_key='apply1',recommendation_id=rec['operation_id']))
        self.assertEqual(result['state'],'rejected')
        self.assertEqual(result['result']['error'],'pricing_recommendation_basis_changed')
        self.assertFalse(any(body for _,_,body in self.calls))

    def test_restore_requires_original_run_or_explicit_source_grant(self):
        source='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'
        other='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        preview='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
        def request(path,owner,body=None):
            if path=='/audits/'+source:return dict(execution_id=source,run_id=other,status='CONFIRMED',sync_confirmed=True)
            if path=='/restore-previews/'+preview:return dict(source_execution_id=source,restore_preview_id=preview,available_platforms=['PS','XBOX','PC'])
            return self.request(path,owner,body)
        self.grant()
        for action in ('restore_preview','restore'):
            args=dict(action=action,request_key=action,source_execution_id=source)
            if action=='restore':args['restore_preview_id']=preview
            self.assertEqual(self.call(args,request=request)['state'],'rejected')
        self.assertFalse(any(body for _,_,body in self.calls))
        with self.tasks.db() as db:db.execute('DELETE FROM pricing_grants')
        self.grant(restore_sources=[source])
        for action in ('restore_preview','restore'):
            args=dict(action=action,request_key=action+'Granted',source_execution_id=source)
            if action=='restore':args['restore_preview_id']=preview
            self.assertEqual(self.call(args,request=request)['state'],'accepted')

    def test_automatic_review_cannot_receive_restore_source_grant(self):
        with self.assertRaisesRegex(ValueError,'restore_grant_scope'):
            self.grant('automatic_review',restore_sources=['bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'])

    def test_legacy_audit_restore_uses_preview_run_provenance(self):
        self.grant();source='bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';preview='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
        def request(path,owner,body=None):
            if path=='/audits/'+source:return dict(execution_id=source,preview_id=preview,status='CONFIRMED',sync_confirmed=True)
            if path=='/previews/'+preview:return dict(run_id=RUN)
            return self.request(path,owner,body)
        self.assertEqual(self.call(dict(action='restore_preview',request_key='legacy',source_execution_id=source),request=request)['state'],'accepted')

    def test_custom_model_price_requires_program_evaluation_with_same_quote(self):
        self.grant('automatic_review')
        original=self.request
        def request(path,owner,body=None):
            if path=='/pricing/evaluate':
                result=copy.deepcopy(self.quote['result'])
                canonical=p.fingerprint(self.quote)
                return {'canonical_quote_sha256':canonical,'result':result}
            return original(path,owner,body)
        self.request=request
        result=self.recommend(console_choice='evaluated',pc_choice='evaluated',console_usd='20.00',pc_usd='20.00')
        self.assertEqual(result['state'],'accepted')
        self.assertEqual(result['result']['source'],'program_verified_evaluation')

    def test_custom_evaluation_cannot_silently_use_a_new_quote(self):
        self.grant('automatic_review');original=self.request
        def request(path,owner,body=None):
            if path=='/pricing/evaluate':return {'canonical_quote_sha256':'different','result':{}}
            return original(path,owner,body)
        self.request=request
        self.assertEqual(self.recommend(console_choice='evaluated',pc_choice='evaluated',console_usd='20',pc_usd='20')['state'],'rejected')


class CallerContract(unittest.TestCase):
    def test_v2_does_not_execute_retired_discount_bands(self):
        quote=quoted()
        self.assertEqual(quote['result']['strategy_version'],p.VERSION)
        self.assertEqual(len(quote['result']['rows']),3)

    def test_selected_console_requires_both_and_policy_minimum_cannot_be_lowered(self):
        quote=quoted()
        with self.assertRaisesRegex(ValueError,'common_console_scope'):
            p.verify_quote(quote,{'minimum_gross_margin_pct':'10'},['PS'],now=NOW)
        with self.assertRaisesRegex(ValueError,'policy_margin_changed'):
            p.verify_quote(quote,{'minimum_gross_margin_pct':'12'},['PS','XBOX'],now=NOW)

    def test_pc_identity_and_future_trade_cannot_enter_quote(self):
        for fields in ({'game':'OTHER'},{'trade_at':(NOW+timedelta(days=1)).isoformat()}):
            e,rows,_=fixture();e['costs']['PC'].update(fields)
            with self.assertRaises(ValueError):p.apply_decision(rows,e,{},now=NOW)

    def test_effective_cost_identity_matches_selected_shared_record(self):
        e,rows,_=fixture();e['costs']['PS'].update(cny_per_1k='.8',trade_at='26-10-22 02:11:00')
        p.apply_decision(rows,e,{},now=NOW)
        self.assertEqual(rows[1]['cost_record_id'],'1')
        self.assertEqual(rows[1]['raw_cost_record_id'],'2')

    def test_model_intents_are_not_visible_to_another_owner(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'evidence').mkdir()
            (root/'evidence/hermes-pricing-1.json').write_text(json.dumps({'owner':'DY','phase':'unknown'}))
            self.assertIsNone(pricing_state.owned_review(root,'wulv'))
            self.assertEqual(pricing_state.owned_review(root,'DY')['phase'],'unknown')


if __name__=='__main__':unittest.main()
