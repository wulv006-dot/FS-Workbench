import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class Release(unittest.TestCase):
    def test_exact_fifteen_targets_and_only_two_new_units(self):
        sys.modules['release']=SimpleNamespace()
        self.addCleanup(sys.modules.pop,'release',None)
        spec=importlib.util.spec_from_file_location('archive_release',ROOT/'deploy/archive_release.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertEqual(len(module.TARGETS),15)
        self.assertEqual({Path(p).name for p in module.UNITS},{'fs-data-archive.service','fs-data-archive.timer'})
        self.assertEqual(len(module.NEW),7)
        self.assertEqual({module.SOURCES[k] for k in module.TARGETS if k.endswith('/daily_archive.py')},{'source/daily_archive.py'})
        self.assertFalse(any('price' in p or 'automation' in p for p in module.TARGETS.values()))
        timer=(ROOT/'deploy/fs-data-archive.timer').read_text()
        self.assertIn('00:50:00',timer);self.assertIn('Persistent=false',timer)
        spec=importlib.util.spec_from_file_location('archive_metrics_fix',ROOT/'deploy/archive_metrics_fix.py')
        fix=importlib.util.module_from_spec(spec);spec.loader.exec_module(fix)
        self.assertEqual(len(fix.TARGETS),3)
        self.assertFalse(any('/systemd/' in path for path in fix.TARGETS.values()))
        spec=importlib.util.spec_from_file_location('job_retry_fix',ROOT/'deploy/job_retry_fix.py')
        fix=importlib.util.module_from_spec(spec);spec.loader.exec_module(fix)
        self.assertEqual(fix.TARGETS,{'runtime/archive_jobs.py':'/opt/fs-exact-range-20261001/archive_jobs.py'})
        spec=importlib.util.spec_from_file_location('archive_maturity_fix',ROOT/'deploy/archive_maturity_fix.py')
        fix=importlib.util.module_from_spec(spec);spec.loader.exec_module(fix)
        self.assertEqual(len(fix.TARGETS),8)
        self.assertFalse(any('/systemd/' in path for path in fix.TARGETS.values()))
        spec=importlib.util.spec_from_file_location('report_source_retry',ROOT/'deploy/report_source_retry.py')
        fix=importlib.util.module_from_spec(spec);spec.loader.exec_module(fix)
        self.assertEqual(len(fix.TARGETS),4)
        self.assertFalse(any('/systemd/' in p or 'price' in p for p in fix.TARGETS.values()))


if __name__=='__main__':unittest.main()
