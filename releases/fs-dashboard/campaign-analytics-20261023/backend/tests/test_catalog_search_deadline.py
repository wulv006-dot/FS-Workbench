import json
import threading
import time
import unittest
from types import SimpleNamespace

from bridge import handle
from campaign_backend.adapters import AdminRead
from campaign_backend.core import ContractError
from test_management_discovery import goods


class Response:
    def __init__(self,payload,status=200):
        self.status_code=status;self.raw=json.dumps(payload).encode();self.closed=False
    def iter_content(self,chunk_size):yield self.raw
    def close(self):self.closed=True


class Session:
    def __init__(self,response=None,error=None,retries=0):
        self.token='SYNTHETIC_PRIVATE_TOKEN';self.calls=[];self.closed=False;self.error=error
        self.response=response or Response({'code':1,'data':{'list':[goods()],'total':1}})
        self.admin=SimpleNamespace(get=self.get,get_adapter=lambda url:SimpleNamespace(max_retries=SimpleNamespace(total=retries)))
    def get(self,url,**options):
        self.calls.append((url,options))
        if self.error:raise self.error
        return self.response
    def get_admin(self,*args,**kwargs):raise AssertionError('shared retry/refresh path must not be invoked')
    def close(self):self.closed=True


class CatalogDeadlineTests(unittest.TestCase):
    def request(self):return dict(action='catalog_search',site_id='266',game_id='1327',keyword='Haaland',page=1,page_size=20)

    def test_single_same_session_get_uses_bounded_socket_timeout_and_no_redirect(self):
        session=Session();result=handle(self.request(),lambda:AdminRead(session))
        self.assertEqual(result['total'],1);self.assertEqual(len(session.calls),1)
        url,options=session.calls[0]
        self.assertEqual(url,'https://admin-api.p2pah.cn/admin/goods.Goods/index')
        self.assertEqual(options['headers'],{'batoken':session.token})
        self.assertEqual(options['timeout'],(5,15));self.assertFalse(options['allow_redirects']);self.assertTrue(options['stream'])
        self.assertTrue(session.response.closed);self.assertTrue(session.closed)

    def test_exact_goods_search_bypasses_shared_get_admin_retry_path_as_well(self):
        session=Session(Response({'code':1,'data':{'row':goods()}}))
        request=self.request();request.pop('keyword');request['goods_id']='170014917'
        result=handle(request,lambda:AdminRead(session))
        self.assertEqual(result['total'],1);self.assertEqual(len(session.calls),1)
        self.assertTrue(session.calls[0][0].endswith('/admin/goods.Goods/edit'))
        self.assertEqual(session.calls[0][1]['params'],{'id':'170014917'})

    def test_http_refusal_is_one_attempt_no_refresh_alternate_route_or_raw_message(self):
        for status in (301,302,401,403,429):
            session=Session(Response({'msg':'PRIVATE_RAW_ERROR'},status))
            with self.subTest(status=status),self.assertRaisesRegex(ContractError,'^CATALOG_SEARCH_HTTP_REJECTED$'):
                handle(self.request(),lambda:AdminRead(session))
            self.assertEqual(len(session.calls),1);self.assertTrue(session.response.closed)

    def test_upstream_http_504_is_timeout_not_refusal_and_never_retried(self):
        session=Session(Response({'msg':'PRIVATE_UPSTREAM_TIMEOUT'},504))
        with self.assertRaisesRegex(ContractError,'^CATALOG_SEARCH_TIMEOUT$'):
            handle(self.request(),lambda:AdminRead(session))
        self.assertEqual(len(session.calls),1);self.assertTrue(session.response.closed)

    def test_socket_timeout_never_uses_shared_retry_loop(self):
        session=Session(error=TimeoutError('PRIVATE_SOCKET_ERROR'))
        with self.assertRaisesRegex(ContractError,'^CATALOG_SEARCH_TIMEOUT$'):
            handle(self.request(),lambda:AdminRead(session))
        self.assertEqual(len(session.calls),1);self.assertTrue(session.closed)

    def test_absolute_deadline_returns_without_joining_blocked_read_and_never_retries(self):
        release,entered,finished=threading.Event(),threading.Event(),threading.Event();calls=[]
        def slow(*args,**kwargs):
            calls.append(1);entered.set()
            try:release.wait(5);return 200,{'code':1,'data':{'list':[],'total':0}}
            finally:finished.set()
        reader=AdminRead(Session(),catalog_get_once=slow,catalog_timeout=0.05)
        started=time.monotonic()
        try:
            with self.assertRaisesRegex(ContractError,'^CATALOG_SEARCH_TIMEOUT$'):
                reader.search_goods_page('266','1327',keyword='Haaland')
            self.assertLess(time.monotonic()-started,1)
            self.assertTrue(entered.is_set());self.assertEqual(calls,[1])
        finally:
            release.set();self.assertTrue(finished.wait(1));reader.close()

    def test_automatic_transport_retries_must_already_be_disabled(self):
        session=Session(retries=1)
        with self.assertRaisesRegex(ContractError,'^CATALOG_SEARCH_TRANSPORT_NOT_SINGLE_ATTEMPT$'):
            handle(self.request(),lambda:AdminRead(session))
        self.assertEqual(session.calls,[])

    def test_business_or_json_failure_never_retries_or_discloses_body(self):
        for payload in ({'code':0,'msg':'PRIVATE_MSG'},{'code':True,'data':{}},{'code':1,'data':None}):
            session=Session(Response(payload))
            with self.assertRaisesRegex(ContractError,'^UPSTREAM_UNAVAILABLE$'):
                handle(self.request(),lambda:AdminRead(session))
            self.assertEqual(len(session.calls),1)
        session=Session();session.response.raw=b'PRIVATE_NOT_JSON'
        with self.assertRaisesRegex(ContractError,'^UPSTREAM_UNAVAILABLE$'):
            handle(self.request(),lambda:AdminRead(session))
        self.assertEqual(len(session.calls),1)

    def test_response_size_and_deadline_configuration_fail_closed(self):
        session=Session();session.response.raw=b'x'*2000001
        with self.assertRaisesRegex(ContractError,'^CATALOG_SEARCH_RESPONSE_TOO_LARGE$'):
            handle(self.request(),lambda:AdminRead(session))
        self.assertEqual(len(session.calls),1);self.assertTrue(session.response.closed)
        for timeout in (0,21,True,'20'):
            with self.assertRaisesRegex(ContractError,'INVALID_CATALOG_DEADLINE'):AdminRead(Session(),catalog_timeout=timeout)


if __name__=='__main__':unittest.main()
