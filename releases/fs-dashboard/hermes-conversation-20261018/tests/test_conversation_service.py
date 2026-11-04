from contextlib import contextmanager
from datetime import timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "source"
sys.path.insert(0, str(SOURCE))


@contextmanager
def guard(_path):
    yield True


class Pool:
    def __init__(self):
        self.jobs = []

    def submit(self, fn, *args):
        self.jobs.append((fn, args))


class Tasks:
    def __init__(self):
        self.state = "RUNNING"

    def get(self, task_id, user):
        return {"id": task_id, "owner": user, "state": self.state}

    def observe(self, task_id, user, lease, state, *, worker_stopped=False):
        assert worker_stopped and state == "completed"
        self.state = "VALIDATING"
        return self.get(task_id, user)

    def change(self, task, state):
        self.state = state

    def fence(self, task_id, user):
        self.state = "NEEDS_RECONCILE"


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        controller = types.ModuleType("controller")
        controller.NoRedirect = object
        controller.admission_guard = guard
        controller.atomic = lambda *_: None
        evidence = types.ModuleType("fs_evidence")
        evidence.build_book = lambda *a, **k: None
        inprocess = types.ModuleType("fs_inprocess")
        inprocess.gateway = lambda *a: None
        inprocess.spending_hold = lambda *a: False
        pilot = types.ModuleType("pilot")
        pilot.SHANGHAI = timezone.utc
        pilot.digest = lambda _: "a" * 64
        pilot.encoded = lambda obj: json.dumps(obj)
        with patch.dict(sys.modules, {"controller": controller, "fs_evidence": evidence,
                                      "fs_inprocess": inprocess, "pilot": pilot}):
            spec = importlib.util.spec_from_file_location("candidate_conversation_service", SOURCE / "conversation_service.py")
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)

    def test_admin_on_every_read_write_and_exact_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = types.SimpleNamespace(root=Path(directory), authorizer=lambda user: user in {"admin_a", "admin_b"},
                                           daily=None, tasks=None)
            service = self.module.ConversationService(hermes, Path(directory) / "data", Path(directory) / "run")
            service.pool.shutdown(wait=True)
            service.pool = Pool()
            with self.assertRaises(PermissionError):
                service.create("ordinary")
            cid = service.create("admin_a")["conversation_id"]
            self.assertEqual(service.listed("admin_a")["items"][0]["conversation_id"], cid)
            self.assertEqual(service.listed("admin_b")["items"], [])
            for name, args in (("listed", ()), ("detail", (cid,)), ("events", (cid,)),
                               ("submit", (cid, "hello", "request_001")),
                               ("artifact", (cid, "a" * 32)),
                               ("steer", (cid, "run_" + "a" * 32, "hello", "request_001")),
                               ("stop", (cid, "run_" + "a" * 32, "request_001"))):
                with self.subTest(name=name), self.assertRaises(PermissionError):
                    getattr(service, name)("ordinary", *args)
            with self.assertRaises(LookupError):
                service.detail("admin_b", cid)
            turn = service.submit("admin_a", cid, "用户原文", "request_002")
            self.assertEqual(turn["state"], "preparing")
            self.assertEqual(len(service.pool.jobs), 1)
            self.assertEqual(service.detail("admin_a", cid)["turns"][0]["text"], "用户原文")

    def test_completed_original_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = types.SimpleNamespace(root=Path(directory), authorizer=lambda user: user == "admin",
                                           daily=None, tasks=None)
            service = self.module.ConversationService(hermes, Path(directory) / "data", Path(directory) / "run")
            service.pool.shutdown(wait=True)
            service.pool = Pool()
            cid = service.create("admin")["conversation_id"]
            turn = service.store.reserve_turn("admin", cid, "write", "request_001")
            run_id = "run_" + "b" * 32
            service.store.bind_run("admin", cid, turn["turn_id"], run_id)
            html = "<!doctype html><html><script>parent.document.cookie</script></html>"
            service._terminal_from_status("admin", cid, run_id, html)
            service._terminal_from_status("admin", cid, run_id, html)
            detail = service.detail("admin", cid)
            self.assertEqual(detail["turns"][0]["reply"], html)
            self.assertEqual(len(detail["turns"][0]["artifacts"]), 1)
            self.assertEqual(detail["turns"][0]["artifacts"][0]["mime"], "text/html")
            self.assertEqual(service.artifact("admin", cid, detail["turns"][0]["artifacts"][0]["artifact_id"])["content"], html.encode())

    def test_restart_reconciles_original_run_and_persisted_task(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks = Tasks()
            hermes = types.SimpleNamespace(root=Path(directory), authorizer=lambda user: user == "admin",
                                           daily=None, tasks=tasks)
            service = self.module.ConversationService(hermes, Path(directory) / "data", Path(directory) / "run")
            service.pool.shutdown(wait=True)
            service.pool = Pool()
            cid = service.create("admin")["conversation_id"]
            turn = service.store.reserve_turn("admin", cid, "query", "request_001")
            run_id = "run_" + "c" * 32
            service.store.bind_task("admin", cid, turn["turn_id"], "d" * 32, "e" * 32)
            service.store.bind_run("admin", cid, turn["turn_id"], run_id)
            service._request = lambda method, path, *args, **kwargs: (200, {"status": "completed", "output": "原稿"})
            service._recover("admin", cid, turn["turn_id"], run_id)
            self.assertEqual(tasks.state, "SUCCEEDED")
            self.assertEqual(service.detail("admin", cid)["turns"][0]["reply"], "原稿")
            self.assertEqual(len(service.detail("admin", cid)["turns"][0]["artifacts"]), 1)

    def test_html_fence_keeps_reply_and_extracts_exact_document(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = types.SimpleNamespace(root=Path(directory), authorizer=lambda user: user == "admin",
                                           daily=None, tasks=None)
            service = self.module.ConversationService(hermes, Path(directory) / "data", Path(directory) / "run")
            service.pool.shutdown(wait=True)
            cid = service.create("admin")["conversation_id"]
            turn = service.store.reserve_turn("admin", cid, "report", "request_001")
            run_id = "run_" + "a" * 32
            service.store.bind_run("admin", cid, turn["turn_id"], run_id)
            html = "<!doctype html>\n<html>\n<script>window.a=1</script>\n</html>"
            reply = "```html\n" + html + "\n```"
            service._terminal_from_status("admin", cid, run_id, reply)
            snapshot = service.detail("admin", cid)["turns"][0]
            self.assertEqual(snapshot["reply"], reply)
            item = snapshot["artifacts"][0]
            self.assertEqual(item["mime"], "text/html")
            self.assertEqual(service.artifact("admin", cid, item["artifact_id"])["content"], html.encode())

    def test_embedded_single_complete_html_is_archived_verbatim(self):
        with tempfile.TemporaryDirectory() as directory:
            hermes = types.SimpleNamespace(root=Path(directory), authorizer=lambda user: user == "admin",
                                           daily=None, tasks=None)
            service = self.module.ConversationService(hermes, Path(directory) / "data", Path(directory) / "run")
            service.pool.shutdown(wait=True)
            cid = service.create("admin")["conversation_id"]
            turn = service.store.reserve_turn("admin", cid, "report", "request_001")
            run_id = "run_" + "f" * 32
            service.store.bind_run("admin", cid, turn["turn_id"], run_id)
            html = '<!DOCTYPE html>\n<html lang="zh"><body>原字节</body></html>'
            reply = '报告如下：\n<article class="card">\n' + html + '\n</article>\n请下载查看。'
            service._terminal_from_status("admin", cid, run_id, reply)
            snapshot = service.detail("admin", cid)["turns"][0]
            self.assertEqual(snapshot["reply"], reply)
            item = snapshot["artifacts"][0]
            self.assertEqual(item["mime"], "text/html")
            self.assertEqual(service.artifact("admin", cid, item["artifact_id"])["content"], html.encode())
            self.assertIsNone(service._html_document(reply + html))
            self.assertIsNone(service._html_document('报告如下：\n' + html[:-7]))

    def test_unconfirmed_worker_status_keeps_task_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            tasks = Tasks()
            hermes = types.SimpleNamespace(root=Path(directory), authorizer=lambda user: user == "admin",
                                           daily=None, tasks=tasks)
            service = self.module.ConversationService(hermes, Path(directory) / "data", Path(directory) / "run")
            service.pool.shutdown(wait=True)
            service.pool = Pool()
            cid = service.create("admin")["conversation_id"]
            turn = service.store.reserve_turn("admin", cid, "query", "request_001")
            service.store.bind_task("admin", cid, turn["turn_id"], "d" * 32, "e" * 32)
            service._abandon_task("admin", cid, turn["turn_id"], None)
            self.assertEqual(tasks.state, "NEEDS_RECONCILE")

    def test_current_method_and_reviewed_owner_learning_are_on_demand(self):
        calls = []
        context = types.ModuleType("business_context")
        owner = ('已审索引\n<owner_learning_document path="profile/memories/MEMORY.md" sha256="' + "b" * 64 +
                 '">\n已审业务记忆\n</owner_learning_document>')
        context.learning_bundle = lambda root: (calls.append("owner") or owner, "a" * 64,
                                                [{"path": "profile/memories/MEMORY.md", "sha256": "b" * 64}])
        method = types.ModuleType("report_method")
        method.method_bundle = lambda track: (calls.append("method") or {"version": "report-html-1.5.1",
                                                                      "sha256": "c" * 64,
                                                                      "methods_text": "现行方法", "governance_text": "现行验收"})
        book = types.SimpleNamespace(call=lambda name, args: {"old": name})
        with patch.dict(sys.modules, {"business_context": context, "report_method": method}):
            self.module.attach_current_learning(book, Path("/fake/root"))
            self.assertEqual(calls, [])
            self.assertEqual(book.call("fc.get_data_catalog", {})["old"], "fc.get_data_catalog")
            self.assertEqual(calls, [])
            index = book.call("fc.read_skill", {"topic": "methods"})
            self.assertEqual(index["version"], "report-html-1.5.1")
            self.assertNotIn("text", index)
            method_id = next(row["section_id"] for row in index["sections"] if row["path"].startswith("current/"))
            memory_id = next(row["section_id"] for row in index["sections"] if row["path"] == "profile/memories/MEMORY.md")
            self.assertIn("现行方法", book.call("fc.read_skill", {"topic": "methods", "section_id": method_id})["text"])
            self.assertIn("已审业务记忆", book.call("fc.read_skill", {"topic": "methods", "section_id": memory_id})["text"])
            legacy = book.call("fc.read_skill", {"topic": "methods", "section_id": "M1"})
            self.assertEqual(legacy["kind"], "index")
            self.assertEqual(legacy["unknown_section_id"], "M1")
            self.assertEqual(legacy["sections"], index["sections"])
            self.assertEqual(index["owner_learning_sha256"], "a" * 64)
            book.call("fc.read_skill", {"topic": "methods"})
            self.assertEqual(calls, ["method", "owner"])
            self.assertEqual(book.call("fc.read_skill", {"topic": "background"})["old"], "fc.read_skill")

    def test_business_policy_question_can_read_current_reviewed_memory(self):
        self.assertIn("经营政策", self.module.SHORT_RULES)
        self.assertIn("fc.read_skill", self.module.SHORT_RULES)
        sibling = SOURCE.parents[1]
        candidates = (
            (sibling / "hermes-data-workspace-20261018/source/business_context.py",
             sibling / "hermes-data-workspace-20261018/skills"),
            (sibling / "fs_hermes_data_workspace_20261018/hermes/source/business_context.py",
             sibling / "fs_hermes_data_workspace_20261018/skills"),
        )
        found = [(source, skills) for source, skills in candidates if source.is_file() and skills.is_dir()]
        self.assertEqual(len(found), 1, "reviewed_learning_source_missing_or_ambiguous")
        source, skills = found[0]
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         "8e4b799340957d5e03b92f8b9d2c6d32407fcd0e02592b3525687a77ab825dfd")
        skill = (skills / "data-storytelling/SKILL.md").read_bytes()
        self.assertEqual(hashlib.sha256(skill.replace(b"\r\n", b"\n")).hexdigest(),
                         "a9e8e61e9d90be4417039983b6b9560119c363063ce5f5cc052865fb95ee1acd")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            runtime = root / "runtime-src"
            runtime.mkdir(mode=0o700)
            checked_source = runtime / "business_context.py"
            checked_source.write_bytes(source.read_bytes())
            checked_source.chmod(0o600)
            original_loop = (source.parent / "learning-loop.md").read_bytes()
            self.assertEqual(hashlib.sha256(original_loop).hexdigest(),
                             "a52370bc39936efd92ab66214784c5d8e414566d5ab54dab10761a1e3f0e8f46")
            loop = runtime / "learning-loop.md"
            loop.write_bytes(original_loop)
            loop.chmod(0o600)
            copied_skills = root / "profile" / "skills" / "data-storytelling"
            copied_skills.mkdir(parents=True, mode=0o700)
            copied_skills.parent.chmod(0o700)
            copied_skills.parent.parent.chmod(0o700)
            copied_skills.chmod(0o700)
            copied_skill = copied_skills / "SKILL.md"
            copied_skill.write_bytes(skill)
            copied_skill.chmod(0o600)
            business = root / "desktop-business-context.md"
            business.write_text("已确认业务规则", encoding="utf-8")
            business.chmod(0o600)
            spec = importlib.util.spec_from_file_location("active_business_context_candidate", checked_source)
            active = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(active)
            context = types.ModuleType("business_context")
            context.learning_bundle = lambda _: active.learning_bundle(
                root, skill_root=copied_skills.parent, profile_root=root / "profile")
            method = types.ModuleType("report_method")
            method.method_bundle = lambda track: {"version": "report-html-1.5.1", "sha256": "c" * 64,
                                                  "methods_text": "现行方法", "governance_text": "现行验收"}
            book = types.SimpleNamespace(call=lambda name, args: {"old": name})
            with patch.dict(sys.modules, {"business_context": context, "report_method": method}):
                self.module.attach_current_learning(book, root)
                index = book.call("fc.read_skill", {"topic": "governance"})
                row = next(row for row in index["sections"] if row["path"] == "skills/data-storytelling/SKILL.md")
                policy = book.call("fc.read_skill", {"topic": "governance", "section_id": row["section_id"]})
            self.assertIn("新客首单30%", policy["text"])
            self.assertLess(len(json.dumps(index, ensure_ascii=False).encode("utf-8")), 8000)
            self.assertLess(len(json.dumps(policy, ensure_ascii=False).encode("utf-8")), 8000)

    def test_active_request_capabilities_exact_get_preserves_transport(self):
        import ast
        import io
        import re
        from email.message import Message
        from urllib import request as http
        from urllib.error import HTTPError
        from urllib.response import addinfourl
        root = Path(__file__).resolve().parents[4]
        active = root / 'releases/fc-coins/fc-pricing-v3-20261026/source/conversation_service.py'
        tree = ast.parse(active.read_bytes())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_request')
        controller = ast.parse((root / 'releases/fs-dashboard/hermes-v2-core-20261020/source/controller.py').read_bytes())
        redirect = next(n for n in controller.body if isinstance(n, ast.ClassDef) and n.name == 'NoRedirect')
        scope = {'HTTPRedirectHandler': http.HTTPRedirectHandler, 're': re, 'Request': http.Request,
                 'build_opener': http.build_opener, 'RUNNER': 'http://127.0.0.1:8941',
                 'MAX_RESPONSE': 10 * 1024 * 1024, 'encoded': self.module.encoded, 'json': json}
        exec(compile(ast.Module(body=[redirect, node], type_ignores=[]), str(active), 'exec'), scope)
        self.assertTrue(issubclass(scope['NoRedirect'], http.HTTPRedirectHandler))
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory);(run_root / 'api-key').write_text('synthetic-capability-key', encoding='ascii')
            service = types.SimpleNamespace(run_root=run_root)
            call = lambda method, path, *a, **kw: scope['_request'](service, method, path, *a, **kw)
            requests = []; reads = []; options = {'status': 200, 'large': False}
            class Body(io.BytesIO):
                def read(self, size=-1):
                    reads.append(size)
                    return b'x' * size if options['large'] else super().read(size)
            def boundary(_handler, request):
                requests.append(request)
                headers = Message()
                if options['status'] == 302:headers['Location'] = 'http://unreached.invalid/redirect'
                body = json.dumps({'object': 'hermes.api_server.capabilities'}).encode()
                response = addinfourl(Body(body), headers, request.full_url, options['status'])
                response.msg = 'synthetic final HTTP boundary'
                return response
            with patch.object(http, 'getproxies', return_value={}), \
                 patch.object(http.HTTPHandler, 'http_open', autospec=True, side_effect=boundary), \
                 patch.object(http.HTTPSHandler, 'https_open', side_effect=AssertionError('no_real_network')):
                status, result = call('GET', '/v1/capabilities', timeout=2.75)
                self.assertEqual((status, result), (200, {'object': 'hermes.api_server.capabilities'}))
                request = requests[-1]
                self.assertIsInstance(request, http.Request)
                self.assertEqual(request.full_url, 'http://127.0.0.1:8941/v1/capabilities')
                self.assertEqual(request.get_method(), 'GET');self.assertIsNone(request.data)
                self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-capability-key')
                self.assertEqual(request.timeout, 2.75)
                self.assertEqual(reads, [scope['MAX_RESPONSE'] + 1])
                before = len(requests)
                with patch.object(Path, 'read_text', side_effect=AssertionError('rejected_route_cannot_read_key')):
                    for method, path in [('POST', '/v1/capabilities'), ('HEAD', '/v1/capabilities'),
                            ('get', '/v1/capabilities'), ('GET', '/v1/capabilities/extra'),
                            ('GET', '/v1/capabilities/'), ('GET', '/v1/capabilities?probe=1'),
                            ('GET', '/health'), ('GET', '/v1/health'), ('GET', '/v1/models'),
                            ('GET', '/api/sessions'), ('GET', '/v1/runs?limit=1')]:
                        with self.subTest(method=method, path=path), self.assertRaisesRegex(ValueError, '^runtime_route$'):
                            call(method, path)
                self.assertEqual(len(requests), before)
                run_id = 'run_' + 'a' * 32
                for method, path in [('POST', '/v1/runs'), ('GET', '/v1/runs/' + run_id),
                        ('GET', '/v1/runs/' + run_id + '/events'), ('POST', '/v1/runs/' + run_id + '/steer'),
                        ('POST', '/v1/runs/' + run_id + '/stop'), ('GET', '/v1/native/hc_' + 'b' * 64)]:
                    with self.subTest(legacy=path):
                        body = {'input': 'synthetic'} if method == 'POST' else None
                        self.assertEqual(call(method, path, body, 'original-id')[0], 200)
                        request = requests[-1]
                        self.assertEqual(request.timeout, 30)
                        self.assertEqual(request.get_header('Idempotency-key'), 'original-id')
                        self.assertEqual(request.data, self.module.encoded(body).encode() if body is not None else None)
                        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-capability-key')
                options['large'] = True
                with self.assertRaisesRegex(ValueError, '^runtime_response_size$'):call('GET', '/v1/capabilities')
                options.update(large=False, status=302);before = len(requests)
                with self.assertRaises(HTTPError) as denied:call('GET', '/v1/capabilities')
                self.assertEqual(denied.exception.code, 302)
                self.assertEqual(len(requests), before + 1)



def load_tests(loader, tests, pattern):
    import test_conversation_knowledge
    import test_conversation_desktop
    tests.addTests(loader.loadTestsFromModule(test_conversation_knowledge))
    tests.addTests(loader.loadTestsFromModule(test_conversation_desktop))
    return tests


if __name__ == "__main__":
    unittest.main()
