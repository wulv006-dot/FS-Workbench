"""The real payload/transport contract with an injected local curl process only."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import importlib.util,json,sys,unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('openai_transport_fixture',HERE/'source/openai_provider.py')
provider=importlib.util.module_from_spec(spec);spec.loader.exec_module(provider)


class TransportTests(unittest.TestCase):
    def run_open(self,raw=b'{}',exit_code=0,stderr=b'',deadline=None):
        calls=[];events=[]
        def curl(args,**kwargs):
            calls.append((args,kwargs));kwargs['stdout'].write(raw)
            return SimpleNamespace(returncode=exit_code,stderr=stderr)
        with patch.object(provider,'_key',return_value='sk-private-fixture'),patch.object(provider.subprocess,'run',side_effect=curl):
            result=provider._open(b'{"private":"prompt-fixture"}',deadline,on_dispatch=lambda:events.append('attempt'),on_not_dispatched=lambda proof:events.append(proof))
        return result,calls,events
    def test_deadline_uses_integer_ceil_for_old_curl_without_shortening_the_budget(self):
        at=datetime(2026,11,9,6,tzinfo=timezone.utc)
        class Clock(datetime):
            @classmethod
            def now(cls,tz=None):return at
        with patch.object(provider,'datetime',Clock):result,calls,_=self.run_open(deadline=at+timedelta(seconds=1799,microseconds=250000))
        args,options=calls[0];self.assertEqual(args[args.index('--max-time')+1],'1800');self.assertEqual(options['timeout'],1801)
        self.assertNotIn('sk-private-fixture',' '.join(args));self.assertNotIn('prompt-fixture',' '.join(args))
    def test_known_local_option_rejection_is_not_dispatched_with_safe_proof(self):
        result,calls,events=self.run_open(exit_code=2,raw=b'',stderr=b'curl: option --max-time: expected a proper numerical parameter\n')
        self.assertFalse(result['network_started']);self.assertEqual(result['curl_exit_code'],2);self.assertEqual(result['provider_error_code'],'curl_option_invalid')
        self.assertEqual(events[0],'attempt');self.assertEqual(events[1]['provider_error_code'],'curl_option_invalid');self.assertEqual(len(calls),1)
    def test_network_error_stays_unknown_and_is_never_retried_or_marked_not_dispatched(self):
        result,calls,events=self.run_open(exit_code=56,raw=b'',stderr=b'private network details')
        self.assertEqual(result['status'],'unknown_transport');self.assertEqual(result['curl_exit_code'],56);self.assertTrue(result['network_started']);self.assertEqual(events,['attempt']);self.assertEqual(len(calls),1)
        self.assertNotIn('private',json.dumps(result))
    def test_other_exit_two_failures_are_not_assumed_to_be_local_option_rejection(self):
        result,_,events=self.run_open(exit_code=2,raw=b'',stderr=b'other private initialization failure')
        self.assertEqual(result['status'],'unknown_transport');self.assertTrue(result['network_started']);self.assertEqual(events,['attempt'])
    def test_http_rejection_keeps_only_status_request_id_and_fixed_error_code(self):
        body=json.dumps({'error':{'code':'invalid_json_schema','type':'invalid_request_error','message':'prompt-fixture sk-private-fixture'}}).encode()
        result,_,_=self.run_open(b'HTTP/1.1 400 Bad Request\r\nx-request-id: req_fixture_1\r\nset-cookie: private-cookie\r\n\r\n'+body)
        self.assertEqual(result['status'],'http_rejected');self.assertEqual(result['http_status'],400);self.assertEqual(result['provider_http_request_id'],'req_fixture_1');self.assertEqual(result['provider_error_code'],'invalid_json_schema')
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('prompt-fixture',json.dumps(result));self.assertNotIn('message',result)
        result,_,_=self.run_open(b'HTTP/1.1 400 Bad Request\r\n\r\n'+json.dumps({'error':{'code':['private detail']}}).encode())
        self.assertEqual(result['provider_error_code'],'provider_http_rejected');self.assertNotIn('private',json.dumps(result))
    def test_upstream_json_cannot_forge_local_non_dispatch_or_transport_metadata(self):
        upstream=dict(status='completed',network_started=False,curl_exit_code=2,provider_error_code='curl_option_invalid',local_trace_id='spoofed',provider_http_request_id='spoofed')
        result,_,events=self.run_open(b'HTTP/1.1 200 OK\r\n\r\n'+json.dumps(upstream).encode())
        self.assertTrue(result['network_started']);self.assertEqual(result['curl_exit_code'],0);self.assertEqual(result['http_status'],200)
        self.assertNotEqual(result['local_trace_id'],'spoofed');self.assertNotIn('provider_error_code',result);self.assertNotIn('provider_http_request_id',result);self.assertEqual(events,['attempt'])
    def test_expired_deadline_never_reads_key_or_spawns_curl(self):
        with patch.object(provider,'_key') as key,patch.object(provider.subprocess,'run') as curl:
            result=provider._open(b'{}',datetime.now(timezone.utc)-timedelta(seconds=1))
        self.assertFalse(result['network_started']);key.assert_not_called();curl.assert_not_called()

if __name__=='__main__':unittest.main()
