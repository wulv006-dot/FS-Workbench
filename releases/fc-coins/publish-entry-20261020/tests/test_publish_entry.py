"""离线测试：宿主可信发布入口（无网络、无 subprocess、无真实 /opt）。

重点覆盖 dot 指出的问题：锁协议与顺序（含缺失/符号链接/属性）、取锁后与停服务后复核、
停服务失败即止、回退也检查停服务、授权走同一 fd 且父目录拒绝符号链接、按真实依赖推导重启单元。
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

import fc27_publish_entry as entry  # noqa: E402

ORIGINAL_SWAP = entry.Publisher._atomic_swap
COMMIT = "1" * 40
AUTHOR = "wulv006@gmail.com"
SOURCE_DIR = "fc27_cloud_browser"
UNITS = ("fc27-cloud-api", "fc27-cloud-worker", "fc27-automation-tick.timer")


def sha(data):
    import hashlib

    return hashlib.sha256(data).hexdigest()


MODULE_FILES = {
    "automation_tick.py": b"from automation_policy import load_policy\nfrom player_sync_policy import load_policy as x\n",
    "automation_policy.py": b"ROOT = 1\n",
    "player_sync_policy.py": b"ROOT = 2\n",
    "fc27_cloud_api.py": b"from automation_tick import latest_cycle\nfrom automation_policy import load_policy\n",
    "fc27_cloud_worker.py": (b"from automation_tick import queue_mutation\n"
                             b"from fc27_cloud_api import writer_status\n"
                             b"from price_writer import write_price\n"),
    "price_writer.py": b"from automation_policy import ROOT\n",
    "snapshot_layer.py": b"ROOT = 3\n",
}


class FakeQueueCM:
    """模拟模块自带 queue_mutation 的行为（含拿到锁/释放时的可观察点）。"""

    def __init__(self, mode="ok", events=None):
        self.mode = mode
        self.events = events if events is not None else []
        self.entered = False

    def __enter__(self):
        if self.mode == "busy":
            raise BlockingIOError("queue_mutation_busy")
        if self.mode == "untrusted":
            raise OSError("queue_lock_metadata_untrusted")
        if self.mode == "missing":
            raise FileNotFoundError("automation-tick.lock")
        self.entered = True
        self.events.append("queue_acquired")
        return self

    def __exit__(self, *_exc):
        self.events.append("queue_released")
        return False


class FakeSystemd:
    def __init__(self, fail_restart=None, fail_stop_at=None, inactive=None):
        self.calls = []
        self.fail_restart = set(fail_restart or [])
        self.fail_stop_at = dict(fail_stop_at or {})   # unit -> 第几次 stop 失败（1 起）
        self.stop_counts = {}
        self.inactive = set(inactive or [])

    def __call__(self, unit, action):
        self.calls.append((unit, action))
        if action == "is-active":
            return (False, "inactive") if unit in self.inactive else (True, "active")
        if action == "stop":
            self.stop_counts[unit] = self.stop_counts.get(unit, 0) + 1
            if self.stop_counts[unit] == self.fail_stop_at.get(unit):
                return (False, "stop-failed")
            return (True, "stopped")
        if action == "restart":
            return (False, "restart-failed") if unit in self.fail_restart else (True, "active")
        raise AssertionError(action)


class FakeArtifacts:
    def __init__(self, blobs, module_files=None, commits=None, subjects=None, authors=None):
        self.blobs = blobs
        self.module_files = dict(MODULE_FILES if module_files is None else module_files)
        self.commits = set(commits or [COMMIT])
        self.subjects = subjects or {COMMIT: "fix(fc-coins): demo (#231)"}
        self.authors = authors or {COMMIT: AUTHOR}
        self.main_ref = "refs/remotes/origin/main"
        self.untrusted = set()

    def blob(self, commit, path):
        if path in self.untrusted:
            raise entry.PublishError("git_failed", f"tampered {path}")
        try:
            return self.blobs[(commit, path)]
        except KeyError:
            raise entry.PublishError("git_failed", f"missing {commit}:{path}")

    def exists(self, ref, path):
        return (ref, path) in self.blobs or any(
            k[1] == path and k[0] == COMMIT for k in self.blobs if ref == COMMIT)

    def is_ancestor(self, commit, ref):
        return commit in self.commits

    def subject(self, commit):
        return self.subjects.get(commit, "")

    def author(self, commit):
        return self.authors.get(commit, "")

    def list_files(self, commit, directory):
        return sorted(self.module_files)


class Harness(unittest.TestCase):
    MODULE = "fc-coins"
    RELEASE = "demo-20261020"
    PR = "231"
    BASE = f"releases/fc-coins/{RELEASE}"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.opt = self.tmp / "opt" / "fc27-cloud-browser"
        self.opt.mkdir(parents=True)
        self.state = self.tmp / "var"
        for name in ("queue", "jobs", "executions", "state", "rollback", "releases"):
            (self.state / name).mkdir(parents=True)
        self.price_lock = self.state / "state" / "price-writer.lock"
        self.price_lock.write_bytes(b"")
        os.chmod(self.price_lock, 0o644)
        self.authorizations = self.tmp / "etc" / "authorizations"
        (self.authorizations / self.MODULE).mkdir(parents=True)
        self.policy_path = self.tmp / "release-policy.json"

        self.live = {"automation_tick.py": b"old tick\n", "price_writer.py": b"old writer\n"}
        for name, data in self.live.items():
            (self.opt / name).write_bytes(data)
        (self.opt / "fc27_quote_engine.py").write_bytes(b"quote engine\n")
        self.new = {name: data.replace(b"old", b"new") for name, data in self.live.items()}

        self.policy = {
            "version": 1,
            "checkout": str(self.tmp / "checkout"),
            "authorization": {"dir": str(self.authorizations), "owner_uid": os.getuid(),
                              "commit_authors": [AUTHOR]},
            "modules": {
                self.MODULE: {
                    "release_prefix": "releases/fc-coins/",
                    "allowed_roots": [str(self.opt)],
                    "module_source_dir": SOURCE_DIR,
                    "queue_lock": {"module_dir": str(self.opt), "factory": "automation_tick:queue_mutation"},
                    "units": {unit: ["is-active", "stop", "restart"] for unit in UNITS},
                    "unit_entrypoints": {
                        "fc27-cloud-api": ["fc27_cloud_api.py"],
                        "fc27-cloud-worker": ["fc27_cloud_worker.py"],
                        "fc27-automation-tick.timer": ["automation_tick.py"],
                    },
                    "targets": {
                        "automation_tick.py": str(self.opt / "automation_tick.py"),
                        "price_writer.py": str(self.opt / "price_writer.py"),
                    },
                }
            },
        }
        self.write_policy()
        self.write_authorization()
        self.events = []
        self.refresh_artifacts()

    # -- 夹具 ------------------------------------------------------------ #
    def write_policy(self):
        self.policy_path.write_text(json.dumps(self.policy, ensure_ascii=False), encoding="utf-8")
        os.chmod(self.policy_path, 0o644)

    def targets_json(self):
        return json.dumps({"targets": {
            name: {"target": self.policy["modules"][self.MODULE]["targets"][name],
                   "before": sha(self.live[name]), "after": sha(self.new[name])}
            for name in self.live}}).encode()

    def approval(self, **overrides):
        payload = {"pr": int(self.PR), "merge_commit": COMMIT, "scope": sorted(self.live)}
        payload.update(overrides)
        return json.dumps(payload).encode()

    def authorization_path(self):
        return self.authorizations / self.MODULE / f"{self.RELEASE}.json"

    def write_authorization(self, **overrides):
        record = {"merge_commit": COMMIT, "scope": sorted(self.live), "authorized_by": "吴律",
                  "authorized_at": "2026-10-20T09:00:00+08:00",
                  "expires_at": "2099-01-01T00:00:00+00:00"}
        record.update(overrides)
        self.authorization_path().write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.chmod(self.authorization_path(), 0o640)

    def refresh_artifacts(self):
        blobs = {
            (COMMIT, f"{self.BASE}/targets.json"): self.targets_json(),
            (COMMIT, f"{self.BASE}/approval.json"): self.approval(),
            ("refs/remotes/origin/main", f"{self.BASE}/approval.json"): self.approval(),
        }
        for name, data in self.new.items():
            blobs[(COMMIT, f"{self.BASE}/source/{name}")] = data
        for name, data in MODULE_FILES.items():
            blobs[(COMMIT, f"{SOURCE_DIR}/{name}")] = data
        self.artifacts = FakeArtifacts(blobs)
        return self.artifacts

    def publisher(self, **kwargs):
        paths = entry.Paths(policy=self.policy_path, checkout=self.tmp / "checkout",
                            state_root=self.state, authorization_root=self.authorizations)
        queue_mode = kwargs.pop("queue_mode", "ok")
        publisher = entry.Publisher(
            paths=paths, artifacts=kwargs.pop("artifacts", self.artifacts),
            systemd=kwargs.pop("systemd", FakeSystemd()),
            monitor=kwargs.pop("monitor", lambda: {"health": {"worker": "ok"}}),
            sleep=kwargs.pop("sleep", lambda _s: None), now=kwargs.pop("now", None),
            queue_factory=kwargs.pop("queue_factory", lambda: FakeQueueCM(queue_mode, self.events)),
            policy_owner_uid=os.getuid())
        return publisher

    def plan(self):
        publisher = self.publisher()
        publisher.load_policy()
        return publisher, publisher.plan(self.MODULE, self.RELEASE, self.PR)


class SuccessAndDepsTest(Harness):
    def test_publish_writes_backs_up_and_receipts(self):
        systemd = FakeSystemd()
        pub = self.publisher(systemd=systemd)
        pub.load_policy()
        module_entry = pub.module_policy(self.MODULE)
        plan = pub.plan(self.MODULE, self.RELEASE, self.PR)
        with pub.locks():
            pub.reverify(plan, "post-lock")
            pub.check_idle()
            pub.check_units(plan, module_entry)
            result = pub.apply(plan, module_entry)

        self.assertEqual(result["status"], "published")
        for name, data in self.new.items():
            self.assertEqual((self.opt / name).read_bytes(), data)
        for name, data in self.live.items():
            self.assertEqual((Path(result["rollback_dir"]) / name).read_bytes(), data)
        stored = json.loads(Path(result["receipt"]).read_text())
        self.assertEqual(stored["status"], "published")
        self.assertEqual(stored["pr"], int(self.PR))
        self.assertIn("queue_acquired", self.events)
        self.assertIn("queue_released", self.events)

    def test_automation_tick_restarts_every_unit_that_imports_it(self):
        """api、worker、timer 都加载 automation_tick.py，三个都要重启。"""
        _, plan = self.plan()
        self.assertEqual(sorted(plan["units"]), sorted(UNITS))
        self.assertEqual(plan["units"]["fc27-cloud-api"], ["automation_tick.py"])
        self.assertEqual(plan["units"]["fc27-cloud-worker"], ["automation_tick.py", "price_writer.py"])
        self.assertEqual(plan["units"]["fc27-automation-tick.timer"], ["automation_tick.py"])

    def test_unit_without_dependent_target_is_not_restarted(self):
        _, plan = self.plan()
        worker_only = self.publisher()
        worker_only.load_policy()
        entry_policy = worker_only.module_policy(self.MODULE)
        units = worker_only.dependency_units(entry_policy, COMMIT, self.BASE, ["price_writer.py"])
        self.assertEqual(sorted(units), ["fc27-cloud-worker"])

    def test_missing_dependent_unit_grant_fails(self):
        self.policy["modules"][self.MODULE]["units"].pop("fc27-cloud-api")
        self.write_policy()
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
            pub.plan(self.MODULE, self.RELEASE, self.PR)
        self.assertEqual(ctx.exception.code, "policy_unit_entrypoint_unknown")

    def test_dependency_not_granted_restart(self):
        self.policy["modules"][self.MODULE]["units"]["fc27-cloud-api"] = ["is-active"]
        self.write_policy()
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
            pub.plan(self.MODULE, self.RELEASE, self.PR)
        self.assertEqual(ctx.exception.code, "unit_action_not_granted")


class LockTest(Harness):
    def test_price_lock_missing_stops_and_does_not_create(self):
        self.price_lock.unlink()
        pub = self.publisher()
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            with pub.locks():
                self.fail("must not acquire")
        self.assertIn(ctx.exception.code, ("path_missing", "price_lock_missing"))
        self.assertFalse(self.price_lock.exists(), "不得创建缺失的锁")
        # 队列锁先取、发现价格锁缺失后必须成对释放，不能悬着
        self.assertEqual(self.events, ["queue_acquired", "queue_released"])

    def test_price_lock_symlink_rejected(self):
        target = self.tmp / "elsewhere.lock"
        target.write_bytes(b"")
        self.price_lock.unlink()
        os.symlink(target, self.price_lock)
        pub = self.publisher()
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            with pub.locks():
                self.fail("must not acquire")
        self.assertEqual(ctx.exception.code, "path_is_symlink")

    def test_price_lock_writable_by_group_rejected(self):
        os.chmod(self.price_lock, 0o666)
        pub = self.publisher()
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            with pub.locks():
                self.fail("must not acquire")
        self.assertEqual(ctx.exception.code, "price_lock_writable")

    def test_price_lock_hardlink_rejected(self):
        extra = self.tmp / "link.lock"
        os.link(self.price_lock, extra)
        pub = self.publisher()
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            with pub.locks():
                self.fail("must not acquire")
        self.assertEqual(ctx.exception.code, "price_lock_hardlinked")

    def test_price_lock_busy(self):
        import fcntl

        holder = os.open(self.price_lock, os.O_RDONLY)
        fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            pub = self.publisher()
            pub.load_policy()
            with self.assertRaises(entry.PublishError) as ctx:
                with pub.locks():
                    self.fail("must not acquire")
            self.assertEqual(ctx.exception.code, "price_lock_busy")
        finally:
            fcntl.flock(holder, fcntl.LOCK_UN)
            os.close(holder)

    def test_queue_lock_busy(self):
        pub = self.publisher(queue_mode="busy")
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            with pub.locks():
                self.fail("must not acquire")
        self.assertEqual(ctx.exception.code, "queue_lock_busy")

    def test_queue_lock_untrusted_metadata(self):
        pub = self.publisher(queue_mode="untrusted")
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            with pub.locks():
                self.fail("must not acquire")
        self.assertEqual(ctx.exception.code, "queue_lock_untrusted")

    def test_queue_lock_missing_is_not_created(self):
        pub = self.publisher(queue_mode="missing")
        pub.load_policy()
        with self.assertRaises(Exception):
            with pub.locks():
                self.fail("must not acquire")
        self.assertFalse((self.state / "state" / "automation-tick.lock").exists())

    def test_queue_first_then_price_and_release_in_reverse(self):
        import fcntl

        seen = {}
        probe = os.open(self.price_lock, os.O_RDONLY)

        class ProbeQueue(FakeQueueCM):
            def __enter__(inner):
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen["price_held_at_queue_enter"] = False
                    fcntl.flock(probe, fcntl.LOCK_UN)
                except BlockingIOError:
                    seen["price_held_at_queue_enter"] = True
                return super().__enter__()

            def __exit__(inner, *_exc):
                try:
                    fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen["price_released_before_queue_exit"] = True
                    fcntl.flock(probe, fcntl.LOCK_UN)
                except BlockingIOError:
                    seen["price_released_before_queue_exit"] = False
                return super().__exit__(*_exc)

        pub = self.publisher(queue_factory=lambda: ProbeQueue(events=self.events))
        pub.load_policy()
        with pub.locks():
            with self.assertRaises(BlockingIOError):
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.close(probe)
        self.assertFalse(seen["price_held_at_queue_enter"])
        self.assertTrue(seen["price_released_before_queue_exit"])


class ReverifyTest(Harness):
    def test_baseline_drift_after_locks_is_caught(self):
        pub, plan = self.plan()
        (self.opt / "price_writer.py").write_bytes(b"changed after plan\n")
        with self.assertRaises(entry.PublishError) as ctx:
            pub.reverify(plan, "post-lock")
        self.assertEqual(ctx.exception.code, "baseline_drift")
        self.assertIn("post-lock", ctx.exception.detail)

    def test_candidate_change_after_locks_is_caught(self):
        pub, plan = self.plan()
        self.artifacts.untrusted.add(f"{self.BASE}/source/price_writer.py")
        with self.assertRaises(entry.PublishError):
            pub.reverify(plan, "post-lock")

    def test_expired_authorization_after_locks_is_caught(self):
        pub, plan = self.plan()
        self.write_authorization(expires_at="2020-01-01T00:00:00+00:00")
        with self.assertRaises(entry.PublishError) as ctx:
            pub.reverify(plan, "post-lock")
        self.assertEqual(ctx.exception.code, "authorization_expired")

    def test_drift_during_stop_blocks_replacement(self):
        """停服务后、替换前再核一次：此时被改就直接失败，且不写任何字节。"""
        systemd = FakeSystemd()
        pub = self.publisher(systemd=systemd)
        pub.load_policy()
        module_entry = pub.module_policy(self.MODULE)
        plan = pub.plan(self.MODULE, self.RELEASE, self.PR)
        original_stop = systemd.__call__

        def stop_then_tamper(unit, action):
            result = original_stop(unit, action)
            if action == "stop":
                (self.opt / "price_writer.py").write_bytes(b"tampered while stopping\n")
            return result

        pub._systemd = stop_then_tamper
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")
        self.assertEqual(ctx.exception.detail.split(":")[0], "baseline_drift")
        self.assertEqual((self.opt / "automation_tick.py").read_bytes(), self.live["automation_tick.py"])
        self.assertEqual((self.opt / "price_writer.py").read_bytes(), b"tampered while stopping\n")


class StopFailureTest(Harness):
    def test_stop_failure_aborts_before_replacement(self):
        systemd = FakeSystemd(fail_stop_at={"fc27-cloud-worker": 1})
        pub = self.publisher(systemd=systemd)
        pub.load_policy()
        module_entry = pub.module_policy(self.MODULE)
        plan = pub.plan(self.MODULE, self.RELEASE, self.PR)
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")
        self.assertEqual(ctx.exception.detail.split(":")[0], "unit_stop_failed")
        for name, data in self.live.items():
            self.assertEqual((self.opt / name).read_bytes(), data, "停服务失败时不能替换代码")
        stored = json.loads(list((self.state / "releases").glob("*.json"))[0].read_text())
        self.assertEqual(stored["rollback"]["restored"], {})  # 未替换时不重写任何文件
        self.assertTrue(stored["rollback"]["ok"])
        self.assertNotIn("installed", json.dumps(stored["targets"]), "没替换就不该有 installed 记录")

    def test_rollback_checks_stop_result(self):
        # 第一次 stop 成功，回退时再 stop 失败
        systemd = FakeSystemd(fail_stop_at={"fc27-cloud-worker": 2},
                              fail_restart={"fc27-cloud-worker"})
        pub = self.publisher(systemd=systemd)
        pub.load_policy()
        module_entry = pub.module_policy(self.MODULE)
        plan = pub.plan(self.MODULE, self.RELEASE, self.PR)
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "unknown_write_state")
        stored = json.loads(list((self.state / "releases").glob("*.json"))[0].read_text())
        self.assertTrue(any("stop:" in e for e in stored["rollback"]["unit_errors"]))
        self.assertFalse(stored["rollback"]["ok"])
        self.assertEqual(stored["rollback"]["restored"], {})
        for name, data in self.new.items():
            self.assertEqual((self.opt / name).read_bytes(), data)


class AuthorizationTest(Harness):
    def assert_code(self, code):
        with self.assertRaises(entry.PublishError) as ctx:
            self.plan()
        self.assertEqual(ctx.exception.code, code, ctx.exception.detail)

    def test_missing_authorization_file(self):
        self.authorization_path().unlink()
        self.assert_code("path_missing")

    def test_authorization_symlink_rejected(self):
        real = self.tmp / "real-auth.json"
        real.write_text(json.dumps({"merge_commit": COMMIT, "scope": sorted(self.live),
                                    "authorized_by": "x", "expires_at": "2099-01-01T00:00:00+00:00"}))
        os.chmod(real, 0o640)
        self.authorization_path().unlink()
        os.symlink(real, self.authorization_path())
        self.assert_code("path_is_symlink")

    def test_authorization_parent_symlink_rejected(self):
        self.authorization_path().unlink()
        (self.authorizations / self.MODULE).rmdir()
        os.symlink(self.tmp, self.authorizations / self.MODULE)
        self.assert_code("path_is_symlink")

    def test_authorization_hardlink_rejected(self):
        os.link(self.authorization_path(), self.tmp / "auth-extra.json")
        self.assert_code("path_hardlinked")

    def test_authorization_writable_rejected(self):
        os.chmod(self.authorization_path(), 0o666)
        self.assert_code("path_writable")

    def test_authorization_owner_mismatch(self):
        self.policy["authorization"]["owner_uid"] = os.getuid() + 1
        self.write_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            self.plan()
        self.assertIn(ctx.exception.code, ("path_owner_mismatch", "path_parent_untrusted"))

    def test_merge_commit_must_match(self):
        self.write_authorization(merge_commit="2" * 40)
        self.assert_code("authorization_commit_mismatch")

    def test_scope_must_match(self):
        self.write_authorization(scope=["automation_tick.py"])
        self.assert_code("authorization_scope_mismatch")

    def test_expired(self):
        self.write_authorization(expires_at="2020-01-01T00:00:00+00:00")
        self.assert_code("authorization_expired")

    def test_expiry_naive(self):
        self.write_authorization(expires_at="2099-01-01T00:00:00")
        self.assert_code("authorization_expiry_naive")

    def test_authorizer_required(self):
        self.write_authorization(authorized_by="  ")
        self.assert_code("authorization_authorizer_missing")

    def test_commit_author_allowlist(self):
        self.artifacts.authors = {COMMIT: "stranger@example.com"}
        self.assert_code("authorization_author_not_allowed")

    def test_repo_free_text_does_not_authorize(self):
        patched = self.approval(authorized_by="吴律", authorized_at="2026-10-20T09:00:00+08:00")
        self.artifacts.blobs[(COMMIT, f"{self.BASE}/approval.json")] = patched
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = patched
        self.authorization_path().unlink()
        self.assert_code("path_missing")


class ValidationTest(Harness):
    def assert_code(self, code, **call):
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
            pub.plan(call.get("module", self.MODULE), call.get("release", self.RELEASE), call.get("pr", self.PR))
        self.assertEqual(ctx.exception.code, code, ctx.exception.detail)

    def test_module_not_in_policy(self):
        self.assert_code("module_not_in_policy", module="fc-players")

    def test_release_traversal(self):
        self.assert_code("release_invalid", release="../x")

    def test_pr_numeric(self):
        self.assert_code("pr_invalid", pr="231x")

    def test_release_must_be_on_main(self):
        self.artifacts.blobs.pop(("refs/remotes/origin/main", f"{self.BASE}/approval.json"))
        self.assert_code("release_not_on_main")

    def test_pr_mismatch(self):
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = self.approval(pr=999)
        self.assert_code("approval_pr_mismatch")

    def test_merge_commit_ancestor(self):
        self.artifacts.commits = set()
        self.assert_code("merge_commit_not_on_main")

    def test_merge_commit_pr_binding(self):
        self.artifacts.subjects = {COMMIT: "no pr tag"}
        self.assert_code("merge_commit_pr_binding")

    def test_scope_must_equal_targets(self):
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = \
            self.approval(scope=["automation_tick.py"])
        self.assert_code("approval_scope_mismatch")

    def test_target_not_in_policy(self):
        manifest = json.loads(self.targets_json())
        manifest["targets"]["extra.py"] = {"target": str(self.opt / "extra.py"),
                                           "before": "a" * 64, "after": "b" * 64}
        self.artifacts.blobs[(COMMIT, f"{self.BASE}/targets.json")] = json.dumps(manifest).encode()
        self.write_authorization(scope=sorted(manifest["targets"]))
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = \
            self.approval(scope=sorted(manifest["targets"]))
        self.assert_code("target_not_in_policy")

    def test_target_path_mismatch(self):
        manifest = json.loads(self.targets_json())
        manifest["targets"]["price_writer.py"]["target"] = str(self.tmp / "price_writer.py")
        self.artifacts.blobs[(COMMIT, f"{self.BASE}/targets.json")] = json.dumps(manifest).encode()
        self.assert_code("target_path_mismatch")

    def test_candidate_hash_mismatch(self):
        self.artifacts.blobs[(COMMIT, f"{self.BASE}/source/price_writer.py")] = b"tampered\n"
        self.assert_code("candidate_hash_mismatch")

    def test_baseline_drift(self):
        (self.opt / "price_writer.py").write_bytes(b"someone else\n")
        self.assert_code("baseline_drift")

    def test_target_symlink(self):
        target = self.opt / "price_writer.py"
        target.unlink()
        os.symlink(self.opt / "automation_tick.py", target)
        self.assert_code("target_is_symlink")

    def test_target_parent_symlink(self):
        real = self.tmp / "real-browser"
        real.mkdir()
        (real / "price_writer.py").write_bytes(self.live["price_writer.py"])
        linked = self.tmp / "opt-linked"
        os.symlink(real, linked)
        new_target = str(linked / "price_writer.py")
        self.policy["modules"][self.MODULE]["targets"]["price_writer.py"] = new_target
        self.policy["modules"][self.MODULE]["allowed_roots"] = [str(self.opt), str(self.tmp)]
        self.write_policy()
        manifest = json.loads(self.targets_json())
        manifest["targets"]["price_writer.py"]["target"] = new_target
        self.artifacts.blobs[(COMMIT, f"{self.BASE}/targets.json")] = json.dumps(manifest).encode()
        self.assert_code("target_parent_symlink")

    def test_policy_target_outside_root(self):
        self.policy["modules"][self.MODULE]["targets"]["price_writer.py"] = "/etc/passwd"
        self.write_policy()
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
        self.assertEqual(ctx.exception.code, "policy_target_outside_root")

    def test_policy_unit_action_whitelist(self):
        self.policy["modules"][self.MODULE]["units"]["fc27-cloud-worker"] = ["is-active", "reload-or-restart"]
        self.write_policy()
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
        self.assertEqual(ctx.exception.code, "policy_unit_action")

    def test_policy_requires_module_source_dir(self):
        self.policy["modules"][self.MODULE].pop("module_source_dir")
        self.write_policy()
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
        self.assertEqual(ctx.exception.code, "policy_module_source_missing")

    def test_policy_rejects_unreadable_policy(self):
        os.chmod(self.policy_path, 0o666)
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
        self.assertEqual(ctx.exception.code, "path_writable")


class RuntimeGateTest(Harness):
    def test_queue_busy(self):
        (self.state / "queue" / "job.json").write_text("{}")
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "queue_not_idle")

    def test_running_job(self):
        (self.state / "jobs" / "j.json").write_text(json.dumps({"status": "running"}))
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "job_not_idle")

    def test_unresolved_execution(self):
        (self.state / "executions" / "e.json").write_text(json.dumps({"status": "UNCERTAIN"}))
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "coin_execution_unresolved")

    def test_unknown_missing_and_corrupt_execution_fail_closed(self):
        path = self.state / "executions" / "unknown.json"
        for value in ('{"status":"UNKNOWN"}', '{}', 'null', '[]', '{broken', '{"status":"FUTURE_STATE"}'):
            with self.subTest(value=value):
                path.write_text(value)
                with self.assertRaises(entry.PublishError) as ctx:
                    self.publisher().check_idle()
                self.assertEqual(ctx.exception.code, "coin_execution_unresolved")

    def test_resolved_execution_contracts(self):
        for status in ("CONFIRMED", "RESTORED", "CHECK_ONLY", "FAILED_BEFORE_WRITE"):
            self.assertTrue(entry.resolved_execution({"status": status}))
        self.assertFalse(entry.resolved_execution({"status": "FAILED_BEFORE_WRITE", "changed": ["PS"]}))
        aligned = {"kind": "all_baseline_repair", "status": "ALL_ALIGNED",
                   "stage": "all_alignment_complete", "sync_confirmed": True,
                   "mmoexp_write_performed": False,
                   "all_baseline": {"status": "confirmed", "platforms": ["PS", "XBOX", "PC"]}}
        self.assertTrue(entry.resolved_execution(aligned))
        aligned["all_baseline"]["platforms"].pop()
        self.assertFalse(entry.resolved_execution(aligned))
        validated = {"kind": "player_validation_once", "status": "VALIDATED",
                     "stage": "complete_independent_readback", "completed_at": "2026-10-20T01:00:00Z",
                     "independent_readback": {"sha256": "a" * 64, "checked_at": "2026-10-20T00:59:00Z"},
                     "sample_verified_count": 1, "samples": [{}]}
        self.assertTrue(entry.resolved_execution(validated))
        validated["sample_verified_count"] = 2
        self.assertFalse(entry.resolved_execution(validated))
        validated["sample_verified_count"] = 1
        validated["independent_readback"]["checked_at"] = "2026-10-20T02:00:00Z"
        self.assertFalse(entry.resolved_execution(validated))

    def test_confirmed_without_completed_at(self):
        (self.state / "jobs" / "a.json").write_text(json.dumps(
            {"kind": "auto_cycle", "status": "done", "result": {"status": "confirmed"}}))
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "job_not_idle")

    def test_idle_check_reads_only(self):
        (self.state / "jobs" / "done.json").write_text(json.dumps({"status": "completed"}))
        before = {p.name: p.read_bytes() for p in (self.state / "jobs").iterdir()}
        self.publisher().check_idle()
        after = {p.name: p.read_bytes() for p in (self.state / "jobs").iterdir()}
        self.assertEqual(before, after)

    def test_inactive_unit(self):
        pub = self.publisher(systemd=FakeSystemd(inactive={"fc27-cloud-api"}))
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.check_units({"units": {"fc27-cloud-api": ["automation_tick.py"]}},
                            pub.module_policy(self.MODULE))
        self.assertEqual(ctx.exception.code, "unit_not_active")

    def test_unit_without_is_active_not_allowed(self):
        self.policy["modules"][self.MODULE]["units"]["fc27-cloud-api"] = ["stop", "restart"]
        self.write_policy()
        pub = self.publisher()
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.check_units({"units": {"fc27-cloud-api": ["automation_tick.py"]}},
                            pub.module_policy(self.MODULE))
        self.assertEqual(ctx.exception.code, "unit_readback_not_granted")


class RollbackTest(Harness):
    def prepare(self, pub):
        pub.load_policy()
        return pub.module_policy(self.MODULE), pub.plan(self.MODULE, self.RELEASE, self.PR)

    def test_restart_failure_rolls_back(self):
        pub = self.publisher(systemd=FakeSystemd(fail_restart={"fc27-cloud-worker"}))
        module_entry, plan = self.prepare(pub)
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back_unit_errors")
        for name, data in self.live.items():
            self.assertEqual((self.opt / name).read_bytes(), data)

    def test_readback_mismatch_rolls_back(self):
        pub = self.publisher()
        module_entry, plan = self.prepare(pub)
        original_wait = pub._wait_health

        def wait_and_tamper(deadline=10.0):
            (self.opt / "price_writer.py").write_bytes(b"external writer line")
            return original_wait(deadline)

        pub._wait_health = wait_and_tamper
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")
        for name, data in self.live.items():
            self.assertEqual((self.opt / name).read_bytes(), data)

    def test_protected_drift_rolls_back(self):
        pub = self.publisher()
        module_entry, plan = self.prepare(pub)
        original_wait = pub._wait_health

        def wait_and_tamper(deadline=10.0):
            (self.opt / "fc27_quote_engine.py").write_bytes(b"tampered protected\n")
            return original_wait(deadline)

        pub._wait_health = wait_and_tamper
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")

    def test_health_timeout_rolls_back(self):
        pub = self.publisher(monitor=lambda: {"health": {"worker": "degraded"}})
        module_entry, plan = self.prepare(pub)
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")
        self.assertEqual((self.opt / "price_writer.py").read_bytes(), self.live["price_writer.py"])

    def test_rollback_failure_reports_unknown_write_state(self):
        pub = self.publisher(systemd=FakeSystemd(fail_restart={"fc27-cloud-worker"}))
        module_entry, plan = self.prepare(pub)

        def broken_swap(data, target):
            raise OSError("disk gone")

        entry.Publisher._atomic_swap = staticmethod(broken_swap)
        try:
            with self.assertRaises(entry.PublishError) as ctx:
                pub.apply(plan, module_entry)
        finally:
            entry.Publisher._atomic_swap = staticmethod(ORIGINAL_SWAP)
        self.assertEqual(ctx.exception.code, "unknown_write_state")
        stored = json.loads(list((self.state / "releases").glob("*.json"))[0].read_text())
        self.assertEqual(stored["status"], "unknown_write_state")
        self.assertFalse(stored["rollback"]["ok"])


class UsageTest(unittest.TestCase):
    def test_bad_argument_count(self):
        self.assertEqual(entry.main(["fc-coins"]), 2)
        self.assertEqual(entry.main(["fc-coins", "r", "1", "extra"]), 2)

    def test_unit_runner_rejects_unknown_verb(self):
        with self.assertRaises(entry.PublishError) as ctx:
            entry.SystemdRunner()("fc27-cloud-worker", "enable")
        self.assertEqual(ctx.exception.code, "unit_action_rejected")

    def test_symlinked_ancestors_helper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            os.symlink(real, root / "link")
            self.assertEqual(entry.symlinked_ancestors(str(root / "link" / "x.py")), [str(root / "link")])
            self.assertEqual(entry.symlinked_ancestors(str(real / "x.py")), [])


if __name__ == "__main__":
    unittest.main()

