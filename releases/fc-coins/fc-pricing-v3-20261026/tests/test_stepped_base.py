from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from test_dual20_sprint import source,NOW
from fc_pricing_v3 import engine,runtime,adapters,dispatch
from fc_pricing_v3.financial import fingerprint
from fc_pricing_v3.ledger import Ledger


class SteppedBase(unittest.TestCase):
    def test_coupled_path_checks_every_transition_and_keeps_unique_ids(self):
        before=dict(base_prices=dict(console='10'),region_coefficients={'21:PS':'.8'})
        after=dict(base_prices=dict(console='8'),region_coefficients={'21:PS':'1'})
        checked=[]
        def validate(state):
            value=Decimal(state['base_prices']['console'])*Decimal(state['region_coefficients']['21:PS'])
            if not Decimal('7.5')<=value<=Decimal('8.5'):raise ValueError('outside_proven_band')
            checked.append(deepcopy(state))
        steps=engine.commit_path(before,after,validate)
        self.assertGreater(sum(s['kind']=='base' for s in steps),1)
        self.assertEqual(steps[-1]['intermediate'],after)
        self.assertEqual(len(steps),len({s['step_id'] for s in steps}))
        for step in steps:validate(step['intermediate'])
        self.assertEqual(before['base_prices']['console'],'10')

    def exercise(self,unknown_second=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'v3/control.sqlite3')
            for name in ('config','quotes','previews','requests','executions','v3/authorizations'):(root/name).mkdir(parents=True,exist_ok=True)
            (root/'config/v3-control.json').write_text(json.dumps(dict(enabled=True,generation='g')))
            with patch('fc_pricing_v3.ledger.clock',return_value=NOW),patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'STORE',root/'v3'),patch.object(runtime,'clock',return_value=NOW):
                db.activate_generation('g',[])
                data=source(loot='9.18',item='8.14',cost='.32',bonus='5')
                data['fx']['cny_per_usd']='6.72';data['costs']['PC']['cny_per_1k']='.36'
                data['historical_discount_mix'].update(retained_ratio='.9158',net_order_usd='91.58',actual_discount_usd='8.42')
                mix=data['historical_discount_mix'];mix['sha256']=fingerprint({k:v for k,v in mix.items() if k!='sha256'})
                for p in engine.PLATFORMS:
                    data['storefront']['rows'][p]['package_usd']='8.80' if p=='PC' else '8.72'
                    data['offers'][p]['Lootbar']['bonus_k']='5'
                data['offers']['PC']['Lootbar']['usd_price']='8.68'
                data['regional_controls']=[dict(id=i,region_id=21,platforms=[p],factor='.9055',resource='region:21:'+p,verified=True,price_semantics='regional_regular_multiplicative',history=dict(basis='pooled_other_promotions_excluding_region_verified'),scope={},expected_rule_set_sha256='a'*64) for i,p in enumerate(('PS','XBOX'),3)]
                data['region_rules']=deepcopy(data['regional_controls'])
                data['arab_ut_quotes']=[dict(platform=p,region_id=21,price_usd='8.27',purchase_k='100',bonus_k='0',captured_at=NOW.isoformat(),delivery='normal',selection_verified=True,currency='USD') for p in ('PS','XBOX')]
                anchor=dict(base_prices=dict(console='8.72',pc='8.80'),region_coefficients={'21:PS':'.9055','21:XBOX':'.9055'})
                plan=db.create_plan('revenue_sprint',['base:console','base:pc','region:21:PS','region:21:XBOX'],anchor)
                db.activate_plan(plan['plan_id']);plan=db.get('pricing_plans',plan['plan_id'])
                result=runtime.calculate(data);bundle=result['decision_receipt']
                self.assertGreater(sum(s['kind']=='base' for s in bundle['steps']),1)
                quote=dict(run_id=data['run_id'],evidence=data,result=result)
                (root/'quotes'/(data['run_id']+'.json')).write_text(json.dumps(quote))
                preview=dict(preview_id='00000000-0000-4000-8000-000000000001',run_id=data['run_id'],targets=[],backend_before=dict(rows=[]))
                for row in result['rows']:
                    p=row['platform'];old=Decimal(anchor['base_prices']['pc' if p=='PC' else 'console'])/100
                    preview['backend_before']['rows'].append(dict(platform=p,b2c=str(old),costPrice=str(old*Decimal('5.32'))))
                    preview['targets'].append(dict(platform=p,quote=row['proposal']))
                (root/'previews'/(preview['preview_id']+'.json')).write_text(json.dumps(preview))
                op=db.prepare(plan,bundle,dispatch_context=dict(preview=dict(preview_id=preview['preview_id'],status='review_only'),selected=list(engine.PLATFORMS),actor='system-automation',policy_revision=42,automatic=True))
                calls=[];unknown=[]
                def writer(command,*args):
                    request=json.loads(Path(command[1]).read_text());child=request['execution_id']
                    calls.append(child)
                    dispatch.validate_dispatch(child,request['preview_id'],request['platforms'])
                    saved=json.loads((root/'previews'/(request['preview_id']+'.json')).read_text())
                    projected=runtime.project_base_step(quote,saved['v3_execution_step'])
                    runtime.verify_quote(projected,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),for_execution=True)
                    tampered=deepcopy(projected);tampered['result']['rows'][0]['proposal']='.0001'
                    with self.assertRaisesRegex(ValueError,'projection_changed'):runtime.verify_quote(tampered,dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),for_execution=True)
                    after=dict(rows=[dict(platform=t['platform'],b2c=t['quote'],costPrice=t['targetCost']) for t in saved['targets']])
                    audit=dict(execution_id=child,preview_id=request['preview_id'],run_id=data['run_id'],created_at=NOW.isoformat(),status='CONFIRMED',sync_confirmed=True,all_baseline=dict(status='confirmed'),before=saved['backend_before'],after=after,targets=saved['targets'],selected=request['platforms'],changed=request['platforms'])
                    if unknown_second and len(calls)==2:
                        unknown.append(deepcopy(audit));audit.update(status='UNCERTAIN',sync_confirmed=False,all_baseline={})
                    (root/'executions'/(child+'.json')).write_text(json.dumps(audit))
                    return 0,dict(status=audit['status'])
                worker=SimpleNamespace(APP=Path('/mechanical'),run=writer)
                public=dict(status='PUBLIC_CONFIRMED',public=dict(status='verified'))
                def region(*args,**kwargs):return dict(status='CONFIRMED',rule_set_sha256='b'*64)
                with patch.dict(sys.modules,{'fc27_cloud_worker':worker}),patch('automation_policy.load_policy',return_value=dict(minimum_gross_margin_pct='20')),patch.object(adapters,'region_step',side_effect=region),patch.object(adapters,'reconcile_postwrite',return_value=public),patch.object(adapters,'reconcile_base',return_value=dict(status='UNKNOWN')) as reconcile:
                    outcome=runtime.drive_steps(op,quote)
                    if unknown_second:
                        self.assertEqual(outcome['status'],'UNKNOWN');count=len(calls)
                        runtime.reconcile(op['operation_id']);self.assertEqual(len(calls),count)
                        reconcile.assert_called_once()
                        recovered=unknown[0];(root/'executions'/(recovered['execution_id']+'.json')).write_text(json.dumps(recovered))
                        outcome=runtime.reconcile(op['operation_id'])
                    self.assertEqual(outcome['status'],'COMPLETED',[(s['step_id'],s.get('receipt')) for s in outcome['steps']])
                    self.assertEqual(len(calls),len(set(calls)))
                    self.assertEqual(len(calls),sum(s['kind']=='base' for s in bundle['steps']))
                    self.assertEqual(runtime.reconcile(op['operation_id'])['status'],'COMPLETED')
                aggregate=json.loads((root/'executions'/(op['operation_id']+'.json')).read_text())
                self.assertEqual(aggregate['mechanical_execution_kind'],'audited_step_aggregate')
                self.assertEqual(aggregate['child_execution_ids'],calls)
                self.assertEqual(len(db.all('operations')),1)
                self.assertEqual(len(db.all('actual_price_windows')),1)

    def test_each_base_has_durable_unique_request_and_one_parent(self):self.exercise()
    def test_unknown_second_base_reconciles_original_without_resend(self):self.exercise(True)


if __name__=='__main__':unittest.main()
