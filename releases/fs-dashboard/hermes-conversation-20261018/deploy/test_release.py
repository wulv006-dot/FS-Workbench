import datetime
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from contextlib import nullcontext
from unittest.mock import patch
import hashlib
from pathlib import Path

from preflight import HERE, prepare
from release_scope import NEW_ALLOWED, TARGETS


class ReleaseContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        paths = json.loads((HERE / "baseline-paths.json").read_text())["paths"]
        self.rows = [{"path": path, "exists": path not in NEW_ALLOWED,
                      "sha256": None if path in NEW_ALLOWED else "0" * 64,
                      "uid": 0, "gid": 0, "links": 1, "mode": "0o644"} for path in paths]
        self.baseline = self.root / "baseline.json"
        self.write_baseline()

    def write_baseline(self):
        self.baseline.write_text(json.dumps({"contract": "fs-hermes-conversation-baseline-v1",
            "observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "production_writes": 0, "files": self.rows,
            "units": {"fs-business-range.service": {"ActiveState": "active"},
                      "fs-hermes-fc.service": {"ActiveState": "active"}}}))

    def load(self, stage):
        spec = importlib.util.spec_from_file_location("isolated_bridge", stage / "release_bridge.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load_base()

    def test_exact_stage_and_manifest(self):
        stage = self.root / "stage"
        result = prepare(self.baseline, "a" * 40, stage)
        self.assertFalse(result["releaseReady"])
        self.assertEqual(result["files"], len(TARGETS))
        base = self.load(stage)
        manifest = json.loads((stage / "approved-manifest.json").read_text())
        base.validate(manifest, stage)
        with self.assertRaisesRegex(ValueError, "exact_frozen_manifest_required"):
            base.validate(dict(manifest, businessWrites=True), stage)
        with self.assertRaisesRegex(ValueError, "new_stage_required"):
            prepare(self.baseline, "a" * 40, stage)

    def test_preflight_rejects_existing_target_drift(self):
        next(row for row in self.rows if row["path"] == "/opt/fs-exact-range-20261001/range_api.py")["sha256"] = "not-a-sha"
        self.write_baseline()
        with self.assertRaisesRegex(ValueError, "target_sha_missing"):
            prepare(self.baseline, "a" * 40, self.root / "stage")

    def test_followup_release_accepts_precise_existing_new_target(self):
        row = next(row for row in self.rows if row["path"] == "/opt/fs-hermes-fc/conversation_store.py")
        row.update(exists=True, sha256="1" * 64)
        self.write_baseline()
        stage = self.root / "stage"
        prepare(self.baseline, "a" * 40, stage)
        manifest = json.loads((stage / "approved-manifest.json").read_text())
        self.assertEqual(next(item for item in manifest["files"] if item["target"] == row["path"])["beforeSha256"], "1" * 64)
        self.load(stage).validate(manifest, stage)

    def test_quiescence_checks_both_ledgers(self):
        stage = self.root / "stage"
        prepare(self.baseline, "a" * 40, stage)
        base = self.load(stage)
        tasks = self.root / "var/lib/fs-hermes-fc/fs/tasks.sqlite3"
        tasks.parent.mkdir(parents=True)
        with closing(sqlite3.connect(tasks)) as db:
            db.execute("CREATE TABLE requests(state TEXT)")
            db.commit()
        base.hermes_quiescent(self.root)
        conversations = tasks.parent / "conversations/conversations.db"
        conversations.parent.mkdir()
        with closing(sqlite3.connect(conversations)) as db:
            db.execute("CREATE TABLE turns(state TEXT)")
            db.execute("INSERT INTO turns VALUES('running')")
            db.commit()
        with self.assertRaisesRegex(ValueError, "active_or_unknown_conversation_run"):
            base.hermes_quiescent(self.root)

    def test_failed_activation_restores_code_before_old_service_restart(self):
        stage = self.root / "stage"
        prepare(self.baseline, "a" * 40, stage, release_ready=True)
        manifest_path = stage / "approved-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        for row in manifest["files"]:
            if row["beforeSha256"] is not None:
                target = self.root / row["target"].lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"old")
                row["beforeSha256"] = hashlib.sha256(b"old").hexdigest()
        manifest_path.write_text(json.dumps(manifest))
        base = self.load(stage)
        base.validate = lambda value, location: value["files"]
        base.inspect = lambda *args: None
        base.guards = lambda *args, **kwargs: None
        base.retirement = lambda *args: None
        base.directory_sync = lambda *args: None
        base.locks = lambda *args: nullcontext()
        base.live_lock = lambda *args: nullcontext()
        base.hermes_admission_fence = lambda *args: nullcontext()
        base.model_release_lock = lambda *args: nullcontext()
        calls = []
        def activate(*args):
            calls.append("activate")
            if len(calls) == 1: raise ValueError("nginx_syntax_failed")
            for row in manifest["files"]:
                target = self.root / row["target"].lstrip("/")
                if row["beforeSha256"] is None: self.assertFalse(target.exists())
                else: self.assertEqual(target.read_bytes(), b"old")
            calls.append("old_code_restored_before_restart")
        base.restart_for = activate
        approval = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "nginx_syntax_failed"):
            base.apply(manifest, stage, approval, manifest_path.read_bytes(), "nav-20261018T091122Z", self.root)
        self.assertEqual(calls, ["activate", "activate", "old_code_restored_before_restart"])


if __name__ == "__main__": unittest.main()
