import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "source/start.sh").read_text(encoding="utf-8")
BASELINE = (ROOT / "baseline/start.sh").read_text(encoding="utf-8")
PYTHON = SOURCE.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]


class Clock:
    def __init__(self):
        self.value = 0

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.value += seconds


class StartTests(unittest.TestCase):
    def helper(self, reads, proc="42 (Xvfb) S 1", kill_error=None):
        namespace = {"__name__": "test_start"}
        exec(compile(PYTHON, "start.sh embedded readiness", "exec"), namespace)
        clock = Clock()
        chunks = list(reads)

        def open_file(path, mode="r"):
            if path == "/owned-ready-file":
                value = chunks.pop(0) if len(chunks) > 1 else chunks[0]
                return io.BytesIO(value)
            self.assertEqual(path, "/proc/42/stat")
            if isinstance(proc, Exception):
                raise proc
            return io.StringIO(proc)

        kill = Mock(side_effect=kill_error)
        namespace.update(open=open_file, os=SimpleNamespace(kill=kill), time=clock)
        return namespace["wait_display"], clock, kill

    def test_ready_display_zero(self):
        wait, clock, kill = self.helper([b"0\n"])
        self.assertEqual(wait("/owned-ready-file", 42), "0")
        kill.assert_called_once_with(42, 0)
        self.assertEqual(clock.value, 0)

    def test_non99_display_preserves_readiness(self):
        wait, _, _ = self.helper([b"123\n"])
        self.assertEqual(wait("/owned-ready-file", 42), "123")

    def test_waits_for_newline(self):
        wait, clock, _ = self.helper([b"", b"1", b"12\n"])
        self.assertEqual(wait("/owned-ready-file", 42), "12")
        self.assertAlmostEqual(clock.value, .1)

    def test_ten_second_timeout(self):
        wait, clock, _ = self.helper([b""])
        with self.assertRaisesRegex(RuntimeError, "xvfb_readiness_timeout"):
            wait("/owned-ready-file", 42)
        self.assertAlmostEqual(clock.value, 10)

    def test_short_timeout_stays_bounded(self):
        wait, clock, _ = self.helper([b"9"])
        with self.assertRaisesRegex(RuntimeError, "xvfb_readiness_timeout"):
            wait("/owned-ready-file", 42, timeout=.075)
        self.assertAlmostEqual(clock.value, .075)

    def test_dead_pid(self):
        wait, _, _ = self.helper([b""], kill_error=ProcessLookupError())
        with self.assertRaisesRegex(RuntimeError, "xvfb_exited_before_ready"):
            wait("/owned-ready-file", 42)

    def test_missing_proc(self):
        wait, _, _ = self.helper([b""], proc=FileNotFoundError())
        with self.assertRaisesRegex(RuntimeError, "xvfb_exited_before_ready"):
            wait("/owned-ready-file", 42)

    def test_zombie_pid(self):
        wait, _, _ = self.helper([b""], proc="42 (Xvfb) Z 1")
        with self.assertRaisesRegex(RuntimeError, "xvfb_exited_before_ready"):
            wait("/owned-ready-file", 42)

    def test_permission_unknown_never_ready(self):
        wait, _, _ = self.helper([b""], proc=PermissionError())
        with self.assertRaises(PermissionError):
            wait("/owned-ready-file", 42)

    def test_invalid_display_numbers(self):
        for data in (b"\n", b"-1\n", b"99\n0\n", b"999999\n", b"x\n", b"1" * 32):
            with self.subTest(data=data):
                wait, _, _ = self.helper([data])
                with self.assertRaisesRegex(RuntimeError, "xvfb_invalid_display_number"):
                    wait("/owned-ready-file", 42)

    def test_dead_after_ready_is_failure(self):
        wait, _, _ = self.helper([b"0\n"], kill_error=ProcessLookupError())
        with self.assertRaises(ProcessLookupError):
            wait("/owned-ready-file", 42)

    def test_chrome_and_profile_contract_unchanged(self):
        self.assertEqual(SOURCE.split("exec google-chrome-stable", 1)[1], BASELINE.split("exec google-chrome-stable", 1)[1])
        self.assertIn('test -d "$profile"\ntest -w "$profile"', SOURCE)
        self.assertEqual(SOURCE.split("profile=", 1)[1].splitlines()[0], BASELINE.split("profile=", 1)[1].splitlines()[0])

    def test_ports_and_remote_access_contract_unchanged(self):
        for command in ("websockify", "socat"):
            self.assertEqual(next(l for l in SOURCE.splitlines() if l.startswith(command)), next(l for l in BASELINE.splitlines() if l.startswith(command)))
        old_vnc = next(l for l in BASELINE.splitlines() if l.startswith("x11vnc"))
        new_vnc = next(l for l in SOURCE.splitlines() if l.startswith("x11vnc"))
        self.assertEqual(new_vnc, old_vnc.replace(":99", '"$DISPLAY"'))
        self.assertIn('DISPLAY=":$display_number"\n    export DISPLAY', SOURCE)

    def test_no_x_lock_or_profile_deletion(self):
        deletion = [l.strip() for l in SOURCE.splitlines() if "rm -" in l]
        self.assertEqual(deletion, ['trap \'rm -f "$display_file"\' 0', 'rm -f "$display_file"'])
        self.assertNotIn("/tmp/.X99-lock", SOURCE)
        self.assertNotIn("/tmp/.X11-unix", SOURCE)
        self.assertNotIn("sleep 2", SOURCE)
        self.assertIn("Xvfb -displayfd 3 -screen 0 1440x900x24 -nolisten tcp", SOURCE)

    def test_failure_stops_before_chrome_and_keeps_x_errors(self):
        self.assertIn('else\n    kill "$xvfb_pid" 2>/dev/null || :\n    exit 1\nfi', SOURCE)
        self.assertNotIn('wait "$xvfb_pid"', SOURCE)
        xvfb = next(l for l in SOURCE.splitlines() if l.startswith("Xvfb"))
        self.assertNotIn("2>&1", xvfb)


if __name__ == "__main__":
    unittest.main()
