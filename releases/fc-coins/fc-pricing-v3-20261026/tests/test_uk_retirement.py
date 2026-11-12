from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock,patch
import json,sys,unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fixtures import fixture,NOW,set_console_cost
from fc_pricing_v3 import api,adapters,runtime,region_source,uk_retirement as uk
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger

RUN='00000000-0000-4000-8000-000000000081';OP='00000000-0000-4000-8000-000000000082'


def evidence():
    data=fixture()[0];data['run_id']=RUN
    for p in ('PS','XBOX','PC'):
        data['costs'][p]['cny_per_1k']='0.10';data['storefront']['rows'][p]['package_usd']='20'
    set_console_cost(data)
    data['regional_controls']=[]
    data['region_rules']=[dict(id=1,region_id=39,platforms=['PS','XBOX','PC'],factor='.9100',verified=True,
        price_semantics='regional_regular_multiplicative',rounding='half_up_cent',
        history=dict(by_platform={p:dict(basis='platform_other_promotions_excluding_region_verified') for p in ('PS','XBOX','PC')}))]
    data['region_contract']=dict(rules=[dict(uk.SCOPE,id=1,factor='.9100',status=1)])
    return data


class UKRetirement(unittest.TestCase):
    def setup_plan(self,folder):
        db=Ledger(Path(folder)/'control.sqlite3');db.activate_generation('g',[])
        with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            plan=db.create_plan('daily',['base:PS','base:XBOX','base:PC'],dict(base_prices=dict(PS='20',XBOX='20',PC='20'),region_coefficients={}))
            db.activate_plan(plan['plan_id'])
        return db,db.get('pricing_plans',plan['plan_id'])

    def calculate(self,db,plan,data=None):
        data=data or evidence()
        with patch.object(runtime,'clock',return_value=NOW):
            result=uk.calculate(data,dict(request=dict(v3_plan_id=plan['plan_id'],v3_operation_id=OP)),db)
        return data,result

    def test_only_exact_UK_retirement_changes_factor_inheritance_and_uses_original_authority(self):
        with TemporaryDirectory() as folder:
            db,plan=self.setup_plan(folder);data,result=self.calculate(db,plan);bundle=result['decision_receipt']
            self.assertEqual(bundle['action']['base_prices'],bundle['before_action']['base_prices'])
            self.assertEqual(set(bundle['action']['region_coefficients'].values()),{'1'})
            self.assertTrue(bundle['before_financial_proof']['pass_all']);self.assertTrue(bundle['financial_proof']['pass_all'])
            self.assertEqual(bundle['uk_rule_expectations'][0]['status'],0)
            root=Path(folder);(root/'config').mkdir();(root/'config/v3-control.json').write_text(json.dumps(dict(enabled=True,generation='g')))
            (root/'jobs').mkdir();(root/'jobs'/(RUN+'.json')).write_text(json.dumps(dict(request=dict(v3_plan_id=plan['plan_id'],v3_operation_id=OP,v3_authorization_purpose=uk.PURPOSE))))
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'clock',return_value=NOW),patch.object(db,'assignment',side_effect=AssertionError('retirement_must_not_draw_a_strategy_price')):
                routed=runtime.calculate(data)
            self.assertEqual(routed['decision_receipt']['maintenance_purpose'],uk.PURPOSE)
            with patch.object(runtime,'ROOT',root):
                checked=runtime.verify_quote(dict(evidence=data,result=result),dict(minimum_gross_margin_pct='20'),['PS','XBOX','PC'],now=NOW,for_execution=True)
            self.assertEqual(checked['review_contract'],uk.PURPOSE)
            operation=db.prepare(plan,bundle,now=NOW)
            claimed=db.claim_dispatch(OP,bundle['steps'][0]['step_id'],now=NOW)
            self.assertEqual(claimed['target_status'],0)
            self.assertEqual(operation['bundle']['mutable_resources'],uk.RESOURCES)
            tampered=deepcopy(bundle);tampered['action']['base_prices']['PS']='21'
            with self.assertRaisesRegex(ValueError,'base_changed'):uk.authority_resources(tampered)
            tampered=deepcopy(bundle);tampered['steps'][0]['scope']['lang_region_id']=21
            with self.assertRaisesRegex(ValueError,'scope_changed'):uk.authority_resources(tampered)

    def test_retirement_requires_before_and_after_full_dual20_and_rejects_changed_rule(self):
        with TemporaryDirectory() as folder:
            db,plan=self.setup_plan(folder);data=evidence()
            data['region_contract']['rules'][0]['factor']='.90'
            with self.assertRaisesRegex(ValueError,'rule_changed'):self.calculate(db,plan,data)
            data=evidence()
            for p in ('PS','XBOX','PC'):data['costs'][p]['cny_per_1k']='100'
            set_console_cost(data)
            with self.assertRaises(ValueError):self.calculate(db,plan,data)

    def test_transport_disables_one_exact_row_and_retains_its_value_and_other_rules(self):
        current=[dict(uk.SCOPE,id=1,factor='.9100',status=1),dict(uk.SCOPE,id=2,lang_region_id=21,aid=21587,factor='.98',status=1)]
        before=deepcopy(current);session=Mock();callback=Mock()
        def post(path,payload):
            self.assertEqual(path,region_source.CONTROLLER+'edit')
            self.assertEqual(payload,dict(uk.SCOPE,id=1,factor='0.9100',status=0))
            current[0]['status']=0;return 200,dict(code=1)
        session.post_admin.side_effect=post
        step=dict(scope=uk.SCOPE,rule_id=1,value='.9100',target_status=0,intent=uk.PURPOSE,expected_rule_set_sha256=fingerprint(current))
        result=region_source.save_rule(session,lambda *args:deepcopy(current),step,before_send=callback)
        self.assertEqual(result['status'],'CONFIRMED');self.assertEqual(current[1],before[1]);self.assertEqual(current[0]['factor'],'.9100')
        self.assertEqual(session.post_admin.call_count,1);callback.assert_called_once()
        with self.assertRaisesRegex(ValueError,'rule_set_changed'):region_source.save_rule(session,lambda *args:current,step)
        self.assertEqual(session.post_admin.call_count,1)

    def test_unknown_original_is_read_back_without_a_second_POST_even_after_quote_expiry(self):
        with TemporaryDirectory() as folder:
            root=Path(folder);db,plan=self.setup_plan(root);data,result=self.calculate(db,plan);bundle=result['decision_receipt']
            db.prepare(plan,bundle,now=NOW);step=bundle['steps'][0];db.claim_dispatch(OP,step['step_id'],now=NOW)
            original=db.get('operations',OP);original['steps'][0]['transport_claimed_at']=NOW.isoformat();original['status']='UNKNOWN';db.put('operations',OP,original)
            def read(operation,step_id,**kwargs):
                self.assertFalse(kwargs.get('write',False));self.assertEqual(operation,OP)
                return dict(status='CONFIRMED',rule_set_sha256='new-rules')
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'clock',return_value=NOW+timedelta(hours=1)),patch.object(adapters,'region_step',side_effect=read) as reader,patch.object(adapters,'reconcile_postwrite',return_value=dict(status='PUBLIC_CONFIRMED',uk_discount_retired=True)):
                complete=runtime.reconcile(OP)
            self.assertEqual(complete['status'],'COMPLETED');self.assertEqual(complete['operation_id'],OP);reader.assert_called_once()
            self.assertEqual(db.get('actual_price_windows',OP)['resources'],uk.RESOURCES)

    def test_public_readback_binds_current_status_zero_instead_of_permanent_UK_091(self):
        with TemporaryDirectory() as folder:
            db,plan=self.setup_plan(folder);data,result=self.calculate(db,plan);bundle=result['decision_receipt'];rules=deepcopy(data['region_contract']['rules']);rules[0]['status']=0
            public=dict(offers={p:dict(regular_usd=bundle['financial_proof']['prices']['39:'+p]['price']['regular_usd'],coefficient='1') for p in ('PS','XBOX','PC')})
            with patch.object(adapters,'region_step',return_value=dict(rules=rules)),patch('fc_pricing_v3.regional_public.collect',return_value=public) as read:
                verified=adapters.verify_regions(dict(operation_id=OP,bundle=bundle))
            self.assertEqual(verified['status'],'verified');self.assertTrue(verified['uk_discount_retired']);read.assert_called_once_with('uk',39)
            rules[0]['status']=1
            with patch.object(adapters,'region_step',return_value=dict(rules=rules)):
                self.assertEqual(adapters.verify_regions(dict(operation_id=OP,bundle=bundle))['reason'],'pricing_uk_rule_changed')

    def test_same_request_reuses_one_job_and_conflicting_payload_is_rejected(self):
        with TemporaryDirectory() as folder:
            db,plan=self.setup_plan(folder);request=dict(request_key='uk-once',plan_id=plan['plan_id'])
            with patch.object(api,'ledger',return_value=db):
                first=api.post('retire-uk-discount',request,'wulv');second=api.post('retire-uk-discount',request,'wulv')
                with self.assertRaisesRegex(ValueError,'payload_conflict'):api.post('retire-uk-discount',dict(request,plan_id='other'),'wulv')
            self.assertEqual(first,second)
            with db.connect() as conn:self.assertEqual(conn.execute("SELECT count(*) FROM durable_jobs WHERE kind='uk_retirement'").fetchone()[0],1)


if __name__=='__main__':unittest.main()
