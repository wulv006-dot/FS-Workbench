"""B consumer contracts; actual A binding/service integration is separate."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent / "source"))
from conversation_file_tools import NAMES, WIRE_NAMES, attach_conversation_file_tools, file_prompt, tool_schemas

FID = "a" * 32


class FileToolContracts(unittest.TestCase):
    def setUp(self):
        self.original = Mock(return_value={"old": True})
        self.book = SimpleNamespace(call=self.original)
        self.context = Mock()
        attach_conversation_file_tools(self.book, self.context)

    def read_args(self, **changes):
        return dict(file_id=FID, sheet=0, offset=0, limit=200, **changes)

    def test_schemas_preserve_exact_names_and_disallow_identity_arguments(self):
        schemas = tool_schemas()
        self.assertEqual(tuple(s["function"]["name"] for s in schemas), WIRE_NAMES)
        for s in schemas:
            p = s["function"]["parameters"]
            self.assertFalse(p["additionalProperties"])
            self.assertFalse(set(p["properties"]) & {"owner", "cid", "turn_id", "url", "path"})

    def test_static_prompt_does_not_load_files_during_preparation(self):
        self.assertIn("selected_sheet", file_prompt(self.context))
        self.context.assert_not_called()
        self.assertEqual(self.context.mock_calls, [])

    def test_non_file_tool_passes_through_unchanged(self):
        args = {"original": 1}
        self.assertEqual(self.book.call("fc.get_data_catalog", args), {"old": True})
        self.original.assert_called_once_with("fc.get_data_catalog", args)
        self.assertEqual(self.context.mock_calls, [])

    def test_absent_context_is_denied_and_empty_catalog_is_preserved(self):
        empty = SimpleNamespace(call=self.original)
        attach_conversation_file_tools(empty, None)
        with self.assertRaises(PermissionError):
            empty.call(NAMES[0], {})
        self.context.catalog.return_value = {"items": []}
        self.assertEqual(self.book.call(NAMES[0], {})["items"], [])

    def test_partial_page_and_selected_sheet_scope_are_not_promoted(self):
        response = {"file_id": FID, "complete": False, "truncated": True, "next_offset": 200,
                    "sheets": [{"name": "CSV", "rows": [["x"]]}],
                    "coverage": {"scope": "selected_sheet", "total_sheets": 2, "complete": False}}
        self.context.read_table.return_value = deepcopy(response)
        value = self.book.call(NAMES[1], self.read_args())
        for k, v in response.items():
            self.assertEqual(value[k], v)
        self.context.read_table.assert_called_once_with(FID, sheet=0, offset=0, limit=200)
        value["sheets"].clear()
        self.assertEqual(len(self.context.read_table.return_value["sheets"]), 1)
        self.context.read_table.return_value = dict(response, complete=True, truncated=False, next_offset=None)
        self.assertEqual(self.book.call(NAMES[1], self.read_args())["coverage"]["scope"], "selected_sheet")

    def test_model_identity_and_invalid_paging_never_reach_a(self):
        for args in ({"owner": "other"}, {"file_id": "../secret", "sheet": 0, "offset": 0, "limit": 1},
                     dict(self.read_args(), limit=201), dict(self.read_args(), sheet=True),
                     dict(self.read_args(), offset=-1), dict(self.read_args(), url="https://example.invalid")):
            with self.assertRaises(ValueError):
                self.book.call(NAMES[1], args)
        self.assertEqual(self.context.mock_calls, [])

    def test_recheck_revocation_turn_and_expiry_on_every_call(self):
        self.context.catalog.side_effect = [{"items": []}, PermissionError("revoked")]
        self.book.call(NAMES[0], {})
        with self.assertRaises(PermissionError):
            self.book.call(NAMES[0], {})
        self.context.read_table.side_effect = LookupError("file_expired")
        with self.assertRaises(LookupError):
            self.book.call(NAMES[1], self.read_args())
        self.assertEqual(self.context.catalog.call_count, 2)

    def test_unknown_revision_is_preserved_and_not_retried(self):
        args = dict(file_id=FID, edits=[], format="xlsx", request_id="revision_001")
        self.context.revise.return_value = {"status": "unknown", "request_id": "revision_001"}
        value = self.book.call(NAMES[2], args)
        self.assertEqual(value["status"], "unknown")
        self.assertEqual(value["request_id"], "revision_001")
        self.context.revise.assert_called_once_with(FID, [], "xlsx", "revision_001")
        self.context.revise.reset_mock(side_effect=True)
        self.context.revise.side_effect = TimeoutError("unknown")
        with self.assertRaises(TimeoutError):
            self.book.call(NAMES[2], args)
        self.context.revise.assert_called_once()

    def test_revision_edits_are_bounded_and_finite(self):
        args = dict(file_id=FID, edits=[], format="csv", request_id="revision_001")
        edit = dict(sheet=0, row=0, column=0, value="7")
        for change in (dict(edits=[edit] * 1001), dict(edits=[dict(edit, value=float("nan"))]),
                       dict(edits=[dict(edit, row=True)]), dict(request_id="x"), dict(format="py")):
            with self.assertRaises(ValueError):
                self.book.call(NAMES[2], dict(args, **change))
        self.context.revise.assert_not_called()


class FileProxyContracts(unittest.TestCase):
    @contextmanager
    def proxy(self, source):
        root = Path(__file__).resolve().parents[3]
        pilot = SimpleNamespace(TOOLS=("fc.old",), digest=lambda _: "fixture", encoded=json.dumps, SHANGHAI=timezone.utc)
        research = SimpleNamespace(RESEARCH_NAMES=(), tool_schemas=lambda: [])
        strategy = SimpleNamespace(NAMES=(), schemas=lambda: [], call=Mock())
        def load(name, path):
            spec = importlib.util.spec_from_file_location(name, root / path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        with patch.dict(sys.modules, pilot=pilot, research=research, strategy_tools=strategy):
            contract = load("file_contract_fixture", "releases/fs-dashboard/hermes-v2-strategy-20261021/source/runs_contract.py")
            with patch.dict(sys.modules, runs_contract=contract):
                yield load("file_proxy_fixture", source), contract

    def sources(self):
        return ("releases/fs-dashboard/hermes-v2-strategy-20261021/source/proxy_gateway.py",
                "releases/fc-coins/fc-review-channel-20261026/source/proxy_gateway.py")

    def test_shared_schema_and_wire_allowlist_align_without_removing_original(self):
        for source in self.sources():
            with self.subTest(source=source), self.proxy(source) as (proxy, contract):
                names = tuple(s["function"]["name"] for s in proxy.schemas())
                self.assertEqual(names, contract.WIRE_TOOLS)
                self.assertEqual(names[0], "mcp__fcro__fc_old")
                self.assertEqual(names[-3:], WIRE_NAMES)

    def test_task_lease_and_turn_context_guards_precede_file_access(self):
        for source in self.sources():
            with self.subTest(source=source), self.proxy(source) as (proxy, contract):
                task = {"state": "RUNNING", "lease": "lease1", "spec": {"snapshot_id": "capture1"}}
                tasks = SimpleNamespace(get=Mock(return_value=task))
                book = SimpleNamespace(capture_id="capture1", call=Mock())
                clock = lambda: datetime.now(timezone.utc)
                scoped = proxy.ScopedTools(tasks, book, clock)
                with self.assertRaises(PermissionError):
                    scoped.call("alice", "task1", "lease1", WIRE_NAMES[0], {})
                book.call.assert_not_called()
                context = Mock(); context.catalog.return_value = {"items": []}
                attach_conversation_file_tools(book, context)
                value = scoped.call("alice", "task1", "lease1", WIRE_NAMES[0], {})
                self.assertEqual(value["data"]["items"], [])
                self.assertEqual(context.catalog.call_count, 1)
                for change in ({"state": "CANCELLED"}, {"lease": "other"}, {"spec": {"snapshot_id": "other"}}):
                    tasks.get.return_value = dict(task, **change)
                    with self.assertRaises(PermissionError):
                        scoped.call("alice", "task1", "lease1", WIRE_NAMES[0], {})
                self.assertEqual(context.catalog.call_count, 1)


if __name__ == "__main__":
    unittest.main()
