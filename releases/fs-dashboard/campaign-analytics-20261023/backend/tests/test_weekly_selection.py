import copy
import unittest
import json
from unittest.mock import patch,MagicMock
from urllib.parse import parse_qs
from campaign_backend.adapters import AdminRead
from campaign_backend.weekly import weekly_selection
from campaign_backend.core import ContractError
from campaign_backend.models import player_type

def normal():
    return {'baseprop':[dict(id=393,name='PlayersType',default={'checked_item':8067},pvs=[dict(id=8067,prop_id=393,name='normal',status=1,checked=True)])]}

class Reader:
    def __init__(self):
        self.tags=[dict(id=1,name='Popular',gid=1327,cate_id=['9627'],status=1),dict(id=2,name='Newest',gid=1327,cate_id=['9627'],status=1)]
        self.players=[dict(id=i,gid=1327,cid=9627,title='Player '+str(i),status=1,auto_off=0,is_put=1,tid=['1','2'],shelf_time=100,more=normal()) for i in range(20,0,-1)]
        self.cores=[dict(self.players[0],id=i,cid=10203,title='SBC Player') for i in range(108,99,-1)]
        self.bundles=[dict(self.players[0],id=i,cid=10255,title='Configured Bundle '+str(i)) for i in range(201,205)]
    def begin_catalog_read(self):pass
    def catalog_model(self,model_id):
        return copy.deepcopy(next(x for x in self.players+self.cores+self.bundles if str(x['id'])==str(model_id)))
    def storefront_popular_page(self,tag_id,page=1):
        rows=getattr(self,'public_order',self.players)
        return dict(total=len(rows),rows=[dict(mid=x['id'],site_id=266,gid=1327,cid=9627,aid=21587,baseprop={'393':{'code':'players_type','name':player_type(x)}}) for x in rows[(page-1)*12:page*12]])
    def _get_catalog_once(self,route,**kwargs):
        if 'categorySelect' in route:return {'list':[{'id':9627,'title':'Players','children':[]},{'id':9625,'title':'SBC','children':[{'id':10203,'title':'SBC Players','children':[]}]}]}
        if 'GoodsTag' in route:return {'list':copy.deepcopy(self.tags),'total':len(self.tags)}
        # Exact gid/cid filters are serialized by the existing adapter.
        rows=self.cores if '10203' in str(kwargs) else self.players
        start=(kwargs.get('page',1)-1)*kwargs.get('limit',200)
        return {'list':copy.deepcopy(rows[start:start+kwargs.get('limit',200)]),'total':len(rows)}
    def search_goods_page(self,site,game,model_id,category_id,**kwargs):
        return {'total':3,'rows':[dict(id=int(model_id)*10+i,mid=int(model_id),cid=int(category_id),site_id=266,gid=1327,aid=aid,sid=7645,status=1,auto_off=0,num=1,min_qty=1,unit='',attr_switch=1,sku_switch=0) for i,aid in enumerate([21587,21585,21589])],'has_more':False}
    def catalog_goods(self,goods_id):
        mid=int(goods_id)//10;cid='10203' if mid in [x['id'] for x in self.cores] else '10255' if mid in [x['id'] for x in self.bundles] else '9627'
        return dict(self.search_goods_page('266','1327',str(mid),cid)['rows'][int(goods_id)%10],more={'saleprop':[],'skuTableSet':[]},unit_price=10,discount=100)

class WeeklyTests(unittest.TestCase):
    def test_configured_bundles_follow_real_legacy_goods_and_model_refs_not_entire_pack_category(self):
        reader=Reader();result=weekly_selection(reader,[{'goods_id':'2010'},{'model_id':'202'}])
        self.assertEqual(result['bundle_model_ids'],['201','202'])
        self.assertEqual(result['evidence']['configured_bundle_model_ids'],['201','202'])
        self.assertTrue(result['evidence']['bundles_complete'])
        bundles=[m for m in result['models'] if m['kind']=='bundle']
        self.assertEqual([m['model_id'] for m in bundles],['201','202'])
        self.assertTrue(all(p['state']=='verified' for m in bundles for p in m['platforms'].values()))
        self.assertEqual(result['scout_model_ids'],['20','19','18']);self.assertEqual(len(result['sbc_model_ids']),9)
        reader.bundles[0]['status']=0
        refreshed=weekly_selection(reader,[{'model_id':'201'},{'model_id':'204'}])
        self.assertEqual(refreshed['bundle_model_ids'],['204'])
        self.assertEqual(refreshed['evidence']['bundle_excluded'],[{'model_id':'201','reason':'not_currently_listed'}])
    def test_existing_management_bridge_passes_only_bounded_configured_bundle_refs(self):
        from bridge import handle
        reader=Reader();closed=[];reader.close=lambda:closed.append(True)
        result=handle(dict(action='weekly_selection',site_id='266',game_id='1327',bundle_refs=[{'goods_id':'2010'}]),reader_factory=lambda:reader)
        self.assertEqual(result['bundle_model_ids'],['201']);self.assertEqual(closed,[True])
        with self.assertRaisesRegex(ContractError,'WEEKLY_PROJECT_SCOPE_REQUIRED'):
            handle(dict(action='weekly_selection',site_id='266',game_id='1327',bundle_refs=[],extra=True),reader_factory=lambda:reader)

    def test_configured_bundle_scope_duplicate_and_shape_are_checked(self):
        for refs,code in [([{'goods_id':'200'}],'WEEKLY_BUNDLE_SCOPE_MISMATCH'),([{'model_id':'20'}],'WEEKLY_BUNDLE_SCOPE_MISMATCH'),([{'goods_id':'2010'},{'model_id':'201'}],'WEEKLY_BUNDLE_SELECTION_DUPLICATE'),([{'model_id':'201','goods_id':'2010'}],'WEEKLY_BUNDLE_SELECTION_INVALID')]:
            with self.subTest(code=code):
                with self.assertRaisesRegex(ContractError,code):weekly_selection(Reader(),refs)

    def test_newest_complete_scan_preserves_sixty_page_budget_beyond_1200(self):
        reader=Reader()
        reader.players=[dict(reader.players[0],id=i,tid=['1'] if i>330 else ['1','2']) for i in range(1600,299,-1)]
        result=weekly_selection(reader)
        self.assertEqual(result['evidence']['newest_scanned'],1301)
        self.assertEqual(result['evidence']['newest_normal_count'],31)
        self.assertTrue(result['evidence']['newest_complete'])
        self.assertEqual(result['trio_player_ids'],[str(i) for i in range(330,299,-1)])
    def test_trio_uses_complete_dynamic_newest_not_first_six_latest(self):
        reader=Reader();reader.tags[1]['id']=99
        reader.players=[dict(reader.players[0],id=i,tid=['1'] if i>330 else ['1','99']) for i in range(550,299,-1)]
        result=weekly_selection(reader)
        self.assertEqual(result['trio_player_ids'],[str(i) for i in range(330,299,-1)])
        self.assertEqual(len(result['latest_player_ids']),24)
        evidence=result['evidence'];self.assertEqual(evidence['newest_tag_id'],'99')
        self.assertEqual(evidence['newest_scanned'],251);self.assertEqual(evidence['newest_normal_count'],31)
        self.assertTrue(evidence['newest_complete'])
    def test_sbc_paginates_past_offline_first_page_for_ninth_core(self):
        reader=Reader()
        reader.cores=[dict(reader.cores[0],id=i,status=1 if i>192 or i==180 else 0) for i in range(200,167,-1)]
        result=weekly_selection(reader)
        self.assertEqual(result['sbc_model_ids'],[str(i) for i in range(200,192,-1)]+['180'])
        self.assertEqual(result['evidence']['sbc_total'],33)
    def test_public_reader_uses_exact_ajax_contract_without_private_session(self):
        response=MagicMock();response.__enter__.return_value=response
        response.geturl.return_value='https://www.mmoexp.com/ajax/goods'
        response.read.return_value=json.dumps({'goods':{'index':{'list':[],'total':0}}}).encode()
        with patch('campaign_backend.adapters.urllib.request.urlopen',return_value=response) as fetch:
            self.assertEqual(AdminRead.__new__(AdminRead).storefront_popular_page('12305'),{'rows':[],'total':0})
        request=fetch.call_args[0][0];body=parse_qs(request.data.decode(),keep_blank_values=True)
        self.assertEqual(body['top_cid'],['2']);self.assertEqual(body['category_id'],['']);self.assertEqual(body['keyword'],[''])
        self.assertEqual(request.get_header('X-requested-with'),'XMLHttpRequest');self.assertIsNone(request.get_header('Cookie'))
        self.assertEqual(fetch.call_args[1]['timeout'],20)
    def test_scout_uses_original_storefront_order_not_admin_sort(self):
        reader=Reader();reader.public_order=[reader.players[12],reader.players[16],reader.players[2]]
        result=weekly_selection(reader)
        self.assertEqual(result['scout_model_ids'],['8','4','18'])
        self.assertEqual(result['evidence']['popular_order'],'storefront_default_recommendation_priority')
    def test_normal_is_observed_and_latest_continues_past_signature_page(self):
        reader=Reader()
        extra=[dict(reader.players[0],id=i,more={}) for i in range(60,20,-1)]
        reader.players=extra+reader.players
        result=weekly_selection(reader)
        self.assertEqual(result['latest_player_ids'],[str(i) for i in range(20,0,-1)])
        self.assertEqual(result['trio_player_ids'],[str(i) for i in range(20,0,-1)])
        self.assertEqual(result['sbc_model_ids'],[str(i) for i in range(108,99,-1)])
        self.assertIsNone(player_type({'more':{}}))
        row={'more':normal()};row['more']['baseprop'][0]['pvs'][0]['checked']=False
        self.assertIsNone(player_type(row))

    def test_compact_admin_type_supports_24_normal_and_all_nine_cores(self):
        reader=Reader()
        reader.players=[dict(reader.players[0],id=i,more={'baseprop':{'393':{'a':8067}}}) for i in range(70,30,-1)]
        reader.players[0]['more']={'baseprop':{'393':{'a':8115}}}
        reader.players[1]['more']={}
        reader.cores=[dict(reader.cores[0],id=i,more={}) for i in range(29,20,-1)]
        result=weekly_selection(reader)
        self.assertEqual(result['latest_player_ids'],[str(i) for i in range(68,44,-1)])
        self.assertEqual(result['sbc_model_ids'],[str(i) for i in range(29,20,-1)])
        self.assertEqual(result['scout_model_ids'],['68','67','66'])
        self.assertEqual(player_type({'more':{'baseprop':{'393':{'a':8115}}}}),'Signature')

    def test_dynamic_tag_order_and_real_identity_without_sellability_claim(self):
        result=weekly_selection(Reader())
        self.assertEqual(result['scout_model_ids'],['20','19','18'])
        self.assertEqual(result['sbc_model_ids'],[str(i) for i in range(108,99,-1)])
        self.assertEqual(result['evidence']['popular_tag_id'],'1')
        self.assertEqual(len(result['models']),29)
        self.assertFalse(result['authoritative_quote'])
        self.assertTrue(all(not row['available'] for row in result['models']))
        self.assertTrue(result['observations'][0]['platforms'][0]['attributes_required'])
    def test_duplicate_active_tag_is_not_silently_selected(self):
        reader=Reader();reader.tags.append(dict(reader.tags[0],id=3))
        with self.assertRaisesRegex(ContractError,'WEEKLY_POPULAR_TAG_AMBIGUOUS'):weekly_selection(reader)
    def test_incomplete_nine_core_or_eighteen_normal_pool_is_explicit(self):
        reader=Reader();reader.cores=reader.cores[:8]
        with self.assertRaisesRegex(ContractError,'WEEKLY_SBC_CORE_COVERAGE_INCOMPLETE'):weekly_selection(reader)
        reader=Reader();reader.players=reader.players[:17]
        with self.assertRaisesRegex(ContractError,'WEEKLY_SBC_COMPANION_POOL_INSUFFICIENT'):weekly_selection(reader)
    def test_offline_tag_and_unordered_latest_fail(self):
        reader=Reader();reader.tags[0]['status']=0
        with self.assertRaisesRegex(ContractError,'WEEKLY_POPULAR_TAG_AMBIGUOUS'):weekly_selection(reader)
        reader=Reader();reader.players.reverse()
        with self.assertRaisesRegex(ContractError,'PAGINATION_ORDER_CHANGED'):weekly_selection(reader)
    def test_latest_population_keeps_actual_titles_and_versions(self):
        reader=Reader();reader.players[0]['title']='Real Player / Different Card Edition'
        result=weekly_selection(reader)
        self.assertEqual(result['models'][0]['title'],reader.players[0]['title'])
        self.assertIsNone(result['observations'][0]['created_at'])

if __name__=='__main__':unittest.main()
