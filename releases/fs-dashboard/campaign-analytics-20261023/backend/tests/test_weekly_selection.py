import copy
import unittest
from campaign_backend.weekly import weekly_selection
from campaign_backend.core import ContractError

class Reader:
    def __init__(self):
        self.tags=[dict(id=1,name='Popular',gid=1327,cate_id=['9627'],status=1)]
        self.players=[dict(id=i,gid=1327,cid=9627,title='Player '+str(i),status=1,auto_off=0,is_put=1,tid=['1'],shelf_time=100,more={}) for i in range(20,0,-1)]
        self.cores=[dict(self.players[0],id=30,cid=10203,title='SBC Player')]
    def begin_catalog_read(self):pass
    def _get_catalog_once(self,route,**kwargs):
        if 'categorySelect' in route:return {'list':[{'id':9627,'title':'Players','children':[]},{'id':9625,'title':'SBC','children':[{'id':10203,'title':'SBC Players','children':[]}]}]}
        if 'GoodsTag' in route:return {'list':copy.deepcopy(self.tags),'total':len(self.tags)}
        # Exact gid/cid filters are serialized by the existing adapter.
        rows=self.cores if '10203' in str(kwargs) else self.players
        return {'list':copy.deepcopy(rows),'total':len(rows)}
    def search_goods_page(self,site,game,model_id,category_id,**kwargs):
        return {'total':3,'rows':[dict(id=int(model_id)*10+i,mid=int(model_id),cid=int(category_id),site_id=266,gid=1327,aid=aid,sid=7645,status=1,auto_off=0,num=1,min_qty=1,unit='',attr_switch=1,sku_switch=0) for i,aid in enumerate([21587,21585,21589])],'has_more':False}
    def catalog_goods(self,goods_id):
        mid=int(goods_id)//10;cid='10203' if mid==30 else '9627'
        return dict(self.search_goods_page('266','1327',str(mid),cid)['rows'][int(goods_id)%10],more={'saleprop':[],'skuTableSet':[]},unit_price=10,discount=100)

class WeeklyTests(unittest.TestCase):
    def test_dynamic_tag_order_and_real_identity_without_sellability_claim(self):
        result=weekly_selection(Reader())
        self.assertEqual(result['scout_model_ids'],['20','19','18'])
        self.assertEqual(result['sbc_model_ids'],['30'])
        self.assertEqual(result['evidence']['popular_tag_id'],'1')
        self.assertEqual(len(result['models']),17)
        self.assertFalse(result['authoritative_quote'])
        self.assertTrue(all(not row['available'] for row in result['models']))
        self.assertTrue(result['observations'][0]['platforms'][0]['attributes_required'])
    def test_duplicate_active_tag_is_not_silently_selected(self):
        reader=Reader();reader.tags.append(dict(reader.tags[0],id=2))
        with self.assertRaisesRegex(ContractError,'WEEKLY_POPULAR_TAG_AMBIGUOUS'):weekly_selection(reader)
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
