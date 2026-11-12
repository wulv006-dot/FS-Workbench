"""Offline tests: in-memory remote and local temp files only, no network/services."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from support import REPO

SOURCE = REPO / "tools/release_d4follow.py"
spec = importlib.util.spec_from_file_location("release_d4follow", SOURCE)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


class FakeRemote:
    def __init__(self, initial=None):
        self.files = dict(initial or {})
        self.dirs = set()
        self.commands = []
        self.replacements = []
        self.hook = None
        self.write_count = 0
        self.fail_write = 0

    def hashes(self, root, rels):
        return {p: r.sha256_bytes(self.files[root.rstrip("/") + "/" + p])
                for p in rels if root.rstrip("/") + "/" + p in self.files}

    def mkdir_exclusive(self, path):
        if path in self.dirs:
            raise r.Refused("directory exists")
        self.dirs.add(path)

    def must(self, cmd, **kwargs):
        self.commands.append(cmd)
        parts = shlex.split(cmd)
        if parts[0] != "rmdir":
            raise AssertionError(cmd)
        for path in (parts[1], parts[4]):
            if path not in self.dirs or any(x.startswith(path + "/") for x in self.dirs):
                raise r.Refused("not our empty lock")
            self.dirs.remove(path)
        return ""

    def copy(self, src, dst):
        self.files[dst] = self.files[src]

    def upload_tree(self, local_dir, remote_tmp):
        self.mkdir_exclusive(remote_tmp)
        for p in Path(local_dir).rglob("*"):
            if p.is_file():
                self.files[remote_tmp + "/" + p.relative_to(local_dir).as_posix()] = p.read_bytes()

    def replace_checked(self, src, dst, before, after, restore=False):
        self.replacements.append((src, dst, restore))
        if self.hook:
            self.hook(self, src, dst, restore, "before")
        actual = r.sha256_bytes(self.files[dst]) if dst in self.files else None
        if actual != before or r.sha256_bytes(self.files[src]) != after:
            raise r.Refused("CAS mismatch")
        self.files[dst] = self.files[src]
        if not restore:
            del self.files[src]
        if self.hook:
            self.hook(self, src, dst, restore, "after")

    def write_text(self, path, text):
        self.write_count += 1
        if self.write_count == self.fail_write:
            raise r.Refused("ledger unavailable")
        self.files[path] = text.encode("utf-8")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.args = SimpleNamespace(apply=True, release_id="test-release", host="test-host", user="u",
                                    key="unused", ref="immutable-sha", remote_dir="/unit",
                                    state_dir=self.tmp.name, files="", allow_unmanaged=False)
        self.old = {"a.py": b"old a", "b.py": b"old b"}
        self.new = {"a.py": b"new a", "b.py": b"new b", "new.py": b"new module"}
        self.remote = FakeRemote({"/unit/" + k: v for k, v in self.old.items()})

    def apply(self):
        target = {k: r.sha256_bytes(v) for k, v in self.new.items()}
        before = self.remote.hashes("/unit", target)
        known = {k: {v} for k, v in before.items()}
        actions, refusals = r.plan_actions(before, target, known)
        result = (self.remote, self.args.ref, target, before, known, actions, refusals)
        with patch.object(r, "gather", return_value=result), \
             patch.object(r, "git", return_value=SimpleNamespace(stdout=b"fake-tree\n")), \
             patch.object(r, "git_show", side_effect=lambda ref, path: self.new[path[len(r.UNIT_PREFIX):]]), \
             contextlib.redirect_stdout(io.StringIO()):
            return r.cmd_apply(self.args)

    def record(self):
        return json.loads(r.state_path(self.args.state_dir, self.args.release_id).read_text(encoding="utf-8"))

    def rollback(self):
        with patch.object(r, "Remote", return_value=self.remote), contextlib.redirect_stdout(io.StringIO()):
            return r.cmd_rollback(self.args)

    def test_success_and_rollback_new_file_retained(self):
        self.assertEqual(self.apply(), 0)
        self.assertEqual(self.record()["status"], "applied")
        self.assertIn("/unit/.release_test-release.tmp", self.remote.dirs)
        self.assertEqual(self.rollback(), 0)
        for rel, contents in self.old.items():
            self.assertEqual(self.remote.files["/unit/" + rel], contents)
        self.assertEqual(self.remote.files["/unit/new.py"], self.new["new.py"])
        self.assertEqual(self.record()["recovery"]["retainedNew"], ["new.py"])
        self.assertNotIn("/unit/.release.lock", self.remote.dirs)

    def test_partial_failure_restores_all_attempted_old_files(self):
        def fail(remote, src, dst, restore, phase):
            if dst.endswith("b.py") and not restore and phase == "before":
                raise r.Refused("upload replacement failed")
        self.remote.hook = fail
        with self.assertRaisesRegex(r.Refused, "未恢复=\\[\\]"):
            self.apply()
        for rel, contents in self.old.items():
            self.assertEqual(self.remote.files["/unit/" + rel], contents)
        self.assertEqual(self.record()["status"], "apply-failed")
        self.assertNotIn("/unit/new.py", self.remote.files)

    def test_unknown_ssh_result_checks_attempted_file(self):
        def fail(remote, src, dst, restore, phase):
            if dst.endswith("b.py") and not restore and phase == "after":
                raise TimeoutError("receipt lost after mv")
        self.remote.hook = fail
        with self.assertRaises(r.Refused):
            self.apply()
        self.assertEqual(self.remote.files["/unit/b.py"], self.old["b.py"])
        self.assertEqual(self.record()["recovery"]["unrestored"], [])

    def test_final_cas_does_not_overwrite_later_change(self):
        def mutate(remote, src, dst, restore, phase):
            if dst.endswith("b.py") and not restore and phase == "before":
                remote.files[dst] = b"another publisher"
        self.remote.hook = mutate
        with self.assertRaisesRegex(r.Refused, "现态已变化"):
            self.apply()
        self.assertEqual(self.remote.files["/unit/a.py"], self.old["a.py"])
        self.assertEqual(self.remote.files["/unit/b.py"], b"another publisher")

    def test_success_ledger_failure_restores_existing_keeps_new(self):
        self.remote.fail_write = 2
        with self.assertRaisesRegex(r.Refused, "ledger unavailable"):
            self.apply()
        self.assertEqual(self.remote.files["/unit/a.py"], self.old["a.py"])
        self.assertEqual(self.remote.files["/unit/new.py"], self.new["new.py"])
        self.assertEqual(self.record()["status"], "apply-failed")

    def test_rollback_cas_preflight_is_all_or_nothing(self):
        self.apply()
        self.remote.files["/unit/b.py"] = b"later change"
        before = len(self.remote.replacements)
        with self.assertRaisesRegex(r.Refused, "回滚前现态"):
            self.rollback()
        self.assertEqual(len(self.remote.replacements), before)
        self.assertEqual(self.remote.files["/unit/a.py"], self.new["a.py"])

    def test_rollback_backup_corruption_refuses_before_write(self):
        self.apply()
        self.remote.files["/unit/_bak_release_test-release/b.py.before"] = b"broken"
        before = len(self.remote.replacements)
        with self.assertRaisesRegex(r.Refused, "回滚备份"):
            self.rollback()
        self.assertEqual(len(self.remote.replacements), before)

    def test_rollback_wrong_host_refused(self):
        self.apply()
        self.args.host = "other-host"
        with self.assertRaisesRegex(r.Refused, "主机/目录"):
            self.rollback()

    def test_existing_backup_is_not_reused(self):
        self.remote.dirs.add("/unit/_bak_release_test-release")
        with self.assertRaisesRegex(r.Refused, "directory exists"):
            self.apply()
        self.assertEqual(self.remote.replacements, [])

    def test_existing_staging_is_not_cleared_or_reused(self):
        self.remote.dirs.add("/unit/.release_test-release.tmp")
        self.remote.files["/unit/.release_test-release.tmp/evidence"] = b"keep"
        with self.assertRaisesRegex(r.Refused, "directory exists"):
            self.apply()
        self.assertEqual(self.remote.files["/unit/.release_test-release.tmp/evidence"], b"keep")
        self.assertEqual(self.remote.replacements, [])

    def test_recovery_failure_report_does_not_claim_restored(self):
        def fail(remote, src, dst, restore, phase):
            if restore or (dst.endswith("b.py") and phase == "before"):
                raise r.Refused("storage unavailable")
        self.remote.hook = fail
        with self.assertRaisesRegex(r.Refused, "未恢复=.*a.py"):
            self.apply()
        recovery = self.record()["recovery"]
        self.assertNotIn("a.py", recovery["restored"])
        self.assertTrue(any("a.py" in x for x in recovery["unrestored"]))

    def test_changed_baseline_after_upload_refuses_before_first_replace(self):
        original = self.remote.upload_tree
        def changed(local, target):
            original(local, target)
            self.remote.files["/unit/a.py"] = b"changed during upload"
        self.remote.upload_tree = changed
        with self.assertRaisesRegex(r.Refused, "最终现态"):
            self.apply()
        self.assertEqual(self.remote.replacements, [])

    def test_unknown_version_guard_preserved(self):
        actions, refused = r.plan_actions({"a.py": "unknown"}, {"a.py": "new"}, {"a.py": {"old"}})
        self.assertEqual(actions, [])
        self.assertEqual(len(refused), 1)


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.target_commit = "a" * 40
        self.baseline_commit = "b" * 40
        self.args = SimpleNamespace(host="fake", user="u", key="unused", remote_dir="/unit", files="",
                                    ref=self.target_commit, baseline_ref=self.baseline_commit[:8], allow_unmanaged=False)
        self.remote = FakeRemote({"/unit/a.py": b"old", "/unit/same.py": b"same"})
        self.targets = {"a.py": r.sha256_bytes(b"new"), "same.py": r.sha256_bytes(b"same"),
                        "new.py": r.sha256_bytes(b"new file")}

    def gather(self, baseline_contents=b"old"):
        def resolve(*args):
            self.assertEqual(args[:2], ("rev-parse", "--verify"))
            value = self.target_commit if args[2].startswith(self.target_commit) else self.baseline_commit
            return SimpleNamespace(returncode=0, stdout=(value + "\n").encode())
        with patch.object(r, "git", side_effect=resolve), \
             patch.object(r, "Remote", return_value=self.remote), \
             patch.object(r, "target_map", return_value=self.targets), \
             patch.object(r, "git_show", return_value=baseline_contents) as show, \
             patch.object(r, "repo_known_shas", side_effect=AssertionError("history scan forbidden")), \
             contextlib.redirect_stdout(io.StringIO()):
            result = r.gather(self.args)
        return result, show

    def test_fixed_baseline_only_reads_changed_existing_path(self):
        result, show = self.gather()
        show.assert_called_once_with(self.baseline_commit, "opt/d4follow/a.py")
        self.assertEqual(result[1], self.target_commit)
        self.assertEqual(self.args._baseline_commit, self.baseline_commit)
        self.assertEqual({a[0]: a[1] for a in result[5]}, {"a.py": "OLD", "same.py": "SAME", "new.py": "NEW"})
        self.assertEqual(result[6], [])

    def test_baseline_mismatch_refused_without_history_fallback(self):
        result, _ = self.gather(b"older than remote")
        self.assertEqual([item[0] for item in result[6]], ["a.py"])
        self.assertNotIn("a.py", [item[0] for item in result[5]])

    def test_missing_baseline_path_is_unmanaged(self):
        result, _ = self.gather(None)
        self.assertEqual([item[0] for item in result[6]], ["a.py"])

    def test_baseline_rejects_unmanaged_override(self):
        self.args.allow_unmanaged = True
        with self.assertRaisesRegex(r.Refused, "禁止 --allow-unmanaged"):
            self.gather()

    def test_baseline_requires_full_target_sha(self):
        self.args.ref = "HEAD"
        with self.assertRaisesRegex(r.Refused, "完整"):
            self.gather()

    def test_baseline_rejects_mutable_ref(self):
        self.args.baseline_ref = "main"
        with self.assertRaisesRegex(r.Refused, "固定"):
            self.gather()

    def test_default_history_behavior_unchanged(self):
        self.args.baseline_ref = None
        with patch.object(r, "Remote", return_value=self.remote), \
             patch.object(r, "target_map", return_value=self.targets), \
             patch.object(r, "repo_known_shas", return_value={"a.py": {r.sha256_bytes(b"old")}}) as history, \
             patch.object(r, "baseline_known_shas", side_effect=AssertionError("unexpected baseline read")):
            result = r.gather(self.args)
        history.assert_called_once_with(list(self.targets))
        self.assertEqual(result[6], [])


class RemoteTests(unittest.TestCase):
    def test_host_key_strict_and_optional_known_hosts(self):
        remote = r.Remote.__new__(r.Remote)
        remote.key = "key.pem"
        with patch.dict(os.environ, {}, clear=True):
            opts = remote.opts()
            self.assertIn("StrictHostKeyChecking=yes", opts)
            self.assertIn("BatchMode=yes", opts)
            self.assertTrue(any("curve25519" in x for x in opts))
            self.assertFalse(any("/dev/null" in x for x in opts))
        with tempfile.TemporaryDirectory(prefix="known hosts ") as d:
            known = Path(d) / "known_hosts"
            known.write_text("test key", encoding="utf-8")
            with patch.dict(os.environ, {"D4_RELEASE_KNOWN_HOSTS": str(known)}):
                self.assertTrue(any(str(known).replace("\\", "/") in x for x in remote.opts()))

    def test_lock_cannot_release_other_owner(self):
        remote = FakeRemote()
        first = r.RemoteLock(remote, "/unit")
        with first:
            with self.assertRaises(r.Refused):
                with r.RemoteLock(remote, "/unit"):
                    self.fail("second lock acquired")
            self.assertIn(first.owner, remote.dirs)
        self.assertEqual(remote.dirs, set())
        self.assertTrue(all(cmd.startswith("rmdir ") for cmd in remote.commands))

    def test_upload_uses_exclusive_staging_and_legacy_scp(self):
        remote = r.Remote.__new__(r.Remote)
        remote.scp, remote.host, remote.user = "scp", "host", "u"
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.py").write_bytes(b"a")
            with patch.object(remote, "mkdir_exclusive") as mkdir, \
                 patch.object(remote, "opts", return_value=[]), \
                 patch.object(r.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
                remote.upload_tree(d, "/fresh")
                mkdir.assert_called_once_with("/fresh")
                self.assertIn("-O", run.call_args.args[0])

    def execute_remote_command_locally(self, cmd, **kwargs):
        argv = shlex.split(cmd)
        self.assertEqual(argv[:2], ["python3", "-c"])
        with patch.object(sys, "argv", ["-c"] + argv[3:]):
            exec(compile(argv[2], "<remote-script-local-test>", "exec"), {})

    def test_write_text_correct_args_makes_parent_and_roundtrips_unicode(self):
        remote = r.Remote.__new__(r.Remote)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "ledger" / "entry.json"
            with patch.object(remote, "must", side_effect=self.execute_remote_command_locally):
                remote.write_text(str(path), '{"状态":"完成"}')
            self.assertEqual(path.read_text(encoding="utf-8"), '{"状态":"完成"}')

    def test_real_replace_script_cas_and_restore_preserve_backup(self):
        remote = r.Remote.__new__(r.Remote)
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "source", Path(d) / "destination"
            src.write_bytes(b"new")
            dst.write_bytes(b"old")
            with patch.object(remote, "must", side_effect=self.execute_remote_command_locally):
                with self.assertRaisesRegex(RuntimeError, "CAS mismatch"):
                    remote.replace_checked(str(src), str(dst), "wrong", r.sha256_bytes(b"new"))
                self.assertEqual(dst.read_bytes(), b"old")
                remote.replace_checked(str(src), str(dst), r.sha256_bytes(b"old"), r.sha256_bytes(b"new"), restore=True)
                self.assertEqual(dst.read_bytes(), b"new")
                self.assertEqual(src.read_bytes(), b"new")

    def test_real_replace_script_new_requires_absence(self):
        remote = r.Remote.__new__(r.Remote)
        with tempfile.TemporaryDirectory() as d:
            src, dst = Path(d) / "source", Path(d) / "destination"
            src.write_bytes(b"new")
            dst.mkdir()
            with patch.object(remote, "must", side_effect=self.execute_remote_command_locally):
                with self.assertRaisesRegex(RuntimeError, "non-regular"):
                    remote.replace_checked(str(src), str(dst), None, r.sha256_bytes(b"new"))
            self.assertTrue(dst.is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
