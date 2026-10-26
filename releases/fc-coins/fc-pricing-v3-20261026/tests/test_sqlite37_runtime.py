"""Exercise mutable V3 rows on the server's SQLite 3.7 SQL subset."""
from pathlib import Path
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3.ledger import Ledger


class Sqlite37RuntimeTest(unittest.TestCase):
    def test_generation_plan_assignment_and_rowid_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Ledger(Path(temporary) / 'control.sqlite3')
            db.activate_generation('test-generation', [])
            db.put('metadata', 'sample', {'value': 1})
            with db.connect() as conn:
                before = conn.execute("SELECT rowid FROM metadata WHERE id='sample'").fetchone()[0]
            db.put('metadata', 'sample', {'value': 2})
            with db.connect() as conn:
                after = conn.execute("SELECT rowid FROM metadata WHERE id='sample'").fetchone()[0]
            self.assertEqual(before, after)
            self.assertEqual(db.get('metadata', 'sample')['value'], 2)
            plan = db.create_plan('daily', ['base:console'],
                                  {'base_prices': {'console': '8', 'pc': '8'}, 'region_coefficients': {}},
                                  daily_budget='9')
            active = db.activate_plan(plan['plan_id'])
            self.assertEqual(active['state'], 'ACTIVE')
            candidates = [{'action': {'base_prices': {'console': '8', 'pc': '8'},
                                      'region_coefficients': {}},
                           'score': {'objective': '1', 'revenue': '1'}, 'control': True}]
            first = db.assignment(active, candidates)
            self.assertEqual(db.assignment(active, candidates)['assignment_id'], first['assignment_id'])


if __name__ == '__main__':
    unittest.main()
