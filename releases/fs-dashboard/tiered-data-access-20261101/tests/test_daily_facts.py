from contextlib import closing
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source'),str(ROOT/'releases/fs-dashboard/daily-archive-20261021/source')]
from daily_archive import Archive
from daily_facts import Facts,totals,ratio


class Daily(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.archive=Archive(Path(self.tmp.name)/'archive')
        self.facts=Facts(self.archive,{'fixture':dict(metric_contract='fixture-v1',currencies=['CNY','USD'],timezone='Asia/Shanghai',date_semantics='shipping_transaction_at',additive_metrics=['sales','cost'])})
        self.facts.initialize()

    def put(self,date='2026-10-01',sequence=1,**kw):
        return self.facts.publish('fixture','trusted-scope',date,'CNY',sequence,kw.pop('metrics',dict(sales='10',cost='7')),source_complete=kw.pop('source_complete',True),source_watermark='fixture-'+str(sequence),**kw)

    def read(self):return self.facts.read('fixture','trusted-scope','2026-10-01','2026-10-03','CNY')

    def test_reuses_original_catalog_and_repeat_is_idempotent(self):
        first=self.put();self.assertEqual(first,self.put())
        with closing(self.archive.database()) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM daily_facts').fetchone()[0],1)
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='versions'").fetchone())
        self.assertEqual(sorted(p.name for p in self.archive.root.iterdir()),['catalog.sqlite3'])

    def test_failed_source_keeps_old_current_and_does_not_publish_zero(self):
        self.put();before=self.read()
        with self.assertRaisesRegex(ValueError,'incomplete'):self.put(sequence=2,source_complete=False,metrics=dict(sales='0',cost='0'))
        self.assertEqual(self.read(),before)

    def test_date_move_marks_both_days_deduplicates_and_reopens_sealed(self):
        self.put(status='sealed');self.put('2026-10-02',status='sealed')
        args=('fixture','trusted-scope','event-1','2026-10-01','2026-10-02','paid_date_correction')
        self.assertTrue(self.facts.mark_dirty(*args,currency='CNY'));self.assertFalse(self.facts.mark_dirty(*args,currency='CNY'))
        self.assertEqual(self.read()['dirty'],['2026-10-01','2026-10-02'])
        self.assertFalse(self.read()['complete'])
        with self.assertRaisesRegex(ValueError,'dirty_requires_new_revision'):self.put(status='sealed')
        self.put(sequence=2,metrics=dict(sales='0',cost='0'));self.put('2026-10-02',sequence=2,metrics=dict(sales='20',cost='14'))
        self.assertTrue(self.read()['complete']);self.assertEqual(totals(self.read()),dict(sales='20',cost='14'))

    def test_source_revision_and_event_conflicts_fail_closed(self):
        self.put(sequence=2)
        with self.assertRaisesRegex(ValueError,'revision_conflict'):self.put(sequence=1)
        with self.assertRaisesRegex(ValueError,'revision_conflict'):self.put(sequence=2,metrics=dict(sales='11',cost='7'))
        self.facts.mark_dirty('fixture','trusted-scope','same','2026-10-01',None,'refund',currency='CNY')
        with self.assertRaisesRegex(ValueError,'event_conflict'):self.facts.mark_dirty('fixture','trusted-scope','same','2026-10-02',None,'refund',currency='CNY')

    def test_scope_currency_gaps_and_metric_semantics(self):
        self.put()
        with self.assertRaisesRegex(ValueError,'coverage'):totals(self.read())
        self.assertEqual(self.facts.read('fixture','other-scope','2026-10-01','2026-10-02','CNY')['rows'],[])
        self.assertEqual(self.facts.read('fixture','trusted-scope','2026-10-01','2026-10-02','USD')['rows'],[])
        with self.assertRaisesRegex(ValueError,'metric_contract'):self.put(metrics=dict(distinct_customers=10))
        self.assertIsNone(ratio('10','0'));self.assertEqual(ratio('3','10'),'0.3')

if __name__=='__main__':unittest.main()
