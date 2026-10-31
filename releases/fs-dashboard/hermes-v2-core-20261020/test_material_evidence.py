"""B analysis coverage/route/handoff contracts using synthetic attachment facts."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import sys
import unittest
from copy import deepcopy
sys.path.insert(0, str(Path(__file__).parent / "source"))
from material_evidence import MaterialEvidence
from conversation_file_tools import attach_conversation_file_tools, NAMES
from b1_model_routing import Capability, handoff, select_model

FID = "a" * 32
SHA = "b" * 64


def page(start, end, total=5, sheet=0, sheets=1, sha=SHA):
    complete = start == 0 and end == total
    return {"file_id": FID, "sha256": sha, "complete": complete,
            "next_offset": end if end < total else None,
            "sheets": [{"name": "sheet", "rows": [["private cell"] for _ in range(start, end)]}],
            "coverage": {"scope": "selected_sheet", "sheet": sheet, "offset": start,
                "end_exclusive": end, "total_rows": total, "returned_rows": end-start,
                "total_sheets": sheets, "complete": complete}}


class MaterialEvidenceContracts(unittest.TestCase):
    def setUp(self):
        self.ledger = MaterialEvidence(clock=lambda: "2026-10-31T14:00:00+00:00")

    def observe(self, value, ledger=None):
        c = value["coverage"]
        return (ledger or self.ledger).observe_page(value, {"file_id": FID,
            "sheet": c["sheet"], "offset": c["offset"], "limit": 200})

    def test_out_of_order_overlap_and_duplicate_pages_do_not_double_count(self):
        self.observe(page(3, 5))
        self.observe(page(0, 2))
        gap = self.observe(page(0, 2))
        self.assertFalse(gap["workbook_complete"])
        self.assertEqual(gap["observed_sheets"][0]["covered_rows"], 4)
        self.assertEqual(gap["observed_sheets"][0]["missing_ranges"], [[2, 3]])
        final = self.observe(page(1, 4))
        self.assertTrue(final["workbook_complete"])
        self.assertEqual(final["observed_sheets"][0]["covered_rows"], 5)

    def test_complete_sheet_is_not_complete_workbook(self):
        first = self.observe(page(0, 5, sheets=2))
        self.assertTrue(first["observed_sheets"][0]["complete"])
        self.assertFalse(first["workbook_complete"])
        self.assertEqual(first["unread_sheet_count"], 1)
        final = self.observe(page(0, 0, total=0, sheet=1, sheets=2))
        self.assertTrue(final["workbook_complete"])

    def test_versions_and_dimensions_are_never_silently_unioned(self):
        for new in (page(2, 5, sha="c" * 64), page(2, 6, total=6), page(2, 5, sheets=2)):
            with self.subTest(new=new):
                ledger = MaterialEvidence()
                self.observe(page(0, 2), ledger)
                result = self.observe(new, ledger)
                self.assertEqual(result["status"], "unverified")
                self.assertFalse(ledger.summaries()[0]["workbook_complete"])
                self.assertTrue(ledger.handoff_evidence()[0]["missing"])

    def test_malformed_or_unknown_page_never_establishes_coverage(self):
        good = page(0, 2)
        variants = [dict(good, status="unknown"), dict(good, file_id="d" * 32),
                    dict(good, complete=True), dict(good, next_offset=None),
                    dict(good, sha256="not a version"), dict(good, sheets=[]),
                    dict(good, coverage=dict(good["coverage"], scope="workbook")),
                    dict(good, coverage=dict(good["coverage"], offset=True))]
        for bad in variants:
            with self.subTest(bad=bad):
                value = self.ledger.observe_page(bad, {"file_id": FID, "sheet": 0, "offset": 0, "limit": 200})
                self.assertEqual(value["status"], "unverified")
                self.assertFalse(value["workbook_complete"])
        self.assertEqual(self.ledger.summaries(), [])

    def test_source_coverage_is_preserved_and_handoff_contains_no_cells(self):
        value = page(0, 2, sheets=2)
        before = deepcopy(value)
        context = SimpleNamespace(read_table=lambda *a, **kw: value)
        book = SimpleNamespace(call=lambda *a: {})
        attach_conversation_file_tools(book, context)
        result = book.call(NAMES[1], {"file_id": FID, "sheet": 0, "offset": 0, "limit": 200})
        self.assertEqual(value, before)
        self.assertEqual(result["coverage"], value["coverage"])
        refs = book.material_evidence.handoff_evidence()
        task = handoff(task_id="materials", revision=1, goal="inspect necessary sheet", constraints=[],
                       evidence=refs, completed_actions=[], next_step="read missing range if relevant")
        self.assertNotIn("private cell", str(task))
        for stored in book.material_evidence.files.values():
            for sheet in stored["sheets"].values():
                self.assertNotIn("rows", sheet)
        self.assertNotIn("private cell", str(book.material_evidence.files))
        self.assertTrue(task["evidence"][0]["missing"])
        self.assertEqual(task["evidence"][0]["source"], "turn_file_tool_read_receipt")

    def test_new_turn_starts_with_no_inherited_read_coverage(self):
        self.observe(page(0, 5))
        self.assertTrue(self.ledger.summaries()[0]["workbook_complete"])
        book = SimpleNamespace(call=lambda *a: {})
        attach_conversation_file_tools(book, SimpleNamespace(catalog=lambda: {"items": []}))
        book.call(NAMES[0], {})
        self.assertEqual(book.material_evidence.handoff_evidence(), [])

    def test_material_task_routes_to_tool_capable_provider_before_brand_preference(self):
        models = [Capability("openai", "fixture-text", frozenset({"text"}), frozenset({"investigation"}),
                             tools=False, available=True),
                  Capability("deepseek", "fixture-tools", frozenset({"text"}), frozenset({"investigation"}),
                             tools=True, available=True)]
        selected = select_model(models, task="investigation", inputs={"text"}, needs_tools=True,
                                allowed_providers={"openai", "deepseek"})
        self.assertEqual(selected["provider"], "deepseek")

    def test_real_bound_file_pages_feed_the_model_coverage_and_b1_handoff(self):
        source = Path(__file__).parent.parent / "hermes-conversation-20261018/source"
        sys.path.insert(0, str(source))
        from conversation_store import ConversationStore
        from conversation_files import ConversationFiles
        from conversation_file_bindings import context_factory
        with TemporaryDirectory() as directory:
            store = ConversationStore(directory)
            cid = store.create("alice")["conversation_id"]
            item = ConversationFiles(store).save("alice", cid, "sample.csv",
                b"item,amount\na,2\nb,3\n", "upload_evidence_001")
            turn = store.reserve_turn("alice", cid, "read materials", "turn_evidence_001", [item["file_id"]])
            store.bind_run("alice", cid, turn["turn_id"], "run_" + turn["turn_id"])
            book = SimpleNamespace(call=lambda *a: {})
            attach_conversation_file_tools(book, context_factory(store, "alice", cid, turn["turn_id"], lambda _: True))
            args = {"file_id": item["file_id"], "sheet": 0, "offset": 0, "limit": 2}
            first = book.call(NAMES[1], args)
            self.assertFalse(first["analysis_coverage"]["workbook_complete"])
            final = book.call(NAMES[1], dict(args, offset=first["next_offset"]))
            self.assertFalse(final["complete"])  # A's single page remains partial.
            self.assertTrue(final["analysis_coverage"]["workbook_complete"])
            refs = book.material_evidence.handoff_evidence()
            self.assertEqual(refs[0]["missing"], [])
            self.assertEqual(refs[0]["version"], item["sha256"])
