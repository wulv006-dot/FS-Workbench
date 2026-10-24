import contextlib,io,json,runpy,sys,types,unittest
from pathlib import Path
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]/'auth-recovery/source/supplement_reader.py'


class SharedAdmin(unittest.TestCase):
    def execute(self,replies):
        sent=[]
        class Manager:
            def __init__(self,config):pass
            def ensure(self):raise AssertionError('independent login forbidden')
            def request(self,path,data,token):
                sent.append((path,data,token));return 200,json.dumps({'code':1,'data':{'total':3,'amount':'4.25'}}).encode()
        def response(value):
            if isinstance(value,Exception):raise value
            return contextlib.closing(io.BytesIO(json.dumps(value).encode()))
        session=types.SimpleNamespace(SessionManager=Manager,read_private_config=lambda:{})
        fields=types.SimpleNamespace(extract=lambda v:{'metrics':{'newCustomers':{'value':2}},'dimensions':{'kept':True},'definitionVersion':'original'})
        requests=[dict(key=str(i),start='2026-10-23 00:00:00',end='2026-10-23 23:59:59',game=1327) for i in range(len(replies))]
        output=io.StringIO()
        with patch.dict(sys.modules,p2pah_session_service=session,supplement_fields=fields),patch.object(sys,'argv',[str(SOURCE),json.dumps(requests)]),patch('urllib.request.urlopen',side_effect=[response(r) if not isinstance(r,Exception) else r for r in replies]),contextlib.redirect_stdout(output):
            runpy.run_path(str(SOURCE),run_name='__main__')
        return json.loads(output.getvalue()),sent

    def test_each_read_borrows_current_token_without_login_or_refresh(self):
        result,sent=self.execute([{'ready':True,'token':'first-current'},{'ready':True,'token':'renewed-current'}])
        self.assertEqual([r[2] for r in sent],['first-current','renewed-current'])
        self.assertEqual(result['0']['status'],'available');self.assertEqual(result['0']['comparisonOnly'],{'orders':3,'revenueUsd':'4.25'})
        self.assertEqual(result['0']['newCustomers'],2);self.assertEqual(result['0']['dimensions'],{'kept':True})
        self.assertEqual(sent[0][1]['game'],1327)

    def test_unavailable_or_invalid_session_never_starts_own_login(self):
        result,sent=self.execute([{'ready':False,'token':None},{'ready':True,'token':'bad\nheader'}])
        self.assertEqual(sent,[]);self.assertTrue(all(r['status']=='unavailable' and r['newCustomers'] is None for r in result.values()))

    def test_local_endpoint_failure_is_original_per_row_unavailable(self):
        result,sent=self.execute([OSError('temporary local failure')])
        self.assertEqual(sent,[]);self.assertEqual(result['0']['status'],'unavailable')


if __name__=='__main__':unittest.main()
