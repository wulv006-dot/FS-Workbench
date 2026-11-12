"""New plans use primary Lootbar, independent ArabUT fallback and global regions."""
import ast
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from test_dual20_sprint import source, NOW
from test_optional_competitors import missing
from fc_pricing_v3 import engine


POLICY = 'lootbar_primary_arabut_secondary_v1'


def plan(mode='revenue_sprint'):
    return dict(mode=mode, resources=['base:PS','base:XBOX', 'base:PC', 'region:21:PS'],
                parameters=dict(competitor_policy=POLICY, region_pricing='global'))


def evidence():
    data = source(loot='10', item='1', cost='.10', bonus='0')
    data['arab_ut_quotes'] = [dict(source='ArabUT', platform=p, region_id=21,
        source_region_id=21, reference_scope='global', total_usd='9.47' if p=='PC' else '8.61',
        purchase_k='100', bonus_k='0', currency='USD', captured_at=NOW.isoformat(),
        delivery='standard' if p=='PC' else 'normal', selection_verified=True)
        for p in engine.PLATFORMS]
    return data


class BidirectionalMarkets(unittest.TestCase):
    def projected_source(self, currency='USD'):
        # Exercise the production projection and its USD guard, not a hand-built engine row.
        path=Path(__file__).resolve().parents[1]/'source/server_quote_job.py'
        fn=next(n for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef) and n.name=='_quote_for_run')
        projection=next(n for n in fn.body if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='offer')
        from server_quote_job import age_ok
        rows=[dict(run_id='same',source='Lootbar',platform=p,status='valid',purchase_k='100',bonus_k='5',
                   gross_usd='8.25' if p!='PC' else '7.88',captured_at=NOW.isoformat(),url='https://www.lootbar.com/game-coins/fc27',
                   conditional=False,comparable=True) for p in engine.PLATFORMS]
        if currency is not None:
            for row in rows:row['currency']=currency
        data=evidence()
        scope=dict(snapshot=dict(competitors=rows),planned=dict(required_markets=['Lootbar','ArabUT']),
            PLATFORMS=engine.PLATFORMS,SITES=('Lootbar',),offers={p:{} for p in engine.PLATFORMS},
            run_id='same',now=NOW,age_ok=age_ok)
        exec(compile(ast.Module(body=[projection],type_ignores=[]),str(path),'exec'),scope)
        data['offers']=scope['offers']
        return data

    def test_verified_lootbar_USD_survives_real_quote_projection_and_remains_primary(self):
        data=self.projected_source()
        self.assertTrue(all(data['offers'][p]['Lootbar'].get('currency')=='USD' for p in engine.PLATFORMS))
        quotes,gaps=engine.current_market_quotes(data,engine.PLATFORMS,NOW,plan=plan())
        self.assertEqual(gaps,[])
        anchors={p:engine.resolve_anchor(data,p,quotes,NOW,plan=plan()) for p in engine.PLATFORMS}
        self.assertEqual({row['source'] for row in anchors.values()},{'Lootbar'})
        self.assertEqual(Decimal(anchors['PC']['unit_100k']),Decimal('7.88')/Decimal('105')*100)

    def test_quote_projection_never_assigns_USD_to_missing_or_non_USD_source_currency(self):
        for currency in (None,'SAR','EUR'):
            with self.subTest(currency=currency):
                data=self.projected_source(currency)
                self.assertTrue(all(not data['offers'][p] for p in engine.PLATFORMS))
                quotes,gaps=engine.current_market_quotes(data,engine.PLATFORMS,NOW,plan=plan())
                self.assertEqual({engine.resolve_anchor(data,p,quotes,NOW,plan=plan())['source'] for p in engine.PLATFORMS},{'ArabUT'})
                self.assertEqual({gap['source'] for gap in gaps},{'Lootbar'})

    def test_lootbar_wins_lower_arab_and_item_without_altering_legacy(self):
        data=evidence()
        market=engine.competition(data, engine.PLATFORMS, NOW, plan=plan())
        self.assertEqual({a['source'] for a in market['anchors'].values()}, {'Lootbar'})
        self.assertEqual({q['source'] for q in market['quotes']}, {'Lootbar', 'ArabUT'})
        self.assertEqual(engine.competition(data, ['PS'], NOW)['anchors']['PS']['source'], 'Lootbar')

    def test_missing_loot_uses_independent_pc_standard_arab_with_source_region(self):
        data=evidence();missing(data, 'Lootbar')
        market=engine.competition(data, engine.PLATFORMS, NOW, plan=plan())
        self.assertEqual(market['anchors']['PS']['source'], 'ArabUT')
        self.assertEqual(Decimal(market['anchors']['PC']['unit_100k']), Decimal('9.47'))
        pc=next(q for q in market['quotes'] if q['platform']=='PC')
        self.assertEqual(pc['source_region_id'], 21)
        self.assertEqual(pc['delivery'], 'standard')

    def test_invalid_arab_pc_never_borrows_console_or_item(self):
        for change in ({'delivery':'normal'}, {'selection_verified':False}, {'currency':'SAR'},
                       {'source':'Lootbar'}, {'purchase_k':'200'},
                       {'captured_at':(NOW-timedelta(seconds=901)).isoformat()}):
            with self.subTest(change=change):
                data=evidence();missing(data, 'Lootbar', ['PC'])
                data['arab_ut_quotes'][-1].update(change)
                market=engine.competition(data, ['PC'], NOW, plan=plan())
                self.assertIsNone(market['anchors']['PC']['source'])
                self.assertEqual(market['decision_type'], 'floor_fallback')
                self.assertTrue(any(g['source']=='ArabUT' for g in market['source_gaps']))

    def test_pc_quote_must_be_unique_and_platform_must_match(self):
        for duplicate in (True, False):
            data=evidence();missing(data, 'Lootbar', ['PC'])
            if duplicate:data['arab_ut_quotes'].append(deepcopy(data['arab_ut_quotes'][-1]))
            else:data['arab_ut_quotes'][-1]['platform']='PS'
            self.assertIsNone(engine.competition(data, ['PC'], NOW, plan=plan())['anchors']['PC']['source'])

    def test_lootbar_wrong_source_platform_or_currency_cannot_override_arab(self):
        for change in ({'source':'ArabUT'}, {'platform':'PC'}, {'currency':'SAR'},
                       {'currency':'SAR', 'fx_version':'unverified-label'}):
            with self.subTest(change=change):
                data=evidence();data['offers']['PS']['Lootbar'].update(change)
                self.assertEqual(engine.competition(data, ['PS'], NOW, plan=plan())['anchors']['PS']['source'], 'ArabUT')

    def test_console_fast_does_not_hide_normal_and_pc_cannot_replace_console(self):
        data=evidence();missing(data, 'Lootbar')
        data['arab_ut_quotes'].insert(0,dict(data['arab_ut_quotes'][0], delivery='fast'))
        self.assertEqual(Decimal(engine.competition(data, ['PS'], NOW, plan=plan())['anchors']['PS']['unit_100k']), Decimal('8.61'))
        data['arab_ut_quotes']=[r for r in data['arab_ut_quotes'] if r['platform']=='PC']
        self.assertIsNone(engine.competition(data, ['PS'], NOW, plan=plan())['anchors']['PS']['source'])

    def test_auxiliary_item_age_and_low_price_do_not_change_or_block_candidates(self):
        data=evidence();other=deepcopy(data)
        for row in other['reference_market']['offers']:
            row.update(captured_at=(NOW-timedelta(seconds=600)).isoformat(), gross_usd='.01')
        a=engine.evaluate(data, 'revenue_sprint', plan=plan(), now=NOW)
        b=engine.evaluate(other, 'revenue_sprint', plan=plan(), now=NOW)
        self.assertIsNotNone(a['selected'], a['failures'])
        self.assertEqual([c['action'] for c in a['candidates']], [c['action'] for c in b['candidates']])

    def test_new_daily_uses_arab_target_legacy_keeps_item(self):
        data=evidence();missing(data, 'Lootbar')
        selected=engine.evaluate(data, 'daily', plan=plan('daily'), now=NOW)['selected']
        self.assertIsNotNone(selected)
        self.assertEqual(selected['daily_reference']['PC']['source'], 'ArabUT')
        self.assertEqual(selected['daily_pricing']['PC']['basis'], 'arabut_actual_delivery_target')
        self.assertEqual(selected['daily_pricing']['PC']['driver_source'], 'ArabUT')
        self.assertIn('ARABUT', selected['decision_reason'])
        self.assertEqual(engine.daily_reference(data, ['PC'], NOW)['PC']['source'], 'ArabUT')

    def test_new_daily_both_missing_uses_average30_not_item(self):
        data=evidence();missing(data, 'Lootbar');data['arab_ut_quotes']=[]
        result=engine.evaluate(data, 'daily', plan=plan('daily'), now=NOW)
        selected=result['selected'];self.assertIsNotNone(selected, result['failures'])
        self.assertEqual(selected['daily_reference']['PC']['average_margin_target_pct'], '30')
        self.assertEqual(selected['daily_pricing'], {})
        self.assertGreaterEqual(Decimal(selected['daily_average_target_proof']['PC']['scopes']['global:PC']['estimated_average_margin_pct']), 30)

    def test_global_region_one_without_arab_region_requirement_or_price_discount(self):
        data=evidence();data['arab_ut_quotes']=[]
        control=dict(id=3, region_id=21, platforms=['PS'], factor='1', resource='region:21:PS',
            verified=True, rounding='half_up_cent', price_semantics='regional_regular_multiplicative',
            history=dict(by_platform={p:dict(basis='platform_other_promotions_excluding_region_verified') for p in engine.PLATFORMS}))
        data['region_rules']=[control];data['regional_controls']=[control]
        global_market=engine.competition(data, ['PS', 'XBOX'], NOW, plan=plan())
        regional=engine.competition(data, ['PS'], NOW, region=21, plan=plan(),
                                    resolved_global=global_market, base_total='9.70')
        self.assertEqual(regional['legal_coefficients'], ['1'])
        self.assertEqual(regional['decision_type'], 'regional_follow_global')
        self.assertEqual(regional['reason'], 'USER_GLOBAL_PRICING_FOLLOW_GLOBAL')
        self.assertEqual(regional['regional_fallbacks'], {})
        selected=engine.evaluate(data, 'revenue_sprint', plan=plan(), now=NOW)['selected']
        self.assertEqual(selected['action']['region_coefficients']['21:PS'], '1')
        data['regional_controls'][0]['factor']='.97'
        daily=engine.evaluate(data, 'daily', plan=plan('daily'), now=NOW)
        self.assertIsNotNone(daily['selected'], daily['failures'])
        self.assertEqual(daily['selected']['action']['region_coefficients']['21:PS'], '1')
        self.assertEqual(data['regional_controls'][0]['factor'], '.97')


if __name__=='__main__':unittest.main()
