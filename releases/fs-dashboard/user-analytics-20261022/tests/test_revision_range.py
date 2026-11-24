"""Synthetic SQLite replay tests, portable; POSIX provisioning is tested separately."""
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from user_store import Store, StoreUnavailable
import user_version_index as index


def fact(key, revision, paid, valid=1, customer='c1', site='266', gid='1327'):
    return dict(order_key=key, site=site, gid=gid, customer_id=customer,
                paid_at=paid+'T00:00:00+08:00', valid=valid,
                body=json.dumps(dict(id=key, amount_usd='1.00', order_no=key)), revision=revision)


class RevisionRange(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store.__new__(Store)
        self.store.path = Path(self.temp.name)/'customers.sqlite3'
        self.store.read_only = False; self.store.config = {}
        db = sqlite3.connect(self.store.path)
        db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO meta VALUES('revision','1');
            CREATE TABLE orders(order_key TEXT PRIMARY KEY,site TEXT,gid TEXT,customer_id TEXT,paid_at TEXT,valid INTEGER,body TEXT,revision INTEGER);
            CREATE INDEX purchase_time ON orders(paid_at,valid);
            CREATE INDEX customer_time ON orders(customer_id,paid_at);
            CREATE TABLE revisions(id INTEGER PRIMARY KEY,reason TEXT,body TEXT);''')
        db.commit(); db.close()

    def change(self, revision, rows):
        with self.store.db() as db:
            current = int(db.execute("SELECT value FROM meta WHERE key='revision'").fetchone()[0])
            old = []
            for row in rows:
                previous = db.execute('SELECT * FROM orders WHERE order_key=?', (row['order_key'],)).fetchone()
                if previous: old.append(dict(previous))
                db.execute('INSERT OR REPLACE INTO orders VALUES(?,?,?,?,?,?,?,?)', tuple(row[k] for k in index.COLUMNS.split(',')))
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (revision, 'synthetic', json.dumps(old)))
            index.advance(db, current, revision, old)
            db.execute("UPDATE meta SET value=? WHERE key='revision'", (str(revision),))

    def migrate(self):
        while True:
            with self.store.db() as db:
                db.execute('BEGIN IMMEDIATE')
                result = index.build_batch(db, limit=1)
            if result['ready']: break

    def compare(self, versions, windows):
        for version in versions:
            for start, end in windows:
                self.store.config['revision_range_index'] = False
                old = self.store.read_at(str(version), start, end)
                self.store.config['revision_range_index'] = True
                self.assertEqual(old, self.store.read_at(str(version), start, end))
            self.store.config['revision_range_index'] = False
            old = self.store.orders_at(version, 'c1')
            self.store.config['revision_range_index'] = True
            self.assertEqual(old, self.store.orders_at(version, 'c1'))

    def test_date_moves_both_directions_refund_invalid_identity_and_scope(self):
        self.change(2, [fact('a',2,'2026-10-02'), fact('b',2,'2026-09-02'), fact('c',2,'2026-10-03',0)])
        self.change(3, [fact('a',3,'2026-09-02'), fact('b',3,'2026-10-02'), fact('c',3,'2026-10-03')])
        self.change(4, [fact('a',4,'2026-09-02',0), fact('b',4,'2026-10-02',customer='c2',site='277',gid='2000')])
        self.migrate()
        self.compare(range(1,5), [('2026-09-01','2026-10-01'), ('2026-10-01','2026-11-01'), (None,None)])
        self.store.config['revision_range_index'] = True
        self.assertEqual([r['order_key'] for r in self.store.read_at('2','2026-10-01','2026-11-01')], ['a'])
        with self.store.db() as db:
            self.assertEqual([r['order_key'] for r in index.read(db,3,scope=('266','1327'),start='2026-10-01',end='2026-11-01')], ['c','b'])

    def test_incremental_write_and_stale_rollback_fallback(self):
        self.change(2,[fact('a',2,'2026-10-02')]); self.migrate()
        self.change(3,[fact('a',3,'2026-09-02')])
        self.compare([2,3],[('2026-10-01','2026-11-01')])
        with self.store.db() as db:
            self.assertTrue(index.ready(db,3))
            db.execute('UPDATE user_version_index_state SET target=2')
        self.compare([2,3],[('2026-10-01','2026-11-01')])

    def test_current_bounded_read_uses_date_index_and_never_replays_unindexed_history(self):
        self.change(2,[fact('first',2,'2026-10-01'),fact('outside',2,'2026-10-02'),
                       fact('invalid',2,'2026-10-01',valid=0)])
        self.store.read_only=True
        window=('2026-10-01','2026-10-02')
        before=self.store.path.read_bytes()
        self.assertEqual([r['order_key'] for r in self.store.read_at('2',*window,bounded_only=True)],['first'])
        self.assertEqual(self.store.path.read_bytes(),before)
        self.store.read_only=False
        self.change(3,[fact('first',3,'2026-10-02')])
        self.assertEqual([r['order_key'] for r in self.store.read_at('2',*window)],['first'])
        self.assertEqual([r['order_key'] for r in self.store.read_at('2',*window,bounded_only=True)],['first'])
        self.migrate()
        self.store.config['revision_range_index']=True
        self.store.read_only=True
        self.assertEqual([r['order_key'] for r in self.store.read_at('2',*window,bounded_only=True)],['first'])

    def test_unindexed_bounded_tail_replays_moves_refunds_recovery_and_new_orders(self):
        window=('2026-10-01','2026-10-02')
        self.change(2, [fact('moved_out',2,'2026-10-01'), fact('moved_in',2,'2026-10-02'),
                        fact('void_later',2,'2026-10-01'), fact('recover_later',2,'2026-10-01',valid=0)])
        self.change(3, [fact('moved_out',3,'2026-10-02'), fact('moved_in',3,'2026-10-01'),
                        fact('void_later',3,'2026-10-01',valid=0), fact('recover_later',3,'2026-10-01'),
                        fact('new_order',3,'2026-10-01')])
        self.change(4, [fact('moved_out',4,'2026-10-01'), fact('new_order',4,'2026-10-02')])
        self.store.read_only=True
        actual=self.store.read_at('2',*window,bounded_only=True)
        self.assertEqual(actual,self.store.read_at('2',*window))
        self.assertEqual([row['order_key'] for row in actual],['moved_out','void_later'])

    def test_normal_historical_period_projects_only_in_window_rows_and_undo(self):
        self.change(2, [fact('in',2,'2026-10-01'), fact('out',2,'2026-09-01'),
                        fact('moved',2,'2026-10-01')])
        self.change(3, [fact('moved',3,'2026-10-02')])
        self.change(4, [fact('moved',4,'2026-10-01')])
        window = ('2026-10-01', '2026-10-02')
        reference = [row for row in self.store.read_at('2')
                     if window[0] <= row['paid_at'] < window[1]]
        with patch.object(self.store, 'analytics_row_v1', wraps=self.store.analytics_row_v1) as project:
            self.assertEqual(self.store.read_at('2', *window), reference)
        self.assertNotIn('out', [call.args[0]['order_key'] for call in project.call_args_list])
        self.assertEqual([row['order_key'] for row in reference], ['in', 'moved'])

    def test_unindexed_bounded_tail_refuses_excess_revisions_and_bytes(self):
        self.change(2,[fact('a',2,'2026-10-01')])
        self.change(3,[fact('a',3,'2026-10-02')])
        window=('2026-10-01','2026-10-02')
        for budget in ('BOUNDED_TAIL_REVISIONS','BOUNDED_TAIL_BYTES'):
            with self.subTest(budget=budget), patch('user_store.'+budget,0):
                self.assertIsNone(self.store.read_at('2',*window,bounded_only=True))
                self.assertEqual([row['order_key'] for row in self.store.read_at('2',*window)],['a'])

    def test_unindexed_bounded_tail_refuses_missing_revision(self):
        self.change(2,[fact('a',2,'2026-10-01')])
        self.change(3,[fact('a',3,'2026-10-02')])
        with self.store.db() as db:
            db.execute('DELETE FROM revisions WHERE id=3')
        with self.assertRaisesRegex(StoreUnavailable,'users_revision_history_incomplete'):
            self.store.read_at('2','2026-10-01','2026-10-02',bounded_only=True)

    def test_interrupted_migration_resume_and_source_change_refusal(self):
        self.change(2,[fact('a',2,'2026-10-02')])
        self.change(3,[fact('a',3,'2026-09-02')])
        with self.store.db() as db:
            self.assertFalse(index.build_batch(db,1)['ready'])
            self.assertFalse(index.ready(db,3))
        self.migrate()
        with self.store.db() as db:
            self.assertTrue(index.ready(db,3))
            db.execute("UPDATE meta SET value='4' WHERE key='revision'")
            with self.assertRaisesRegex(ValueError,'source_changed'): index.build_batch(db)

    def test_transaction_rollback_does_not_rewind_authoritative_writes(self):
        self.change(2,[fact('a',2,'2026-10-02')]); self.migrate()
        with self.assertRaises(RuntimeError):
            with self.store.db() as db:
                index.advance(db,2,3,[fact('a',2,'2026-10-02')])
                raise RuntimeError('injected failure')
        with self.store.db() as db:
            self.assertTrue(index.ready(db,2))
            self.assertEqual(db.execute('SELECT count(*) FROM user_order_versions').fetchone()[0],0)

    def test_query_plan_and_vm_work_do_not_scale_with_outside_current_history(self):
        self.change(2,[fact('a',2,'2026-10-02')]); self.migrate()
        def measure():
            with self.store.db() as db:
                steps=[0]
                db.set_progress_handler(lambda: steps.__setitem__(0,steps[0]+1) or 0,1)
                rows=list(index.read(db,2,start='2026-10-01',end='2026-11-01'))
                db.set_progress_handler(None,0)
                plans=[r[3] for sql,args in index.statements(2,start='2026-10-01',end='2026-11-01') for r in db.execute('EXPLAIN QUERY PLAN '+sql,args)]
                return rows,steps[0],plans
        before=measure()
        with self.store.db() as db:
            db.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',
                           (tuple(fact('outside'+str(i),2,'2020-01-01')[k] for k in index.COLUMNS.split(',')) for i in range(20000)))
            db.executemany('INSERT INTO user_order_versions VALUES(?,?,?,?,?,?,?,?,?)',
                           (tuple(fact('outside'+str(i),1,'2019-01-01')[k] for k in index.COLUMNS.split(','))+(2,) for i in range(20000)))
        after=measure()
        self.assertEqual(before[0],after[0]); self.assertLess(after[1],before[1]+100)
        self.assertTrue(all('SEARCH' in plan and 'INDEX' in plan for plan in after[2]),after[2])
        print('SYNTHETIC range benchmark:',dict(outside_current_rows=20000,outside_historical_rows=20000,before_vm_steps=before[1],after_vm_steps=after[1],plans=after[2]))


if __name__=='__main__': unittest.main()
