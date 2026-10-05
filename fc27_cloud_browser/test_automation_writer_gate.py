"""Confirm the real writer rejects unsafe targets before opening a browser."""
from __future__ import annotations

from pathlib import Path
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import price_writer
from test_automation_policy import configured, quote


ID1 = "00000000-0000-4000-8000-000000000001"
ID2 = "00000000-0000-4000-8000-000000000002"


class WriterGateTest(unittest.TestCase):
    def test_old_quote_engine_hash_invalidates_open_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ("previews", "quotes", "runs", "app"):
                (root / folder).mkdir()
            (root / "app/fc27_quote_engine.py").write_text("new rule", encoding="utf-8")
            now = datetime.now(timezone.utc)
            run = {"run_id": ID1, "status": "ready_for_quote", "created_at": now.isoformat()}
            run_path = root / "runs" / (ID1 + ".json")
            run_path.write_text(json.dumps(run), encoding="utf-8")
            old_hash = hashlib.sha256(b"old rule").hexdigest()
            quote = {"run_id": ID1, "status": "ready_for_preview", "created_at": now.isoformat(),
                     "snapshot_sha256": hashlib.sha256(run_path.read_bytes()).hexdigest(),
                     "quote_engine_sha256": old_hash}
            quote_path = root / "quotes" / (ID1 + ".json")
            quote_path.write_text(json.dumps(quote), encoding="utf-8")
            preview = {"preview_id": ID2, "run_id": ID1, "status": "review_only",
                       "created_at": now.isoformat(),
                       "expires_at": (now + timedelta(minutes=5)).isoformat(),
                       "quote_sha256": hashlib.sha256(quote_path.read_bytes()).hexdigest(),
                       "snapshot_sha256": quote["snapshot_sha256"],
                       "quote_engine_sha256": old_hash}
            (root / "previews" / (ID2 + ".json")).write_text(json.dumps(preview), encoding="utf-8")
            with (patch.object(price_writer, "ROOT", root),
                  patch.object(price_writer, "__file__", str(root / "app/price_writer.py"))):
                with self.assertRaisesRegex(ValueError, "quote_engine_changed_since_preview"):
                    price_writer.load_authorized(ID2)

    def reject_before_browser(self, policy, proposal, automatic, expected):
        with (patch.object(price_writer, "load_authorized", return_value=({}, proposal)),
              patch.object(price_writer, "load_policy", return_value=policy),
              patch.object(price_writer, "sync_playwright") as browser):
            with self.assertRaisesRegex(ValueError, expected):
                price_writer.execute(ID1, ID2, "operator", ["PS"],
                                     policy_revision=policy["revision"], automatic=automatic)
            browser.assert_not_called()

    def test_writer_requires_confirmation_for_manual_low_margin(self):
        proposal = quote({"PS": "0.13", "XBOX": "0.16", "PC": "0.16"})
        self.reject_before_browser(configured("manual"), proposal, False,
                                   "manual_margin_confirmation_required")

    def test_writer_blocks_low_margin_in_automatic_mode(self):
        proposal = quote({"PS": "0.13", "XBOX": "0.16", "PC": "0.16"})
        self.reject_before_browser(configured(), proposal, True, "automatic_margin_floor:PS")

    def test_writer_rejects_changed_policy_before_browser(self):
        policy = configured()
        policy["revision"] = 2
        with (patch.object(price_writer, "load_authorized", return_value=({}, quote())),
              patch.object(price_writer, "load_policy", return_value=policy),
              patch.object(price_writer, "sync_playwright") as browser):
            with self.assertRaisesRegex(ValueError, "automation_policy_changed"):
                price_writer.execute(ID1, ID2, "operator", ["PS"], policy_revision=1)
            browser.assert_not_called()

if __name__ == "__main__":
    unittest.main()
