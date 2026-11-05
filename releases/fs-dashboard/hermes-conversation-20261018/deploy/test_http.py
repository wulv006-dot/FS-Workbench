import http.client
import importlib.util
import json
import threading
import unittest
import builtins
import sys
import ast
import io
import tempfile
from types import SimpleNamespace
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
    def events(self, user, cid, after): return [{"seq": 1, "turn_id": "t" * 32, "type": "run.started", "payload": {}}] if after < 1 else []
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


class StreamClock:
    def __init__(self, after_sleep=lambda: None):
        self.now = 0
        self.after_sleep = after_sleep
    def monotonic(self): return self.now
    def sleep(self, seconds):
        self.now += seconds
        self.after_sleep()


class StreamLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        spec = importlib.util.spec_from_file_location('stream_store', SOURCE.with_name('conversation_store.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.store = module.ConversationStore(Path(self.temp.name) / 'conversations')
        self.cid = self.store.create('admin')['conversation_id']
        self.run_id = 'run_' + 'd' * 32
        with self.store.db() as db:
            db.execute('INSERT INTO turns(id,conversation_id,request_id,input_sha256,text,state,run_id) VALUES(?,?,?,?,?,?,?)',
                       ('t' * 32, self.cid, 'fixture_request', '0' * 64, 'fixture', 'running', self.run_id))
        # Execute the original authorization/event methods without importing model or production dependencies.
        tree = ast.parse(SOURCE.with_name('conversation_service.py').read_text('utf-8'))
        original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'ConversationService')
        methods = [node for node in original.body if isinstance(node, ast.FunctionDef) and node.name in ('_admin', 'events')]
        namespace = {}
        exec(compile(ast.Module(body=methods, type_ignores=[]), 'conversation_service.py', 'exec'), namespace)
        class OwnedService:
            _admin, events = namespace['_admin'], namespace['events']
            def detail(inner, user, cid):
                inner.events(user, cid, 0)  # Real Store._owned plus original per-poll authorization.
                return {}
        self.allowed = True
        self.service = OwnedService()
        self.service.store = self.store
        self.service.hermes = SimpleNamespace(authorizer=lambda user: self.allowed)

    def append(self, upstream, text):
        return self.store.append_event('admin', self.cid, self.run_id, upstream, {'event': 'message.delta', 'delta': text})

    def stream(self, clock, after='0', *, user='admin', disconnect=False):
        class Output(io.BytesIO):
            def write(inner, value):
                if disconnect: raise BrokenPipeError('fixture disconnected')
                return super().write(value)
            def flush(inner):
                if inner.tell() > inner.flushed:
                    inner.deliveries.append(clock.now)
                    inner.flushed = inner.tell()
        output = Output()
        output.flushed, output.deliveries = 0, []
        handler = SimpleNamespace(wfile=output, headers_written=False)
        handler.send_response = lambda status: setattr(handler, 'status', status)
        handler.send_header = lambda key, value: None
        handler.end_headers = lambda: setattr(handler, 'headers_written', True)
        with patch.object(adapter, 'time', clock):
            adapter.stream_events(handler, self.service, user, self.cid, after)
        rows = [json.loads(line[6:]) for line in output.getvalue().decode().splitlines() if line.startswith('data: ')]
        return handler, output, rows

    def test_delayed_second_batch_is_flushed_on_the_same_bounded_stream(self):
        self.append(0, 'a')
        def later():
            if clock.now == 1: self.append(1, 'b')
        clock = StreamClock(later)
        _, output, rows = self.stream(clock)
        self.assertEqual([row['payload']['delta'] for row in rows], ['a', 'b'])
        self.assertEqual(output.deliveries, [0, 1])
        self.assertEqual(clock.now, 20)

    def test_resume_cursor_and_store_page_limit_do_not_duplicate_or_drop_events(self):
        with self.store.db() as db:
            db.executemany('INSERT INTO events(turn_id,upstream_seq,type,payload) VALUES(?,?,?,?)',
                           [('t' * 32, index, 'message.delta', json.dumps({'delta': 'x'})) for index in range(502)])
        _, output, rows = self.stream(StreamClock(), after='1')
        self.assertEqual([row['seq'] for row in rows], list(range(2, 503)))
        self.assertEqual(output.deliveries, [0, 1])

    def test_revoked_authorization_stops_before_a_later_batch(self):
        self.append(0, 'a')
        def revoke():
            self.append(1, 'private later')
            self.allowed = False
        clock = StreamClock(revoke)
        _, _, rows = self.stream(clock)
        self.assertEqual([row['payload']['delta'] for row in rows], ['a'])
        self.assertEqual(clock.now, 1)

    def test_changed_owner_stops_before_a_later_batch(self):
        self.append(0, 'a')
        def transfer():
            with self.store.db() as db:
                db.execute('UPDATE conversations SET owner=? WHERE id=?', ('other', self.cid))
        clock = StreamClock(transfer)
        _, _, rows = self.stream(clock)
        self.assertEqual([row['payload']['delta'] for row in rows], ['a'])
        self.assertEqual(clock.now, 1)

    def test_disconnect_stops_without_waiting_or_resubmitting(self):
        self.append(0, 'a')
        clock = StreamClock()
        _, _, rows = self.stream(clock, disconnect=True)
        self.assertEqual(rows, [])
        self.assertEqual(clock.now, 0)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM turns').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0], 1)

    def test_invalid_cursor_or_initial_access_never_writes_headers(self):
        handler = SimpleNamespace()
        for cursor in ('-1', 'x', '1' * 13):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                adapter.stream_events(handler, self.service, 'admin', self.cid, cursor)
        with self.assertRaises(LookupError):
            adapter.stream_events(handler, self.service, 'other', self.cid, '0')
        self.allowed = False
        with self.assertRaises(PermissionError):
            adapter.stream_events(handler, self.service, 'admin', self.cid, '0')


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
        with patch.object(adapter, 'time', StreamClock()):
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
