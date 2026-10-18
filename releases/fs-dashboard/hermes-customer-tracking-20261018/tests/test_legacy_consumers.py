"""Old report and conversation consumers against the new candidate sources."""
import importlib.util
from pathlib import Path
import sys
import unittest


from _paths import ROOT, RELEASE
NEW = RELEASE / "source"


class LegacyConsumers(unittest.TestCase):
    def test_daily_weekly_book_denies_private_customer_tool(self):
        from research import ResearchBook, tool_schemas
        from runs_contract import WIRE_TOOLS
        from proxy_gateway import schemas

        self.assertEqual(Path(sys.modules["research"].__file__).resolve(), NEW / "research.py")
        book = ResearchBook(
            {"snapshot_id": "fc-detail-legacy-regression",
             "as_of": "2026-10-18T00:00:00+00:00",
             "coverage": {"period": {"start": "2026-10-17", "end": "2026-10-18"}},
             "orders": [], "backlog": []}, {},
            {"start": "2026-10-17", "end": "2026-10-17"})
        with self.assertRaisesRegex(PermissionError, "tool_denied"):
            book.call("fc.query_customer_tracking", {"tracking_id": "a" * 32})
        self.assertTrue({s["function"]["name"] for s in tool_schemas()} <= set(WIRE_TOOLS))
        self.assertEqual(set(WIRE_TOOLS), {s["function"]["name"] for s in schemas()})

    def test_prior_conversation_contract_with_new_service_source(self):
        path = ROOT / "releases/fs-dashboard/hermes-conversation-20261018/tests" / "test_conversation_service.py"
        spec = importlib.util.spec_from_file_location("legacy_conversation_contract", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.SOURCE = NEW
        self.assertEqual(module.SOURCE, NEW)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        self.assertEqual(suite.countTestCases(), 8)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])


if __name__ == "__main__":
    unittest.main()
