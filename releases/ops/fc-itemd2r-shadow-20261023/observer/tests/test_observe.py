import ast
from datetime import datetime,timezone,timedelta
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('observe',ROOT/'source/observe.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ObserverTest(unittest.TestCase):
    def test_nonconcurrent_sources_do_not_become_weighted_simulation(self):
        now=datetime.now(timezone.utc)
        rows=[dict(status='valid',captured_at=now.isoformat()),dict(status='valid',captured_at=(now-timedelta(minutes=6)).isoformat())]
        self.assertFalse(m.comparable_cohort(rows))
        rows[1]['captured_at']=(now-timedelta(minutes=2)).isoformat()
        self.assertTrue(m.comparable_cohort(rows))
    def test_missing_or_naive_capture_not_comparable(self):
        self.assertFalse(m.comparable_cohort([]))
        self.assertFalse(m.comparable_cohort([dict(status='valid',captured_at='2026-10-23T15:00:00')]))
    def test_no_business_writer_model_or_original_data_mutation_entry(self):
        tree=ast.parse((ROOT/'source/observe.py').read_text())
        calls=[ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]
        self.assertFalse(any(x in calls for x in ['calculate','check_write','request','recommend','execute','restore','collect_once']))
        literals=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)]
        self.assertNotIn('daemon-reload',literals)
        self.assertNotIn('restart',literals)
        self.assertIn('original_snapshot_unchanged',literals)

if __name__=='__main__':unittest.main()
