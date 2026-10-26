"""Shadow reads a consistent SQLite backup without opening production WAL for write."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path.insert(0, str(SOURCE))
from fc_pricing_v3.ledger import Ledger
from fc_pricing_v3.scheduler import export_shadow_snapshot


class ShadowExportTest(unittest.TestCase):
    def test_outbox_cursor_and_snapshot_are_atomic(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Ledger(Path(temporary) / 'control.sqlite3')
            target = Path(temporary) / 'shadow-readonly.sqlite3'
            first = export_shadow_snapshot(db, target)
            self.assertEqual((first['status'], first['cursor']), ('published', 0))
            self.assertEqual(export_shadow_snapshot(db, target)['status'], 'current')
            with db.transaction() as conn:
                conn.execute('INSERT INTO event_outbox(event_key,kind,body) VALUES (?,?,?)',
                             ('one', 'snapshot_ready', '{"snapshot_id":"one"}'))
                db.put('pricing_snapshots', 'one', {'snapshot_id': 'one'}, conn)
            second = export_shadow_snapshot(db, target)
            self.assertEqual((second['status'], second['cursor']), ('published', 1))
            with closing(sqlite3.connect('file:' + str(target.resolve()) + '?mode=ro', uri=True)) as snapshot:
                self.assertEqual(snapshot.execute('PRAGMA journal_mode').fetchone()[0], 'delete')
                self.assertEqual(snapshot.execute('SELECT count(*) FROM event_outbox').fetchone()[0], 1)
                self.assertEqual(snapshot.execute("SELECT body FROM pricing_snapshots WHERE id='one'").fetchone()[0],
                                 '{"snapshot_id": "one"}')
            self.assertFalse(Path(str(target) + '-wal').exists())
            self.assertFalse(Path(str(target) + '-shm').exists())


if __name__ == '__main__':
    unittest.main()
