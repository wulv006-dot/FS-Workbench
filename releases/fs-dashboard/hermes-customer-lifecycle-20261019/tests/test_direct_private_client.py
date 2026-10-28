import json,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE/'source'),str(HERE.parent/'hermes-customer-tracking-20261018/source'),str(HERE.parent/'hermes-generic-data-20261018/source'),str(HERE.parent/'admin-data-tools-20261018/candidate/hermes')]
from tracking_controller import PrivateClient
import tracking_private_session as private

class DirectPrivate(unittest.TestCase):
    def test_scan_keeps_api_budget_while_private_boundary_caps_each_request(self):
        from customer_tracking import DEFAULT_CONFIG
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';key.write_bytes(b'a'*64+b'\n');key.chmod(0o600)
            api=Mock();api.admin.get.return_value=SimpleNamespace(status_code=200,content=b'{"code":1}')
            def scan(request,*args):
                request('/admin/order.Order/index',75)
                return {'status':'available','candidates':[]}
            with patch.dict(sys.modules,p2pah_auth=SimpleNamespace(Session=lambda:api,ADMIN_API='http://127.0.0.1:8912'),es_order_structure=SimpleNamespace(GAME_LABELS={'FC27':'FC 27'},server_bundle=lambda q:{'status':'available'})),patch.object(private,'scan_day',side_effect=scan):
                client=PrivateClient(key_file=key)
                for _ in range(100):
                    result=client.read({'action':'scan','day':'2026-10-17','config':DEFAULT_CONFIG})
                    if result['status']!='pending':break
                    time.sleep(.002)
                self.assertEqual(result['status'],'available')
                self.assertEqual(api.admin.get.call_args.kwargs['timeout'],10)
                client.reads.pool.shutdown()

    def test_existing_key_and_private_validation_remain_on_direct_api(self):
        with tempfile.TemporaryDirectory() as folder:
            key=Path(folder)/'key';key.write_bytes(b'a'*64+b'\n');key.chmod(0o600)
            api=Mock();api.admin.get.return_value=SimpleNamespace(status_code=200,content=b'{"code":1}')
            def history(request,*args):
                request('/admin/order.Order/index',timeout=10)
                return {'status':'available','orders':[],'coverage':{'complete':True}}
            with patch.dict(sys.modules,p2pah_auth=SimpleNamespace(Session=lambda:api,ADMIN_API='http://127.0.0.1:8912')),patch.object(private,'admin_email_history',side_effect=history):
                client=PrivateClient(key_file=key)
                for _ in range(100):
                    result=client.read({'action':'history','email':'test@example.invalid','profile':'FC27','start':None,'end':None})
                    if result['status']!='pending':break
                    time.sleep(.002)
                self.assertEqual(result['status'],'available');self.assertEqual(api.admin.get.call_count,2)
                self.assertTrue(all(call.args[0].startswith('http://127.0.0.1:8912/admin/') for call in api.admin.get.call_args_list))
                with self.assertRaises(ValueError):client.read({'action':'history','email':'test@example.invalid','profile':'D4','start':None,'end':None})
                client.reads.pool.shutdown()
            with self.assertRaises(OSError):PrivateClient(key_file=Path(folder)/'missing').read({})

if __name__=='__main__':unittest.main()
