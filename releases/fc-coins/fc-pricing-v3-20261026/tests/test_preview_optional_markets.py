"""The original Node preview accepts financially verified V3 fallback quotes."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
sys.path.insert(0,str(SOURCE))
from test_bidirectional_markets import evidence
from test_dual20_sprint import NOW
from fc_pricing_v3 import engine,runtime
from fc_pricing_v3.ledger import Ledger


@unittest.skipUnless(shutil.which('node'),'requires Node for the original backend preview')
class PreviewOptionalMarkets(unittest.TestCase):
    def payload(self,arab=True):
        data=evidence();data['offers']={p:{} for p in engine.PLATFORMS}
        if not arab:data['arab_ut_quotes']=[]
        data['storefront']['status']='ok'
        for p,row in data['storefront']['rows'].items():row.update(status='ok',platform=p,base_k='100',checked_at=NOW.isoformat())
        for cost in data['costs'].values():cost['cny_per_1k']=str(runtime.number(cost['cny_per_1k']))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);db=Ledger(root/'control.db');db.activate_generation('g',[])
            with patch('fc_pricing_v3.ledger.clock',return_value=NOW):
                base=db.create_plan('revenue_sprint',['base:console','base:pc'],engine.current_action(data));db.activate_plan(base['plan_id'],now=NOW)
                plan=db.create_plan('smart',['base:console','base:pc'],engine.current_action(data),starts_at=(NOW-timedelta(days=2)).isoformat())
                db.activate_plan(plan['plan_id'],now=NOW);db.migrate_smart_strategy(plan['plan_id'],1,'wulv')
            with patch.object(runtime,'ledger',return_value=db),patch.object(runtime,'ROOT',root),patch.object(runtime,'clock',return_value=NOW):
                result=runtime.calculate(data)
                runtime.verify_quote(dict(evidence=data,result=result),dict(minimum_gross_margin_pct='20'),list(engine.PLATFORMS),now=NOW)
        return dict(evidence=data,result=result)

    def preview(self,payload):
        script="const fs=require('node:fs'),logic=require(process.argv[1]),x=JSON.parse(fs.readFileSync(0,'utf8'));console.log(JSON.stringify(logic.buildPreview(x.payload,Date.parse(x.now))));"
        return subprocess.run(['node','-e',script,str(SOURCE/'repricing_logic.js')],input=json.dumps(dict(payload=payload,now=NOW.isoformat())),capture_output=True,text=True,encoding='utf-8',timeout=15)

    def test_missing_lootbar_with_verified_independent_arab_anchors_previews(self):
        payload=self.payload();receipt=payload['result']['decision_receipt']
        self.assertTrue(receipt['financial_proof']['pass_all'])
        self.assertEqual({anchor['source'] for market in receipt['market_comparison'].values() for anchor in market['anchors'].values()},{'ArabUT'})
        result=self.preview(payload)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual([row['platform'] for row in json.loads(result.stdout)['targets']],['PS','XBOX','PC'])
        self.assertEqual([row['id'] for row in json.loads(result.stdout)['targets']],['21942','21944','21946'])

    def test_both_missing_with_original_legal_financial_floor_previews(self):
        payload=self.payload(arab=False);receipt=payload['result']['decision_receipt']
        self.assertTrue(receipt['financial_proof']['pass_all'])
        self.assertEqual({m['decision_type'] for m in receipt['market_comparison'].values()},{'floor_fallback'})
        result=self.preview(payload);self.assertEqual(result.returncode,0,result.stderr)

    def test_present_bad_offer_and_original_cost_or_price_checks_still_reject(self):
        payload=self.payload()
        for mutation in ('currency','expired','cost','price','legacy','financial'):
            changed=deepcopy(payload)
            if mutation in ('currency','expired'):
                changed['evidence']['offers']['PS']['Lootbar']=dict(usd_price='9',base_k='100',bonus_k='0',checked_at=NOW.isoformat(),currency='USD')
                if mutation=='currency':changed['evidence']['offers']['PS']['Lootbar']['currency']='SAR'
                else:changed['evidence']['offers']['PS']['Lootbar']['checked_at']=(NOW-timedelta(hours=2)).isoformat()
            elif mutation=='cost':changed['result']['rows'][0]['raw_cost_cny']='999'
            elif mutation=='price':changed['result']['rows'][0]['proposal']='0'
            elif mutation=='financial':changed['result']['decision_receipt']['financial_proof']['pass_all']=False
            else:changed['result']['decision_receipt']['strategy_parameters'].pop('competitor_policy')
            with self.subTest(mutation=mutation):self.assertNotEqual(self.preview(changed).returncode,0)


if __name__=='__main__':unittest.main()
