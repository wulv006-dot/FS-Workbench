import importlib.util
import json
import socket
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / 'source' / 'admin_live_session.py'

class SessionTests(unittest.TestCase):
 def setUp(self):
  self.assertTrue(SOURCE.is_file(), 'bounded session verifier has not been implemented')
  spec=importlib.util.spec_from_file_location('admin_live_session', SOURCE)
  self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
 def socket_reply(self,response,cookie='MMOEXP_AUTH=synthetic'):
  left,right=socket.socketpair();received=[]
  def peer():
   try:
    received.append(right.recv(8192));right.sendall(response)
   finally:right.close()
  thread=threading.Thread(target=peer);thread.start()
  try:result=self.module.verify_socket(left,cookie)
  finally:left.close();thread.join(2)
  return result,received[0]
 def test_missing_cookie_never_invokes_verifier(self):
  with patch.object(self.module.socket,'socket') as connect:
   self.assertEqual(self.module.verify('unrelated=x')[0],401);connect.assert_not_called()
 def test_only_allowlisted_session_cookies_are_forwarded(self):
  m=self.module
  self.assertEqual(m.session_cookie('other=unneeded; MMOEXP_AUTH=synthetic; fc27sess=fixture'), 'MMOEXP_AUTH=synthetic; fc27sess=fixture')
  self.assertIsNone(m.session_cookie('MMOEXP_AUTH=one; MMOEXP_AUTH=two'))
 def test_success_uses_portal_identity_and_fixed_destination(self):
  result,request=self.socket_reply(b'HTTP/1.0 200 OK\r\nX-Auth-User: actual-user\r\nX-Auth-Role: admin\r\n\r\n')
  self.assertEqual(result,{'status':200,'user':'actual-user'});self.assertIn(b'GET /verify?group=dashboard HTTP/1.0\r\n',request);self.assertNotIn(b'X-Auth-User:',request)
 def test_invalid_session_or_global_denial_is_denied(self):
  for status,role,expected in [(401,'',401),(403,'',403),(200,'readonly',200)]:
   response=('HTTP/1.0 %s Error\r\nX-Auth-User: not-owner\r\nX-Auth-Role: %s\r\n\r\n'%(status,role)).encode()
   with self.subTest(status=status,role=role):self.assertEqual(self.socket_reply(response)[0]['status'],expected)
 def test_oversized_duplicate_or_malformed_response_is_unavailable(self):
  for response in (b'HTTP/1.0 200 OK\r\nX-Auth-User: a\r\nX-Auth-User: b\r\nX-Auth-Role: admin\r\n\r\n',b'HTTP/1.0 200 OK\r\nX-Fill: '+b'a'*17000+b'\r\n\r\n',b'bad\r\n\r\n'):
   with self.subTest(size=len(response)):self.assertEqual(self.socket_reply(response)[0]['status'],503)
 def test_timeout_and_exception_fail_closed(self):
  for exc in (TimeoutError('timeout'),OSError('offline')):
   with patch.object(self.module.socket,'socket',side_effect=exc):self.assertEqual(self.module.verify('MMOEXP_AUTH=synthetic')[0],503)
 def test_reject_cookie_injection(self):
  for cookie in ('MMOEXP_AUTH=x\r\nX-Auth-User: forged','MMOEXP_AUTH=two words','MMOEXP_AUTH='):
   self.assertIsNone(self.module.session_cookie(cookie))
 def test_busy_verifier_rejects_without_opening_another_connection(self):
  self.assertTrue(self.module._SLOT.acquire(blocking=False))
  try:
   with patch.object(self.module.socket,'socket') as connect:
    self.assertEqual(self.module.verify('MMOEXP_AUTH=synthetic'),(429,None));connect.assert_not_called()
  finally:self.module._SLOT.release()

if __name__=='__main__':unittest.main(verbosity=2)
