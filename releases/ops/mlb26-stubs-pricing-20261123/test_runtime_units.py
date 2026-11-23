from configparser import ConfigParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
SERVICE = "fs-mlb26-stubs-preview.service"


class PreviewUnitsTests(unittest.TestCase):
    def test_hourly_timer_runs_the_bundled_preview_launcher(self):
        timer = ConfigParser()
        self.assertEqual(timer.read(ROOT / "fs-mlb26-stubs-preview.timer", encoding="utf-8"),
                         [str(ROOT / "fs-mlb26-stubs-preview.timer")])
        self.assertEqual(timer["Timer"]["Unit"], SERVICE)
        self.assertEqual(timer["Timer"]["OnCalendar"], "hourly")
        self.assertFalse(timer["Timer"].getboolean("Persistent"))

        service = ConfigParser()
        service.read(ROOT / SERVICE, encoding="utf-8")
        self.assertEqual(service["Service"]["Type"], "oneshot")
        executable, path = service["Service"]["ExecStart"].split()
        self.assertEqual(executable, "/bin/sh")
        launcher = (ROOT / Path(path).relative_to(service["Service"]["WorkingDirectory"])).read_text()
        self.assertIn("-m source.cli preview", launcher)
        self.assertIn("--primary-worker", launcher)
