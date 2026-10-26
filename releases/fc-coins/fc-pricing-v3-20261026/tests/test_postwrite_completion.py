import json,sys,tempfile,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from fc_pricing_v3 import runtime
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.financial import fingerprint
from fixtures import fixture,NOW

class PostwriteCompletion(unittest.TestCase):
    def test_expired_ending_plan_reproves_saved_price_without_daily_range_or_new_budget(self):
        evidence,_,_=fixture();evidence['run_id']='00000000-0000-4000-8000-000000000090'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'jobs').mkdir();(root/'executions').mkdir();(root/'config').mkdir()
            db=Ledger(root/'control.db');db.activate_generation('g',[])
            anchor=dict(base_prices=dict(console='30',pc='30'),region_coefficients={})
            with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
                plan=db.create_plan('flash_sale',['base:console','base:pc'],anchor,starts_at=NOW.isoformat(),daily_budget='100')
                db.activate_plan(plan['plan_id'])
            plan.update(state='ENDING',ends_at=NOW.isoformat());db.put('pricing_plans',plan['plan_id'],plan)
            action=dict(base_prices=dict(console='20',pc='20'),region_coefficients={})
            bundle=dict(plan_id=plan['plan_id'],action=action,mutable_resources=plan['resources'],assignment_id='assignment',
                        budget_reservation={'console':{'concession':'99'}},review_contract='inherited_hermes_review_with_explicit_v3_deterministic_path',review_receipt=dict(phase='completed'))
            op=dict(operation_id='original',plan_id=plan['plan_id'],generation='g',resources=plan['resources'],bundle=bundle)
            db.put('operations','original',op);db.put('reservations','original',dict(groups=bundle['budget_reservation'],state='RESERVED',plan_id=plan['plan_id'],operation_id='original'))
            (root/'executions/original.json').write_text(json.dumps(dict(execution_id='original',sync_confirmed=True,after=dict(rows=[dict(platform=p,b2c='.2') for p in ('PS','XBOX','PC')]))))
            (root/'config/v3-control.json').write_text(json.dumps(dict(enabled=True,generation='g')))
            job=dict(request=dict(v3_operation_id='original'))
            with patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate_postwrite(evidence,job,db)
                quote=dict(evidence=evidence,result=result)
                receipt=runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),['PS','XBOX','PC'],now=NOW,for_execution=True,purpose='original_unsent_ALL_steps_only')
                self.assertEqual(receipt['action']['base_prices'],action['base_prices'])
                self.assertEqual(receipt['budget_reservation'],bundle['budget_reservation'])
                self.assertEqual(receipt['budget_kind'],'original_reservation_no_new_price_or_concession')
                with self.assertRaisesRegex(ValueError,'purpose_mismatch'):
                    runtime.verify_quote(quote,dict(minimum_gross_margin_pct='20'),['PS','XBOX','PC'],now=NOW,for_execution=True)
                self.assertEqual(db.get('pricing_plans',plan['plan_id'])['state'],'ENDING')
                with self.assertRaisesRegex(ValueError,'pricing_margin_contract_changed'):
                    runtime.verify_quote(quote,dict(minimum_gross_margin_pct='10'),['PS','XBOX','PC'],now=NOW,for_execution=True,purpose='original_unsent_ALL_steps_only')
                op['bundle']['budget_policy']='none'
                db.put('operations','original',op)
                with db.transaction() as conn:conn.execute("DELETE FROM reservations WHERE id='original'")
                new_result=runtime.calculate_postwrite(evidence,job,db)
                new_receipt=runtime.verify_quote(dict(evidence=evidence,result=new_result),dict(minimum_gross_margin_pct='20'),['PS','XBOX','PC'],now=NOW,for_execution=True,purpose='original_unsent_ALL_steps_only')
                self.assertEqual(new_receipt['budget_policy'],'none')

if __name__=='__main__':unittest.main()
