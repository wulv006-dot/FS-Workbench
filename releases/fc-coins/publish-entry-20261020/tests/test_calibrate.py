"""离线测试：现场哈希校准（无网络、无文件系统写入宿主路径）。"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

import calibrate  # noqa: E402

H_A = "a" * 64
H_B = "b" * 64


def policy(doc):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(doc, handle)
    handle.close()
    return handle.name


class Fixture(unittest.TestCase):
    def setUp(self):
        self.policy_doc = {
            "version": 1,
            "modules": {
                "fc-coins": {
                    "targets": {
                        "automation_tick.py": "/opt/fc27-cloud-browser/automation_tick.py",
                        "price_writer.py": "/opt/fc27-cloud-browser/price_writer.py",
                    },
                    "units": {"fc27-cloud-worker": ["is-active"]},
                }
            },
        }
        self.policy_path = policy(self.policy_doc)
        self.addCleanup(lambda: Path(self.policy_path).unlink(missing_ok=True))

    def run_main(self, argv, stdin_text=None):
        buffer = io.StringIO()
        original = sys.stdin
        if stdin_text is not None:
            sys.stdin = io.StringIO(stdin_text)
        try:
            with redirect_stdout(buffer):
                code = calibrate.main(argv)
        finally:
            sys.stdin = original
        return code, buffer.getvalue()


class EmitTest(Fixture):
    def test_emit_commands_lists_every_target_and_unit(self):
        code, out = self.run_main(["--policy", self.policy_path, "--module", "fc-coins", "--emit-commands"])
        self.assertEqual(code, 0)
        self.assertIn("sha256sum /opt/fc27-cloud-browser/automation_tick.py", out)
        self.assertIn("sha256sum /opt/fc27-cloud-browser/price_writer.py", out)
        self.assertIn("systemctl is-active fc27-cloud-worker", out)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("sha256sum ")]), 2)

    def test_unknown_module_exits(self):
        with self.assertRaises(SystemExit):
            calibrate.load_targets(self.policy_path, "fc-nba")


class ParseTest(unittest.TestCase):
    def test_accepts_text_and_binary_markers(self):
        text = f"{H_A}  /a.py\n{H_B} */b.py\n"
        hashes, ignored = calibrate.parse_readback(text)
        self.assertEqual(hashes, {"/a.py": H_A, "/b.py": H_B})
        self.assertEqual(ignored, [])

    def test_ignores_relative_comments_and_noise(self):
        text = f"# comment\nnot a hash line\n{H_A}  relative/path.py\n\n{H_B}  /ok.py\n"
        hashes, ignored = calibrate.parse_readback(text)
        self.assertEqual(hashes, {"/ok.py": H_B})
        self.assertEqual(len(ignored), 2)


class CompareTest(Fixture):
    def load(self):
        return calibrate.load_targets(self.policy_path, "fc-coins")

    def test_all_present_without_expected_is_ok(self):
        _, targets = self.load()
        report = calibrate.compare(targets, {
            "/opt/fc27-cloud-browser/automation_tick.py": H_A,
            "/opt/fc27-cloud-browser/price_writer.py": H_B,
        })
        self.assertTrue(report["ok"])
        self.assertEqual(sorted(report["matched"]), ["automation_tick.py", "price_writer.py"])

    def test_drift_against_expected(self):
        _, targets = self.load()
        expected = {"/opt/fc27-cloud-browser/automation_tick.py": H_A,
                    "/opt/fc27-cloud-browser/price_writer.py": H_A}
        report = calibrate.compare(targets, {
            "/opt/fc27-cloud-browser/automation_tick.py": H_A,
            "/opt/fc27-cloud-browser/price_writer.py": H_B,
        }, expected)
        self.assertFalse(report["ok"])
        self.assertEqual(report["drift"][0]["name"], "price_writer.py")
        self.assertEqual(report["drift"][0]["actual"], H_B)

    def test_missing_target_blocks(self):
        _, targets = self.load()
        report = calibrate.compare(targets, {"/opt/fc27-cloud-browser/automation_tick.py": H_A})
        self.assertFalse(report["ok"])
        self.assertEqual(report["missing"][0]["name"], "price_writer.py")

    def test_paths_outside_policy_are_reported_not_counted(self):
        _, targets = self.load()
        report = calibrate.compare(targets, {
            "/opt/fc27-cloud-browser/automation_tick.py": H_A,
            "/opt/fc27-cloud-browser/price_writer.py": H_B,
            "/opt/fc27-cloud-browser/sidecar.py": H_A,
        })
        self.assertTrue(report["ok"])
        self.assertEqual(report["not_in_policy"], ["/opt/fc27-cloud-browser/sidecar.py"])


class TargetsJsonTest(Fixture):
    def test_expected_reads_before_by_path_and_name(self):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"targets": {
            "automation_tick.py": {"target": "/opt/fc27-cloud-browser/automation_tick.py",
                                   "before": H_A, "after": H_B},
            "price_writer.py": {"target": "/opt/fc27-cloud-browser/price_writer.py",
                                "before": H_B, "after": H_A},
        }}, handle)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        expected = calibrate.load_expected(handle.name)
        self.assertEqual(expected["/opt/fc27-cloud-browser/automation_tick.py"], H_A)
        self.assertEqual(expected["automation_tick.py"], H_A)
        self.assertEqual(expected["price_writer.py"], H_B)


class MainTest(Fixture):
    def test_readback_all_match_exit_zero(self):
        text = (f"{H_A}  /opt/fc27-cloud-browser/automation_tick.py\n"
                f"{H_B}  /opt/fc27-cloud-browser/price_writer.py\n")
        code, out = self.run_main(["--policy", self.policy_path, "--module", "fc-coins",
                                   "--readback", "-"], stdin_text=text)
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_readback_drift_exit_four(self):
        text = f"{H_A}  /opt/fc27-cloud-browser/automation_tick.py\n"
        code, out = self.run_main(["--policy", self.policy_path, "--module", "fc-coins",
                                   "--readback", "-"], stdin_text=text)
        self.assertEqual(code, 4)
        self.assertFalse(json.loads(out)["ok"])

    def test_missing_readback_argument_is_usage_error(self):
        with self.assertRaises(SystemExit):
            calibrate.main(["--policy", self.policy_path, "--module", "fc-coins"])


if __name__ == "__main__":
    unittest.main()
