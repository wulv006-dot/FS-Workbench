import importlib.util
from pathlib import Path
import unittest

MODULE=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('game_monitor_build',MODULE/'build.py')
build=importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildTests(unittest.TestCase):
    def test_standalone_bundle_reads_same_origin_and_preserves_original_entry(self):
        raw=build.build().decode('utf-8')
        self.assertNotIn('<script src=',raw)
        self.assertNotIn('@import',raw)
        self.assertIn('src="index.html"',raw)
        self.assertIn("intelligence:'intelligence.json'",raw)
        self.assertNotIn('window.MONITOR_DATA',raw)
        self.assertNotIn('fs-monitor-preview',raw)


if __name__=='__main__':
    unittest.main()
