"""离线测试：调用端（无特权）只做预检、不写任何东西。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

import fc_publish  # noqa: E402
import fc27_publish_entry as entry  # noqa: E402

COMMIT = "2" * 40
RELEASE = "demo-20261020"
PR = "231"
BASE = f"releases/fc-coins/{RELEASE}"
NEW = b"new tick\n"
LIVE = b"old tick\n"


def sha(data):
    import hashlib

    return hashlib.sha256(data).hexdigest()


class FakeGit:
    ref = "refs/remotes/origin/main"

    def __init__(self):
        self.main_ref = self.ref
        self.blobs = {}
        self.commits = set()
        self.subjects = {}

    def install(self):
        fc_publish.GitArtifacts = lambda checkout: self
        return self

    def blob(self, commit, path):
        try:
            return self.blobs[(commit, path)]
        except KeyError:
            raise entry.PublishError("git_failed", f"missing {path}")

    def exists(self, ref, path):
        return (ref, path) in self.blobs

    def is_ancestor(self, commit, ref):
        return commit in self.commits

    def subject(self, commit):
        return self.subjects.get(commit, "")


def manifest(**overrides):
    row = {"target": "/opt/fc27-cloud-browser/automation_tick.py",
           "before": sha(LIVE), "after": sha(NEW)}
    row.update(overrides)
    return json.dumps({"targets": {"automation_tick.py": row}}).encode()


def approval(**overrides):
    payload = {"pr": int(PR), "merge_commit": COMMIT, "authorized_by": "吴律",
               "authorized_at": "2026-10-20T09:00:00+08:00", "scope": ["automation_tick.py"]}
    payload.update(overrides)
    return json.dumps(payload).encode()


class CallerTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeGit()
        self.fake.blobs = {
            (self.fake.ref, f"{BASE}/approval.json"): approval(),
            (COMMIT, f"{BASE}/approval.json"): approval(),
            (COMMIT, f"{BASE}/targets.json"): manifest(),
            (COMMIT, f"{BASE}/source/automation_tick.py"): NEW,
        }
        self.fake.commits = {COMMIT}
        self.fake.subjects = {COMMIT: "fix(fc-coins): demo (#231)"}
        self.fake.install()
        self.addCleanup(lambda: setattr(fc_publish, "GitArtifacts", entry.GitArtifacts))

    def preflight(self, **kwargs):
        return fc_publish.preflight(Path("/nonexistent"), "fc-coins", RELEASE, PR, **kwargs)

    def assert_code(self, code, **kwargs):
        with self.assertRaises(entry.PublishError) as ctx:
            self.preflight(**kwargs)
        self.assertEqual(ctx.exception.code, code, ctx.exception.detail)

    def test_happy_path_reports_host_command_and_no_write(self):
        result = self.preflight()
        self.assertEqual(result["merge_commit"], COMMIT)
        self.assertEqual(result["candidates_verified"], ["automation_tick.py"])
        self.assertEqual(result["host_command"],
                         f"sudo /usr/local/sbin/fc27-publish fc-coins {RELEASE} {PR}")
        self.assertIn("not_checked_here", result["live_baseline"])
        self.assertIn("not_checked_here", result["policy_and_scope"])

    def test_release_must_exist_on_main(self):
        self.fake.blobs.pop((self.fake.ref, f"{BASE}/approval.json"))
        self.assert_code("release_not_on_main")

    def test_pr_must_match_approval(self):
        self.fake.blobs[(self.fake.ref, f"{BASE}/approval.json")] = approval(pr=1)
        self.assert_code("approval_pr_mismatch")

    def test_merge_commit_must_bind_pr(self):
        self.fake.subjects = {COMMIT: "fix(fc-coins): demo (#999)"}
        self.assert_code("merge_commit_pr_binding")

    def test_scope_must_equal_targets(self):
        self.fake.blobs[(self.fake.ref, f"{BASE}/approval.json")] = approval(scope=["a.py", "b.py"])
        self.assert_code("approval_scope_mismatch")

    def test_candidate_bytes_must_match_commit(self):
        self.fake.blobs[(COMMIT, f"{BASE}/source/automation_tick.py")] = b"tampered\n"
        self.assert_code("candidate_hash_mismatch")

    def test_traversal_release_rejected(self):
        with self.assertRaises(entry.PublishError) as ctx:
            fc_publish.preflight(Path("/nonexistent"), "fc-coins", "../evil", PR)
        self.assertEqual(ctx.exception.code, "release_invalid")

    def test_bad_pr_rejected(self):
        with self.assertRaises(entry.PublishError) as ctx:
            fc_publish.preflight(Path("/nonexistent"), "fc-coins", RELEASE, "abc")
        self.assertEqual(ctx.exception.code, "pr_invalid")

    def test_main_returns_zero_and_prints_json(self):
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = fc_publish.main(["fc-coins", RELEASE, PR, "--checkout", "/nonexistent"])
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["pr"], PR)

    def test_main_returns_three_on_validation_error(self):
        code = fc_publish.main(["fc-coins", "../evil", PR, "--checkout", "/nonexistent"])
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
