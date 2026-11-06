import importlib.util,json,sys,types,unittest
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'source'))
dummy=types.ModuleType('p2pah_session_service');dummy.SessionManager=object;dummy.read_private_config=lambda:None
with patch.dict(sys.modules,{'p2pah_session_service':dummy}):
    spec=importlib.util.spec_from_file_location('detail_reader',ROOT/'source/fc_detail_reader.py')
    reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)
from test_fc_detail import raw,CFG
class ReaderTest(unittest.TestCase):
    def test_shipping_membership_classifies_before_current_backlog_and_does_not_skip_unknown_active(self):
        events=[];exact_lookups=[]
        def source(n,paid):
            return raw(n,paytime=paid,content='<span class="item">Synthetic x 1 = $20</span>',site={'full_title':'www.mmoexp.com'})
        def request(path):
            if 'siteList' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':266}]}})
            p={k:v[0] for k,v in parse_qs(urlsplit(path).query).items()}
            fields={p[k]:p[k.replace('[field]','[val]')] for k in p if k.endswith('[field]')}
            if 'order_no' in fields:
                exact_lookups.append(fields['order_no']);rows=[source(2,'2026-10-09 12:00:00')]
            elif 'progress' in fields:rows=[source(2,'2026-10-09 12:00:00')] if fields['progress']=='1' else []
            else:rows=[source(3,'2026-10-11 12:00:00')]
            return 200,json.dumps({'code':1,'data':{'total':len(rows),'list':rows}})
        def native(read,pages,rows,period,config):
            events.append([r['id'] for r in rows])
            for row in rows:
                row['_fc_native_items']=[dict(pid='10',goods={'id':'10','cid':'9623'},native_type='1')]
                row['_fc_items_complete']=True
            return {'9623':['1','9623']},{'status':'available'}
        shipping=lambda period:dict(rows=[dict(delivery_id='1',source='www.mmoexp.com',sn='TEST2',trade_at='2026-10-11 14:00:00',sale_total='100',cost_total='80')],coverage={'native_summary_reconciled':True})
        with patch('fc_dashboard.native_membership',native),patch.object(reader.time,'sleep',lambda n:None):
            result=reader.collect(request,{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},CFG,shipping_reader=shipping)
        self.assertEqual(events,[[3],[2],[2]])
        self.assertEqual(exact_lookups,['TEST2'])
        shipped=next(r for r in result['shipping_orders'] if r['id']=='TEST2')
        self.assertEqual(shipped['category_status'],'verified')
        self.assertEqual(result['backlog'][0]['category_status'],'verified')
    def test_native_same_page_adjacent_exact_duplicates_are_dropped(self):
        rows,dropped=reader.native_page_rows([raw(3),raw(3),raw(2)],set())
        self.assertEqual([r['id'] for r in rows],[3,2]);self.assertEqual(dropped,1)
    def test_native_cross_page_duplicate_or_same_page_conflict_is_rejected(self):
        for rows,seen in (([raw(3)],{3}),([raw(3),raw(3,amount='21')],set()),([raw(3),raw(2),raw(3)],set())):
            with self.subTest(rows=rows),self.assertRaisesRegex(ValueError,'duplicate_page_records'):
                reader.native_page_rows(rows,seen)
    def test_native_total_uses_original_rows_and_unique_membership_is_separate(self):
        def request(path):
            if 'siteList' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':266}]}})
            if 'categorySelect' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':1,'children':[{'id':9623}]}]}})
            if 'productSalesByEs' in path:return 200,json.dumps({'code':1,'data':{'total':1,'list':[dict(pid=10,gid=1327,cid=1,goods={'id':10,'cid':9623})]}})
            p={k:v[0] for k,v in parse_qs(urlsplit(path).query).items()}
            fields={p[k]:p[k.replace('[field]','[val]')] for k in p if k.endswith('[field]')}
            if 'progress' in fields:rows=[]
            elif 'pid' in fields:rows=[raw(3),raw(3),raw(2)]
            else:rows=[raw(3),raw(2)]
            for row in rows:row['content']='<span class="item">Synthetic x 1 = $20</span>'
            page=int(p['page']);return 200,json.dumps({'code':1,'data':{'total':len(rows),'list':rows[(page-1)*2:page*2]}})
        with patch.object(reader.time,'sleep',lambda n:None):
            result=reader.collect(request,{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},{**CFG,'page_size':2},shipping_reader=lambda p:[])
        observation=next(r for r in result['coverage']['observations'] if r['dataset']=='native-pid-10')
        self.assertEqual(observation['source_total'],3)
        self.assertEqual(observation['received_source_rows'],3)
        self.assertEqual(observation['received'],2)
        self.assertEqual(observation['duplicatesDropped'],1)
        self.assertEqual({r['category'] for r in result['orders']},{'Coins'})
    def request(self,path):
        if 'site.Site/siteList' in path:return 200,json.dumps({'code':1,'data':{'list':[{'id':266},{'id':141}]}})
        p={k:v[0]for k,v in parse_qs(urlsplit(path).query).items()}
        progress=next((p[k.replace('[field]','[val]')]for k,v in p.items()if k.endswith('[field]') and v=='progress'),None)
        self.assertEqual(p.get('order'),None if progress else 'id,desc')
        rows=[raw(3),raw(2),raw(1)] if progress is None else []
        page=int(p['page']);return 200,json.dumps({'code':1,'data':{'total':len(rows),'list':rows[(page-1)*2:page*2]}})
    def test_complete_pagination_and_separate_current_queries(self):
        with patch.object(reader.time,'sleep',lambda n:None):result=reader.collect(self.request,{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},{**CFG,'page_size':2})
        self.assertEqual(len(result['orders']),3);self.assertEqual(len(result['coverage']['observations']),10)
        self.assertEqual(result['coverage']['stable_sort'],'source_id_descending')
    def test_timeout_retries_same_read_only_page(self):
        calls=[]
        def request(path):
            calls.append(path)
            if len(calls)==1:raise TimeoutError()
            return self.request(path)
        with patch.object(reader.time,'sleep',lambda n:None):reader.collect(request,{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},{**CFG,'page_size':2})
        self.assertEqual(calls[0],calls[1])
    def test_wrong_game_is_not_published(self):
        def request(path):
            status,body=self.request(path);data=json.loads(body)
            if 'order.Order/index' in path and data['data']['list']:data['data']['list'][0]['gid']=1329
            return status,json.dumps(data)
        with self.assertRaisesRegex(ValueError,'filter_not_applied'):reader.collect(request,{'period':{'start':'2026-10-11 00:00','end':'2026-10-12 00:00'}},{**CFG,'page_size':2})
if __name__=='__main__':unittest.main()
