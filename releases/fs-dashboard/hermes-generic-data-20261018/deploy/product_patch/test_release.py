"""Synthetic inventory assembly and actual fixed publisher validation."""

import datetime as dt
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import prepare_release
import release_bridge
from scope import BACKEND, SOURCE_SHA256


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class ProductPatchRelease(unittest.TestCase):
    def test_exact_parallel_drift_requires_ack_and_preserves_guard(self):
        prior = json.loads(prepare_release.PRIOR.read_text("utf-8"))
        before = {r["path"]: r["sha256"] for r in prior["unchangedRequired"]}
        before.update({r["target"]: r["sha256"] for r in prior["immutableAssets"] + prior["targets"]})
        inventory = {"contract": "fs-hermes-product-patch-live-baseline-v1",
                     "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "inventoryPlanSha256": sha(prepare_release.PLAN.read_bytes()), "production_writes": 0,
                     "files": [{"path": path, "exists": True,
                                "sha256": prepare_release.PARALLEL_ACK[path][1]
                                if path in prepare_release.PARALLEL_ACK else digest,
                                "uid": 0, "gid": 0, "mode": "0o644", "links": 1}
                               for path, digest in sorted(before.items())],
                     "units": prepare_release.UNITS}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            baseline.write_text(json.dumps(inventory), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "protected_or_target_baseline_drift"):
                prepare_release.prepare(baseline, root / "blocked")
            result = prepare_release.prepare(baseline, root / "allowed", True)
            self.assertEqual(result["protected"], 346)
            manifest = json.loads((root / "allowed/approved-manifest.json").read_text("utf-8"))
            self.assertEqual(len(manifest["acknowledgedParallelChanges"]), 2)
            protected = {r["path"]: r["sha256"] for r in manifest["unchangedRequired"]}
            for path, (_, live) in prepare_release.PARALLEL_ACK.items():
                self.assertEqual(protected[path], live)
            inventory["files"][0]["sha256"] = "0" * 64
            baseline.write_text(json.dumps(inventory), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "protected_or_target_baseline_drift"):
                prepare_release.prepare(baseline, root / "rejected", True)

    def test_three_target_stage_and_lifecycle_hook(self):
        prior = json.loads(prepare_release.PRIOR.read_text("utf-8"))
        before = {r["path"]: r["sha256"] for r in prior["unchangedRequired"]}
        before.update({r["target"]: r["sha256"] for r in prior["immutableAssets"] + prior["targets"]})
        self.assertEqual(len(before), 349)
        plan_raw = prepare_release.PLAN.read_bytes()
        inventory = {"contract": "fs-hermes-product-patch-live-baseline-v1",
                     "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "inventoryPlanSha256": sha(plan_raw), "production_writes": 0,
                     "files": [{"path": path, "exists": True, "sha256": digest,
                                "uid": 0, "gid": 0, "mode": "0o644", "links": 1}
                               for path, digest in sorted(before.items())],
                     "units": prepare_release.UNITS}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            baseline.write_text(json.dumps(inventory), encoding="utf-8")
            stage = root / "stage"
            summary = prepare_release.prepare(baseline, stage)
            self.assertEqual((summary["files"], summary["protected"]), (3, 346))
            m = json.loads((stage / "approved-manifest.json").read_text("utf-8"))
            self.assertFalse(m["releaseReady"])
            self.assertEqual({r["target"] for r in m["files"]}, {target for _, target in BACKEND})
            self.assertEqual(m["files"][0]["sha256"], SOURCE_SHA256)
            bridge = stage / "release_bridge.py"
            sys.path.insert(0, str(stage))
            try:
                module = types.ModuleType("_product_patch_staged_bridge")
                module.__file__ = str(bridge)
                exec(compile(bridge.read_bytes(), str(bridge), "exec"), module.__dict__)
                publisher = module.load_base()
                self.assertEqual(len(publisher.validate(m, stage)), 3)
                calls = []
                class FakeLifecycle:
                    def apply(self, manifest, stage, backup, journal, root, atomic, journal_write, digest, no_link):
                        calls.append(("apply", atomic is publisher.atomic, journal_write is publisher.journal_write,
                                      digest is publisher.digest, no_link is publisher.no_target_link))
                    def restore(self, backup, journal, journal_write):
                        calls.append(("restore", journal_write is publisher.journal_write))
                publisher.session_lifecycle = lambda _: FakeLifecycle()
                publisher.generic_session_apply(m, stage, root / "backup", {}, root)
                publisher.generic_session_restore(root / "backup", {"manifest": m})
                self.assertEqual(calls, [("apply", True, True, True, True), ("restore", True)])
            finally:
                sys.path.remove(str(stage))
            bad = json.loads(json.dumps(m))
            bad["files"][0]["beforeSha256"] = None
            with self.assertRaises(ValueError):
                publisher.validate(bad, stage)


if __name__ == "__main__":
    unittest.main()
