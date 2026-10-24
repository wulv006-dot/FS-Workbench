import importlib.util
import json
from pathlib import Path
import unittest

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'tools/campaign_catalog_probe.py').is_file())
def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / ('tools/' + name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module
probe = load('campaign_catalog_probe')


class CatalogProbeTests(unittest.TestCase):
    def test_original_seed_exact_coverage_no_money_fields(self):
        # Pure fixture assertions here; real Python -> Node extraction runs in catalog-seed.test.mjs.
        seed = json.loads((ROOT / 'docs/planning/activity-center-v3/handoffs/C-CATALOG-SEED-04.json').read_text(encoding='utf8'))
        self.assertEqual((seed['reference_count'], seed['unique_goods_count'], seed['game_count']), (96, 86, 6))
        self.assertEqual(len(seed['references']),96)
        self.assertEqual(len({r['reference_key'] for r in seed['references']}),96)
        self.assertEqual(len({tuple(r['product_ref'][k] for k in ('site_id','game_id','goods_id'))
                              for r in seed['references']}),86)
        self.assertEqual(len({r['game_key'] for r in seed['references']}),6)
        self.assertEqual(set(seed['source_artifacts']),{'app/catalog.json','app/seasonal/campaign-data.js'})
        for value in seed['source_artifacts'].values():
            self.assertRegex(value,r'^[a-f0-9]{64}$')
        self.assertFalse(seed['authoritative'])
        self.assertFalse(seed['checkout_enabled'])
        raw = json.dumps(seed).lower()
        for key in ('price', 'cost', 'token', 'order', 'email'):
            self.assertNotIn(key, raw)
        rows = [r for r in seed['references'] if r['game_key'] == 'diablo']
        self.assertEqual([r['expected_quantity']['value'] for r in rows], ['100000', '300000', '600000'])
        self.assertTrue(all(r['expected_quantity']['source_unit'] == 'M' for r in rows))

    def test_get_only_caching_rate_limit_projection_and_public_evidence(self):
        row = dict(id=1, mid=9, site_id=266, gid=1327, aid=21587, sid=7645, cid=9627,
                   min_qty=1, unit='', sku_switch=1, attr_switch=1, status=1, buy_status=0,
                   price='SECRET_PRICE', cost='SECRET_COST', email='SECRET_EMAIL',
                   more={'saleprop':[{'id':11,'name':'Tier','values':[{'id':22,'label':'Gold','price':'SECRET_PRICE'}]}],
                         'skuTableSet':[{'id':7,'propvalues':{'11':'22'},'cost':123}]})
        class Session:
            def __init__(self): self.calls=[]
            def get_admin(self, route, **params):
                self.calls.append((route,params));data=dict(row,id=int(params['id']))
                if route==probe.ADMIN['model']:data={'id':9,'gid':1327,'more':{'saleprop':[]}}
                return 200,dict(code=1,data=dict(row=data))
        references=[dict(reference_key='r'+str(i),product_ref=dict(site_id='266',game_id='1327',goods_id=str(gid)),public_path='/Fc-27/Players.html') for i,gid in enumerate((1,1,2))]
        urls=[]
        def get(url):
            urls.append(url)
            if url.endswith('.html'):return b'<input name="num" value="1"><input name="email" value="SECRET_EMAIL"><script src="/js/buy.js?v=1"></script><script src="https://evil.invalid/js/private.js"></script>'
            return b'const form={category:"new_items",attr:selection.attr,num:quantity,id:goods.id,price:99}; /* SECRET_TOKEN */'
        waits=[];session=Session();result=probe.run_probe(dict(schema_version=1,references=references),session,get,sleep=waits.append)
        self.assertEqual((result['reference_count'],result['unique_goods_count']),(3,2))
        self.assertEqual((result['goods_requests'],result['model_requests']),(2,1))
        self.assertEqual(len(session.calls),3);self.assertEqual(len(urls),2);self.assertTrue(all(v>=.2 for v in waits))
        raw=json.dumps(result)
        self.assertNotIn('SECRET',raw);self.assertNotIn('price',raw);self.assertNotIn('cost',raw);self.assertNotIn('evil',raw)
        self.assertEqual(result['products'][0]['goods']['specifications']['more']['saleprop']['value'][0]['values'][0]['id'],22)
        self.assertIn(dict(field='attr',expression='selection.attr'),result['public_scripts']['/js/buy.js']['purchase_expressions'])
        self.assertFalse(result['checkout_enabled']);self.assertFalse(result['authoritative'])

    def test_route_scope_failure_and_failed_model_not_retried(self):
        class Session:
            def __init__(self):self.calls=[]
            def get_admin(self,route,**params):
                self.calls.append(route)
                if route==probe.ADMIN['model']:return 403,{'msg':'SECRET_TOKEN'}
                return 200,dict(code=1,data=dict(row=dict(id=int(params['id']),site_id=266,gid=1327,mid=9)))
        seed=dict(schema_version=1,references=[dict(product_ref=dict(site_id='266',game_id='1327',goods_id=str(i)),public_path='/Fc-27/Players.html') for i in (1,2)])
        session=Session();result=probe.run_probe(seed,session,lambda _:b'',sleep=lambda _:None)
        self.assertEqual(session.calls.count(probe.ADMIN['model']),1);self.assertEqual(result['observed_goods_count'],0);self.assertNotIn('SECRET',json.dumps(result))
        seed['references'][0]['public_path']='/Cart/add.html'
        with self.assertRaisesRegex(ValueError,'PUBLIC_ROUTE_NOT_ALLOWED'):probe.run_probe(seed,session)


if __name__=='__main__':unittest.main()
