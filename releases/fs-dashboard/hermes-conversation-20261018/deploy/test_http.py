import http.client
import importlib.util
import json
import threading
import unittest
import builtins
import sys
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


SOURCE = Path(__file__).resolve().parents[1] / "source/conversation_http.py"
SPEC = importlib.util.spec_from_file_location("conversation_http", SOURCE)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)
CID = "a" * 32
RID = "r" * 32


class Service:
    def listed(self, user): return {"items": [{"conversation_id": CID}]}
    def create(self, user): return {"conversation_id": CID}
    def detail(self, user, cid):
        if user != "admin" or cid != CID: raise LookupError()
        return {"conversation_id": cid, "turns": [], "last_seq": 0}
    def submit(self, user, cid, text, key): return {"accepted": text}
    def events(self, user, cid, after): return [{"seq": 1, "turn_id": "t" * 32, "type": "run.started", "payload": {}}]
    def steer(self, user, cid, rid, text, key): return {"steered": text}
    def stop(self, user, cid, rid, key): return {"stopping": True}
    def artifact(self, user, cid, aid):
        mime = "text/plain" if aid == "p" * 32 else "text/html"
        return {"content": b"<script>1</script>", "mime": mime, "filename": "report.html", "sha256": "0" * 64}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self): self.dispatch("GET")
    def do_POST(self): self.dispatch("POST")
    def dispatch(self, method):
        adapter.handle(self, method, urlsplit(self.path), self.headers.get("X-Auth-User"), Service(), lambda user: user == "admin")
    def log_message(self, *args): pass


class SocketContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(2)

    def call(self, method, path, user="admin", body=None, csrf=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        headers = {"X-Auth-User": user}
        if body is not None:
            body = json.dumps(body)
            headers["Content-Type"] = "application/json"
            if csrf: headers.update({"X-FS-Advisor-Action": "submit", "Sec-Fetch-Site": "same-origin"})
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        connection.close()
        return result

    def test_admin_and_csrf(self):
        self.assertEqual(self.call("GET", adapter.PREFIX, user="employee")[0], 403)
        self.assertEqual(self.call("POST", adapter.PREFIX, body={}, csrf=False)[0], 403)
        self.assertEqual(self.call("POST", adapter.PREFIX, body={})[0], 201)
        self.assertEqual(self.call("POST", adapter.PREFIX + "/" + CID + "/turns", body={"text": "hello", "client_request_id": "web_123"})[0], 202)

    def test_non_native_turn_controls_do_not_import_attachment_support(self):
        original=builtins.__import__
        def importing(name,*args,**kwargs):
            if name=='conversation_files':raise ModuleNotFoundError('attachment support unavailable')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=importing):
            for suffix,body in (('/turns',{'text':'hello','client_request_id':'web_123'}),
                                ('/runs/'+RID+'/steer',{'text':'hello','client_request_id':'web_123'}),
                                ('/runs/'+RID+'/stop',{'client_request_id':'web_123'})):
                with self.subTest(suffix=suffix):
                    self.assertEqual(self.call('POST',adapter.PREFIX+'/'+CID+suffix,body=body)[0],202)
            self.assertEqual(self.call('POST',adapter.PREFIX+'/'+CID+'/turns',
                body={'text':'x'*16384,'client_request_id':'web_123'})[0],422)

    def test_native_turn_controls_keep_existing_upload_json_limit(self):
        with patch.object(sys,'path',[str(SOURCE.parent),*sys.path]):
            from conversation_files import MAX_BYTES
        self.assertEqual(MAX_BYTES,10*1024*1024)
        with patch.object(Service,'native',True,create=True),patch.object(adapter,'read_json',wraps=adapter.read_json) as read:
            for suffix,body in (('/turns',{'text':'x'*20000,'client_request_id':'web_123'}),
                                ('/runs/'+RID+'/steer',{'text':'x'*20000,'client_request_id':'web_123'})):
                with self.subTest(suffix=suffix):
                    self.assertEqual(self.call('POST',adapter.PREFIX+'/'+CID+suffix,body=body)[0],202)
                    self.assertEqual(read.call_args.kwargs['maximum'],MAX_BYTES)

    def test_sse_finishes_and_can_resume(self):
        status, headers, data = self.call("GET", adapter.PREFIX + "/" + CID + "/events?after=0")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Connection"], "close")
        self.assertIn(b'"seq": 1', data)

    def test_artifact_preview_is_sandboxed(self):
        status, headers, _ = self.call("GET", adapter.PREFIX + "/" + CID + "/artifacts/" + RID + "?view=1")
        self.assertEqual(status, 200)
        self.assertIn("sandbox allow-scripts", headers["Content-Security-Policy"])
        self.assertNotIn("allow-same-origin", headers["Content-Security-Policy"])
        self.assertIn("connect-src 'none'", headers["Content-Security-Policy"])
        status, headers, _ = self.call("GET", adapter.PREFIX + "/" + CID + "/artifacts/" + "p" * 32 + "?view=1")
        self.assertEqual(status, 200)
        self.assertIn("inline", headers["Content-Disposition"])
        self.assertNotIn("allow-scripts", headers["Content-Security-Policy"])


if __name__ == "__main__": unittest.main()
