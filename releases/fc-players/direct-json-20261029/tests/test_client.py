import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'source'
spec = importlib.util.spec_from_file_location('fc_direct_client_contract', SOURCE / 'admin_client.py')
C = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = C
spec.loader.exec_module(C)


class ClientContract(unittest.TestCase):
    def client(self, opener=None):
        client = C.AdminClient('http://127.0.0.1:8912', opener=opener, get_retries=0)
        client._token = 'offline-only'
        return client

    def test_add_is_one_json_post_and_preserves_payload(self):
        seen = []
        def opened(request, **kwargs):
            seen.append(request)
            return io.BytesIO(b'{"code":1,"data":{"id":12}}')
        client = self.client(opened)
        payload = {'gid':1327,'cid':9627,'title':'Sergej / Signature','more':{'extend':[]}}
        self.assertEqual(client.add_model(payload)['data']['id'], 12)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].method, 'POST')
        self.assertEqual(seen[0].get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(seen[0].data), payload)
        self.assertTrue(seen[0].full_url.endswith('/admin/goods.GoodsMould/add'))

    def test_no_retry_on_rejected_add(self):
        calls = []
        def opened(request, **kwargs):
            calls.append(request)
            return io.BytesIO('{"code":401,"msg":"签名无效"}'.encode())
        with self.assertRaises(C.AdminContractError) as ctx:
            self.client(opened).add_model({'gid':1327,'cid':9627})
        self.assertEqual(len(calls), 1)
        self.assertEqual(ctx.exception.diagnostic['response_code'], 401)

    def test_add_scope_and_existing_id_rejected_before_network(self):
        client = self.client(lambda *a, **k: self.fail('unexpected request'))
        for payload in ({'gid':1327,'cid':9627,'id':2}, {'gid':1322,'cid':9627}, {'gid':1327,'cid':2}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                client.add_model(payload)

    def test_get_form_validates_response(self):
        client = self.client()
        with patch.object(client, '_request_json', return_value={'code':1,'data':{'row':{'more':{}}}}) as get:
            self.assertEqual(client.get_model_add_form(), {'row':{'more':{}}})
            self.assertEqual(get.call_args.args[:2], ('GET','/admin/goods.GoodsMould/add'))
        with patch.object(client, '_request_json', return_value={'code':1,'data':{}}), self.assertRaises(C.AdminContractError):
            client.get_model_add_form()

    def test_shelves_one_explicit_model_and_only_three_fc_platforms(self):
        client = self.client()
        payload = {'site_ids':[266],'aids':[21587,21585,21589],'status':'0','price':'9999','num':1}
        with patch.object(client, '_request_json', return_value={'code':1}) as post:
            client.shelves_models([21], payload=payload)
            self.assertEqual(post.call_args.kwargs['json_body'], {**payload,'search':{'mids':21}})
        for ids, bad in (([21,22],payload),([21],{**payload,'site_ids':[266,10]}),([21],{**payload,'aids':[21587]}),([21],{**payload,'search':{}})):
            with self.subTest(ids=ids,bad=bad), self.assertRaises(ValueError):
                client.shelves_models(ids,payload=bad)

    def test_activation_is_bound_to_model_product_pair(self):
        client = self.client()
        with patch.object(client,'get_products',return_value=({'id':31,'mid':21,'gid':1327,'cid':9627},)), patch.object(client,'_request_json',return_value={'code':1}) as post:
            client.set_product_status(21,31,1)
            self.assertEqual(post.call_args.kwargs['json_body'], {'id':31,'status':1})
        with patch.object(client,'get_products',return_value=({'id':31,'mid':22,'gid':1327,'cid':9627},)), self.assertRaises(C.AdminContractError):
            client.set_product_status(21,31,1)
        with self.assertRaises(ValueError): client.set_product_status(21,31,True)

    def test_old_product_edit_remains_inventory_only(self):
        with self.assertRaises(ValueError): self.client().edit_product({'id':31,'status':1})

    def test_fallback_price_is_only_for_a_missing_market_price_platform(self):
        client = self.client()
        products = ({'id':31,'mid':21,'gid':1327,'cid':9627,'aid':21589},)
        with patch.object(client, 'get_products', return_value=products), patch.object(client, 'get_model', return_value={'more':{'extend':[{'key':'pc_price','value':None}]}}), patch.object(client, '_request_json', return_value={'code':1}) as post:
            client.set_product_fallback_price(21,31)
            self.assertEqual(post.call_args.kwargs['json_body'], {'id':31,'unit_price':'9999'})
        for value in ('15000', 0, '9999'):
            with self.subTest(value=value), patch.object(client, 'get_products', return_value=products), patch.object(client, 'get_model', return_value={'more':{'extend':[{'key':'pc_price','value':value}]}}), self.assertRaises(C.AdminContractError):
                client.set_product_fallback_price(21,31)

    def test_added_methods_do_not_allow_arbitrary_endpoints(self):
        with self.assertRaises(C.AdminContractError):
            self.client().build_url('/admin/user.Member/add')


if __name__ == '__main__': unittest.main()
