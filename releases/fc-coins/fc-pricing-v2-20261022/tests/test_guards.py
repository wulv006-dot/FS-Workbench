import ast
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_control import quoted,RUN
from test_pricing_v2 import NOW
import pricing_v2 as p
import automation_policy
import hermes_pricing_bridge as bridge
import pricing_sources as sources

SOURCE=Path(__file__).resolve().parents[1]/'source'


class FinalGuards(unittest.TestCase):
    def test_simulation_bridge_accepts_exact_current_core_and_rejects_drift(self):
        import sys,types,shutil
        spec=importlib.util.spec_from_file_location('v14_simulation_bridge_test',SOURCE/'pricing_simulation.py')
        module=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'pilot':types.SimpleNamespace(digest=p.fingerprint)}):spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            code=Path(folder)
            for name in ('pricing_v2.py','fc27_quote_engine.py','automation_policy.py'):shutil.copy2(SOURCE/name,code/name)
            bridge=module.SimulationBridge(code=code)
            engine,policy=bridge.modules();self.assertTrue(callable(engine.calculate));self.assertTrue(callable(policy.normalize_policy))
            with (code/'pricing_v2.py').open('a') as f:f.write('\n# unapproved drift\n')
            with self.assertRaisesRegex(ValueError,'simulation_v2_code_changed'):bridge.modules()

    def test_shared_admin_uses_existing_full_runtime_from_stdlib_caller(self):
        from types import SimpleNamespace
        import subprocess
        quote=quoted();envelope=quote['evidence']['promotion_envelope'];public=quote['evidence']['storefront']
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(envelope))) as run:
            self.assertEqual(sources.collect(public,persist=False),envelope)
            self.assertEqual(run.call_args.args[0][0],'/opt/python39/bin/python3')
            self.assertFalse(json.loads(run.call_args.kwargs['input'])['persist'])
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=1,stdout=json.dumps(dict(reason='current_source_failed')))):
            with self.assertRaisesRegex(ValueError,'current_source_failed'):sources.collect(public)
        with patch('subprocess.run',side_effect=subprocess.TimeoutExpired('collect',40)):
            with self.assertRaisesRegex(ValueError,'shared_source_timeout'):sources.collect(public)

    def test_write_rechecks_live_promotions_and_rejects_new_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('quotes','previews','monitor'):(root/name).mkdir()
            quote=quoted();(root/'quotes'/(RUN+'.json')).write_text(json.dumps(quote))
            (root/'previews'/(RUN+'.json')).write_text(json.dumps(dict(run_id=RUN)))
            public=quote['evidence']['storefront'];public.update(status='ok',source='https://www.mmoexp.com/Fc-27/Coins.html',currency='USD')
            (root/'monitor/storefront.json').write_text(json.dumps(public))
            request=dict(preview_id=RUN,platforms=['PS','XBOX','PC'])
            with patch.object(automation_policy,'load_policy',lambda:{'minimum_gross_margin_pct':'10'}),patch.object(p,'datetime',wraps=datetime) as pc,patch.object(sources,'datetime',wraps=datetime) as sc,patch.object(sources,'collect') as collect:
                pc.now.return_value=sc.now.return_value=NOW
                collect.return_value=quote['evidence']['promotion_envelope']
                self.assertEqual(sources.refresh_before_write(request,root)['status'],'current_promotions_rechecked')
                self.assertTrue(collect.call_args.kwargs['persist'])
                collect.return_value=dict(quote['evidence']['promotion_envelope'],sha256='newly_changed')
                with self.assertRaisesRegex(ValueError,'promotions_changed_since_quote'):sources.refresh_before_write(request,root)
                public['rows']['PS']['package_usd']='19.99';(root/'monitor/storefront.json').write_text(json.dumps(public))
                collect.return_value=quote['evidence']['promotion_envelope']
                self.assertEqual(sources.refresh_before_write(dict(source_execution_id=RUN,platforms=['PS','XBOX']),root)['status'],'current_promotions_rechecked')

    def test_unverified_legal_coupon_combination_is_analysis_only(self):
        quote=quoted();envelope=quote['evidence']['promotion_envelope']
        envelope['coupon_other_benefits_contract']='unverified'
        with self.assertRaisesRegex(ValueError,'coupon_other_benefits_unverified'):
            p.verify_quote(quote,{'minimum_gross_margin_pct':'10'},['PS','XBOX'],now=NOW,for_execution=True)

    def test_restore_rechecks_current_cost_and_console_combination(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'quotes').mkdir();(root/'config').mkdir()
            quote=quoted();(root/'quotes'/(RUN+'.json')).write_text(json.dumps(quote))
            (root/'config/pricing-inputs.json').write_text(json.dumps(quote['evidence']['promotion_envelope']))
            node=next(n for n in ast.parse((SOURCE/'restore_price.py').read_text('utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='restore_safety')
            scope=dict(ROOT=root,load_policy=lambda:{'minimum_gross_margin_pct':'10','revision':40},json=json,
                       hashlib=__import__('hashlib'),datetime=datetime,timezone=__import__('datetime').timezone,Decimal=__import__('decimal').Decimal)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<actual-restore-guard>','exec'),scope)
            rows=[dict(platform=x,restore_b2c='.20') for x in ('PS','XBOX','PC')]
            with patch.object(automation_policy,'POLICY_FILE',root/'config/automation.json'),patch.object(p,'datetime',wraps=datetime) as clock:
                clock.now.return_value=NOW
                # The restore guard's current clock must agree with the frozen source clock.
                with patch.dict(scope,datetime=clock):
                    self.assertEqual(scope['restore_safety'](rows,['PS','XBOX'])['run_id'],RUN)
                    rows[0]['restore_b2c']='.21'
                    with self.assertRaisesRegex(ValueError,'console_restore'):scope['restore_safety'](rows,['PS','XBOX'])
                    rows[0]['restore_b2c']=rows[1]['restore_b2c']='.01'
                    with self.assertRaisesRegex(ValueError,'catalog_hard_margin_floor'):scope['restore_safety'](rows,['PS','XBOX'])
                    rows[0]['restore_b2c']=rows[1]['restore_b2c']='.12'
                    with self.assertRaisesRegex(ValueError,'average_catalog_margin_floor'):scope['restore_safety'](rows,['PS','XBOX'])

    def test_policy_and_original_manual_exception_cannot_waive_floor(self):
        quote=quoted();quote['automation_policy_revision']=40
        quote['result']['minimum_gross_margin_pct']='10'
        policy=automation_policy.initial_policy();policy.update(system_enabled=True,mode='auto',revision=40,platforms=['PS','XBOX','PC'])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'pricing-inputs.json').write_text(json.dumps(quote['evidence']['promotion_envelope']))
            with patch.object(automation_policy,'POLICY_FILE',root/'automation.json'),patch.object(automation_policy,'datetime',wraps=datetime) as clock,patch.object(p,'datetime',wraps=datetime) as priceclock:
                clock.now.return_value=priceclock.now.return_value=NOW
                self.assertEqual(automation_policy.check_write(policy,quote,['PS','XBOX'],confirmed=['PS','XBOX'],reason='人工确认'),[])
                quote['result']['rows'][0]['proposal']='0.0001'
                with self.assertRaisesRegex(ValueError,'tampered'):
                    automation_policy.check_write(policy,quote,['PS','XBOX'],confirmed=['PS','XBOX'],reason='人工确认')

    def test_unknown_model_create_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'evidence').mkdir();calls=[]
            def request(*args,**kwargs):calls.append(args);raise TimeoutError()
            def save(path,value):path.write_text(json.dumps(value))
            with patch.object(bridge,'ROOT',root),patch.object(bridge,'request',request),patch.object(bridge,'save',save),patch.object(bridge.os,'chown',lambda *a:None,create=True):
                job={'job_id':RUN,'actor':'wulv'};quote=quoted()
                first=bridge.review(job,quote,wait_seconds=0)
                second=bridge.review(job,quote,wait_seconds=0)
                self.assertEqual(len(calls),1);self.assertEqual(first['phase'],second['phase'])
                self.assertTrue(first['do_not_replay']);self.assertEqual(first['phase'],'unknown')

    def test_feedback_contract_is_sent_in_actual_review_turn(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'evidence').mkdir();calls=[]
            def request(owner,path,body=None):
                calls.append((path,body))
                return {'conversation_id':'feedback-conversation'} if path=='/api/hermes/conversations' else {'turn_id':'feedback-turn'}
            with patch.object(bridge,'ROOT',root),patch.object(bridge,'FS',root),patch.object(bridge,'request',request),patch.object(bridge,'save',lambda path,value:path.write_text(json.dumps(value))),patch.object(bridge.os,'chown',lambda *a:None,create=True),patch('pricing_operations.grant'),patch.object(bridge,'turn_state',return_value={'state':'completed','task_id':'feedback-task'}),patch.object(bridge,'recommendation',return_value=None):
                result=bridge.review({'job_id':RUN,'actor':'wulv'},quoted(),wait_seconds=0)
            self.assertEqual(result['phase'],'completed')
            text=calls[1][1]['text']
            for expected in ('同范围采购毛利额','promotion_usage','不同交易时刻','24–48','程序baseline'):
                self.assertIn(expected,text)
            self.assertEqual([path for path,body in calls],['/api/hermes/conversations','/api/hermes/conversations/feedback-conversation/turns'])

    def test_publisher_target_whitelist_and_new_file_boundary(self):
        path=SOURCE.parent/'deploy/release.py';spec=importlib.util.spec_from_file_location('pricing_release_contract',path)
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        manifest=dict(scope=release.SCOPE,businessWrites=False,timersChanged=False,
            files=[dict(candidate=k,target=v,beforeSha256=None if k in release.NEW else 'a'*64,sha256='b'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()])
        self.assertEqual(release.checked_manifest(manifest),manifest)
        manifest['files'][0]['target']='/opt/unrelated.py'
        with self.assertRaisesRegex(ValueError,'exact_fc_v2'):release.checked_manifest(manifest)


if __name__=='__main__':unittest.main()
