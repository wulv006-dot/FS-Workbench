import copy
import json
import unittest
from datetime import datetime
from unittest.mock import patch

from bridge import handle
from campaign_backend.adapters import AdminRead
from campaign_backend.core import ContractError
from campaign_backend.provider import bounded_pages, tier_observations
from test_management_discovery import Session, response, detail


def model(rid=500,**changes):
    value=dict(id=rid,gid=1327,cid=9623,title='Synthetic Coins Model',sid=0,aid=0,status=1,buy_status=0,
        auto_off=0,attr_switch=1,sku_switch=1,min_qty=1,num=1,unit='K',price=0,discount=100,
        more=dict(gold=[10,1000],price=[1.25,125],discount=[100,95],
            saleprop=[dict(id=11,name='Synthetic region',options=[dict(id=21,name='Option',cost='PRIVATE_COST')])]),
        buy_price_cny='PRIVATE_COST',token='PRIVATE_TOKEN')
    value.update(changes);return value


def goods(rid=1000,aid=21587,**changes):
    row=model();row.update(id=rid,mid=500,site_id=266,sid=7645,aid=aid,unit_price=0.125)
    row.update(changes);return row


class ProviderTests(unittest.TestCase):
    def request(self,**changes):
        value=dict(action='model_provider_read',site_id='266',game_id='1327',category_id='9623',model_id='500')
        value.update(changes);return value

    def pool(self,**changes):
        value=dict(action='model_category_pool',site_id='266',game_id='1327',category_id='9623')
        value.update(changes);return value

    def invoke(self,request,results):
        session=Session(results)
        try:result=handle(request,lambda:AdminRead(session,catalog_get_once=session.get_admin))
        finally:self.assertTrue(session.closed)
        return result,session

    def batch(self,items,results):
        session=Session(results)
        try:result=handle(dict(action='model_provider_batch',site_id='266',items=items),
            lambda:AdminRead(session,catalog_get_once=session.get_admin))
        finally:self.assertTrue(session.closed)
        return result,session

    def test_batch_read_sweeps_the_catalogue_once_for_all_models_of_a_game(self):
        rows=[goods(1001,21587),goods(1002,21587,mid=501)]
        result,session=self.batch([dict(key='a',site_id='266',game_id='1327',model_id='500',category_id='9623'),
            dict(key='b',site_id='266',game_id='1327',model_id='501',category_id='9623')],
            [response(rows,2),detail(model()),detail(model(501))])
        # One IN sweep replaces the per-model child lookup; only the model details remain.
        self.assertEqual([call[0] for call in session.calls],
            ['/admin/goods.Goods/index','/admin/goods.GoodsMould/edit','/admin/goods.GoodsMould/edit'])
        sweep=session.calls[0][1]
        self.assertEqual((sweep['search[2][field]'],sweep['search[2][operator]'],sweep['search[2][val]']),
            ('mid','IN','500,501'))
        self.assertEqual([result['readings'][key]['status'] for key in ('a','b')],['ok','ok'])
        self.assertEqual([[row['product_ref']['goods_id'] for row in result['readings'][key]['data']['products']]
            for key in ('a','b')],[['1001'],['1002']])

    def test_batch_read_reports_a_failed_game_without_dropping_the_other_games(self):
        class Stalling(Session):
            def get_admin(self,route,**params):
                self.calls.append((route,params))
                if params.get('search[1][val]')=='891':raise TimeoutError()
                return next(self.responses)
        session=Stalling([response([goods(1001,21587)],1),detail(model())])
        request=dict(action='model_provider_batch',site_id='266',items=[
            dict(key='fc',site_id='266',game_id='1327',model_id='500',category_id='9623'),
            dict(key='aion',site_id='266',game_id='891',model_id='700',category_id='6527')])
        try:result=handle(request,lambda:AdminRead(session,catalog_get_once=session.get_admin))
        finally:self.assertTrue(session.closed)
        self.assertEqual(result['readings']['fc']['status'],'ok')
        self.assertEqual(result['readings']['aion'],dict(status='error',error='CATALOG_SEARCH_TIMEOUT'))
        self.assertEqual([row['product_ref']['goods_id'] for row in result['readings']['fc']['data']['products']],['1001'])

    def test_real_adapter_and_bridge_project_observed_tiers_without_currency_or_item_conversion(self):
        rows=[goods(1003,21589),goods(1002,21587),goods(1001,21585)]
        result,session=self.invoke(self.request(),[detail(model()),response(rows,3)])
        self.assertEqual(len(session.calls),2)
        self.assertEqual(session.calls[0],('/admin/goods.GoodsMould/edit',{'id':'500'}))
        self.assertEqual(session.calls[1][0],'/admin/goods.Goods/index')
        params=session.calls[1][1]
        self.assertEqual([(params['search[%d][field]'%i],params['search[%d][val]'%i]) for i in range(4)],
            [('site_id','266'),('gid','1327'),('mid','500'),('cid','9623')])
        self.assertEqual(params['limit'],50);self.assertTrue(result['coverage']['complete'])
        self.assertEqual([p['platform_attribute_id'] for p in result['products']],['21589','21587','21585'])
        product=result['products'][1]
        self.assertEqual(product['product_ref'],dict(site_id='266',game_id='1327',model_id='500',goods_id='1002'))
        self.assertEqual(product['region_id'],'7645');self.assertEqual(product['quantity'],dict(minimum='1',group='1',unit='K'))
        self.assertEqual(product['tiers'][1],dict(source_index=1,quantity='1000',unit='K',source_price='125',
            source_discount='95',currency=None,authoritative=False))
        self.assertEqual(product['source_unit_price'],'0.125');self.assertEqual(product['source_price'],'0')
        self.assertFalse(result['coverage']['snapshot_atomic']);self.assertFalse(result['coverage']['sellability_verified'])
        self.assertEqual(result['source'],'admin_readonly');self.assertIsNotNone(datetime.fromisoformat(result['observed_at']).tzinfo)
        for row in [result,result['model']]+result['products']:
            self.assertIsNone(row['currency']);self.assertFalse(row['available']);self.assertFalse(row['checkout_enabled'])
        self.assertNotIn('PRIVATE_',json.dumps(result));self.assertNotIn('sku_id',product['product_ref'])
        self.assertEqual(product['specification']['saleprop']['observed'][0]['options'][0],dict(id=21,name='Option'))

    def test_item_list_without_formatted_price_reads_scoped_details(self):
        item_model=model(unit='',more=dict(saleprop=[],skuTableSet=[],baseprop=[]))
        rows=[goods(1003,21589,unit='',more=dict(saleprop=[],skuTableSet=[],baseprop=[])),goods(1002,21587,unit='',more=dict(saleprop=[],skuTableSet=[],baseprop=[]))]
        details=[dict(row,full_price_format='5.43') for row in rows]
        result,session=self.invoke(self.request(),[detail(item_model),response(rows,2)]+[detail(row) for row in details])
        self.assertEqual(len(session.calls),4)
        self.assertEqual([row['source_display_price'] for row in result['products']],['5.43','5.43'])
        self.assertEqual([call[1]['id'] for call in session.calls[-2:]],['1003','1002'])
        with self.assertRaisesRegex(ContractError,'PROVIDER_SCOPE_MISMATCH'):
            self.invoke(self.request(),[detail(item_model),response(rows,2),detail(dict(details[0],mid=501))])

    def test_no_products_or_missing_tables_return_honest_observations(self):
        result,_=self.invoke(self.request(),[detail(model(more={})),response([],0)])
        self.assertEqual(result['site_association'],'not_observed');self.assertEqual(result['products'],[])
        self.assertIn('SITE_ASSOCIATION_NOT_OBSERVED',result['warnings'])
        self.assertEqual(result['model']['tiers'],[])
        self.assertIn('QUANTITY_TABLE_NOT_OBSERVED',result['model']['warnings'])

    def test_parallel_tables_require_all_lengths_values_unique_quantity_and_never_infer_sku(self):
        original=goods()
        for change in ({'price':[1]},{'gold':[10,10]},{'gold':[True,1000]},{'price':['USD 1.25',125]},
                {'discount':[float('nan'),100]},{'gold':[],'price':[],'discount':[]}):
            row=copy.deepcopy(original);row['more'].update(change)
            tiers,warning=tier_observations(row)
            self.assertEqual(tiers,[]);self.assertIsNotNone(warning)
        self.assertEqual(tier_observations(dict(more={})),([], 'QUANTITY_TABLE_NOT_OBSERVED'))

    def test_scope_mismatch_never_projects_another_site_game_model_or_category(self):
        for changes in ({'site_id':99},{'gid':99},{'mid':99},{'cid':99}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):
                self.invoke(self.request(),[detail(model()),response([goods(**changes)],1)])
        with self.assertRaisesRegex(ContractError,'PROVIDER_SCOPE_MISMATCH'):
            self.invoke(self.request(),[detail(model(cid=1))])

    def test_per_model_bounded_200_rows_retains_partial_status_and_rechecks_anchor(self):
        rows=[goods(rid) for rid in range(1200,1000,-1)]
        pages=[response(rows[n:n+50],201) for n in range(0,200,50)]
        result,session=self.invoke(self.request(),[detail(model())]+pages+[pages[0]])
        self.assertEqual(len(result['products']),200);self.assertEqual(len(session.calls),6)
        self.assertFalse(result['coverage']['complete']);self.assertEqual(result['coverage']['reason'],'PAGE_LIMIT_REACHED')
        self.assertEqual(result['coverage']['row_limit'],200);self.assertTrue(result['coverage']['anchor_rechecked'])
        self.assertIn('ASSOCIATION_INCOMPLETE',result['warnings'])

    def test_189_server_associations_are_complete_but_not_distinct_models(self):
        rows=[goods(rid) for rid in range(1189,1000,-1)]
        pages=[response(rows[n:n+50],189) for n in range(0,189,50)]
        result,session=self.invoke(self.request(),[detail(model())]+pages+[pages[0]])
        self.assertEqual(len(result['products']),189);self.assertTrue(result['coverage']['complete'])
        self.assertEqual({p['product_ref']['model_id'] for p in result['products']},{'500'})
        self.assertTrue(result['coverage']['anchor_rechecked'])

    def test_pagination_changed_total_short_page_and_changed_first_anchor_are_rejected(self):
        rows=[model(700),model(600),model(500)]
        first=dict(rows=rows[:2],total=3,has_more=True)
        for later in (
            [dict(rows=rows[2:],total=4,has_more=False)],
            [dict(rows=[],total=3,has_more=False)],
            [dict(rows=rows[2:],total=3,has_more=False),dict(rows=[model(701),model(600)],total=3,has_more=True)]):
            results=iter([first]+later)
            with self.assertRaises(ContractError):bounded_pages(lambda _:next(results),2,2)

    def test_global_duplicate_removes_repeat_but_cannot_be_marked_complete(self):
        first=dict(rows=[model(700),model(600)],total=3,has_more=True)
        pages=iter([first,dict(rows=[model(600)],total=3,has_more=False),first])
        rows,coverage=bounded_pages(lambda _:next(pages),2,2)
        self.assertEqual([row['id'] for row in rows],[700,600]);self.assertFalse(coverage['complete'])
        self.assertEqual(coverage['reason'],'PAGINATION_OVERLAP')
        changed=model(600,title='Changed')
        pages=iter([first,dict(rows=[changed],total=3,has_more=False)])
        with self.assertRaisesRegex(ContractError,'PAGINATION_CHANGED'):bounded_pages(lambda _:next(pages),2,2)

    def test_pool_defaults_fixed_exclusions_and_additional_ids_are_not_a_sellable_pool(self):
        artifact=dict(mappings={'fixed':dict(product_ref=dict(site_id='266',game_id='1327',model_id='600'))})
        with patch('campaign_backend.catalog.read_reference_mapping',return_value=artifact):
            result,session=self.invoke(self.pool(exclude_model_ids=['500']),[response([model(700),model(600),model(500)],3)])
        self.assertEqual(session.calls[0][0],'/admin/goods.GoodsMould/index')
        params=session.calls[0][1];self.assertEqual(params['limit'],10);self.assertEqual(params['page'],1)
        self.assertNotIn('quick_search',params);self.assertNotIn('search[2][field]',params)
        self.assertEqual([item['model_id'] for item in result['items']],['700']);self.assertEqual(result['excluded_count'],2)
        self.assertTrue(result['coverage']['complete']);self.assertFalse(result['eligible_for_draw'])
        self.assertEqual(result['items'][0]['site_association'],'not_yet_verified')
        self.assertIn('SITE_ASSOCIATIONS_NOT_RESOLVED',result['blocked_reasons'])

    def test_pool_keyword_pages_have_bounded_requests_and_no_implicit_site_binding(self):
        rows=[model(700),model(600),model(500)]
        result,session=self.invoke(self.pool(keyword='Synthetic',page_size=2,max_pages=2),
            [response(rows[:2],3),response(rows[2:],3),response(rows[:2],3)])
        self.assertEqual(len(session.calls),3);self.assertTrue(result['coverage']['complete'])
        self.assertEqual(session.calls[0][1]['search[2][val]'],'Synthetic')
        self.assertTrue(all(item['site_association']=='not_yet_verified' for item in result['items']))
        self.assertFalse(result['available']);self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_invalid_client_fields_bounds_and_identity_fail_before_session(self):
        for req in (self.request(site_id='99'),self.request(model_id=True),self.request(headers={}),
            self.pool(max_pages=4),self.pool(max_pages=True),self.pool(page_size=21),self.pool(page_size=0),
            self.pool(exclude_model_ids=[True]),self.pool(exclude_model_ids=['1']*101),self.pool(exclude_model_ids='1'),
            self.pool(keyword='a'),self.pool(keyword='X\nY'),self.pool(order='title'),self.pool(filters=[]),
            self.pool(resolve_associations='true'),self.pool(resolve_associations=1)):
            with self.subTest(req=req),self.assertRaises(ContractError):handle(req,lambda:self.fail('no session acquisition'))

    def test_timeout_or_refusal_never_retries_or_returns_a_complete_prefix(self):
        session=Session([]);calls=[]
        def transport(route,**params):
            calls.append(route)
            if len(calls)==1:return detail(model())
            raise TimeoutError('PRIVATE upstream details')
        with self.assertRaisesRegex(ContractError,'CATALOG_SEARCH_TIMEOUT'):
            handle(self.request(),lambda:AdminRead(session,catalog_get_once=transport))
        self.assertTrue(session.closed);self.assertEqual(len(calls),2)

    def test_complete_small_pool_resolves_each_site_association_and_preserves_offline_guard(self):
        artifact=dict(mappings={'fixed':dict(product_ref=dict(site_id='266',game_id='1327',model_id='500'))})
        with patch('campaign_backend.catalog.read_reference_mapping',return_value=artifact):
            result,session=self.invoke(self.pool(resolve_associations=True),[
                response([model(700),model(600),model(500)],3),detail(model(700)),response([goods(1003,mid=700)],1),
                detail(model(600,status=0)),response([goods(1002,mid=600)],1)])
        self.assertEqual(len(session.calls),5);self.assertEqual([item['model_id'] for item in result['items']],['700','600'])
        coverage=result['association_coverage'];self.assertTrue(coverage['complete']);self.assertEqual(coverage['models_resolved'],2)
        self.assertEqual(result['items'][0]['site_association'],'observed')
        self.assertEqual(result['items'][0]['association']['products'][0]['original_guard_observation'],'observed_original_guard')
        self.assertEqual(result['items'][1]['association']['products'][0]['original_guard_observation'],'original_guard_failed')
        self.assertEqual(result['items'][1]['association']['model']['raw_state']['status'],0)
        self.assertIsNone(result['items'][0]['association']['currency']);self.assertFalse(result['eligible_for_draw'])
        self.assertNotIn('SITE_ASSOCIATIONS_NOT_RESOLVED',result['blocked_reasons'])
        self.assertIn('SELLABILITY_UNVERIFIED',result['blocked_reasons'])

    def test_incomplete_or_over_budget_pool_never_resolves_a_truncated_subset(self):
        for request,rows,total,reason in [
            (self.pool(resolve_associations=True,page_size=1),[model(700)],2,'CATEGORY_PAGINATION_INCOMPLETE'),
            (self.pool(resolve_associations=True),[model(900),model(800),model(700),model(600)],4,'MODEL_RESOLUTION_BUDGET_EXCEEDED')]:
            result,session=self.invoke(request,[response(rows,total)])
            self.assertEqual(len(session.calls),1);self.assertFalse(result['association_coverage']['complete'])
            self.assertEqual(result['association_coverage']['reason'],reason)
            self.assertEqual(result['association_coverage']['models_attempted'],0)
            self.assertTrue(all('association' not in item for item in result['items']))

    def test_resolution_deadline_is_shared_with_initial_category_read_not_reset_per_model(self):
        session=Session([response([model(700)],1)])
        # Second tick sits one second past the 45s aggregate catalogue budget, so the
        # child read must be refused instead of getting a fresh window per model.
        with patch('campaign_backend.adapters.time.monotonic',side_effect=[0,0,46]):
            result=handle(self.pool(resolve_associations=True),lambda:AdminRead(session,catalog_get_once=session.get_admin))
        self.assertEqual(len(session.calls),1);self.assertTrue(session.closed)
        self.assertEqual(result['association_coverage']['reason'],'CATALOG_SEARCH_TIMEOUT')
        self.assertFalse(result['association_coverage']['complete'])

    def test_missing_site_is_an_observed_empty_association_not_currency_based_absence(self):
        result,session=self.invoke(self.pool(resolve_associations=True),[response([model(700)],1),detail(model(700)),response([],0)])
        self.assertTrue(result['association_coverage']['complete']);self.assertEqual(len(session.calls),3)
        self.assertEqual(result['items'][0]['site_association'],'not_observed')
        self.assertEqual(result['items'][0]['association']['products'],[])
        self.assertIn('SITE_ASSOCIATION_NOT_OBSERVED',result['blocked_reasons'])
        self.assertFalse(result['eligible_for_draw'])

    def test_second_model_read_failure_preserves_first_observation_without_claiming_complete(self):
        session=Session([]);responses=iter([response([model(700),model(600)],2),detail(model(700)),response([goods(mid=700)],1)])
        calls=[]
        def transport(route,**params):
            calls.append(route)
            if len(calls)==4:raise TimeoutError('PRIVATE message')
            return next(responses)
        result=handle(self.pool(resolve_associations=True),lambda:AdminRead(session,catalog_get_once=transport))
        self.assertEqual(len(calls),4);self.assertTrue(session.closed)
        self.assertFalse(result['association_coverage']['complete']);self.assertEqual(result['association_coverage']['models_resolved'],1)
        self.assertEqual(result['association_coverage']['reason'],'CATALOG_SEARCH_TIMEOUT')
        self.assertIn('association',result['items'][0]);self.assertNotIn('association',result['items'][1])
        self.assertNotIn('PRIVATE',json.dumps(result))


if __name__=='__main__':unittest.main()
