import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "source" / "hermes_worker.py"


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        proxy = types.ModuleType("proxy_gateway")
        proxy.schemas = lambda: []
        proxy.MAX_PROVIDER_CONTEXT_TOKENS = 1000
        proxy.MAX_HERMES_OUTPUT_TOKENS = 1000
        proxy.MAX_PROVIDER_WIRE_BYTES = 10000000
        contract = types.ModuleType("runs_contract")
        contract.WIRE_TOOLS = ()
        contract.PIN = "test"
        with patch.dict(sys.modules, {"proxy_gateway": proxy, "runs_contract": contract}):
            spec = importlib.util.spec_from_file_location("candidate_hermes_worker", SOURCE)
            cls.worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cls.worker)

    def test_conversation_requires_exact_server_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            self.worker.ADMISSIONS = Path(directory)
            session = "hc_" + "a" * 64
            base = {"session_id": session, "token": "T" * 50, "model": "deepseek-flash",
                    "prompt": "readonly", "conversation": True, "ready": True,
                    "run_id": "run_" + "b" * 32}
            path = Path(directory) / (session + ".json")
            path.write_text(json.dumps(base), encoding="utf-8")
            self.assertEqual(self.worker.admission(session)["run_id"], base["run_id"])
            for changed in ({"learning_text": "unsafe"}, {"background": {}}, {"report_mode": "daily"},
                            {"run_id": "run_../other"}, {"conversation": False}):
                path.write_text(json.dumps({**base, **changed}), encoding="utf-8")
                with self.assertRaises(PermissionError):
                    self.worker.admission(session)
            with self.assertRaises(OSError):
                self.worker.admission("hc_" + "c" * 64)

    def test_report_admission_cannot_borrow_conversation_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.worker.ADMISSIONS = Path(directory)
            session = "fc_" + "a" * 64
            item = {"session_id": session, "token": "T" * 50, "model": "deepseek-flash",
                    "prompt": "daily", "conversation": True}
            (Path(directory) / (session + ".json")).write_text(json.dumps(item), encoding="utf-8")
            with self.assertRaises(PermissionError):
                self.worker.admission(session)

    def test_conversation_agent_metadata_uses_no_eager_bundle(self):
        item = {"model": "deepseek-flash", "conversation": True}
        self.assertNotIn("fs_skill_version", self.worker.runtime_metadata(item, {}))
        report = self.worker.runtime_metadata({"model": "deepseek-flash"}, {"version": "v1", "sha256": "a" * 64})
        self.assertEqual(report["fs_skill_version"], "v1")


if __name__ == "__main__":
    unittest.main()
