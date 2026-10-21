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

SOURCE=Path(__file__).resolve().parents[1]/'source'


class FinalGuards(unittest.TestCase):
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

    def test_publisher_target_whitelist_and_new_file_boundary(self):
        path=SOURCE.parent/'deploy/release.py';spec=importlib.util.spec_from_file_location('pricing_release_contract',path)
        release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
        manifest=dict(scope=release.SCOPE,businessWrites=False,timersChanged=False,
            files=[dict(candidate=k,target=v,beforeSha256=None if k in release.NEW else 'a'*64,sha256='b'*64,owner='0:0',mode='0o644') for k,v in release.TARGETS.items()])
        self.assertEqual(release.checked_manifest(manifest),manifest)
        manifest['files'][0]['target']='/opt/unrelated.py'
        with self.assertRaisesRegex(ValueError,'exact_fc_v2'):release.checked_manifest(manifest)


if __name__=='__main__':unittest.main()
