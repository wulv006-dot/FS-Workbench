import importlib.util,io,json,sys,threading,types,unittest
from pathlib import Path
from unittest.mock import patch
from .capabilities import CONTRACT

HERE=Path(__file__).parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class WiringTests(unittest.TestCase):
    def session(self):
        with patch.dict(sys.modules,{'ddddocr':types.SimpleNamespace()}):
            return load('capability_session',HERE/'shared_candidate/p2pah_session_service.py')

    def test_running_manager_projection_never_initializes_or_renews_auth(self):
        module=self.session();manager=module.SessionManager.__new__(module.SessionManager)
        manager.lock=threading.RLock();manager.token='synthetic-private-token';calls=[]
        manager.ensure=lambda: (_ for _ in ()).throw(AssertionError('new login forbidden'))
        manager.identity_ok=lambda token:token==manager.token
        def read(path,**kwargs):
            calls.append((path,kwargs['token']))
            return 200,json.dumps({'code':1,'data':{'data':{'total':0,'amount':'0','game_rank':{},'site_rank':{}}}}).encode()
        manager.request=read
        result=manager.fc_capability({'kind':'native_loss','profile':'FC27','start':'2026-10-05','end':'2026-10-11'})
        self.assertEqual(result['contract'],CONTRACT);self.assertEqual(result['source_orders'],0)
        self.assertEqual(len(calls),1);self.assertNotIn('synthetic-private-token',json.dumps(result))
        manager.token=None;manager.identity_ok=lambda _:False
        self.assertEqual(manager.fc_capability({'kind':'native_loss','profile':'FC27','start':'2026-10-05','end':'2026-10-11'})['reason'],'existing_auth_unavailable')
        self.assertEqual(len(calls),1)

    def test_session_post_is_closed_and_only_returns_projected_result(self):
        module=self.session();handlers=[]
        class Server:
            def __init__(self,address,handler):handlers.append(handler)
            def serve_forever(self):pass
        class Manager:
            def fc_capability(self,q):
                from .capabilities import collect_admin
                return collect_admin(lambda *_:(200,b'{"code":1,"data":{"data":{"total":0,"amount":"0","game_rank":{},"site_rank":{}}}}'),q,{'enabled':True,'game_id':1327,'main_site_id':266})
        with patch.object(module,'ThreadingHTTPServer',Server):module.serve(Manager())
        def post(body,path='/business/fc-capability'):
            h=handlers[0].__new__(handlers[0]);raw=json.dumps(body).encode();h.path=path;h.headers={'Content-Length':str(len(raw))};h.rfile=io.BytesIO(raw);h.wfile=io.BytesIO();codes=[]
            h.send_response=lambda code:codes.append(code);h.send_header=lambda *_:None;h.end_headers=lambda:None;h.send_error=lambda code:codes.append(code)
            h.do_POST();return codes[0],h.wfile.getvalue()
        status,raw=post({'kind':'native_loss','profile':'FC27','start':'2026-10-05','end':'2026-10-11'})
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['scope']['admin_site_id'],266)
        for extra in ('url','token','role','endpoint'):
            status,_=post({'kind':'native_loss','profile':'FC27','start':'2026-10-05','end':'2026-10-11',extra:'forbidden'})
            self.assertEqual(status,400)
        self.assertEqual(post({},'/arbitrary/admin/proxy')[0],404)

    def test_existing_order_loop_projects_actual_opened_detail_and_preserves_legacy(self):
        diagnostics=load('cap_diagnostics_fixture',HERE/'shared_candidate/fc_order_diagnostics.py')
        paths=[]
        class Reader:
            def problem_order_page(self, page, *, timeout):
                paths.append(page)
                return [{'id':'12','platform':'PS','amount_usd':10,'detail':'/order/admin_order/look/id/12.html'}],False

            def problem_order_events(self, order, *, timeout):
                self.detail(order)
                return {'items':[{'gid':'1322','qty':'100','used':'20','unit':'K'}],
                        'events':[{'id':'7','time':'26-10-14 01:00:00','status':'问题单'}],
                        'item_count':1,'event_count':1}

            def problem_order_logs(self, order, *, timeout):
                self.detail(order)
                return [{'time':'26-10-14 01:00:00','status':'问题单','content':'等待客户回复'}]

            @staticmethod
            def detail(order):
                paths.append(order)

        with patch.dict(sys.modules,{'fc_order_diagnostics':diagnostics}):
            reader=load('cap_reader_fixture',HERE/'shared_candidate/fc_order_reader.py')
        result=reader.run({'platform':'PS','pages':1,'samples':1},reader=Reader())
        self.assertEqual(result['contract'],'fc-order-events-raw-v1')
        self.assertEqual(result['samples'][0]['events'][0]['id'],'7')
        legacy=reader.run(reader=Reader())
        self.assertEqual(legacy['contract'],'fc-order-problem-clues-v1')
        self.assertEqual(legacy['samples'][0]['category'],'customer_wait')
        self.assertEqual(paths,[1,'12',1,'12'])
        self.assertNotIn('等待客户回复',json.dumps(result,ensure_ascii=False))

if __name__=='__main__':unittest.main()
