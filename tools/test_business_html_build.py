"""Synthetic contracts only. No real business payload or production access."""
from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from build_business_html import build


class BuildContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.template = self.repo / "template.html"
        self.payload = self.root / "private.json"
        self.output = self.root / "output.html"
        self.contract = self.repo / "contract.json"
        self.data = b'{"synthetic":true}'
        self.template.write_bytes(b"const PROFIT = __PRIVATE_PROFIT_JSON__;")
        self.payload.write_bytes(self.data)
        self.contract.write_text(json.dumps({
            "templateSha256": self.digest(self.template.read_bytes()),
            "privatePayloadSha256": self.digest(self.data),
            "restoredHtmlSha256": self.digest(b"const PROFIT = " + self.data + b";")
        }), encoding="utf-8")

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    def run_build(self):
        return build(self.template, self.payload, self.output, self.contract, self.repo)

    def test_exact_external_reconstruction(self):
        self.assertFalse(self.run_build()["deployed"])
        self.assertEqual(self.output.read_bytes(), b"const PROFIT = " + self.data + b";")

    def test_reject_private_payload_in_repo(self):
        self.payload = self.repo / "private.json"
        self.payload.write_bytes(self.data)
        with self.assertRaises(ValueError):
            self.run_build()

    def test_reject_output_in_repo(self):
        self.output = self.repo / "generated.html"
        with self.assertRaises(ValueError):
            self.run_build()

    def test_reject_changed_payload_without_creating_output(self):
        self.payload.write_bytes(b'{"synthetic":false}')
        with self.assertRaises(ValueError):
            self.run_build()
        self.assertFalse(self.output.exists())

    def test_reject_changed_template_without_creating_output(self):
        self.template.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.run_build()
        self.assertFalse(self.output.exists())

    def test_never_overwrite_existing_output(self):
        self.output.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            self.run_build()
        self.assertEqual(self.output.read_bytes(), b"existing")


if __name__ == "__main__":
    unittest.main()
