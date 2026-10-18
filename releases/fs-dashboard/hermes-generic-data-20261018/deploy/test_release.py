"""Offline contract test using the reviewed prior manifest as a synthetic inventory."""

import datetime as dt
import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path

import prepare_release
import release_bridge
from release_scope import BACKEND, NEW_ALLOWED, SOURCE_SHA256


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ReleaseContract(unittest.TestCase):
    def test_runtime_directory_is_not_a_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime_dir = root / "cohort-observations"
            runtime_dir.mkdir()
            release_bridge.private_directory(runtime_dir)
            runtime_file = root / "wrong-kind"
            runtime_file.write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "wrong_type"):
                release_bridge.private_directory(runtime_file)

    def test_exact_stage_and_rejections(self):
        prior = json.loads(prepare_release.PRIOR.read_text("utf-8"))
        protected = {r["path"]: r["sha256"] for r in prior["unchangedRequired"]}
        protected.update({r["target"]: r["sha256"] for r in prior["targets"] + prior["immutableAssets"]})
        targets = {target for _, _, target in BACKEND}
        plan_raw = prepare_release.PLAN.read_bytes()
        plan = json.loads(plan_raw)
        self.assertEqual(set(plan["paths"]), set(protected) | targets)
        self.assertEqual(len(targets), 12)
        self.assertEqual(len(protected), 345)
        rows = []
        for path in plan["paths"]:
            if path in NEW_ALLOWED:
                rows.append({"path": path, "exists": False, "sha256": None})
            else:
                self.assertIn(path, protected)
                rows.append({"path": path, "exists": True, "sha256": protected[path],
                             "uid": 0, "gid": 0, "mode": "0o644", "links": 1})
        inventory = {"contract": "fs-hermes-generic-data-live-baseline-v1",
                     "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                     "inventoryPlanSha256": sha(plan_raw), "production_writes": 0,
                     "files": rows, "units": prepare_release.REQUIRED_UNITS}
        self.assertEqual(set(SOURCE_SHA256), {local for local, _, _ in BACKEND if not local.startswith("@")})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            baseline.write_text(json.dumps(inventory), encoding="utf-8")
            stage = root / "stage"
            summary = prepare_release.prepare(baseline, stage)
            self.assertEqual((summary["files"], summary["protected"]), (12, 335))
            manifest = json.loads((stage / "approved-manifest.json").read_text("utf-8"))
            staged_bridge = stage / "release_bridge.py"
            module = types.ModuleType("staged_release_bridge")
            module.__file__ = str(staged_bridge)
            exec(compile(staged_bridge.read_bytes(), str(staged_bridge), "exec"), module.__dict__)
            publisher = module.load_base()
            self.assertEqual(len(publisher.validate(manifest, stage)), 12)
            calls = []
            class FakeLifecycle:
                def apply(self, m, s, b, j, r, atomic, write_journal, digest, no_link):
                    calls.append(("apply", atomic is publisher.atomic, write_journal is publisher.journal_write,
                                  digest is publisher.digest, no_link is publisher.no_target_link))
                def restore(self, b, j, write_journal):
                    calls.append(("restore", write_journal is publisher.journal_write))
            publisher.session_lifecycle = lambda _: FakeLifecycle()
            publisher.generic_session_apply(manifest, stage, root / "backup", {}, root)
            publisher.generic_session_restore(root / "backup", {"manifest": manifest})
            self.assertEqual(calls, [("apply", True, True, True, True), ("restore", True)])
            self.assertFalse(manifest["releaseReady"])
            self.assertEqual(sha((stage / "release_bridge.py").read_bytes()), manifest["publisherBridgeSha256"])
            self.assertEqual(sha((stage / "session_image_lifecycle.py").read_bytes()), manifest["imageLifecycleSha256"])
            bad = json.loads(json.dumps(manifest))
            bad["files"][0]["target"] = "/tmp/wrong.py"
            with self.assertRaises(ValueError):
                publisher.validate(bad, stage)
            bad = json.loads(json.dumps(manifest))
            bad["sessionImage"]["baseImage"] = "sha256:" + "0" * 64
            with self.assertRaises(ValueError):
                publisher.validate(bad, stage)
            inventory["files"][0]["sha256"] = "0" * 64
            baseline.write_text(json.dumps(inventory), encoding="utf-8")
            with self.assertRaises(ValueError):
                prepare_release.prepare(baseline, root / "bad-stage")


if __name__ == "__main__":
    unittest.main()
