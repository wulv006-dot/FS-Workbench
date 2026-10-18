from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "source" / "fs_evidence.py"


class LazyEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pilot = types.ModuleType("pilot")
        pilot.digest = lambda _: "a" * 64
        research = types.ModuleType("research")
        research.ResearchBook = object
        research.label = lambda x: x
        skills = types.ModuleType("skill_bundle")
        skills.load_bundle = lambda *a, **k: {"version": "test"}
        with patch.dict(sys.modules, {"pilot": pilot, "research": research, "skill_bundle": skills}):
            spec = importlib.util.spec_from_file_location("candidate_fs_evidence", SOURCE)
            cls.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.module)

    def test_short_tool_skips_capture_paid_tool_single_flight(self):
        started = threading.Event()
        release = threading.Event()
        calls = []

        def reader():
            calls.append("capture")
            started.set()
            release.wait(2)
            return ({"coverage": {"status": "available"},
                     "as_of": datetime.now(timezone.utc).isoformat()}, {"enabled": True})

        class Book:
            def __init__(self):
                self.data = {"coverage": {"status": "not_loaded"}}
                self._lock = threading.RLock()
                self.call = lambda name, args: {"tool": name, "coverage": self.data["coverage"]["status"]}

        book = self.module.lazy_paid_capture(Book(), reader, {"enabled": True})
        self.assertEqual(book.call("fc.read_skill", {}), {"tool": "fc.read_skill", "coverage": "not_loaded"})
        self.assertEqual(calls, [])
        self.assertEqual(book.call("fc.get_data_catalog", {})["coverage"], "not_loaded")
        self.assertEqual(book.call("fc.query_business", {})["status"], "pending")
        self.assertTrue(started.wait(1))
        self.assertEqual(book.call("fc.query_queue", {})["status"], "pending")
        self.assertEqual(calls, ["capture"])
        release.set()
        for _ in range(100):
            result = book.call("fc.query_business", {})
            if result.get("coverage") == "available":
                break
            time.sleep(.01)
        self.assertEqual(result["coverage"], "available")
        self.assertEqual(calls, ["capture"])


if __name__ == "__main__":
    unittest.main()
