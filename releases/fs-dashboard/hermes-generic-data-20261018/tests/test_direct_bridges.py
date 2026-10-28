import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
import admin_product_orders as product
import cohort_paid_source as cohort

class DirectBridges(unittest.TestCase):
    def test_product_keeps_model_budget_and_closes_direct_client(self):
        args=dict(profile='FC27',model_id=123,start='2026-10-17',end='2026-10-17')
        query=product.checked_query(args);client=Mock()
        client.admin.get.return_value=SimpleNamespace(status_code=200,content=b'{}')
        def collect(request,q,model_seconds):
            self.assertEqual(model_seconds,540)
            self.assertEqual(request('/admin/goods.Goods/index',17),(200,b'{}'))
            return dict(kind='admin_product_orders',query=q,status='available')
        with patch.dict(sys.modules,p2pah_auth=SimpleNamespace(Session=lambda:client,ADMIN_API='http://127.0.0.1:8912')),patch.object(product,'collect',side_effect=collect):
            self.assertEqual(product.server_read(args)['query'],query)
        client.admin.get.assert_called_once_with('http://127.0.0.1:8912/admin/goods.Goods/index',timeout=17)
        client.close.assert_called_once()

    def test_cohort_preserves_checked_query_timeout_and_close(self):
        args=dict(profile='FC27',start='2026-10-17',end='2026-10-17');client=Mock()
        client.admin.get.return_value=SimpleNamespace(status_code=200,content=b'{}')
        def collect(request,q):
            self.assertEqual(request('/admin/order.Order/index',29),(200,b'{}'))
            return dict(kind='cohort_paid_orders',query=q,status='available')
        with patch.dict(sys.modules,p2pah_auth=SimpleNamespace(Session=lambda:client,ADMIN_API='http://127.0.0.1:8912')),patch.object(cohort,'collect',side_effect=collect):
            self.assertEqual(cohort.read_service(args)['query'],args)
        client.admin.get.assert_called_once_with('http://127.0.0.1:8912/admin/order.Order/index',timeout=29)
        client.close.assert_called_once()

    def test_source_error_still_closes_both_clients(self):
        for module,call,args in ((product,product.server_read,dict(profile='FC27',product_id=123,start='2026-10-17',end='2026-10-17')),
                                 (cohort,cohort.read_service,dict(profile='FC27',start='2026-10-17',end='2026-10-17'))):
            client=Mock()
            with patch.dict(sys.modules,p2pah_auth=SimpleNamespace(Session=lambda:client,ADMIN_API='http://127.0.0.1:8912')),patch.object(module,'collect',side_effect=ValueError('source_contract')):
                with self.assertRaisesRegex(ValueError,'source_contract'):call(args)
            client.close.assert_called_once()

if __name__=='__main__':unittest.main()
