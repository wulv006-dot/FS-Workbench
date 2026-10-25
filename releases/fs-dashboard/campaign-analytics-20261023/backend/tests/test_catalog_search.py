import copy
import json
import unittest
from unittest.mock import patch

from bridge import handle
from campaign_backend.adapters import AdminRead
from campaign_backend.core import ContractError
from test_management_discovery import goods, model, detail, response, Session


class CatalogSearchTests(unittest.TestCase):
    def request(self,**changes):
        result=dict(action='catalog_search',site_id='266',game_id='1327',keyword='Example',page=1,page_size=20)
        result.update(changes);return result

    def invoke(self,request,responses):
        session=Session(responses)
        result=handle(request,lambda:AdminRead(session,catalog_get_once=session.get_admin))
        self.assertTrue(session.closed)
        return result,session

    def test_keyword_search_is_exactly_one_page_with_server_owned_filters(self):
        request=self.request(page=2,page_size=2,category_id='9627',platform_attribute_id='21587')
        with patch.object(AdminRead,'pages',side_effect=AssertionError('must not traverse pages')):
            result,session=self.invoke(request,[response([goods(id=999),goods(id=998)],100)])
        self.assertEqual(len(session.calls),1)
        route,params=session.calls[0]
        self.assertEqual(route,'/admin/goods.Goods/index')
        self.assertEqual((params['page'],params['limit'],params['quick_search'],params['order']),(2,2,'Example','id,desc'))
        self.assertEqual([(params['search[%d][field]'%i],params['search[%d][val]'%i]) for i in range(4)],
                         [('site_id','266'),('gid','1327'),('cid','9627'),('aid','21587')])
        self.assertEqual((result['page'],result['page_size'],result['total'],result['has_more']),(2,2,100,True))
        self.assertEqual(result['completeness'],'single_page')
        self.assertEqual(result['items'][0]['product_ref']['goods_id'],'999')
        self.assertFalse(result['available']);self.assertFalse(result['checkout_enabled']);self.assertFalse(result['authoritative'])
        self.assertIn('not_live_verified',result['search_verification']['query'])
        self.assertNotIn('SECRET',json.dumps(result))

    def test_model_id_search_yields_goods_links_never_model_as_sku(self):
        request=self.request();request.pop('keyword');request['model_id']='43167385'
        result,session=self.invoke(request,[response([goods()],1)])
        self.assertEqual(session.calls[0][1]['search[2][field]'],'mid')
        self.assertEqual(session.calls[0][1]['search[2][val]'],'43167385')
        ref=result['items'][0]['product_ref']
        self.assertEqual(ref['model_id'],'43167385');self.assertEqual(ref['goods_id'],'170014917')
        self.assertNotIn('sku_id',ref)

    def test_exact_goods_id_uses_one_proved_detail_get_without_list_traversal(self):
        request=self.request();request.pop('keyword');request['goods_id']='170014917'
        result,session=self.invoke(request,[detail(goods())])
        self.assertEqual(session.calls,[('/admin/goods.Goods/edit',{'id':'170014917'})])
        self.assertEqual(result['total'],1);self.assertFalse(result['has_more'])
        result,_=self.invoke(dict(request,category_id='999'),[detail(goods())])
        self.assertEqual(result['items'],[]);self.assertEqual(result['total'],0)

    def test_invalid_requests_fail_before_any_session_or_arbitrary_field_access(self):
        base=self.request()
        invalid=[dict(base,site_id='999'),dict(base,site_id='0'),dict(base,game_id=True),dict(base,keyword='x'),
            dict(base,keyword='  '),dict(base,keyword='a\nb'),dict(base,page=True),dict(base,page=0),dict(base,page=501),
            dict(base,page_size=51),dict(base,page_size='20'),dict(base,model_id='4'),dict(base,fields=['price']),
            dict(base,filters=[['token','=','x']]),dict(base,order='password'),dict(base,path='/admin/other'),
            dict(base,category_id=0),dict(base,platform_attribute_id=False),dict(base,model_id=None)]
        missing=dict(base);missing.pop('keyword');invalid.append(missing)
        exact=dict(missing,goods_id='1',page=2);invalid.append(exact)
        for request in invalid:
            with self.subTest(request=request),self.assertRaises(ContractError):
                handle(request,lambda:self.fail('must validate before acquiring shared session'))

    def test_upstream_scope_filter_mismatch_duplicates_and_invalid_pages_fail_closed(self):
        cases=[response([goods(site_id=0)],1),response([goods(gid=999)],1),response([goods(),goods()],2),
            response([goods()],False),response([],10),response([goods()],0)]
        for page in cases:
            session=Session([page])
            with self.assertRaises(ContractError):handle(self.request(),lambda:AdminRead(session,catalog_get_once=session.get_admin))
            self.assertEqual(len(session.calls),1);self.assertTrue(session.closed)
        for field,request_field in [('aid','platform_attribute_id'),('cid','category_id'),('mid','model_id')]:
            request=self.request(**{request_field:'999'})
            if field=='mid':request.pop('keyword')
            with self.assertRaisesRegex(ContractError,'UPSTREAM_SCOPE_MISMATCH'):
                self.invoke(request,[response([goods()],1)])

    def test_unknown_optional_metadata_is_not_invented_or_made_buyable(self):
        raw=goods(min_qty=None,num=None,unit=None,aid=None,cid=None,sid=None,sku_switch=None,
            attr_switch=None,status=None,buy_status=None,more=None)
        result,_=self.invoke(self.request(),[response([raw],1)])
        item=result['items'][0]
        for name in ('minimum_quantity','unit','platform_attribute_id','category_id','server_id','sku_switch','raw_status'):
            self.assertIsNone(item[name])
        self.assertTrue(item['purchase_mapping_required']);self.assertFalse(item['available'])
        request=dict(action='product_read',site_id='266',game_id='1327',goods_id='170014917')
        result,_=self.invoke(request,[detail(raw),detail(model(more=None,title=None))])
        item=result['product']
        self.assertIsNone(item['quantity_observation']['minimum']);self.assertIsNone(item['quantity_observation']['raw_num'])
        self.assertIsNone(item['model_title']);self.assertTrue(item['purchase_mapping_required'])
        self.assertIn('MINIMUM_QUANTITY_UNKNOWN',item['purchase_mapping_reasons'])
        self.assertNotIn('sku_id',item['product_ref']);self.assertFalse(item['checkout_enabled'])

    def test_unknown_title_and_financial_fields_never_escape_safe_projection(self):
        raw=goods(title='SECRET_TOKEN@example.test',unit='USD SECRET_VALUE',status='SECRET_STATUS')
        result,_=self.invoke(self.request(),[response([raw],1)])
        self.assertIsNone(result['items'][0]['title']);self.assertIsNone(result['items'][0]['unit'])
        self.assertNotIn('SECRET',json.dumps(result));self.assertNotIn('price',result['items'][0])

    def test_product_read_rejects_client_mapping_and_wrong_scope_before_read_or_model(self):
        request=dict(action='product_read',site_id='266',game_id='1327',goods_id='170014917')
        for bad in [dict(request,mapping={'price':'secret'}),dict(request,site_id='999')]:
            with self.assertRaises(ContractError):handle(bad,lambda:self.fail('no read'))
        session=Session([detail(goods(site_id=999))])
        with self.assertRaisesRegex(ContractError,'PRODUCT_SCOPE_MISMATCH'):
            handle(request,lambda:AdminRead(session,catalog_get_once=session.get_admin))
        self.assertEqual(len(session.calls),1)

    def test_details_retain_only_observed_spec_ids_and_labels_not_financial_leaves(self):
        raw=goods(sku_switch=1,more={'saleprop':[{'attribute_id':11,'values':[{'value_id':22,'label':'Edition','price':'SECRET'}]}],
            'skuTableSet':[{'sku_id':77,'propvalues':{'11':'22'},'cost':'SECRET'}]})
        request=dict(action='product_read',site_id='266',game_id='1327',goods_id='170014917')
        result,_=self.invoke(request,[detail(raw),detail(model())]);item=result['product']
        self.assertEqual(item['specification_sources']['goods']['saleprop']['observed'][0]['values'][0]['value_id'],22)
        self.assertEqual(item['specification_sources']['goods']['skuTableSet']['observed'][0]['sku_id'],77)
        self.assertNotIn('SECRET',json.dumps(item));self.assertTrue(item['purchase_mapping_required'])
        self.assertFalse(item['available']);self.assertFalse(item['checkout_enabled'])


if __name__=='__main__':unittest.main()
