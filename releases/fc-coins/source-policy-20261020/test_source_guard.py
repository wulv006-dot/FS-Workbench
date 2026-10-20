import sys, unittest, copy, itertools
from pathlib import Path
from decimal import Decimal
sys.path.insert(0,str(Path(__file__).parent/'source'))
from automation_policy import check_write, initial_policy
from fc27_quote_engine import calculate, source_coverage
PLATFORMS=('PS','XBOX','PC')
def fixture(sites=('U4GM','IGGM','U7Buy'),cost='0.40'):
    policy=initial_policy();policy.update(system_enabled=True,mode='auto',revision=1)
    source={'game':'FC27','product':'coins','fx':{'cny_per_usd':'8'},
        'costs':{p:{'cny_per_1k':cost} for p in PLATFORMS},
        'storefront':{'rows':{p:{'base_k':'100','bonus_k':'5','package_usd':'10.00'} for p in PLATFORMS}},
        'offers':{p:{s:{'usd_price':price,'base_k':'100','bonus_k':'5'}
                 for s,price in [('Lootbar','10.00'),('U4GM','8.50'),('IGGM','8.80'),('U7Buy','9.00')]
                 if s=='Lootbar' or s in sites} for p in PLATFORMS}}
    return policy,source

def quote(source):
    return {'automation_policy_revision':1,'edits':{},'evidence':source,'result':calculate(source)}

class SourceGuard(unittest.TestCase):
    def test_all_reference_combinations_match_writer(self):
        for n in range(4):
            for sites in itertools.combinations(('U4GM','IGGM','U7Buy'),n):
                with self.subTest(sites=sites):
                    p,e=fixture(sites);q=quote(e)
                    for platform in PLATFORMS:self.assertEqual(check_write(p,q,[platform],automatic=True),[])
    def test_fallback_precedence(self):
        for sites,expected in [(('U4GM','U7Buy'),['U4GM']),(('IGGM','U7Buy'),['IGGM']),
                               (('U7Buy',),['U7Buy']),((),[])]:
            p,e=fixture(sites);self.assertEqual(quote(e)['result']['rows'][0]['reference_sources'],expected)
    def test_parity_zero_discount_in_every_margin_band(self):
        for cost in ('0.40','0.50','0.55','0.60','0.65'):
            p,e=fixture((),cost);q=quote(e)
            for row in q['result']['rows']:
                self.assertEqual(row['requested_discount_pct'],'0.00')
                self.assertEqual(row['target_page_usd'],'9.53')
                self.assertEqual(check_write(p,q,[row['platform']],automatic=True),[])
    def test_missing_lootbar_rejected(self):
        p,e=fixture();del e['offers']['PS']['Lootbar'];q=quote(e)
        self.assertIsNone(q['result']['rows'][0]['proposal'])
    def test_invalid_optional_reference_falls_back_to_parity(self):
        for override in ({'usd_price':'bad'},{'usd_price':'0'},{'usd_price':'8.123'},
                         {'base_k':'90'},{'bonus_k':'101'},{'conditional':True}):
            with self.subTest(override=override):
                p,e=fixture(('IGGM',))
                for offers in e['offers'].values():offers['IGGM'].update(override)
                q=quote(e)
                self.assertEqual(q['result']['rows'][0]['requested_discount_pct'],'0.00')
                self.assertEqual(check_write(p,q,['PS'],automatic=True),[])
    def test_tampered_price_rejected(self):
        p,e=fixture();q=quote(e);q['result']['rows'][0].update(proposal='0.0899',target_page_usd='8.99')
        with self.assertRaisesRegex(ValueError,'automatic_tier_rule'):check_write(p,q,['PS'],automatic=True)
    def test_off_and_missing_cost_are_not_bypassed(self):
        p,e=fixture();q=quote(e);p['system_enabled']=False
        with self.assertRaisesRegex(ValueError,'automation_system_off'):check_write(p,q,['PS'],automatic=True)
        del e['costs']['PS'];self.assertIsNone(quote(e)['result']['rows'][0]['proposal'])
    def test_profit_floor_overrides_parity(self):
        p,e=fixture((),'0.90');q=quote(e)
        self.assertTrue(q['result']['rows'][0]['profit_floor_applied'])
        self.assertGreater(Decimal(q['result']['rows'][0]['target_page_usd']),Decimal('9.53'))
        self.assertEqual(check_write(p,q,['PS'],automatic=True),[])
    def test_complete_coverage_required_even_when_reference_missing(self):
        rows=[{'platform':p,'source':s,'status':'valid' if s=='Lootbar' else 'missing'} for p in PLATFORMS for s in ('Lootbar','U4GM','IGGM','U7Buy')]
        self.assertTrue(source_coverage(rows)['ready'])
        with self.assertRaises(ValueError):source_coverage(rows[:-1])
        rows[0]['status']='missing';self.assertFalse(source_coverage(rows)['ready'])

if __name__=='__main__':unittest.main()
