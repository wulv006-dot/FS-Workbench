import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
import io
import json
from email.message import Message
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))
from conversation_store import ConversationStore
from conversation_files import ConversationFiles, parse_table
from conversation_http import handle
from conversation_file_bindings import context_factory


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConversationStore(self.temp.name)
        self.cid = self.store.create('alice')['conversation_id']
        self.files = ConversationFiles(self.store)

    def running_context(self, file_ids, request_id='turn_001'):
        turn = self.store.reserve_turn('alice', self.cid, '分析附件', request_id, file_ids)
        run_id = 'run_' + turn['turn_id']
        self.store.bind_run('alice', self.cid, turn['turn_id'], run_id)
        return turn, run_id, context_factory(self.store, 'alice', self.cid, turn['turn_id'], lambda user: user == 'alice')

    def test_turn_binding_paging_revision_and_explicit_followup(self):
        first = self.files.save('alice', self.cid, 'a.csv', b'a,b\n1,2\n3,4', 'upload_001')
        other = self.files.save('alice', self.cid, 'b.csv', b'secret', 'upload_002')
        turn, run_id, context = self.running_context([first['file_id']])
        self.assertEqual([i['file_id'] for i in context.catalog()['items']], [first['file_id']])
        with self.assertRaisesRegex(LookupError, 'not_bound'):
            context.read_table(other['file_id'])
        full = context.read_table(first['file_id'])
        self.assertTrue(full['complete'])
        self.assertEqual(full['coverage']['scope'], 'workbook')
        rows, offset = [], 0
        while offset is not None:
            page = context.read_table(first['file_id'], sheet=0, offset=offset, limit=2)
            self.assertFalse(page['complete'])
            self.assertEqual(page['coverage']['scope'], 'selected_sheet')
            rows.extend(page['sheets'][0]['rows'])
            offset = page['next_offset']
        self.assertEqual(rows, full['sheets'][0]['rows'])
        result = context.revise(first['file_id'], [{'sheet': 0, 'row': 2, 'column': 1, 'value': 9}], 'xlsx', 'revise_001')
        self.assertEqual(context.read_table(result['file_id'])['sheets'][0]['rows'][2][1], 9)
        self.assertIn(result['file_id'], self.store.detail('alice', self.cid)['turns'][0]['file_bindings']['generated'])
        self.store.set_state('alice', self.cid, turn['turn_id'], 'completed')
        with self.assertRaisesRegex(PermissionError, 'not_running'):
            context.revise(result['file_id'], [], 'csv', 'revise_002')
        followup, _, next_context = self.running_context([result['file_id']], 'turn_002')
        with self.assertRaises(LookupError):
            next_context.read_table(first['file_id'])
        revised = next_context.revise(result['file_id'], [], 'csv', 'revise_001')
        self.assertEqual(revised['version'], 3)
        self.assertEqual(self.files.read('alice', self.cid, first['file_id'])['content'], b'a,b\n1,2\n3,4')

    def test_attachment_set_idempotency_and_failed_binding_rolls_back(self):
        a = self.files.save('alice', self.cid, 'a.csv', b'a', 'upload_001')['file_id']
        b = self.files.save('alice', self.cid, 'b.csv', b'b', 'upload_002')['file_id']
        item = self.store.reserve_turn('alice', self.cid, 'same', 'turn_001', [b, a])
        self.assertTrue(self.store.reserve_turn('alice', self.cid, 'same', 'turn_001', [a, a, b])['reused'])
        with self.assertRaisesRegex(ValueError, 'idempotency_conflict'):
            self.store.reserve_turn('alice', self.cid, 'same', 'turn_001', [a])
        self.store.set_state('alice', self.cid, item['turn_id'], 'failed')
        with self.assertRaises(LookupError):
            self.store.reserve_turn('alice', self.cid, 'bad', 'turn_002', ['f' * 32])
        self.assertEqual(len(self.store.detail('alice', self.cid)['turns']), 1)
        with self.assertRaises(ValueError):
            self.store.reserve_turn('alice', self.cid, 'bad', 'turn_003', 'not-list')

    def test_bound_permissions_state_expiry_and_reopen(self):
        item = self.files.save('alice', self.cid, 'a.csv', b'a,b\n1,2', 'upload_001')
        turn, run_id, context = self.running_context([item['file_id']])
        reopened = context_factory(ConversationStore(self.temp.name), 'alice', self.cid, turn['turn_id'], lambda _: True)
        self.assertEqual(reopened.catalog()['items'][0]['file_id'], item['file_id'])
        context.authorized = lambda _: False
        with self.assertRaisesRegex(PermissionError, 'revoked'):
            context.read_table(item['file_id'])
        wrong_owner = context_factory(self.store, 'bob', self.cid, turn['turn_id'], lambda _: True)
        with self.assertRaises(LookupError):
            wrong_owner.catalog()
        with patch('conversation_files.time.time', return_value=item['expires_at'] + 1):
            with self.assertRaises(LookupError):
                reopened.revise(item['file_id'], [], 'csv', 'revise_001')
        self.store.set_state('alice', self.cid, turn['turn_id'], 'dispatch_unknown')
        with self.assertRaises(PermissionError):
            reopened.catalog()
        self.store.set_state('alice', self.cid, turn['turn_id'], 'stopping')
        with self.assertRaises(PermissionError):
            reopened.catalog()

    def test_empty_turn_does_not_inherit_files(self):
        self.files.save('alice', self.cid, 'a.csv', b'a', 'upload_001')
        _, _, context = self.running_context([])
        self.assertEqual(context.catalog()['items'], [])

    def test_unknown_revision_keeps_id_and_can_be_reconciled_without_duplicate(self):
        original = self.files.save('alice', self.cid, 'a.csv', b'a,b\n1,2', 'upload_001')
        _, _, context = self.running_context([original['file_id']])
        with patch.object(context.bindings, 'write', side_effect=OSError('simulated receipt write failure')):
            with self.assertRaises(OSError):
                context.revise(original['file_id'], [], 'csv', 'revision_001')
        inventory = self.files.listed('alice', self.cid)['items']
        generated = [i for i in inventory if i['generated']]
        self.assertEqual(len(generated), 1)
        # Explicit reconciliation with the original ID, never an automatic new request.
        result = context.revise(original['file_id'], [], 'csv', 'revision_001')
        self.assertEqual(result['file_id'], generated[0]['file_id'])
        self.assertEqual(len(self.files.listed('alice', self.cid)['items']), 2)

    def test_real_bytes_full_rows_revision_restart_and_permissions(self):
        raw = ('name,value\n' + ''.join('item,2\n' for _ in range(500))).encode()
        first = self.files.save('alice', self.cid, 'report.csv', raw, 'upload_001')
        self.assertEqual(self.files.parsed('alice', self.cid, first['file_id'])['cells'], 1002)
        second = self.files.revise('alice', self.cid, first['file_id'],
                                   [{'sheet': 0, 'row': 500, 'column': 1, 'value': '7'}], 'xlsx', 'revise_001')
        self.assertEqual(second['version'], 2)
        self.assertEqual(second['parent_id'], first['file_id'])
        self.assertEqual(self.files.revise('alice', self.cid, first['file_id'],
                                          [{'sheet': 0, 'row': 500, 'column': 1, 'value': '7'}],
                                          'xlsx', 'revise_001'), second)
        with self.assertRaises(ValueError):
            self.files.revise('alice', self.cid, first['file_id'], [], 'xlsx', 'revise_001')
        restarted = ConversationFiles(ConversationStore(self.temp.name))
        self.assertEqual(restarted.read('alice', self.cid, first['file_id'])['content'], raw)
        self.assertEqual(restarted.parsed('alice', self.cid, second['file_id'])['sheets'][0]['rows'][-1], ['item', '7'])
        for operation in (lambda: restarted.read('bob', self.cid, first['file_id']),
                          lambda: restarted.parsed('bob', self.cid, second['file_id']),
                          lambda: restarted.save('bob', self.cid, 'a.csv', raw, 'upload_002')):
            with self.assertRaises(LookupError):
                operation()
        other = self.store.create('alice')['conversation_id']
        with self.assertRaises(LookupError):
            self.files.read('alice', other, first['file_id'])

    def test_idempotency_integrity_expiry_and_legacy_preservation(self):
        item = self.files.save('alice', self.cid, 'a.csv', b'a,b\n1,2', 'upload_001')
        self.assertEqual(self.files.save('alice', self.cid, 'a.csv', b'a,b\n1,2', 'upload_001'), item)
        with self.assertRaises(ValueError):
            self.files.save('alice', self.cid, 'a.csv', b'a,b\n3,4', 'upload_001')
        target = Path(self.temp.name) / 'files' / self.cid / item['file_id']
        target.write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError, 'integrity'):
            self.files.read('alice', self.cid, item['file_id'])
        legacy = Path(self.temp.name) / 'artifacts'
        legacy.mkdir()
        (legacy / 'old').write_bytes(b'preserve')
        with patch('conversation_files.time.time', return_value=item['expires_at'] + 1):
            with self.assertRaises(LookupError):
                self.files.read('alice', self.cid, item['file_id'])
            self.assertTrue(self.files.listed('alice', self.cid)['items'][0]['expired'])
        self.assertFalse(target.exists())
        self.assertEqual((legacy / 'old').read_bytes(), b'preserve')

    def test_xlsx_formula_is_not_executed_and_html_is_escaped(self):
        from openpyxl import Workbook
        book = Workbook()
        book.active.append(['=1+2', '<script>alert(1)</script>'])
        data = io.BytesIO()
        book.save(data)
        book.close()
        item = self.files.save('alice', self.cid, 'formulas.xlsx', data.getvalue(), 'upload_001')
        parsed = self.files.parsed('alice', self.cid, item['file_id'])
        self.assertEqual(parsed['sheets'][0]['rows'][0][0], '=1+2')
        self.assertEqual(parsed['formulas'], 'expressions_preserved_not_evaluated')
        result = self.files.revise('alice', self.cid, item['file_id'], [], 'html', 'revise_001')
        output = self.files.read('alice', self.cid, result['file_id'])['content']
        self.assertIn(b'&lt;script&gt;', output)
        self.assertNotIn(b'<script>', output)
        with patch('conversation_files.MAX_CELLS', 1):
            with self.assertRaisesRegex(ValueError, 'too_large'):
                parse_table(b'a,b\n1,2', 'csv')
        with self.assertRaises(ValueError):
            self.files.save('alice', self.cid, '../x.csv', b'a', 'upload_002')

    def request(self, method, path, body=b'', headers=None, user='alice', allowed=True):
        message = Message()
        for key, value in {'Content-Length': str(len(body)), 'Content-Type': 'application/octet-stream',
                           'X-FS-Advisor-Action': 'submit', 'Sec-Fetch-Site': 'same-origin', **(headers or {})}.items():
            message[key] = value
        status, response_headers = [], {}
        handler = SimpleNamespace(headers=message, rfile=io.BytesIO(body), wfile=io.BytesIO(),
                                  connection=SimpleNamespace(settimeout=lambda _: None),
                                  send_response=status.append, send_header=lambda k, v: response_headers.update({k: v}),
                                  end_headers=lambda: None)
        def submit(owner, cid, text, request_id, file_ids=None):
            return self.store.reserve_turn(owner, cid, text, request_id, file_ids)
        service = SimpleNamespace(store=self.store, detail=self.store.detail, submit=submit)
        self.assertTrue(handle(handler, method, urlsplit('/api/hermes/conversations/' + self.cid + path),
                               user, service, lambda _: allowed))
        return status[0], handler.wfile.getvalue(), response_headers

    def test_http_upload_revision_download_and_revocation(self):
        code, raw, _ = self.request('POST', '/files', b'a,b\n1,2',
                                    {'X-FS-Filename': 'a.csv', 'X-FS-Request-ID': 'upload_001'})
        self.assertEqual(code, 201)
        fid = json.loads(raw)['file_id']
        code, raw, _ = self.request('POST', '/files/' + fid + '/revisions',
                                    json.dumps({'edits': [], 'format': 'xlsx', 'client_request_id': 'revise_001'}).encode(),
                                    {'Content-Type': 'application/json'})
        self.assertEqual(code, 201)
        revised = json.loads(raw)['file_id']
        code, content, headers = self.request('GET', '/files/' + revised)
        self.assertEqual(code, 200)
        self.assertTrue(content.startswith(b'PK'))
        self.assertEqual(headers['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(self.request('GET', '/files/' + fid, user='bob')[0], 404)
        self.assertEqual(self.request('GET', '/files/' + fid, allowed=False)[0], 403)
        self.assertEqual(self.request('POST', '/files', b'x', {'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.request('POST', '/files', b'bad zip',
                                     {'X-FS-Filename': 'bad.xlsx', 'X-FS-Request-ID': 'upload_002'})[0], 422)

    def test_http_submit_binds_attachments_and_conflicting_retry_fails(self):
        first = self.files.save('alice', self.cid, 'a.csv', b'a', 'upload_001')
        payload = {'text': 'analyze', 'client_request_id': 'turn_001', 'file_ids': [first['file_id']]}
        status, raw, _ = self.request('POST', '/turns', json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        self.assertEqual(status, 202)
        turn = json.loads(raw)
        self.assertEqual(self.store.detail('alice', self.cid)['turns'][0]['file_bindings']['inputs'], [first['file_id']])
        payload['file_ids'] = []
        self.assertEqual(self.request('POST', '/turns', json.dumps(payload).encode(), {'Content-Type': 'application/json'})[0], 422)


class StoreTests(unittest.TestCase):
    def test_owner_idempotency_resume_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            conversation = store.create("admin_a")
            cid = conversation["conversation_id"]
            turn = store.reserve_turn("admin_a", cid, "查单品", "request_001")
            self.assertEqual(store.reserve_turn("admin_a", cid, "查单品", "request_001")["turn_id"], turn["turn_id"])
            with self.assertRaises(ValueError):
                store.reserve_turn("admin_a", cid, "换个问题", "request_001")
            with self.assertRaises(RuntimeError):
                store.reserve_turn("admin_a", cid, "并发追问", "request_002")
            run_id = "run_" + "a" * 32
            store.bind_run("admin_a", cid, turn["turn_id"], run_id)
            with self.assertRaises(LookupError):
                store.run("admin_b", cid, run_id)
            with self.assertRaises(LookupError):
                store.events("admin_b", cid)
            store.append_event("admin_a", cid, run_id, 0, {"event": "message.delta", "delta": "查", "reasoning": "secret"})
            store.append_event("admin_a", cid, run_id, 0, {"event": "message.delta", "delta": "查", "reasoning": "secret"})
            store.append_event("admin_a", cid, run_id, 1, {"event": "reasoning.available", "text": "hidden"})
            html = b"<!doctype html><html><script>parent.document.cookie</script></html>"
            store.append_event("admin_a", cid, run_id, 2, {"event": "run.completed", "output": html.decode()})
            store.set_state("admin_a", cid, turn["turn_id"], "completed")
            original = store.save_original("admin_a", cid, run_id, html, "hermes-original.html", "text/html")
            self.assertEqual(original["sha256"], hashlib.sha256(html).hexdigest())
            self.assertEqual(store.save_original("admin_a", cid, run_id, html, "hermes-original.html", "text/html"), original)
            self.assertEqual(store.artifact("admin_a", cid, original["artifact_id"])["content"], html)
            with self.assertRaises(LookupError):
                store.artifact("admin_b", cid, original["artifact_id"])
            with self.assertRaises(LookupError):
                store.artifact("admin_a", cid, "../conversations.db")
            events = store.events("admin_a", cid)
            self.assertEqual([e["type"] for e in events], ["message.delta", "run.completed"])
            self.assertEqual(store.events("admin_a", cid, events[0]["seq"])[0]["type"], "run.completed")
            self.assertNotIn("reasoning", str(events))
            snapshot = store.detail("admin_a", cid)
            self.assertEqual(snapshot["turns"][0]["text"], "查单品")
            self.assertEqual(snapshot["turns"][0]["reply"], html.decode())
            self.assertEqual(snapshot["last_seq"], events[-1]["seq"])

    def test_controls_do_not_repeat_unknown_external_write(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("admin")["conversation_id"]
            turn = store.reserve_turn("admin", cid, "查询", "request_001")
            run_id = "run_" + "b" * 32
            store.bind_run("admin", cid, turn["turn_id"], run_id)
            first = store.action("admin", cid, run_id, "steer", "steer_001", "补充")
            second = store.action("admin", cid, run_id, "steer", "steer_001", "补充")
            self.assertFalse(first["reused"])
            self.assertEqual(second, {"state": "unknown", "reused": True})
            with self.assertRaises(ValueError):
                store.action("admin", cid, run_id, "stop", "steer_001")
            store.action_result("admin", cid, run_id, "steer_001", "accepted")
            self.assertEqual(store.action("admin", cid, run_id, "steer", "steer_001", "补充")["state"], "accepted")

    def test_running_snapshot_failure_and_sse_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("admin")["conversation_id"]
            turn = store.reserve_turn("admin", cid, "先查销售", "request_001")
            run_id = "run_" + "c" * 32
            store.bind_run("admin", cid, turn["turn_id"], run_id)
            store.append_event("admin", cid, run_id, 0, {"event": "message.delta", "delta": "第一段"})
            store.append_event("admin", cid, run_id, None, {"event": "replay.truncated", "requested_seq": 0, "oldest_retained_seq": 2})
            store.append_event("admin", cid, run_id, 2, {"event": "message.delta", "delta": "第二段"})
            self.assertEqual(store.last_upstream("admin", cid, run_id), 2)
            self.assertEqual(store.detail("admin", cid)["turns"][0]["reply"], "第一段第二段")
            store.append_event("admin", cid, run_id, 3, {"event": "run.failed", "error": "已脱敏的错误", "secret": "hidden"})
            store.set_state("admin", cid, turn["turn_id"], "failed")
            self.assertEqual(store.detail("admin", cid)["turns"][0]["error"], "Hermes 运行失败，请检查任务状态")
            self.assertNotIn("已脱敏的错误", str(store.events("admin", cid)))
            self.assertNotIn("secret", str(store.events("admin", cid)))

    def test_terminal_dedup_after_many_events(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("admin")["conversation_id"]
            turn = store.reserve_turn("admin", cid, "长运行", "request_001")
            run_id = "run_" + "d" * 32
            store.bind_run("admin", cid, turn["turn_id"], run_id)
            for seq in range(510):
                store.append_event("admin", cid, run_id, seq, {"event": "message.delta", "delta": "a"})
            store.append_event("admin", cid, run_id, 510, {"event": "run.completed", "output": "最终原文"})
            self.assertTrue(store.has_event("admin", cid, run_id, "run.completed"))
            self.assertEqual(store.detail("admin", cid)["turns"][0]["reply"], "最终原文")


if __name__ == "__main__":
    unittest.main()
