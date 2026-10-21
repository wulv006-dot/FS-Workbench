import copy
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import pricing_v2 as p
import pricing_sources as s

NOW=datetime(2026,10,21,18,20,tzinfo=timezone.utc)
AT=NOW.isoformat()


def fixture():
    public={'rows':{platform:dict(platform=platform,sku_id=str(i+100),base_k='100',bonus_k='5',package_usd='20.00',status='ok',checked_at=AT) for i,platform in enumerate(('PS','XBOX','PC'))}}
    goods=[dict(id=i+100,site_id=266,gid=1327,top_cid=1,unit='K',status=1,mid=99,discount='100',unit_price='.20',
                more=dict(gold=[10,100,1000],give=[0,5,50],discount=[100,100,100])) for i in range(3)]
    envelope=s.normalize([],[],goods,public,now=NOW)
    evidence=dict(game='FC27',product='Game Coins',checked_at=AT,fx=dict(cny_per_usd='7',checked_at=AT),storefront=public,promotion_envelope=envelope,
        costs={platform:dict(platform=platform,game='FC27',product='Game Coins',record_id=str(i+1),trade_at='26-10-22 02:10:00',checked_at=AT,cny_per_1k='.7') for i,platform in enumerate(('PS','XBOX','PC'))},
        offers={platform:{'Lootbar':dict(usd_price='20',base_k='100',bonus_k='5',checked_at=AT,conditional=False,comparable=True)} for platform in ('PS','XBOX','PC')})
    rows=[dict(platform=platform,cost_cny='.7') for platform in ('PS','XBOX','PC')]
    return evidence,rows,goods


class Pricing(unittest.TestCase):
    def test_hard_10_is_not_a_model_or_operator_option(self):
        for minimum in ('0','9.99','100','NaN'):
            with self.subTest(minimum=minimum),self.assertRaises(ValueError):p.hard_floor('.7','7','1.05','.7',minimum)

    def test_rounding_cannot_print_10_and_pass_below_10(self):
        with self.assertRaisesRegex(ValueError,'pricing_hard_margin_floor'):
            p.prove_price('.1111','.7','7','100','100','1','10')
        value=p.prove_price('.1112','.7','7','100','100','1','10')
        self.assertGreaterEqual(Decimal(value['procurement_margin_pct']),10)

    def test_gifts_and_discount_raise_floor(self):
        self.assertGreater(p.hard_floor('.7','7','1.05','.7'),p.hard_floor('.7','7','1','1'))

    def test_common_pool_uses_latest_timestamp_not_lowest(self):
        e,_,_=fixture();e['costs']['PS'].update(cny_per_1k='.8',trade_at='26-10-22 02:11:00')
        cost,basis=p.common_cost(e)
        self.assertEqual(cost,Decimal('.8'));self.assertEqual(basis['selected_platform'],'PS')

    def test_simultaneous_conflict_cannot_be_averaged(self):
        e,_,_=fixture();e['costs']['PS']['cny_per_1k']='.8'
        with self.assertRaisesRegex(ValueError,'simultaneous'):p.common_cost(e)

    def test_matching_verified_pool_holds_when_competitive(self):
        e,rows,_=fixture();receipt=p.apply_decision(rows,e,{},now=NOW)
        self.assertEqual(rows[0]['proposal'],rows[1]['proposal'])
        self.assertEqual(receipt['decisions'][0]['reason'],'already_competitive_hold')
        self.assertGreaterEqual(Decimal(rows[0]['proof']['catalog']['worst_published_margin_pct']),10)

    def test_old_high_margin_is_not_a_reason_to_cut_again(self):
        e,rows,_=fixture()
        for offers in e['offers'].values():offers['Lootbar']['usd_price']='25'
        p.apply_decision(rows,e,{},now=NOW)
        self.assertEqual(rows[0]['main_page_usd'],'20.00')

    def test_unifying_different_console_prices_is_not_labelled_hold(self):
        e,rows,_=fixture();e['storefront']['rows']['PS']['package_usd']='18.00'
        receipt=p.apply_decision(rows,e,{},now=NOW)
        self.assertEqual(receipt['decisions'][0]['reason'],'unify_common_console_base')
        self.assertGreater(Decimal(rows[0]['change_pct']),0)
        self.assertEqual(rows[0]['proposal'],rows[1]['proposal'])

    def test_only_small_needed_change_to_parity(self):
        e,rows,_=fixture()
        for offers in e['offers'].values():offers['Lootbar']['usd_price']='19.5'
        p.apply_decision(rows,e,{},now=NOW)
        self.assertEqual(rows[0]['main_page_usd'],'19.50')

    def test_manual_and_hermes_cannot_cross_hard_floor(self):
        e,rows,_=fixture()
        with self.assertRaisesRegex(ValueError,'hard_margin_floor'):
            p.apply_decision(rows,e,{'quotes':dict(PS='.01',XBOX='.01')},now=NOW)

    def test_manual_console_split_rejected(self):
        e,rows,_=fixture()
        for edits in ({'quotes':{'PS':'.2'}},{'quotes':{'PS':'.2','XBOX':'.21'}}):
            with self.assertRaisesRegex(ValueError,'common_console'):p.apply_decision(rows,e,edits,now=NOW)

    def test_cost_source_cannot_be_edited_down(self):
        e,rows,_=fixture()
        with self.assertRaisesRegex(ValueError,'source_edit'):p.apply_decision(rows,e,{'costs':{'PS':'.01'}},now=NOW)

    def test_stale_and_tampered_promotions_rejected(self):
        e,rows,_=fixture();e['promotion_envelope']['minimum_retained_ratio']='1'
        with self.assertRaisesRegex(ValueError,'hash_changed'):p.apply_decision(rows,e,{},now=NOW)
        e,rows,_=fixture()
        with self.assertRaisesRegex(ValueError,'stale'):p.apply_decision(rows,e,{},now=NOW+timedelta(minutes=16))

    def test_legal_coupon_code_stack_and_single_coupon(self):
        e,_,goods=fixture()
        code=dict(id=1,status=1,site_id=266,gid='1327',type=1,discount='90',attain='0')
        coupon=dict(id=2,status=1,site_id=266,game_id=1327,product_type=1,type=1,mode_type=2,reduce='70',time_effect=2,is_open=0)
        single=s.normalize([code],[coupon],goods,e['storefront'],now=NOW)
        self.assertEqual(Decimal(single['minimum_retained_ratio']),Decimal('.65'))
        coupon['is_open']=1
        stack=s.normalize([code],[coupon],goods,e['storefront'],now=NOW)
        self.assertEqual(Decimal(stack['minimum_retained_ratio']),Decimal('.55'))

    def test_fixed_coupon_is_unknown_not_zero(self):
        e,_,goods=fixture()
        coupon=dict(id=2,status=1,site_id=266,game_id=1327,product_type=1,type=1,mode_type=1,reduce='5',time_effect=2,is_open=0)
        with self.assertRaisesRegex(ValueError,'mode_unverified'):s.normalize([],[coupon],goods,e['storefront'],now=NOW)

    def test_only_unissued_backend_directed_templates_are_ineligible(self):
        e,_,goods=fixture()
        coupon=dict(id=1259,status=1,site_id=0,game_id=0,product_type=0,type=1,mode_type=1,
                    reduce='20',time_effect=1,is_open=0,start_time=0,end_time=0,fetch_scene=4,fetch_qty=0,used_qty=0)
        result=s.normalize([],[coupon],goods,e['storefront'],now=NOW)
        self.assertEqual(result['coupon_count'],0)
        self.assertEqual(result['unissued_directed_templates'][0]['id'],'1259')
        coupon['fetch_qty']=1
        with self.assertRaisesRegex(ValueError,'mode_unverified'):s.normalize([],[coupon],goods,e['storefront'],now=NOW)

    def test_other_game_or_expired_coupon_does_not_inflate_floor(self):
        e,_,goods=fixture()
        coupon=dict(id=2,status=1,site_id=266,game_id=999,product_type=1,type=1,mode_type=1,reduce='100',time_effect=2,is_open=0)
        self.assertEqual(s.normalize([],[coupon],goods,e['storefront'],now=NOW)['coupon_count'],0)

    def test_catalog_checks_small_custom_rounding_and_large_gift_packages(self):
        e,_,_=fixture();rules=e['promotion_envelope']['packages']['PS'];ratio=Decimal('.7')
        floor=p.catalog_floor('.7','7',ratio,'10',rules)
        proof=p.prove_catalog(floor,'.7','7',ratio,'10',rules)
        self.assertEqual(proof['published_packages'],3)
        for q in (10,11,99,100,101,1000,9999):
            result=p.prove_price(floor,'.7','7',Decimal(q)*Decimal('1.05'),str(q),ratio,'10')
            self.assertGreaterEqual(Decimal(result['procurement_margin_pct']),10)

    def test_no_source_price_or_gift_drift_can_hide_in_catalog(self):
        e,_,goods=fixture();goods[0]['more']['give'][1]=10
        with self.assertRaisesRegex(ValueError,'bonus_mismatch'):s.normalize([],[],goods,e['storefront'],now=NOW)

    def test_receipt_and_result_tampering_rejected(self):
        e,rows,_=fixture();edits={'minimum_gross_margin_pct':'10'}
        receipt=p.apply_decision(rows,e,edits,now=NOW)
        quote=dict(evidence=e,edits=edits,result=dict(rows=rows,decision_receipt=receipt))
        p.verify_quote(quote,dict(minimum_gross_margin_pct='10'),['PS','XBOX'],now=NOW)
        quote['result']['rows'][0]['proposal']='.0001'
        with self.assertRaisesRegex(ValueError,'tampered'):p.verify_quote(quote,dict(minimum_gross_margin_pct='10'),['PS','XBOX'],now=NOW)

    def test_tail_has_its_own_combined_budget(self):
        main=Decimal('10.09');checks=[(Decimal(100),Decimal(105),Decimal('.35'),Decimal(7),Decimal('.7'),'10')]
        target,status=p.ending(main,checks)
        self.assertEqual(target,Decimal('9.99'));self.assertEqual(status,'accepted')
        target,status=p.ending(Decimal('10.10'),checks)
        self.assertEqual(target,Decimal('10.10'));self.assertEqual(status,'ending_budget')


if __name__=='__main__':unittest.main()
