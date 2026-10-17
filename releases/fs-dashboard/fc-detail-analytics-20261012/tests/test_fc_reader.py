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
