import json
import http.client
import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch
from http.server import ThreadingHTTPServer

from _paths import ROOT, RELEASE
from tracking_private_session import PrivateReads
from tracking_controller import TrackingController
from customer_tracking import DEFAULT_CONFIG, candidate_rows


class Manager:
    def __init__(self):
        import threading
        self.lock=threading.RLock();self.token='test-only-token'
    def identity_ok(self,token,timeout=10):return token==self.token
    def request(self,path,token=None,timeout=10):return 200,b'{}'


class PrivateTests(unittest.TestCase):
    def test_disabling_daily_scan_does_not_stop_existing_tracking(self):
        with tempfile.TemporaryDirectory() as dirname:
            service=TrackingController(dirname,lambda user:user=='admin',client=object(),auto_start=False)
            service.store.save_config(dict(DEFAULT_CONFIG,enabled=False),1,'e'*32)
            calls=[]
            with patch.object(service.store,'due_histories',return_value=['f'*32]),\
                 patch.object(service,'_poll_history',side_effect=lambda *a,**k:calls.append('history')),\
                 patch.object(service,'_queue_reports',side_effect=lambda:calls.append('report')),\
                 patch('tracking_controller.time.sleep',side_effect=StopIteration):
                with self.assertRaises(StopIteration):service._daily_loop()
            self.assertEqual(calls,['history','report'])

    def test_private_http_rejects_missing_key_before_read(self):
        sys.modules.setdefault('ddddocr',types.SimpleNamespace(DdddOcr=lambda **_:None))
        path=RELEASE/'source'/'p2pah_session_service.py'
        spec=importlib.util.spec_from_file_location('candidate_session_http',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        class Reads:
            def __init__(self):self.calls=0
            def authorized(self,value):return value=='valid-test-key'
            def execute(self,value):self.calls+=1;return {'status':'available','count':0}
        manager=types.SimpleNamespace(customer_reads=Reads())
        captured=[]
        class Capture:
            def __init__(self,address,handler):captured.append(handler)
            def serve_forever(self):pass
        with patch.object(module,'ThreadingHTTPServer',Capture):module.serve(manager)
        server=ThreadingHTTPServer(('127.0.0.1',0),captured[0])
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def send(headers):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                conn.request('POST','/business/customer-tracking-private',body=b'{}',headers=headers)
                response=conn.getresponse();code=response.status;data=response.read();conn.close()
                return code,data
            self.assertEqual(send({'Content-Type':'application/json'})[0],403)
            self.assertEqual(manager.customer_reads.calls,0)
            code,data=send({'Content-Type':'application/json','X-FS-Customer-Tracking-Key':'valid-test-key'})
            self.assertEqual(code,200)
            self.assertEqual(json.loads(data)['status'],'available')
            self.assertEqual(manager.customer_reads.calls,1)
        finally:server.shutdown();server.server_close();thread.join(timeout=3)

    def test_private_key_required_and_query_deduplicated(self):
        with tempfile.TemporaryDirectory() as dirname:
            path=Path(dirname)/'key';path.write_bytes(b'a'*64+b'\n')
            path.chmod(0o600)
            calls=[];reads=PrivateReads(Manager(),path)
            self.assertFalse(reads.authorized(None))
            self.assertFalse(reads.authorized('b'*64))
            self.assertTrue(reads.authorized('a'*64))
            query={'action':'history','email':'guest@example.invalid','profile':'FC27','start':None,'end':None}
            with patch('tracking_private_session.admin_email_history',side_effect=lambda *a:{'status':'available','orders':[],
                    'coverage':{'complete':True,'calls':calls.append(1)}}):
                for _ in range(100):
                    result=reads.execute(query)
                    if result['status']!='pending':break
                    time.sleep(.002)
                self.assertEqual(result['status'],'available')
                self.assertEqual(reads.execute(query)['status'],'available')
            self.assertEqual(len(calls),1)
            self.assertEqual(reads.active(),0)
            with self.assertRaises(ValueError):reads.execute(dict(query,profile='D4'))

    def test_controller_admin_guard_and_history_private_projection(self):
        class Client:
            def read(self,query):
                if query['action']=='history':
                    return {'status':'available','orders':[{'order_no':'FOLLOW-1','email':'guest@example.invalid',
                        'uid':4,'site_id':266,'gid':1327,'paid_at':'2026-10-19 10:00:00','pay_status':1,
                        'current_status':'paid','order_usd':'80','secret':'never-keep'}],
                        'coverage':{'complete':True,'source_total':1}}
                return {'status':'pending'}
        with tempfile.TemporaryDirectory() as dirname:
            service=TrackingController(dirname,lambda user:user=='admin',Client(),auto_start=False)
            es={'游戏':'FC 27','产品类型':'货币(Gold)','订单号':'TRIGGER-1','订单金额（美元）':'520',
                '实付金额':'520','实付币种':'USD','折扣金额':'5','是否新客户':'是','付款时间':'2026-10-17 10:00:00'}
            admin={'order_no':'TRIGGER-1','gid':1327,'site_id':266,'pay_status':1,
                'email':'guest@example.invalid','uid':0,'amount':'520'}
            row=candidate_rows([es],{'TRIGGER-1':admin},DEFAULT_CONFIG)[0][0]
            candidate=service.store.save_candidates('2026-10-17',[row])['items'][0]
            with self.assertRaises(PermissionError):service.post('ordinary',{'kind':'hermes_customer_tracking',
                'action':'track','request_id':'a'*32,'candidate_id':candidate['candidate_id']})
            _,track=service.post('admin',{'kind':'hermes_customer_tracking','action':'track',
                'request_id':'a'*32,'candidate_id':candidate['candidate_id']})
            self.assertEqual(track['state'],'tracked')
            self.assertEqual(track['history_status'],'available')
            _,detail=service.get('admin',{'mode':['hermes'],'structure':['customer_tracking'],
                'view':['detail'],'id':[track['tracking_id']]})
            self.assertEqual(detail['history_coverage']['complete'],True)
            self.assertEqual(detail['owner'],'admin')
            self.assertNotIn('never-keep',json.dumps(detail))
            self.assertIn('status',detail['orders'][0])
            self.assertNotIn('current_status',detail['orders'][0])

if __name__=='__main__':unittest.main()
