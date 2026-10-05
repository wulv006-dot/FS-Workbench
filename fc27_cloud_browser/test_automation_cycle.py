"""Offline tests for the automatic collection-to-write decision path."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fc27_cloud_worker as worker
from test_automation_policy import configured, quote


class AutomationCycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "quotes").mkdir()
        (self.root / "previews").mkdir()
        self.job = {"job_id": "00000000-0000-4000-8000-000000000001",
                    "kind": "auto_cycle", "actor": "system-automation",
                    "request": {"policy_revision": 1}, "status": "running"}

    def cycle(self, policy, prices=None, backend=None):
        (self.root / "quotes" / f"{self.job['job_id']}.json").write_text(
            json.dumps(quote(prices)), encoding="utf-8")
        preview_id = "00000000-0000-4000-8000-000000000004"
        (self.root / "previews" / f"{preview_id}.json").write_text(json.dumps({
            "status": "review_only", "preview_id": preview_id, "run_id": self.job["job_id"],
            "backend_before": {"rows": [{"platform": p, "b2c": (backend or {}).get(p, "0.10")}
                                         for p in ("PS", "XBOX", "PC")]},
            "targets": [{"platform": p, "quote": (prices or {}).get(p, "0.16")}
                        for p in ("PS", "XBOX", "PC")]}
        ), encoding="utf-8")
        with (patch.object(worker, "ROOT", self.root),
              patch.object(worker, "load_policy", return_value=policy),
              patch.object(worker, "collect_quote", return_value={"run_id": self.job["job_id"],
                                                               "quote_status": "ready_for_preview"}),
              patch.object(worker, "save_job"),
              patch.object(worker, "writer_status", return_value="ready"),
              patch.object(worker, "run", return_value=(0, {
                  "status": "review_only", "preview_id": preview_id,
                  "run_id": self.job["job_id"]})) as preview,
              patch.object(worker, "run_writer_request", return_value=(0, {"status": "CONFIRMED"})) as writer):
            result = worker.handle(self.job)
            return result, preview.call_count, writer.call_args_list

    def test_auto_skips_only_blocked_platforms(self):
        prices = {"PS": "0.13", "XBOX": "0.16", "PC": "0.16"}
        result, previews, calls = self.cycle(configured(), prices)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["platforms"], ["XBOX", "PC"])
        self.assertEqual(result["blocked_platforms"], {"PS": "automatic_margin_floor:PS"})
        self.assertEqual(previews, 1)
        self.assertEqual(calls[0].args[2]["platforms"], ["XBOX", "PC"])
        self.assertTrue(calls[0].args[2]["automatic"])

    def test_all_platforms_below_derived_floor_never_preview_or_write(self):
        result, previews, calls = self.cycle(configured(),
                                            {p: "0.13" for p in ("PS", "XBOX", "PC")})
        self.assertEqual(result["status"], "all_platforms_blocked")
        self.assertEqual(previews, 0)
        self.assertEqual(calls, [])

    def test_all_backend_prices_unchanged_skips_writer(self):
        prices = {p: "0.16" for p in ("PS", "XBOX", "PC")}
        result, previews, calls = self.cycle(configured(), prices, prices)
        self.assertEqual(result["status"], "no_price_change")
        self.assertEqual(result["unchanged_platforms"], ["PS", "XBOX", "PC"])
        self.assertEqual(previews, 1)
        self.assertEqual(calls, [])

    def test_one_changed_platform_only_writes_that_platform(self):
        prices = {p: "0.16" for p in ("PS", "XBOX", "PC")}
        before = {**prices, "XBOX": "0.15"}
        result, _, calls = self.cycle(configured(), prices, before)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["platforms"], ["XBOX"])
        self.assertEqual(result["unchanged_platforms"], ["PS", "PC"])
        self.assertEqual(calls[0].args[2]["platforms"], ["XBOX"])

    def test_manual_mode_collects_without_preview_or_write(self):
        result, previews, calls = self.cycle(configured("manual"))
        self.assertEqual(result["status"], "collected_for_manual_review")
        self.assertEqual(previews, 0)
        self.assertEqual(calls, [])

    def test_player_sync_issue_keeps_collecting_but_never_writes(self):
        with (patch.object(worker, "load_policy", return_value=configured()),
              patch.object(worker, "player_sync_gate", return_value="needs_reconcile"),
              patch.object(worker, "collect_quote", return_value={"run_id": self.job["job_id"],
                                                               "quote_status": "ready_for_preview"}) as collector,
              patch.object(worker, "save_job"),
              patch.object(worker, "run_writer_request") as writer):
            result = worker.handle(self.job)
        self.assertEqual(result["status"], "deferred_player_sync")
        collector.assert_called_once()
        writer.assert_not_called()

    def test_auto_waits_when_previous_backend_write_has_not_reached_public_page(self):
        (self.root / "jobs").mkdir()
        (self.root / "monitor").mkdir()
        prior_id = "00000000-0000-4000-8000-000000000002"
        prior = {"job_id": prior_id, "kind": "auto_cycle",
                 "created_at": "2026-09-29T00:00:00+00:00",
                 "result": {"status": "confirmed", "platforms": ["PS"]},
                 "public_page_readback": {"status": "unconfirmed"}}
        (self.root / "jobs" / f"{prior_id}.json").write_text(json.dumps(prior), encoding="utf-8")
        (self.root / "quotes" / f"{prior_id}.json").write_text(
            json.dumps({"result": {"rows": [{"platform": "PS", "target_page_usd": "13.10"}]}}),
            encoding="utf-8")
        state = {"collection_run_id": self.job["job_id"], "status": "ok",
                 "rows": {"PS": {"status": "ok", "package_usd": "13.11"}}}
        page_file = self.root / "monitor/storefront.json"
        page_file.write_text(json.dumps(state), encoding="utf-8")
        result, previews, calls = self.cycle(configured())
        self.assertEqual(result["status"], "previous_public_price_unconfirmed")
        self.assertEqual(result["platforms"], ["PS"])
        self.assertEqual(previews, 0)
        self.assertEqual(calls, [])
        prior.pop("public_page_readback")  # Worker may stop after write, before readback.
        (self.root / "jobs" / f"{prior_id}.json").write_text(json.dumps(prior), encoding="utf-8")
        result, previews, calls = self.cycle(configured())
        self.assertEqual(result["status"], "previous_public_price_unconfirmed")
        self.assertEqual(calls, [])
        state["rows"]["PS"]["package_usd"] = "13.10"
        page_file.write_text(json.dumps(state), encoding="utf-8")
        result, previews, calls = self.cycle(configured())
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(previews, 1)
        self.assertEqual(len(calls), 1)

    def test_later_confirmed_manual_write_replaces_old_auto_public_target(self):
        (self.root / "jobs").mkdir()
        (self.root / "monitor").mkdir()
        (self.root / "executions").mkdir()
        prior_id = "00000000-0000-4000-8000-000000000002"
        manual_id = "00000000-0000-4000-8000-000000000003"
        prior = {"job_id": prior_id, "kind": "auto_cycle", "status": "ready",
                 "created_at": "2026-09-29T00:00:00+00:00",
                 "result": {"status": "confirmed", "platforms": ["PS"]},
                 "public_page_readback": {"status": "unconfirmed"}}
        manual = {"job_id": manual_id, "kind": "execute", "status": "ready",
                  "created_at": "2026-09-29T01:00:00+00:00",
                  "result": {"status": "CONFIRMED", "platforms": ["PS"]}}
        (self.root / "jobs" / f"{prior_id}.json").write_text(json.dumps(prior), encoding="utf-8")
        (self.root / "jobs" / f"{manual_id}.json").write_text(json.dumps(manual), encoding="utf-8")
        (self.root / "quotes" / f"{prior_id}.json").write_text(json.dumps({"result": {"rows": [
            {"platform": "PS", "target_page_usd": "12.40"}]}}), encoding="utf-8")
        audit = {"status": "CONFIRMED", "sync_confirmed": True, "changed": ["PS"],
                 "targets": [{"platform": "PS", "quote": "0.1239"}]}
        (self.root / "executions" / f"{manual_id}.json").write_text(json.dumps(audit), encoding="utf-8")
        state = {"collection_run_id": self.job["job_id"], "status": "ok",
                 "rows": {"PS": {"status": "ok", "package_usd": "12.39"}}}
        page_file = self.root / "monitor/storefront.json"
        page_file.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(worker, "ROOT", self.root):
            self.assertIsNone(worker.previous_public_write_gap(self.job["job_id"]))
        state["rows"]["PS"]["package_usd"] = "13.11"
        page_file.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(worker, "ROOT", self.root):
            self.assertEqual(worker.previous_public_write_gap(self.job["job_id"])["platforms"], ["PS"])

    def test_storefront_refresh_uses_same_run_id_without_changing_quote_result(self):
        with patch.object(worker, "run", return_value=(0, {"status": "ok"})) as run:
            self.assertEqual(worker.refresh_storefront(self.job), {"status": "ok"})
        self.assertEqual(run.call_args.args[0][:3], ["/usr/sbin/runuser", "-u", "fc27api"])
        self.assertEqual(run.call_args.args[0][-1], self.job["job_id"])
        with patch.object(worker, "run", return_value=(1, {"reason": "source_unavailable"})):
            self.assertEqual(worker.refresh_storefront(self.job)["status"], "unavailable")

    def test_quote_embeds_same_round_storefront_before_pricing(self):
        (self.root / "runs").mkdir()
        (self.root / "monitor").mkdir()
        run_id = self.job["job_id"]
        run_path = self.root / "runs" / f"{run_id}.json"
        run_path.write_text(json.dumps({"run_id": run_id, "status": "ready_for_quote"}),
                            encoding="utf-8")
        state = {"collection_run_id": run_id, "status": "ok",
                 "rows": {p: {"platform": p, "status": "ok"}
                          for p in ("PS", "XBOX", "PC")}}
        (self.root / "monitor/storefront.json").write_text(json.dumps(state), encoding="utf-8")
        responses = [(0, {"status": "ready_for_quote"}), (0, {"status": "ok"}),
                     (0, {"status": "ready_for_preview"})]
        with (patch.object(worker, "ROOT", self.root),
              patch.object(worker, "run", side_effect=responses) as run,
              patch.object(worker, "save_job"),
              patch.object(worker.os, "chown", create=True),
              patch.object(worker.os, "chmod")):
            self.assertEqual(worker.collect_quote(self.job)["run_id"], run_id)
        self.assertEqual(json.loads(run_path.read_text(encoding="utf-8"))["storefront"], state)
        self.assertEqual(run.call_count, 3)

    def test_quote_stops_if_front_page_evidence_belongs_to_another_round(self):
        (self.root / "runs").mkdir()
        (self.root / "monitor").mkdir()
        run_id = self.job["job_id"]
        (self.root / "runs" / f"{run_id}.json").write_text(
            json.dumps({"run_id": run_id, "status": "ready_for_quote"}), encoding="utf-8")
        state = {"collection_run_id": "other", "status": "ok",
                 "rows": {p: {"platform": p, "status": "ok"}
                          for p in ("PS", "XBOX", "PC")}}
        (self.root / "monitor/storefront.json").write_text(json.dumps(state), encoding="utf-8")
        with (patch.object(worker, "ROOT", self.root),
              patch.object(worker, "run", side_effect=[(0, {"status": "ready_for_quote"}),
                                                      (0, {"status": "ok"})]),
              patch.object(worker, "save_job")):
            with self.assertRaisesRegex(ValueError, "storefront_run_mismatch"):
                worker.collect_quote(self.job)

    def test_public_page_readback_records_confirmed_and_mismatch(self):
        (self.root / "monitor").mkdir()
        run_id = self.job["job_id"]
        quote_file = self.root / "quotes" / f"{run_id}.json"
        quote_file.write_text(json.dumps({"result": {"rows": [
            {"platform": "PS", "target_page_usd": "13.10"}]}}), encoding="utf-8")
        self.job["result"] = {"status": "confirmed", "platforms": ["PS"]}
        state = {"collection_run_id": run_id, "status": "ok", "last_attempt_at": "now",
                 "rows": {"PS": {"status": "ok", "package_usd": "13.10"}}}
        state_file = self.root / "monitor/storefront.json"
        state_file.write_text(json.dumps(state), encoding="utf-8")
        with patch.object(worker, "ROOT", self.root):
            self.assertEqual(worker.verify_public_page(self.job)["status"], "verified")
            state["rows"]["PS"]["package_usd"] = "13.11"
            state_file.write_text(json.dumps(state), encoding="utf-8")
            self.assertEqual(worker.verify_public_page(self.job)["status"], "unconfirmed")


if __name__ == "__main__":
    unittest.main()
