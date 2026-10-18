import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlsplit, parse_qs

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE/'source'))
sys.path.insert(0,str(PACKAGE.parent/'admin-data-tools-20261018/candidate/hermes'))
sys.path.insert(0,str(PACKAGE.parents[2]/'mmoexp_google_data/details'))
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

    def test_direct_pid_d4_and_aion2_are_game_scoped_without_line_guess(self):
        for profile,gid in (('D4',456),('AION2',891)):
            paths=[]
            def direct(path,timeout):
                paths.append(path)
                params=parse_qs(urlsplit(path).query)
                if path.startswith('/admin/goods.Goods/index'):
                    self.assertEqual(params['search[0][field]'],['id'])
                    data={'total':1,'list':[{'id':8123,'site_id':266,'gid':gid,'title':'Synthetic Item','gameArea':{'title':'Main'}}]}
                else:
                    self.assertEqual(params['search[1][val]'],[str(gid)])
                    self.assertEqual(params['search[2][val]'],['8123'])
                    data={'total':1,'list':[{'id':91,'site_id':266,'gid':gid,'pid':8123,'pay_status':1,
                        'order_no':'synthetic-private-order','paytime':'2026-10-17 12:00:00','amount':'9',
                        'status_format':'Completed','pay_status_format':'Paid','email':'private@example.invalid'}]}
                return 200,json.dumps({'code':1,'data':data}).encode()
            value=product.collect(direct,{'profile':profile,'product_id':8123,'start':'2026-10-17','end':'2026-10-17'})
            self.assertEqual(value['status'],'available')
            self.assertEqual(value['totals']['order_amount_usd'],'9')
            self.assertIsNone(value['products'][0]['groups'][0]['quantity'])
            self.assertNotIn('private@example',json.dumps(value))
            self.assertEqual(len(paths),2)

    def test_direct_pid_rejects_cross_game_and_ambiguous_goods(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def wrong(path,timeout):
            return 200,json.dumps({'code':1,'data':{'total':1,'list':[{'id':8123,'site_id':266,'gid':891,'title':'Synthetic'}]}}).encode()
        self.assertEqual(product.collect(wrong,q)['status'],'unavailable')
        with self.assertRaises(ValueError):product.checked_query(dict(q,platform='ALL'))

    def test_direct_pid_exact_game_area_title_line_quantity(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':8123,'site_id':266,'gid':456,'title':'Synthetic Item',
                    'gameArea':{'title':'Seasonal'}}]
            else:
                content='<em class="game">Diablo 4 &gt;&gt;&gt;</em><em class="area">[Seasonal]</em><span class="item">Gold - Synthetic Item x 2 = $5.00</span>'
                rows=[{'id':9,'site_id':266,'gid':456,'pid':8123,'order_no':'private-order',
                    'paytime':'2026-10-17 12:00:00','amount':'8','currency_code':'USD',
                    'status_format':'Completed','pay_status_format':'Paid','content':content}]
            return 200,json.dumps({'code':1,'data':{'total':1,'list':rows}}).encode()
        value=product.collect(request,q)
        self.assertEqual(value['status'],'available')
        group=value['products'][0]['groups'][0]
        self.assertEqual(group['quantity'],'2')
        self.assertEqual(group['item_line_by_currency'],{'USD':'5.00'})
        self.assertEqual(value['totals']['order_amount_usd'],'8')

    def test_direct_pid_real_d4_multiline_item_and_stable_pages(self):
        q={'profile':'D4','product_id':1365865,'start':'2026-10-17','end':'2026-10-17'}
        content=('<em class="game">Diablo 4 &gt;&gt;&gt;</em>'
            '<em class="area">[Season 15 Softcore] </em>'
            '<span class="item">　☑Lair Boss Key - Synthetic Key x 2 = ￡2.94, <br>'
            '　☑350000 M Diablo IV Gold x 1 = ￡1.24, </span>')
        def request(path,timeout):
            params=parse_qs(urlsplit(path).query)
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':1365865,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}];total=1
            else:
                self.assertEqual(params['limit'],['100'])
                self.assertEqual(params['order'],['id,desc'])
                page=int(params['page'][0])
                ids=range(200,100,-1) if page==1 else [100]
                rows=[{'id':str(row_id),'site_id':266,'gid':456,
                    'order_no':'private-'+str(row_id),'paytime':'2026-10-17 12:00:00',
                    'amount':'8','currency_code':'GBP','status_format':'Completed',
                    'pay_status_format':'Paid','content':content} for row_id in ids] if page<=2 else []
                total=101
            return 200,json.dumps({'code':1,'data':{'total':total,'list':rows}}).encode()
        value=product.collect(request,q)
        self.assertEqual(value['status'],'available')
        group=value['products'][0]['groups'][0]
        self.assertEqual(group['known_line_orders'],101)
        self.assertEqual(group['mixed_orders'],101)
        self.assertEqual(group['quantity'],'101')
        self.assertEqual(group['item_line_by_currency'],{'GBP':'125.24'})
        coverage=value['products'][0]['coverage']
        self.assertTrue(coverage['order_id_desc_verified'])
        self.assertEqual(coverage['row_id_types'],{'int':0,'numeric_string':101,'other':0})
        self.assertEqual(coverage['received_source_rows'],101)
        self.assertEqual(coverage['unique_numeric_row_ids'],101)

    def test_direct_pid_no_target_line_does_not_claim_mixed_order(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':8123,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}]
            else:
                rows=[{'id':9,'site_id':266,'gid':456,'order_no':'private-order',
                    'paytime':'2026-10-17 12:00:00','amount':'8','currency_code':'GBP',
                    'status_format':'Completed','pay_status_format':'Paid',
                    'content':'<span class="item">☑350000 M Diablo IV Gold x 1 = ￡1.24</span>'}]
            return 200,json.dumps({'code':1,'data':{'total':1,'list':rows}}).encode()
        group=product.collect(request,q)['products'][0]['groups'][0]
        self.assertEqual(group['known_line_orders'],0)
        self.assertEqual(group['mixed_orders'],0)

    def test_direct_pid_repeated_page_boundary_stays_partial(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':8123,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}];total=1
            else:
                page=int(parse_qs(urlsplit(path).query)['page'][0])
                ids=list(range(200,100,-1)) if page==1 else [101]
                rows=[{'id':row_id,'site_id':266,'gid':456,'order_no':'private-'+str(row_id),
                    'paytime':'2026-10-17 12:00:00','amount':'8','currency_code':'GBP',
                    'status_format':'Completed','pay_status_format':'Paid'} for row_id in ids]
                total=101
            return 200,json.dumps({'code':1,'data':{'total':total,'list':rows}}).encode()
        value=product.collect(request,q)
        self.assertEqual(value['status'],'partial')
        coverage=value['products'][0]['coverage']
        self.assertEqual(coverage['duplicate_orders'],1)
        self.assertEqual(coverage['received_unique_orders'],100)
        self.assertEqual(coverage['received_source_rows'],101)
        self.assertTrue(coverage['source_rows_complete'])
        self.assertEqual(coverage['duplicate_order_same_row_id'],1)
        self.assertEqual(coverage['duplicate_order_distinct_row_id'],0)
        self.assertFalse(coverage['order_id_desc_verified'])
        self.assertFalse(coverage['complete'])

    def test_direct_pid_real_34_source_rows_33_orders_same_page(self):
        q={'profile':'D4','product_id':1365865,'start':'2026-10-17','end':'2026-10-17'}
        content=('<em class="game">Diablo 4 &gt;&gt;&gt;</em>'
            '<em class="area">[Season 15 Softcore]</em><span class="item">'
            '☑Lair Boss Key x 1 = $1.00, <br>☑350000 M Diablo IV Gold x 1 = $1.24,</span>')
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':1365865,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}];total=1
            else:
                ids=list(range(200,167,-1));ids.insert(10,ids[9])
                rows=[{'id':row_id,'site_id':266,'gid':456,'order_no':'private-'+str(row_id),
                    'paytime':'2026-10-17 12:00:00','amount':'8','currency_code':'USD',
                    'status_format':'Completed','pay_status_format':'Paid',
                    'content':'' if row_id==168 else content} for row_id in ids]
                total=34
            return 200,json.dumps({'code':1,'data':{'total':total,'list':rows}}).encode()
        value=product.collect(request,q)
        self.assertEqual(value['status'],'available')
        self.assertEqual(value['totals']['distinct_orders'],33)
        coverage=value['products'][0]['coverage']
        self.assertEqual(coverage['source_total'],34)
        self.assertEqual(coverage['received_source_rows'],34)
        self.assertTrue(coverage['source_rows_complete'])
        self.assertTrue(coverage['order_id_desc_verified'])
        self.assertEqual(coverage['unique_numeric_row_ids'],33)
        self.assertEqual(coverage['duplicate_order_same_row_id'],1)
        self.assertEqual(coverage['duplicate_order_distinct_row_id'],0)
        self.assertEqual(coverage['duplicate_order_conflicts'],0)
        self.assertTrue(coverage['complete'])
        group=value['products'][0]['groups'][0]
        self.assertEqual(group['known_line_orders'],32)
        self.assertIsNone(group['quantity'])

    def test_direct_pid_nonadjacent_repeated_row_id_is_incomplete(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':8123,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}];total=1
            else:
                rows=[{'id':row_id,'site_id':266,'gid':456,'order_no':'private-'+str(row_id),
                    'paytime':'2026-10-17 12:00:00','amount':'8','currency_code':'USD',
                    'status_format':'Completed','pay_status_format':'Paid'} for row_id in (9,8,9)]
                total=3
            return 200,json.dumps({'code':1,'data':{'total':total,'list':rows}}).encode()
        coverage=product.collect(request,q)['products'][0]['coverage']
        self.assertTrue(coverage['source_rows_complete'])
        self.assertFalse(coverage['order_id_desc_verified'])
        self.assertFalse(coverage['complete'])

    def test_direct_pid_same_order_number_distinct_source_rows_stays_partial(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':8123,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}];total=1
            else:
                rows=[{'id':row_id,'site_id':266,'gid':456,'order_no':'private-shared',
                    'paytime':'2026-10-17 12:00:00','amount':'8','currency_code':'GBP',
                    'status_format':'Completed','pay_status_format':'Paid'} for row_id in (9,8)]
                total=2
            return 200,json.dumps({'code':1,'data':{'total':total,'list':rows}}).encode()
        value=product.collect(request,q)
        self.assertEqual(value['status'],'partial')
        coverage=value['products'][0]['coverage']
        self.assertTrue(coverage['order_id_desc_verified'])
        self.assertEqual(coverage['unique_numeric_row_ids'],2)
        self.assertEqual(coverage['duplicate_order_same_row_id'],0)
        self.assertEqual(coverage['duplicate_order_distinct_row_id'],1)
        self.assertFalse(coverage['complete'])

    def test_direct_pid_same_row_id_conflicting_projection_stays_partial(self):
        q={'profile':'D4','product_id':8123,'start':'2026-10-17','end':'2026-10-17'}
        def request(path,timeout):
            if path.startswith('/admin/goods.Goods/index'):
                rows=[{'id':8123,'site_id':266,'gid':456,'title':'Diablo IV Gold',
                    'gameArea':{'title':'Season 15 Softcore'}}];total=1
            else:
                rows=[{'id':9,'site_id':266,'gid':456,'order_no':'private-shared',
                    'paytime':'2026-10-17 12:00:00','amount':str(amount),
                    'currency_code':'USD','status_format':'Completed',
                    'pay_status_format':'Paid'} for amount in (8,9)]
                total=2
            return 200,json.dumps({'code':1,'data':{'total':total,'list':rows}}).encode()
        value=product.collect(request,q)
        self.assertEqual(value['status'],'partial')
        coverage=value['products'][0]['coverage']
        self.assertTrue(coverage['source_rows_complete'])
        self.assertEqual(coverage['duplicate_order_same_row_id'],1)
        self.assertEqual(coverage['duplicate_order_conflicts'],1)
        self.assertFalse(coverage['order_id_desc_verified'])
        self.assertFalse(coverage['complete'])


if __name__=='__main__':unittest.main()
