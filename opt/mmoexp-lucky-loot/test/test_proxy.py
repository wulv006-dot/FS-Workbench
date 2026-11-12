import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lucky_proxy

class Handler:
    def __init__(self,admin=True,csrf=True):self.admin=admin;self.csrf=csrf;self.calls=[]
    def _require_admin(self):self.calls.append('admin');return self.admin
    def _check_csrf(self):self.calls.append('csrf');return self.csrf
    def _read_body(self):self.calls.append('body');return {'token':'private-test-value'}
    def _json(self,status,body):self.result=(status,body)
    def _serve_static(self,name):self.calls.append(name)

class ProxyTests(unittest.TestCase):
    def test_no_login_or_nonadmin_never_reads_request_or_opens_socket(self):
        for method in ('GET','POST'):
            h=Handler(admin=False)
            with patch.object(lucky_proxy,'UnixConnection',side_effect=AssertionError('network')):
                self.assertTrue(lucky_proxy.handle(h,method,'/api/loot/connect',{}))
            self.assertEqual(h.calls,['admin'])
    def test_csrf_rejection_does_not_forward_token(self):
        h=Handler(csrf=False)
        with patch.object(lucky_proxy,'UnixConnection',side_effect=AssertionError('network')):
            lucky_proxy.handle(h,'POST','/api/loot/connect',{})
        self.assertEqual(h.calls,['admin','csrf'])
    def test_route_allowlist_blocks_arbitrary_proxy_requests(self):
        h=Handler();lucky_proxy.handle(h,'POST','/api/loot/../../admin',{})
        self.assertEqual(h.result[0],404)
    def test_coupon_query_accepts_numeric_id_only(self):
        h=Handler();lucky_proxy.handle(h,'GET','/api/loot/coupon',{'id':['1365&email=secret']})
        self.assertEqual(h.result[0],400)
    def test_static_activity_page_requires_admin(self):
        h=Handler(admin=False);lucky_proxy.handle(h,'GET','/giveaway.html',{})
        self.assertNotIn('giveaway.html',h.calls)
    def test_other_bot_routes_are_not_intercepted(self):
        h=Handler();self.assertFalse(lucky_proxy.handle(h,'GET','/api/guard/config',{}))
        self.assertEqual(h.calls,[])

if __name__=='__main__':unittest.main()
