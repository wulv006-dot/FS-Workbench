import importlib.util
from pathlib import Path
import unittest

MODULE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('game_monitor_build',MODULE/'build.py')
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_standalone_bundle_has_no_retired_workspace_or_daily_reader(self):
        raw=build.build().decode('utf-8')
        self.assertNotIn('<script src=',raw)
        self.assertNotIn('@import',raw)
        self.assertNotIn('src="index.html"',raw)
        self.assertNotIn('legacy-frame',raw)
        self.assertNotIn('资料与工具',raw)
        self.assertNotIn("daily:'daily.json'",raw)
        self.assertIn("intelligence:'intelligence.json'",raw)
        self.assertNotIn('window.MONITOR_DATA',raw)
        self.assertNotIn('fs-monitor-preview',raw)
        self.assertIn('id="game-filter"',raw)
        self.assertNotIn('id="sidebar"',raw)
        self.assertNotIn('id="game-list"',raw)


if __name__=='__main__':
    unittest.main()
