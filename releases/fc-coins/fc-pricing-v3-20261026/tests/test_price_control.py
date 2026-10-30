"""Operator settings and the real quote/verification path, using synthetic prices only."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from fc_pricing_v3 import api,engine,runtime
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.financial import fingerprint
from fixtures import fixture,NOW


class PriceControlTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.db=Ledger(self.root/'control.db')
        self.data=fixture()[0];self.data['run_id']='00000000-0000-4000-8000-000000000099'
        for cost in self.data['costs'].values():cost['cny_per_1k']=str(runtime.number(cost['cny_per_1k']))
        self.db.activate_generation('g',[])
        with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
            self.plan=self.db.create_plan('revenue_sprint',['base:console','base:pc'],engine.current_action(self.data))
            self.plan=self.db.activate_plan(self.plan['plan_id'],now=NOW)
        self.patches=[patch.object(runtime,'ledger',return_value=self.db),patch.object(runtime,'ROOT',self.root),
                      patch.object(runtime,'clock',return_value=NOW),patch.object(api,'ledger',return_value=self.db)]
        for item in self.patches:item.start();self.addCleanup(item.stop)

    def save(self,**changes):
        old=self.db.price_control()
        body={key:old[key] for key in ('manual_enabled','manual_prices','uplift_enabled','uplift_pct')}
        body.update(expected_revision=old['revision'],request_key='settings'+str(old['revision']),**changes)
        return api.post('price-control',body,'wulv')['settings']

    def quote(self):return runtime.calculate(self.data)

    def verify(self,result):
        return runtime.verify_quote(dict(evidence=self.data,result=result),dict(minimum_gross_margin_pct='20'),['PS','XBOX','PC'],now=NOW)

    def test_default_switches_preserve_strategy_and_plan(self):
        result=self.quote();self.verify(result)
        self.assertEqual(result['decision_receipt']['price_control']['revision'],0)
        self.assertEqual(self.db.get('pricing_plans',self.plan['plan_id']),self.plan)

    def test_uplift_uses_selected_price_once_and_off_restores_strategy(self):
        before=self.quote()['decision_receipt']['action']
        self.save(uplift_enabled=True,uplift_pct='10')
        for _ in range(2):
            result=self.quote();receipt=result['decision_receipt'];self.verify(result)
            for group in engine.GROUPS:
                self.assertEqual(Decimal(receipt['action']['base_prices'][group]),
                    (Decimal(before['base_prices'][group])*Decimal('1.1')).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
            self.assertEqual(receipt['strategy_action'],before)
            self.assertEqual(receipt['decision_type'],'temporary_uplift')
            self.assertFalse(receipt['randomization_verified'])
        self.save(uplift_enabled=False)
        self.assertEqual(self.quote()['decision_receipt']['action'],before)

    def test_manual_wins_skips_strategy_and_does_not_need_competitor(self):
        self.save(manual_enabled=True,manual_prices=dict(console='.2',pc='.22'),uplift_enabled=True,uplift_pct='10')
        self.data['offers']={p:{} for p in engine.PLATFORMS}
        with patch.object(runtime,'evaluate',side_effect=AssertionError('manual must not run strategies')):
            result=self.quote()
        self.verify(result)
        receipt=result['decision_receipt']
        self.assertEqual(receipt['action']['base_prices'],dict(console='20.00',pc='22.00'))
        self.assertIsNone(receipt['strategy_action']);self.assertEqual(receipt['decision_type'],'manual_intervention')
        self.assertEqual(self.db.get('pricing_plans',self.plan['plan_id']),self.plan)
        self.data['storefront']['status']='ok'
        for p,row in self.data['storefront']['rows'].items():row.update(status='ok',platform=p,base_k='100')
        script="const fs=require('node:fs'),logic=require(process.argv[1]);logic.buildPreview(JSON.parse(fs.readFileSync(0,'utf8')),Date.parse(process.argv[2]));"
        check=subprocess.run(['node','-e',script,str(SOURCE/'repricing_logic.js'),NOW.isoformat()],
            input=json.dumps(dict(evidence=self.data,result=result)),text=True,encoding='utf-8',capture_output=True,timeout=15)
        self.assertEqual(check.returncode,0,check.stderr)

    def test_manual_off_resumes_strategy_then_saved_uplift(self):
        strategy=self.quote()['decision_receipt']['action']
        self.save(manual_enabled=True,manual_prices=dict(console='.2',pc='.22'),uplift_enabled=True,uplift_pct='10')
        self.quote();self.save(manual_enabled=False)
        receipt=self.quote()['decision_receipt']
        self.assertEqual(receipt['strategy_action'],strategy)
        self.assertEqual(receipt['decision_type'],'temporary_uplift')

    def test_daily_uplift_reproves_against_frozen_plan_anchor(self):
        self.plan.update(mode='daily',parameters={},price_anchor=dict(base_prices=dict(console='16',pc='18'),region_coefficients={}))
        self.db.put('pricing_plans',self.plan['plan_id'],self.plan)
        self.save(uplift_enabled=True,uplift_pct='10')
        self.verify(self.quote())

    def test_price_control_never_bypasses_financial_or_fx_freshness(self):
        self.save(manual_enabled=True,manual_prices=dict(console='.0001',pc='.0001'))
        with self.assertRaisesRegex(ValueError,'margin_floor'):self.quote()
        self.save(manual_prices=dict(console='.2',pc='.22'))
        self.data['fx']['checked_at']='2020-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):self.quote()

    def test_only_plan_owned_groups_are_changed(self):
        self.plan['resources']=['base:pc'];self.db.put('pricing_plans',self.plan['plan_id'],self.plan)
        self.save(manual_enabled=True,manual_prices=dict(console='.2',pc='.22'))
        receipt=self.quote()['decision_receipt']
        self.assertEqual(receipt['action']['base_prices']['console'],receipt['before_action']['base_prices']['console'])
        self.assertEqual(receipt['action']['base_prices']['pc'],'22.00')

    def test_settings_cas_idempotency_and_unknown_lease(self):
        body=dict(request_key='one',expected_revision=0,manual_enabled=False,manual_prices=dict(console=None,pc=None),uplift_enabled=True,uplift_pct='10')
        first=api.post('price-control',body,'wulv')
        self.assertEqual(api.post('price-control',body,'wulv'),first)
        with self.assertRaisesRegex(ValueError,'payload_conflict'):api.post('price-control',dict(body,uplift_pct='20'),'wulv')
        with self.assertRaisesRegex(ValueError,'revision_changed'):api.post('price-control',dict(body,request_key='two'),'wulv')
        with self.db.transaction() as conn:conn.execute("INSERT INTO resource_leases VALUES ('base:pc','unknown-original')")
        with self.assertRaisesRegex(ValueError,'resource_unresolved'):self.save(uplift_enabled=False)
        self.assertEqual(self.db.price_control()['revision'],1)

    def test_stale_quote_cannot_be_prepared_after_switch_change(self):
        receipt=self.quote()['decision_receipt']
        self.save(uplift_enabled=True,uplift_pct='10')
        with self.assertRaisesRegex(ValueError,'revision_changed'):self.db.prepare(self.plan,receipt,now=NOW)

    def test_rehashed_action_tampering_still_fails_reproof(self):
        self.save(manual_enabled=True,manual_prices=dict(console='.2',pc='.22'))
        result=deepcopy(self.quote());receipt=result['decision_receipt']
        receipt['action']['base_prices']['console']='21.00'
        receipt['sha256']=fingerprint({k:v for k,v in receipt.items() if k!='sha256'})
        with self.assertRaisesRegex(ValueError,'price_control_proof_changed'):self.verify(result)

    def test_invalid_settings_do_not_change_saved_value(self):
        for changes in [dict(manual_enabled=1),dict(uplift_enabled='false'),dict(uplift_pct='NaN'),
            dict(uplift_pct='-10'),dict(manual_enabled=True),dict(manual_prices=dict(console='.12345',pc='.2'))]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.save(**changes)
        self.assertEqual(self.db.price_control()['revision'],0)


if __name__=='__main__':unittest.main()
