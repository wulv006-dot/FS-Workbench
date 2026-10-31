"""Local socket acceptance for attachment UI contracts; no browser/model/login.

Authentication is a deliberately injected test session, never production headers.
The real HTTP adapter, store, bindings and B helper handle every file operation.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "hermes-conversation-20261018/source"
sys.path[:0] = [str(HERE / "source"), str(SOURCE)]
from conversation_store import ConversationStore
from conversation_file_bindings import context_factory
from conversation_file_tools import attach_conversation_file_tools, NAMES
from conversation_http import handle


class MaterialsHTTPWorkflow(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = ConversationStore(self.folder.name)
        self.cid = self.store.create("alice")["conversation_id"]
        self.allowed = {"alice", "bob"}
        self.service = SimpleNamespace(store=self.store, detail=self.store.detail)
        self.service.submit = lambda owner, cid, text, client_request_id, file_ids=None: self.store.reserve_turn(
            owner, cid, text, client_request_id, file_ids)
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def dispatch(self):
                # Test-only authenticated identity, not an application auth implementation.
                owner = self.headers.get("X-Fixture-Session")
                if not handle(self, self.command, urlsplit(self.path), owner,
                              fixture.service, lambda user: user in fixture.allowed):
                    self.send_error(404)
            do_GET = do_POST = dispatch
            def log_message(self, *_):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.opener = build_opener(ProxyHandler({}))

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())

    def request(self, suffix, body=None, *, owner="alice", cid=None, headers=None):
        method = "GET" if body is None else "POST"
        request_headers = {"X-Fixture-Session": owner, "X-FS-Advisor-Action": "submit",
                           "Sec-Fetch-Site": "same-origin"}
        if isinstance(body, dict):
            body = json.dumps(body).encode()
            request_headers["Content-Type"] = "application/json"
        elif body is not None:
            request_headers["Content-Type"] = "application/octet-stream"
        request_headers.update(headers or {})
        req = Request(self.base + "/api/hermes/conversations/" + (cid or self.cid) + suffix,
                      data=body, headers=request_headers, method=method)
        try:
            response = self.opener.open(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read()
            value = json.loads(raw) if "application/json" in response.headers.get("Content-Type", "") else raw
            return response.status, value, response.headers

    def upload(self, request_id="upload_ui_001"):
        code, item, _ = self.request("/files", b"item,amount\nrow,2\n", headers={
            "X-FS-Filename": "materials.csv", "X-FS-Request-ID": request_id})
        self.assertEqual(code, 201)
        return item

    def start(self, ids, request_id):
        code, turn, _ = self.request("/turns", {"text": "inspect materials", "file_ids": ids,
                                                 "client_request_id": request_id})
        self.assertEqual(code, 202)
        self.store.bind_run("alice", self.cid, turn["turn_id"], "run_" + turn["turn_id"])
        context = context_factory(self.store, "alice", self.cid, turn["turn_id"], lambda user: user in self.allowed)
        book = SimpleNamespace(call=lambda *args: {"original": True})
        attach_conversation_file_tools(book, context)
        return turn, book

    def test_original_upload_lookup_is_scoped_and_does_not_duplicate(self):
        item = self.upload()
        code, found, _ = self.request("/files?request_id=upload_ui_001")
        self.assertEqual(code, 200)
        self.assertEqual(found["file_id"], item["file_id"])
        self.assertEqual(found["sha256"], item["sha256"])
        self.assertEqual(self.upload()["file_id"], item["file_id"])
        self.assertEqual(self.request("/files?request_id=upload_ui_001", owner="bob")[0], 404)
        other = self.store.create("alice")["conversation_id"]
        self.assertEqual(self.request("/files?request_id=upload_ui_001", cid=other)[0], 404)
        self.assertEqual(self.request("/files?request_id=never_saved_001")[0], 404)
        self.assertEqual(len(self.request("/files")[1]["items"]), 1)
        self.allowed.remove("alice")
        self.assertEqual(self.request("/files?request_id=upload_ui_001")[0], 403)

    def test_terminal_metadata_and_explicit_followup_do_not_reopen_tools(self):
        original = self.upload()
        turn, book = self.start([original["file_id"]], "turn_ui_001")
        derived = book.call(NAMES[2], dict(file_id=original["file_id"], edits=[
            dict(sheet=0, row=1, column=1, value="7")], format="csv", request_id="revision_ui_001"))
        self.store.set_state("alice", self.cid, turn["turn_id"], "completed")
        code, detail, _ = self.request("")
        self.assertEqual(code, 200)
        files = detail["turns"][0]["files"]
        self.assertEqual(files["inputs"][0]["file_id"], original["file_id"])
        self.assertEqual(files["generated"][0]["file_id"], derived["file_id"])
        self.assertEqual(files["generated"][0]["status"], "available")
        self.assertNotIn("content", files["generated"][0])
        with self.assertRaises(PermissionError):
            book.call(NAMES[0], {})
        code, content, headers = self.request("/files/" + derived["file_id"])
        self.assertEqual(code, 200)
        self.assertIn(b"7", content)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.request("/files/" + derived["file_id"], owner="bob")[0], 404)
        empty, empty_book = self.start([], "turn_ui_002")
        self.assertEqual(empty_book.call(NAMES[0], {})["items"], [])
        self.store.set_state("alice", self.cid, empty["turn_id"], "completed")
        _, followup = self.start([derived["file_id"]], "turn_ui_003")
        self.assertEqual(followup.call(NAMES[0], {})["items"][0]["file_id"], derived["file_id"])

    def test_damaged_and_expired_files_keep_honest_metadata_without_bytes(self):
        item = self.upload()
        turn, _ = self.start([item["file_id"]], "turn_ui_001")
        self.store.set_state("alice", self.cid, turn["turn_id"], "completed")
        target = Path(self.folder.name) / "files" / self.cid / item["file_id"]
        original = target.read_bytes()
        target.write_bytes(b"corrupt")
        detail = self.request("")[1]
        self.assertEqual(detail["turns"][0]["files"]["inputs"][0]["status"], "damaged")
        self.assertNotEqual(self.request("/files/" + item["file_id"])[0], 200)
        target.write_bytes(original)
        with patch("conversation_files.time.time", return_value=item["expires_at"] + 1):
            code, detail, _ = self.request("")
            self.assertEqual(code, 200)
            self.assertEqual(detail["turns"][0]["files"]["inputs"][0]["status"], "expired")
            self.assertNotEqual(self.request("/files/" + item["file_id"])[0], 200)

    def test_missing_file_keeps_a_non_downloadable_receipt(self):
        item = self.upload()
        turn, _ = self.start([item["file_id"]], "turn_ui_001")
        self.store.set_state("alice", self.cid, turn["turn_id"], "completed")
        target = Path(self.folder.name) / "files" / self.cid / item["file_id"]
        target.unlink()
        code, detail, _ = self.request("")
        self.assertEqual(code, 200)
        self.assertEqual(detail["turns"][0]["files"]["inputs"][0]["status"], "missing")
        self.assertNotEqual(self.request("/files/" + item["file_id"])[0], 200)


if __name__ == "__main__":
    unittest.main()
