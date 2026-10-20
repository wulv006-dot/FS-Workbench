"""离线测试：宿主可信发布入口（无网络、无 subprocess、无真实 /opt）。

覆盖：策略/白名单、批准绑定、merge commit 归属、候选与现场哈希、
队列/锁/单元、成功发布、回退与未知写入状态。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

import fc27_publish_entry as entry  # noqa: E402

ORIGINAL_SWAP = entry.Publisher._atomic_swap

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
COMMIT = "1" * 40


def sha(data):
    import hashlib

    return hashlib.sha256(data).hexdigest()


class FakeArtifacts:
    def __init__(self, blobs=None, commits=None, subjects=None, main_ref="refs/remotes/origin/main"):
        self.blobs = blobs or {}
        self.commits = set(commits or [COMMIT])
        self.subjects = subjects or {COMMIT: "fix(fc-coins): demo (#231)"}
        self.main_ref = main_ref

    def blob(self, commit, path):
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


class FakeSystemd:
    def __init__(self, fail_restart=None, fail_stop=None, inactive=None):
        self.calls = []
        self.fail_restart = set(fail_restart or [])
        self.fail_stop = set(fail_stop or [])
        self.inactive = set(inactive or [])

    def __call__(self, unit, action):
        self.calls.append((unit, action))
        if action == "is-active":
            return (False, "inactive") if unit in self.inactive else (True, "active")
        if action == "stop":
            return (False, "stop-failed") if unit in self.fail_stop else (True, "stopped")
        if action == "restart":
            return (False, "restart-failed") if unit in self.fail_restart else (True, "active")
        raise AssertionError(action)


class Harness(unittest.TestCase):
    """搭一个临时"宿主"：/opt 根、/var/lib 状态、/etc 策略。"""

    MODULE = "fc-coins"
    RELEASE = "demo-20261020"
    PR = "231"
    BASE = f"releases/fc-coins/{RELEASE}"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.opt = self.tmp / "opt" / "fc27-cloud-browser"
        self.collector = self.tmp / "opt" / "fc27-collector"
        self.opt.mkdir(parents=True)
        self.collector.mkdir(parents=True)
        self.state = self.tmp / "var"
        for name in ("queue", "jobs", "executions", "state", "rollback", "releases"):
            (self.state / name).mkdir(parents=True)
        (self.state / "state" / "price-writer.lock").write_text("")
        self.policy_path = self.tmp / "release-policy.json"

        self.live = {
            "automation_tick.py": b"old tick\n",
            "price_writer.py": b"old writer\n",
        }
        for name, data in self.live.items():
            (self.opt / name).write_bytes(data)
        (self.opt / "fc27_quote_engine.py").write_bytes(b"quote engine\n")

        self.new = {name: data.replace(b"old", b"new") for name, data in self.live.items()}
        self.policy = {
            "version": 1,
            "checkout": str(self.tmp / "checkout"),
            "modules": {
                self.MODULE: {
                    "release_prefix": "releases/fc-coins/",
                    "allowed_roots": [str(self.opt), str(self.collector)],
                    "units": {
                        "fc27-cloud-api": ["is-active", "stop", "restart"],
                        "fc27-cloud-worker": ["is-active", "stop", "restart"],
                        "fc27-automation-tick.timer": ["is-active", "stop", "restart"],
                    },
                    "targets": {
                        "automation_tick.py": str(self.opt / "automation_tick.py"),
                        "price_writer.py": str(self.opt / "price_writer.py"),
                    },
                    "target_units": {
                        "automation_tick.py": ["fc27-automation-tick.timer", "fc27-cloud-worker"],
                        "price_writer.py": ["fc27-cloud-worker"],
                    },
                }
            },
        }
        self.write_policy()
        self.refresh_artifacts()

    def write_policy(self):
        self.policy_path.write_text(json.dumps(self.policy, ensure_ascii=False), encoding="utf-8")

    def targets_json(self):
        return json.dumps({
            "targets": {
                name: {"target": self.policy["modules"][self.MODULE]["targets"][name],
                       "before": sha(self.live[name]), "after": sha(self.new[name])}
                for name in self.live
            }
        }).encode()

    def approval(self, **overrides):
        payload = {"pr": int(self.PR), "merge_commit": COMMIT,
                   "authorized_by": "吴律", "authorized_at": "2026-10-20T09:00:00+08:00",
                   "scope": sorted(self.live)}
        payload.update(overrides)
        return json.dumps(payload).encode()

    def refresh_artifacts(self):
        blobs = {
            (COMMIT, f"{self.BASE}/targets.json"): self.targets_json(),
            (COMMIT, f"{self.BASE}/approval.json"): self.approval(),
            ("refs/remotes/origin/main", f"{self.BASE}/approval.json"): self.approval(),
        }
        for name, data in self.new.items():
            blobs[(COMMIT, f"{self.BASE}/source/{name}")] = data
        self.artifacts = FakeArtifacts(blobs)
        return self.artifacts

    def publisher(self, **kwargs):
        paths = entry.Paths(policy=self.policy_path, checkout=self.tmp / "checkout", state_root=self.state)
        systemd = kwargs.pop("systemd", FakeSystemd())
        monitor = kwargs.pop("monitor", lambda: {"health": {"worker": "ok"}})
        return entry.Publisher(paths=paths, artifacts=self.artifacts, systemd=systemd,
                               monitor=monitor, sleep=lambda _s: None)

    def plan(self, publisher=None):
        publisher = publisher or self.publisher()
        publisher.load_policy()
        return publisher, publisher.plan(self.MODULE, self.RELEASE, self.PR)


class SuccessTest(Harness):
    def test_publish_writes_new_bytes_backs_up_and_receipts(self):
        systemd = FakeSystemd()
        pub = self.publisher(systemd=systemd)
        pub.load_policy()
        module_entry = pub.module_policy(self.MODULE)
        plan = pub.plan(self.MODULE, self.RELEASE, self.PR)
        self.assertEqual(plan["merge_commit"], COMMIT)
        self.assertEqual(sorted(plan["units"]), ["fc27-automation-tick.timer", "fc27-cloud-worker"])

        pub.acquire_lock()
        pub.check_idle()
        pub.check_units(plan)
        result = pub.apply(plan, module_entry)
        pub.release_lock()

        self.assertEqual(result["status"], "published")
        for name, data in self.new.items():
            self.assertEqual((self.opt / name).read_bytes(), data)
        rollback = Path(result["rollback_dir"])
        for name, data in self.live.items():
            self.assertEqual((rollback / name).read_bytes(), data)
        self.assertTrue((rollback / "meta.json").is_file())
        receipt = Path(result["receipt"])
        self.assertTrue(receipt.is_file())
        stored = json.loads(receipt.read_text())
        self.assertEqual(stored["status"], "published")
        self.assertEqual(stored["pr"], int(self.PR))
        self.assertEqual(stored["merge_commit"], COMMIT)

        actions = systemd.calls
        self.assertIn(("fc27-cloud-worker", "stop"), actions)
        self.assertIn(("fc27-cloud-worker", "restart"), actions)
        self.assertIn(("fc27-automation-tick.timer", "stop"), actions)
        self.assertLess(actions.index(("fc27-cloud-worker", "stop")),
                        actions.index(("fc27-cloud-worker", "restart")))
        # worker 被两个目标同时要求，只应停/启一次
        self.assertEqual(actions.count(("fc27-cloud-worker", "stop")), 1)

    def test_check_mode_reports_plan_without_writing(self):
        pub = self.publisher()
        pub.load_policy()
        plan = pub.plan(self.MODULE, self.RELEASE, self.PR)
        self.assertEqual(sorted(plan["targets"]), sorted(self.live))
        for name, data in self.live.items():
            self.assertEqual((self.opt / name).read_bytes(), data)


class ValidationTest(Harness):
    def assert_code(self, code, publisher=None, **call):
        pub = publisher or self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.load_policy()
            pub.plan(call.get("module", self.MODULE), call.get("release", self.RELEASE), call.get("pr", self.PR))
        self.assertEqual(ctx.exception.code, code, ctx.exception.detail)

    def test_module_not_in_policy(self):
        self.assert_code("module_not_in_policy", module="fc-players")

    def test_release_name_rejects_traversal(self):
        self.assert_code("release_invalid", release="../natural-recovery-20261020")

    def test_release_name_rejects_slash(self):
        self.assert_code("release_invalid", release="a/b")

    def test_pr_must_be_numeric(self):
        self.assert_code("pr_invalid", pr="231x")

    def test_release_must_be_on_main(self):
        self.artifacts.blobs.pop(("refs/remotes/origin/main", f"{self.BASE}/approval.json"))
        self.assert_code("release_not_on_main")

    def test_pr_mismatch(self):
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = self.approval(pr=999)
        self.assert_code("approval_pr_mismatch")

    def test_merge_commit_must_be_ancestor(self):
        self.artifacts.commits = set()
        self.assert_code("merge_commit_not_on_main")

    def test_merge_commit_must_bind_pr(self):
        self.artifacts.subjects = {COMMIT: "fix(fc-coins): demo without pr tag"}
        self.assert_code("merge_commit_pr_binding")

    def test_authorization_fields_required(self):
        approval = self.approval(authorized_by="")
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = approval
        self.assert_code("approval_authorization_missing")

    def test_scope_must_equal_targets(self):
        approval = self.approval(scope=["automation_tick.py"])
        self.artifacts.blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = approval
        self.assert_code("approval_scope_mismatch")

    def test_target_must_be_in_policy(self):
        blobs = self.artifacts.blobs
        manifest = json.loads(self.targets_json())
        manifest["targets"]["extra.py"] = {"target": str(self.opt / "extra.py"),
                                           "before": SHA_A, "after": SHA_B}
        blobs[(COMMIT, f"{self.BASE}/targets.json")] = json.dumps(manifest).encode()
        blobs[("refs/remotes/origin/main", f"{self.BASE}/approval.json")] = self.approval(scope=sorted(manifest["targets"]))
        self.assert_code("target_not_in_policy")

    def test_target_path_must_match_policy(self):
        blobs = self.artifacts.blobs
        manifest = json.loads(self.targets_json())
        manifest["targets"]["price_writer.py"]["target"] = str(self.collector / "price_writer.py")
        blobs[(COMMIT, f"{self.BASE}/targets.json")] = json.dumps(manifest).encode()
        self.assert_code("target_path_mismatch")

    def test_candidate_must_match_commit_blob(self):
        self.artifacts.blobs[(COMMIT, f"{self.BASE}/source/price_writer.py")] = b"tampered\n"
        self.assert_code("candidate_hash_mismatch")

    def test_baseline_drift_blocks(self):
        (self.opt / "price_writer.py").write_bytes(b"someone else\n")
        self.assert_code("baseline_drift")

    def test_symlink_target_rejected(self):
        target = self.opt / "price_writer.py"
        target.unlink()
        os.symlink(self.opt / "automation_tick.py", target)
        self.assert_code("target_is_symlink")

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

    def test_unit_not_granted_restart(self):
        self.policy["modules"][self.MODULE]["units"]["fc27-cloud-worker"] = ["is-active"]
        self.write_policy()
        self.assert_code("unit_action_not_granted")

    def test_unit_missing_from_policy(self):
        self.policy["modules"][self.MODULE]["target_units"]["price_writer.py"] = ["fc27-unknown"]
        self.write_policy()
        self.assert_code("policy_unit_reference_unknown")


class RuntimeGateTest(Harness):
    def test_queue_busy(self):
        (self.state / "queue" / "job.json").write_text("{}")
        pub = self.publisher()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.check_idle()
        self.assertEqual(ctx.exception.code, "queue_not_idle")

    def test_running_job_blocks(self):
        (self.state / "jobs" / "j.json").write_text(json.dumps({"status": "running"}))
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "job_not_idle")

    def test_unresolved_execution_blocks(self):
        (self.state / "executions" / "e.json").write_text(json.dumps({"status": "UNCERTAIN"}))
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "coin_execution_unresolved")

    def test_confirmed_without_completed_at_blocks(self):
        (self.state / "jobs" / "a.json").write_text(json.dumps(
            {"kind": "auto_cycle", "status": "done", "result": {"status": "confirmed"}}))
        with self.assertRaises(entry.PublishError) as ctx:
            self.publisher().check_idle()
        self.assertEqual(ctx.exception.code, "job_not_idle")

    def test_price_writer_lock_busy(self):
        pub = self.publisher()
        other = os.open(self.state / "state" / "price-writer.lock", os.O_RDONLY)
        import fcntl

        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            with self.assertRaises(entry.PublishError) as ctx:
                pub.acquire_lock()
            self.assertEqual(ctx.exception.code, "price_writer_lock_busy")
        finally:
            fcntl.flock(other, fcntl.LOCK_UN)
            os.close(other)
        pub.acquire_lock()
        pub.release_lock()

    def test_inactive_unit_blocks(self):
        pub = self.publisher(systemd=FakeSystemd(inactive={"fc27-cloud-worker"}))
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.check_units({"units": {"fc27-cloud-worker": ["restart"]}}, pub.module_policy(self.MODULE))
        self.assertEqual(ctx.exception.code, "unit_not_active")

    def test_unit_without_is_active_not_allowed(self):
        self.policy["modules"][self.MODULE]["units"]["fc27-cloud-worker"] = ["stop", "restart"]
        self.write_policy()
        pub = self.publisher()
        pub.load_policy()
        with self.assertRaises(entry.PublishError) as ctx:
            pub.check_units({"units": {"fc27-cloud-worker": ["restart"]}}, pub.module_policy(self.MODULE))
        self.assertEqual(ctx.exception.code, "unit_readback_not_granted")


class RollbackTest(Harness):
    def prepare(self, pub):
        pub.load_policy()
        module_entry = pub.module_policy(self.MODULE)
        return module_entry, pub.plan(self.MODULE, self.RELEASE, self.PR)

    def test_restart_failure_restores_previous_bytes(self):
        systemd = FakeSystemd(fail_restart={"fc27-cloud-worker"})
        pub = self.publisher(systemd=systemd)
        module_entry, plan = self.prepare(pub)
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")
        for name, data in self.live.items():
            self.assertEqual((self.opt / name).read_bytes(), data)
        receipts = list((self.state / "releases").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        stored = json.loads(receipts[0].read_text())
        self.assertEqual(stored["status"], "rolled_back")
        self.assertTrue(stored["rollback"]["ok"])

    def test_readback_mismatch_triggers_rollback(self):
        """装上去的字节被外部改动 → 读回不符 → 用备份换回 before。"""
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

    def test_protected_file_drift_rolls_back(self):
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
        for name, data in self.live.items():
            self.assertEqual((self.opt / name).read_bytes(), data)

    def test_health_timeout_rolls_back(self):
        pub = self.publisher(monitor=lambda: {"health": {"worker": "degraded"}})
        module_entry, plan = self.prepare(pub)
        with self.assertRaises(entry.PublishError) as ctx:
            pub.apply(plan, module_entry)
        self.assertEqual(ctx.exception.code, "rolled_back")
        self.assertEqual((self.opt / "price_writer.py").read_bytes(), self.live["price_writer.py"])

    def test_rollback_failure_reports_unknown_write_state(self):
        systemd = FakeSystemd(fail_restart={"fc27-cloud-worker"})
        pub = self.publisher(systemd=systemd)
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
        receipts = list((self.state / "releases").glob("*.json"))
        stored = json.loads(receipts[0].read_text())
        self.assertEqual(stored["status"], "unknown_write_state")
        self.assertFalse(stored["rollback"]["ok"])


class UsageTest(unittest.TestCase):
    def test_bad_argument_count_returns_usage(self):
        self.assertEqual(entry.main(["fc-coins"]), 2)
        self.assertEqual(entry.main(["fc-coins", "demo-20261020"]), 2)
        self.assertEqual(entry.main(["fc-coins", "demo-20261020", "231", "extra"]), 2)

    def test_unit_runner_rejects_unknown_verb(self):
        with self.assertRaises(entry.PublishError) as ctx:
            entry.SystemdRunner()("fc27-cloud-worker", "enable")
        self.assertEqual(ctx.exception.code, "unit_action_rejected")


if __name__ == "__main__":
    unittest.main()
