import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import webpush as w

def body():
    return dict(title='Test',message='Hello',redirect_url='https://example.com/',audience_mode='tokens',audience_values=['test-token'])

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.calls=[]
        def sender(config,method,path,data):
            self.calls.append((method,path,data))
            return 200,{'id':'1234','regIdExists':False}
        self.s=w.Service(self.tmp.name,sender)
        self.s.save({'site_name':'Test','app_key':'test-key','app_secret':'test-secret'})

    def test_public_never_returns_secrets(self):
        self.assertNotIn('test-key',json.dumps(self.s.public()))
        self.assertNotIn('test-secret',json.dumps(self.s.public()))
        self.s.save({'site_name':'Rename'})
        self.assertEqual(self.s.config()['app_secret'],'test-secret')

    def test_verify_is_read_only(self):
        self.assertTrue(self.s.verify()['verified'])
        self.assertEqual(self.calls[0][0],'GET')
        self.assertTrue(self.calls[0][1].startswith('alias?'))

    def test_empty_audience_cannot_broadcast(self):
        for values in ([],None,[''],['  ']):
            with self.assertRaises(w.Invalid): w.campaign(dict(body(),audience_values=values))
        with self.assertRaises(w.Invalid): w.campaign(dict(body(),audience_mode=''))

    def test_all_requires_explicit_confirmation(self):
        b=dict(body(),audience_mode='all',confirm=True,request_id='a'*32)
        with self.assertRaises(w.Invalid): self.s.send(b,'tester')
        self.assertEqual(self.calls,[])

    def test_replay_after_restart_sends_once(self):
        b=dict(body(),confirm=True,request_id='b'*32)
        self.assertEqual(self.s.send(b,'tester')['state'],'accepted')
        restarted=w.Service(self.tmp.name,self.s.sender)
        self.assertTrue(restarted.send(b,'tester')['replayed'])
        self.assertEqual(len(self.calls),1)
        with self.assertRaises(w.Invalid): restarted.send(dict(b,message='changed'),'tester')

    def test_concurrent_send_once(self):
        b=dict(body(),confirm=True,request_id='c'*32);results=[]
        threads=[threading.Thread(target=lambda:results.append(self.s.send(b,'tester'))) for _ in range(5)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(len(results),5);self.assertEqual(len(self.calls),1)

    def test_unknown_never_retries(self):
        def timeout(*args):raise TimeoutError('secret in exception')
        self.s.sender=timeout;b=dict(body(),confirm=True,request_id='d'*32)
        self.assertEqual(self.s.send(b,'tester')['state'],'unknown')
        self.s.sender=lambda *args: self.fail('must not resend')
        self.assertEqual(self.s.send(b,'tester')['state'],'unknown')

    def test_draft_persists_without_sending(self):
        ident=self.s.draft(body(),'tester')['draft_id']
        self.assertEqual(w.Service(self.tmp.name).records()['drafts'][0]['id'],ident)
        self.assertEqual(self.calls,[])

    def test_schedule_and_units(self):
        with self.assertRaises(w.Invalid):w.campaign(dict(body(),send_date=12345))
        with self.assertRaises(w.Invalid):w.campaign(dict(body(),ttl=True))
        with self.assertRaises(w.Invalid):w.campaign(dict(body(),ttl=2419201))
        self.assertEqual(w.campaign(dict(body(),ttl=0))['ttl'],0)
        future=int(w.time.time()*1000)+3600000
        self.assertEqual(w.campaign(dict(body(),send_date=future))['send_date'],future)

    def test_bad_links_and_buttons(self):
        for value in ('javascript:alert(1)','https://user:password@example.com','https://example.com/ x'):
            with self.assertRaises(w.Invalid):w.campaign(dict(body(),redirect_url=value))
        with self.assertRaises(w.Invalid):w.campaign(dict(body(),buttons=[{}]))
        with self.assertRaises(w.Invalid):w.campaign(dict(body(),icon='https://example.com/a.svg'))

    def test_subscriber_write_confirmation(self):
        with self.assertRaises(w.Invalid):self.s.subscriber({'action':'add_tag','regId':'x','name':'test'})
        self.assertEqual(self.calls,[])
        self.s.subscriber({'action':'get_alias','regId':'a&name=other'})
        self.assertIn('a%26name%3Dother',self.calls[0][1])

    def test_stats_redacts_extra_provider_fields(self):
        self.s.sender=lambda *args:(200,{'status':'SENT','send':2,'app_secret':'secret'})
        self.assertEqual(self.s.stats({'campaign_id':'123'})['stats'],{'status':'SENT','send':2})
        with self.assertRaises(w.Invalid):self.s.stats({'campaign_id':'../config'})

    def test_http_auth_fail_closed(self):
        class Handler:
            path='/api/webpush/config';command='GET';headers={};wfile=io.BytesIO()
            def send_response(self,s):self.status=s
            def send_header(self,*a):pass
            def end_headers(self):pass
        h=Handler()
        with patch.object(w,'authorize',return_value=None):w.handle(h)
        self.assertEqual(h.status,403)

    def test_authorization_uses_portal_and_csrf(self):
        class Response:
            status=200
            def getheader(self,key):return {'X-Auth-Role':'admin','X-Auth-User':'tester'}.get(key)
            def read(self):return b''
        class Conn:
            def __init__(self,*a,**kw):pass
            def request(self,*a,**kw):pass
            def getresponse(self):return Response()
            def close(self):pass
        with patch.object(w.http.client,'HTTPConnection',Conn):
            self.assertIsNone(w.authorize({},'POST','/api/webpush/send'))
            self.assertIsNone(w.authorize({'X-FS-WebPush-Request':'1','Origin':'https://evil','Host':'good'},'POST','/api/webpush/send'))
            self.assertEqual(w.authorize({'X-FS-WebPush-Request':'1','Origin':'https://good','Host':'good'},'POST','/api/webpush/send'),'tester')

if __name__=='__main__':unittest.main()
