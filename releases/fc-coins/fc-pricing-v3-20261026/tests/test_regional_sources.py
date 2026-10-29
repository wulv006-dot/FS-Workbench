"""Actual source builder -> regional financial gate; public requests are anonymous local fixtures."""
from concurrent.futures import Future
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs

SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3 import regional_public, sources, business_source, region_source, engine
from fc_pricing_v3.financial import fingerprint
from fixtures import set_console_cost

AIDS = {'PS': 21587, 'XBOX': 21585, 'PC': 21589}
SKUS = {'PS': 163329311, 'XBOX': 163329277, 'PC': 163329345}


def products():
    return {p: dict(id=SKUS[p], site_id=266, gid=1327, top_cid=1, cid=9623, sid=7645, aid=AIDS[p], unit='K') for p in AIDS}


class Response:
    def __init__(self, body, url): self.body, self.url = body, url
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, *args): return self.body
    def geturl(self): return self.url


class PublicOpener:
    def __init__(self, code, *, wrong_context=False, factors=None, transform=None):
        self.code, self.wrong_context, self.factors = code, wrong_context, factors or {}
        self.transform=transform
    def open(self, request, **kwargs):
        if request.data is None:
            code, currency = ('uk', 'EUR') if self.wrong_context else (self.code, 'USD')
            text = '<a class="lang-currency"><span>' + code.upper() + '</span> | <span class="currency">' + currency + '</span></a><script>const currencyCode = "' + currency + '"; const GV={valuta: currencyCode ? {"code":"' + currency + '","rate":1} : ""}; /*1327 9623*/</script>'
            return Response(text.encode(), 'https://www.mmoexp.com/' + code + '/Fc-27/Coins.html?cy=' + currency)
        aid = int(parse_qs(request.data.decode())['aid'][0])
        platform = next(p for p in AIDS if AIDS[p] == aid)
        factor = self.factors.get(platform, '.91' if self.code == 'uk' else '1')
        row = dict(products()[platform], _region_factor=factor,
            goods_list={'100': dict(num=100, price_discount=str(Decimal('20') * Decimal(factor)), give=5)})
        if self.transform:self.transform(row)
        return Response(json.dumps(dict(goods=dict(index=dict(list=[row])))).encode(), 'https://www.mmoexp.com/ajax/goods')


class InlinePool:
    def __init__(self, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def submit(self, function, *args, **kwargs):
        future = Future()
        try: future.set_result(function(*args, **kwargs))
        except Exception as error: future.set_exception(error)
        return future


class RegionalSourceEvidenceTest(unittest.TestCase):
    def context(self,rules,ar_factors=None,transform=None):
        data=json.loads(Path(__file__).with_name('fixture.json').read_text(encoding='utf-8-sig'))
        from datetime import datetime
        now=datetime.fromisoformat(data['now'])
        evidence=deepcopy(data['fixture'][0]);set_console_cost(evidence)
        for platform in AIDS:
            evidence['storefront']['rows'][platform].update(sku_id=str(SKUS[platform]),package_usd='20')
        history=dict(status='verified',basis_lower_bound_sufficient=True,paths=[dict(weight_usd='1',
            denominator_basis='regional_regular',promotion_path_excludes_region=True,promotion_path=dict(kind='none'))],source_sha256='a'*64)
        auth=SimpleNamespace(Session=Mock,admin_token_from_service=lambda:('local-fixture','ok'))
        channel=SimpleNamespace(pages=lambda *args:list(products().values()),COLLECTOR='/fixture/collector')
        original_public=regional_public.collect
        def public(code,region,**kwargs):
            with patch.object(regional_public,'build_opener',return_value=PublicOpener(code,factors=ar_factors if code=='ar' else None)):
                result=original_public(code,region,**kwargs)
            if transform:transform(result)
            return result
        with patch.dict(sys.modules,{'channel_source':channel,'p2pah_auth':auth}),patch.object(region_source,'read_rules',return_value=rules),patch.object(business_source,'collect',return_value=dict(history_replay=history,learning_coverage={'status':'await_first_confirmed_exposure'})),patch.object(regional_public,'collect',side_effect=public),patch('concurrent.futures.ThreadPoolExecutor',InlinePool):
            result=sources.shared_context(evidence['storefront'],dict(status='available',offers=[],same_run='preserved'),price_windows=[])
        evidence.update(result)
        return result,evidence,now

    @staticmethod
    def rule(**changes):
        return dict(dict(id=77,site_id=266,lang_region_id=21,goods_id=0,gid=1327,top_cid=1,
            cid=0,sid=7645,aid=21587,factor='.9500',status=1),**changes)

    def test_actual_UK_EUR_response_cannot_be_labelled_ar_USD_verified(self):
        with patch.object(regional_public, 'build_opener', return_value=PublicOpener('ar', wrong_context=True)):
            try:
                result = regional_public.collect('ar', 21)
            except ValueError:
                return
        self.assertFalse(result.get('status') == 'verified' and any(row.get('selection_verified') for row in result.get('offers', {}).values()),
            'Actual redirect/header are UK/EUR, but requested ar/USD was promoted to verified public evidence')

    def test_public_backend_factor_mismatch_is_rejected_by_actual_financial_consumer(self):
        context,evidence,now=self.context([self.rule()],{'PS':'.90'})
        self.assertIs(context['region_rules'][0]['verified'],False)
        self.assertIs(context['regional_controls'][0]['verified'],False)
        before = dict(base_prices=dict(console='20', pc='20'), region_coefficients={'21:PS': '.9500', '21:XBOX': '1', '21:PC': '1'})
        after = deepcopy(before); after['region_coefficients']['21:PS'] = '.9400'
        impacted = engine.impacted_regions(evidence, before, after)
        with self.assertRaisesRegex(ValueError, 'region.*unverified|region.*mismatch'):
            engine.financial(evidence, after, now, regions=impacted)

    def test_matching_existing_rule_and_default_one_pass_actual_financial(self):
        context,evidence,now=self.context([self.rule()],{'PS':'.95'})
        self.assertTrue(all(c['verified'] for c in context['regional_controls']))
        self.assertEqual(context['arab_ut_status']['same_run'],'preserved')
        self.assertEqual(context['learning_coverage']['status'],'await_first_confirmed_exposure')
        action=dict(base_prices=dict(console='20',pc='20'),region_coefficients={'21:PS':'.94','21:XBOX':'.99','21:PC':'.99'})
        result=engine.financial(evidence,action,now,regions=context['regional_controls'])
        self.assertTrue(result['pass_all'])
        self.assertIn('21:PS',result['prices'])

    def test_default_one_requires_actual_public_factor_one(self):
        context,_,_=self.context([],{'PS':'.90'})
        self.assertFalse(context['regional_controls'][0]['verified'])
        self.assertTrue(context['regional_controls'][1]['verified'])
        self.assertIsNone(context['regional_controls'][0]['id'])

    def test_unrelated_category_rule_does_not_match_coins_or_suppress_default(self):
        context,_,_=self.context([self.rule(cid=9999)])
        self.assertEqual(context['region_rules'],[])
        self.assertTrue(all(c['verified'] for c in context['regional_controls']))

    def test_current_control_preserves_complete_existing_scope(self):
        rule=self.rule(goods_id=SKUS['PS'],cid=9623)
        context,_,_=self.context([rule],{'PS':'.95'})
        self.assertEqual(context['regional_controls'][0]['scope'],{k:rule[k] for k in region_source.SCOPE_FIELDS})

    def test_true_selection_label_alone_cannot_replace_context_or_full_sku_trace(self):
        def corrupt(result):
            if result['region_id']==21:
                result['offers']['PS']['product_scope']['sid']=999
        context,_,_=self.context([],transform=corrupt)
        self.assertFalse(context['regional_controls'][0]['verified'])

    def test_public_goods_native_scope_is_checked_before_verification(self):
        for field,value in (('cid',999),('id',1),('sid',1),('site_id',1),('gid',1)):
            with self.subTest(field=field),patch.object(regional_public,'build_opener',return_value=PublicOpener('ar',transform=lambda row:row.update({field:value}))):
                with self.assertRaisesRegex(ValueError,'product_scope_mismatch'):
                    regional_public.collect('ar',21)

    def test_real_selected_header_and_currency_script_are_both_required(self):
        url='https://www.mmoexp.com/ar/Fc-27/Coins.html?cy=USD'
        for html in ('<a class="lang-currency">UK | USD</a><script>const currencyCode="USD";</script>',
                     '<a class="lang-currency">AR | USD</a><script>const currencyCode="EUR";</script>'):
            with self.subTest(html=html),self.assertRaisesRegex(ValueError,'region_.*context'):
                regional_public.selection_context(html,url,'ar',21)


if __name__ == '__main__': unittest.main()
