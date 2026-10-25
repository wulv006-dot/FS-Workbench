import copy
import json
import time
import unittest
from pathlib import Path

from bridge import handle
from campaign_backend.adapters import AdminRead
from campaign_backend.models import KINDS, historical_image, project_model, resolve_model, version_label
from campaign_backend.core import ContractError
from test_management_discovery import Session, response, detail


def model(**changes):
    row=dict(id=500,gid=1327,cid=9627,aid=0,title='Synthetic Haaland / title is not parsed',status=1,auto_off=0,pic='',
        cost='PRIVATE_COST',more={'baseprop':[dict(id=347,name='Version',default={'checked_item':22,'monodromy':''},
            pvs=[dict(id=21,prop_id=347,name='Other Edition',status=1),dict(id=22,prop_id=347,name='Selected Edition',status=1)])]})
    row.update(changes);return row


def goods(goods_id,aid,**changes):
    row=dict(id=goods_id,mid=500,site_id=266,gid=1327,cid=9627,aid=aid,status=1,buy_status=0,auto_off=0,
        min_qty=1,num=1,unit='',price='PRIVATE_PRICE',stock='PRIVATE_STOCK')
    row.update(changes);return row


class ModelTests(unittest.TestCase):
    def search(self,**changes):
        req=dict(action='model_search',site_id='266',game_id='1327',kind='player',keyword='Haal',page=1,page_size=10)
        req.update(changes);return req

    def resolve(self):return dict(action='model_resolve',site_id='266',game_id='1327',kind='player',model_id='500')

    def invoke(self,request,results):
        session=Session(results)
        result=handle(request,lambda:AdminRead(session,catalog_get_once=session.get_admin))
        self.assertTrue(session.closed);return result,session

    def test_kind_categories_match_actual_accepted_catalog_not_old_listing_branch(self):
        data=json.loads((Path(__file__).parents[2]/'app/catalog.json').read_text(encoding='utf-8'))
        for kind,cid in KINDS.items():self.assertEqual({str(p['cid']) for p in data['products'].values() if p['kind']==kind},{cid})

    def test_model_name_search_uses_model_index_true_kind_and_explicit_alias(self):
        result,session=self.invoke(self.search(keyword='哈兰德'),[response([model()],1)])
        self.assertEqual(session.calls[0][0],'/admin/goods.GoodsMould/index')
        params=session.calls[0][1]
        self.assertEqual([(params['search[%d][field]'%i],params['search[%d][val]'%i]) for i in range(3)],
            [('gid','1327'),('cid','9627'),('title','Haaland')])
        self.assertEqual(params['search[2][operator]'],'LIKE');self.assertNotIn('quick_search',params)
        self.assertTrue(result['name_query']['alias_applied']);self.assertEqual(result['name_query']['source'],'explicit_alias')
        card=result['items'][0];self.assertEqual(card['model_id'],'500');self.assertEqual(card['site_association'],'not_yet_verified')
        self.assertFalse(card['available']);self.assertFalse(card['checkout_enabled']);self.assertNotIn('PRIVATE_',json.dumps(result))

    def test_exact_model_id_is_one_scoped_model_detail_get(self):
        req=self.search();req.pop('keyword');req['model_id']='500'
        result,session=self.invoke(req,[detail(model())])
        self.assertEqual(session.calls,[('/admin/goods.GoodsMould/edit',{'id':'500'})])
        self.assertEqual(result['items'][0]['version_label'],'Selected Edition')

    def test_resolve_one_model_into_three_native_platform_goods_without_prices_or_fake_sku(self):
        rows=[goods(1001,21587),goods(1002,21585),goods(1003,21589)]
        result,session=self.invoke(self.resolve(),[detail(model()),response(rows,3)])
        card=result['model'];self.assertEqual(card['key'],'model-266-1327-500');self.assertEqual(card['site_association'],'observed')
        self.assertEqual([card['platforms'][k]['product_ref']['goods_id'] for k in ('ps','xbox','pc')],['1001','1002','1003'])
        for slot in card['platforms'].values():
            self.assertEqual(slot['state'],'verified');self.assertNotIn('sku_id',slot['product_ref'])
            self.assertEqual(slot['observed_quantity'],dict(minimum='1',unit='',group='1'))
        self.assertFalse(card['available']);self.assertFalse(card['authoritative']);self.assertFalse(card['checkout_enabled'])
        self.assertNotIn('PRIVATE_',json.dumps(result));self.assertEqual(len(session.calls),2)
        self.assertEqual(session.calls[1][1]['search[2][field]'],'mid');self.assertEqual(session.calls[1][1]['search[3][val]'],'9627')

    def test_missing_offline_ambiguous_and_unknown_never_fill_another_platform(self):
        rows=[goods(1001,21587),goods(1002,21585,status=0),goods(1003,21589),goods(1004,21589)]
        card=resolve_model(model(),'player',dict(rows=rows,total=4))
        self.assertEqual(card['platforms']['ps']['state'],'verified');self.assertEqual(card['platforms']['xbox']['state'],'offline')
        self.assertEqual(card['platforms']['pc']['state'],'ambiguous');self.assertIsNone(card['platforms']['pc']['product_ref'])
        card=resolve_model(model(),'player',dict(rows=[goods(1001,21587,status=None)],total=1))
        self.assertEqual(card['platforms']['ps']['state'],'unknown');self.assertEqual(card['platforms']['xbox']['state'],'missing')
        card=resolve_model(model(),'player',dict(rows=[goods(1001,21587)],total=11))
        self.assertTrue(all(s['state']=='unknown' for s in card['platforms'].values()))

    def test_disabled_or_unknown_model_never_produces_verified_platforms(self):
        for changes,expected in [({'status':0},'offline'),({'auto_off':1},'offline'),({'status':None},'unknown'),({'auto_off':None},'unknown')]:
            card=resolve_model(model(**changes),'player',dict(rows=[goods(1001,21587)],total=1))
            self.assertEqual(card['platforms']['ps']['state'],expected);self.assertIsNone(card['platforms']['ps']['product_ref'])

    def test_no_site_association_wrong_scope_and_duplicate_children_fail_closed(self):
        with self.assertRaisesRegex(ContractError,'MODEL_SITE_ASSOCIATION_MISSING'):
            self.invoke(self.resolve(),[detail(model()),response([],0)])
        for change in ({'site_id':0},{'gid':99},{'cid':10203},{'mid':501}):
            with self.assertRaises(ContractError):self.invoke(self.resolve(),[detail(model()),response([goods(1001,21587,**change)],1)])
        with self.assertRaisesRegex(ContractError,'DUPLICATE_PAGE'):
            self.invoke(self.resolve(),[detail(model()),response([goods(1001,21587),goods(1001,21587)],2)])

    def test_version_only_selected_checked_item_matches_one_active_pvs_not_title(self):
        self.assertEqual(version_label(model(),'player'),'Selected Edition')
        for change in ('missing','duplicate','inactive','wrong_prop'):
            raw=model();prop=raw['more']['baseprop'][0]
            if change=='missing':prop['default']['checked_item']=999
            elif change=='duplicate':prop['pvs'].append(copy.deepcopy(prop['pvs'][1]))
            elif change=='inactive':prop['pvs'][1]['status']=0
            else:prop['pvs'][1]['prop_id']=999
            self.assertIsNone(version_label(raw,'player'))
        self.assertIsNone(version_label(model(more={}), 'player'))

    def test_historical_image_binds_exact_model_and_goods_not_name_or_new_version(self):
        mapping={'mappings':{'r':dict(family='fc',product_ref=dict(site_id='266',game_id='1327',model_id='500',goods_id='1001'),platform={'attribute_id':'21587'})}}
        catalog={'products':{'p':dict(title='same name',platforms={'ps':{'id':1001,'aid':21587}},imageSource='https://assets.mmoexp.com/player/fc27/1.png')}}
        self.assertEqual(historical_image('500',mapping,catalog),'https://assets.mmoexp.com/player/fc27/1.png')
        self.assertIsNone(historical_image('501',mapping,catalog))
        for image in ('https://private.invalid/1.png','https://assets.mmoexp.com/player/fc27/1.png?token=secret','/assets/unknown.png'):
            catalog['products']['p']['imageSource']=image;self.assertIsNone(historical_image('500',mapping,catalog))
        raw=model(pic='https://private.invalid/1.png');self.assertIsNone(project_model(raw,'player')['image_url'])

    def test_bad_requests_and_unsupported_chinese_fail_before_session(self):
        req=self.search()
        for bad in (dict(req,site_id=0),dict(req,game_id=1329),dict(req,kind='any'),dict(req,kind=[]),dict(req,cid='1'),
            dict(req,keyword='梅西'),dict(req,keyword='H'),dict(req,page=True),dict(req,page_size=21),dict(req,model_id='500'),dict(self.resolve(),model_id=True)):
            with self.subTest(bad=bad),self.assertRaises(ContractError):handle(bad,lambda:self.fail('no shared session'))

    def test_same_category_and_keyword_are_validated_not_assumed_from_http_success(self):
        for raw in (model(cid=10203),model(gid=1),model(title='Another player')):
            with self.assertRaises(ContractError):self.invoke(self.search(),[response([raw],1)])

    def test_model_chain_has_one_aggregate_deadline_and_no_second_request_after_expiry(self):
        session=Session([detail(model())]);reader=AdminRead(session,catalog_get_once=session.get_admin,catalog_timeout=0.01)
        reader.begin_catalog_read();reader.catalog_model('500');time.sleep(0.02)
        with self.assertRaisesRegex(ContractError,'CATALOG_SEARCH_TIMEOUT'):
            reader.search_goods_page('266','1327',model_id='500',category_id='9627',limit=10)
        self.assertEqual(len(session.calls),1)


if __name__=='__main__':unittest.main()
