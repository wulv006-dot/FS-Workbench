import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit, parse_qs

sys.path[:0]=[str(Path(__file__).parent/'candidate/hermes'),str(Path(__file__).resolve().parents[3]/'mmoexp_google_data/details')]
import es_order_structure as es
import admin_product_orders as product


def row(key='synthetic-1', discount='2', new='是', state='已完成', **extra):
    item={v:'' for v in es.COLUMNS.values()}
    item.update({'订单号':key,'游戏':'FC 27','付款时间':'2026/10/17 12:00:00','订单状态':state,'是否新客户':new,'订单金额（美元）':'10','实付币种':'EUR','实付金额':'9','折扣金额':discount,'优惠类型':'测试通用优惠','折扣比例':'0.8','折扣码':'synthetic-code'})
    item.update(extra)
    return item


class DiscountTest(unittest.TestCase):
    args={'profile':'FC27','start':'2026-10-17','end':'2026-10-17','group_by':'discount_new_customer'}
    def project(self,rows):return es.aggregate_rows(rows,['f'*64],0,self.args,1,0)
    def test_dedup_usd_missing_zero_and_status(self):
        rows=[row(),row(),row('synthetic-2','0',new='否'),row('synthetic-3','',new='',state='问题订单')]
        value=self.project(rows)
        self.assertEqual(value['discount_totals'],{'orders':3,'known_discount_orders':2,'unknown_discount_orders':1,'discount_amount_usd':'2'})
        self.assertEqual(value['quality']['duplicate_records'],1)
        self.assertEqual(value['quality']['original_paid_by_currency'],{'EUR':'27'})
        self.assertEqual(len(value['groups']),3)
        self.assertIsNone(next(g for g in value['groups'] if g['new_customer']=='新老客未知')['discount_amount_usd'])
        self.assertEqual(next(g for g in value['groups'] if g['new_customer']=='老客订单')['discount_amount_usd'],'0')
        self.assertNotIn('synthetic-code',json.dumps(value))
    def test_conflict_excluded_and_no_causal_or_net_claim(self):
        value=self.project([row(),row(discount='3')])
        self.assertEqual(value['quality']['ambiguous_orders'],1)
        self.assertIsNone(value['discount_totals']['discount_amount_usd'])
        self.assertEqual(value['quality']['refund_discount_reversal'],'unknown; original discount is not retained net discount')
        self.assertIsNone(value['quality']['discount_rate'])
    def test_private_dataset_keeps_discount_not_identity_or_code(self):
        private=es.make_dataset([row()],['a'*64],0,1,0)
        item=private['rows'][0]
        self.assertEqual(item['折扣金额'],'2')
        self.assertNotEqual(item['订单号'],'synthetic-1')
        self.assertNotIn('折扣码',item)
        self.assertTrue(item['_has_discount_code'])
        value=self.project(private['rows'])
        self.assertEqual(value['discount_totals']['discount_amount_usd'],'2')
    def test_signed_amount_and_old_projection_unchanged(self):
        rows=[row(discount='-1.25')]
        self.assertEqual(self.project(rows)['discount_totals']['discount_amount_usd'],'-1.25')
        value=es.aggregate_rows(rows,['f'*64],0,dict(self.args,group_by='status'),1,0)
        self.assertEqual(value['structure_totals']['order_amount_usd'],'10')
        self.assertNotIn('discount_totals',value)
    def test_no_discount_column_is_unknown(self):
        item=row();item.pop('折扣金额')
        value=self.project([item])
        self.assertEqual(value['status'],'partial')
        self.assertIsNone(value['discount_totals']['discount_amount_usd'])


class ProductTest(unittest.TestCase):
    args={'profile':'FC27','model_id':123,'start':'2026-10-17','end':'2026-10-17','platform':'XBOX'}
    def request(self,path,timeout):
        self.paths.append(path)
        params=parse_qs(urlsplit(path).query)
        if path.startswith('/admin/goods.Goods/index'):
            data={'total':3,'list':[{'id':id,'mid':123,'site_id':266,'gid':1327,'cid':10255,'aid':aid,'title':'Synthetic Pack','gameArea':{'title':name}} for (p,(aid,name)),id in zip(product.AREAS.items(),(1001,1002,1003))]}
        else:
            self.assertEqual(params['search[3][val]'],['1002'])
            self.assertEqual(params['search[4][field]'],['paytime'])
            content='<em class="game">FC 27 >>></em><em class="area">[Xbox Series X|S] </em><span class="item">　☑In-Game Packs - Synthetic Pack x 1 = ￡3.50, </span>'
            rows=[{'site_id':266,'gid':1327,'order_no':'synthetic-private-order','email':'private@example.invalid','paytime':'2026-10-17 12:00:00','amount':'9','currency_code':'GBP','status_format':'已完成','pay_status_format':'Paid','content':content}]
            data={'total':1,'list':rows}
        return 200,json.dumps({'code':1,'data':data}).encode()
    def test_live_mapping_and_whole_vs_line_money(self):
        self.paths=[]
        value=product.collect(self.request,self.args)
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['totals']['order_amount_usd'],'9')
        self.assertEqual(value['products'][0]['groups'][0]['item_line_by_currency'],{'GBP':'3.50'})
        self.assertNotIn('private@example',json.dumps(value))
        self.assertNotIn('synthetic-private-order',json.dumps(value))
        self.assertEqual(len(self.paths),2)
    def test_scope_failure_is_not_zero(self):
        def bad(path,timeout):return 200,json.dumps({'code':1,'data':{'total':0,'list':[]}}).encode()
        value=product.collect(bad,self.args)
        self.assertEqual(value['status'],'unavailable')
        self.assertIsNone(value['totals'])
    def test_arbitrary_urls_keys_all_id_rejected(self):
        for extra in ({'url':'https://evil.invalid'},{'product_id':1002},{'site_id':0}):
            with self.assertRaises(ValueError):product.checked_query(dict(self.args,**extra))
    def test_partial_page_limit_not_full_zero(self):
        self.paths=[]
        def incomplete(path,timeout):
            code,raw=self.request(path,timeout)
            value=json.loads(raw)
            if path.startswith('/admin/order.Order/index'):value['data']['total']=11
            return code,json.dumps(value).encode()
        value=product.collect(incomplete,dict(self.args,max_pages=1))
        self.assertEqual(value['status'],'partial')
        self.assertFalse(value['quality']['complete'])
    def test_mixed_platform_order_usd_once_and_line_platform_context(self):
        self.paths=[]
        def mixed(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):return self.request(path,timeout)
            pid=int(parse_qs(urlsplit(path).query)['search[3][val]'][0])
            if pid==1003:return 200,json.dumps({'code':1,'data':{'total':0,'list':[]}}).encode()
            content='<em class="game">FC 27 >>></em><em class="area">[PC Platform]</em><span class="item">☑In-Game Packs - Synthetic Pack x 2 = ￡5.50, </span><em class="area">[Xbox Series X|S]</em><span class="item">☑In-Game Packs - Synthetic Pack x 1 = ￡3.50, </span>'
            r={'site_id':266,'gid':1327,'order_no':'synthetic-mixed','paytime':'2026-10-17 12:00:00','amount':'9','currency_code':'GBP','status_format':'已完成','pay_status_format':'Paid','content':content}
            return 200,json.dumps({'code':1,'data':{'total':1,'list':[r]}}).encode()
        value=product.collect(mixed,dict(self.args,platform='ALL'))
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['totals']['distinct_orders'],1)
        self.assertEqual(value['totals']['order_amount_usd'],'9')
        by_platform={p['platform']:p for p in value['products']}
        self.assertEqual(by_platform['PC']['groups'][0]['quantity'],'2')
        self.assertEqual(by_platform['XBOX']['groups'][0]['quantity'],'1')
        self.assertEqual(by_platform['PC']['groups'][0]['item_line_by_currency'],{'GBP':'5.50'})
        self.assertEqual(by_platform['XBOX']['groups'][0]['item_line_by_currency'],{'GBP':'3.50'})


if __name__=='__main__':unittest.main()
