"""Real SQLite cross-version grant/source binding compatibility."""
from pathlib import Path
import importlib.util,sqlite3,unittest,tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

HERE=Path(__file__).resolve().parent
current=load('current_grant_compat',HERE.parent/'source/pricing_operations.py')
original=load('original_grant_7f',HERE/'fixtures/pricing_grant_7f.py')
SOURCE='human_authorized_fc_pricing_v3_daily_effect_review_readonly'
RUN='00000000-0000-4000-8000-000000000001'
QUOTE='00000000-0000-4000-8000-000000000002'

class GrantCompatibility(unittest.TestCase):
    def test_original_installed_writer_remains_usable_after_new_grant_storage(self):
        with sqlite3.connect(':memory:') as db:
            current.grant(db,'alice','a'*32,RUN,'daily_review','2099-01-01T00:00:00+00:00',SOURCE,source_quote_run=QUOTE,source_quote_sha256='e'*64)
            failure=None
            try:original.grant(db,'alice','b'*32,RUN,'daily_review','2099-01-01T00:00:00+00:00',SOURCE)
            except sqlite3.OperationalError as error:failure=str(error)
            self.assertIsNone(failure,'Rollback restores this original writer, so its real INSERT must still work')
            self.assertEqual(len(list(db.execute('PRAGMA table_info(pricing_grants)'))),7)
            self.assertEqual(db.execute('SELECT count(*) FROM pricing_grants').fetchone()[0],2)
            self.assertEqual(current.quote_reference(db,'a'*32),(QUOTE,'e'*64))
            self.assertEqual(current.quote_reference(db,'b'*32),(None,None))

    def test_original_missing_reference_cannot_be_upgraded(self):
        with closing(sqlite3.connect(':memory:')) as db:
            original.grant(db,'alice','c'*32,RUN,'daily_review','2099-01-01T00:00:00+00:00',SOURCE)
            current.tables(db)
            with self.assertRaisesRegex(ValueError,'pricing_grant_conflict'):
                current.grant(db,'alice','c'*32,RUN,'daily_review','2099-01-01T00:00:00+00:00',SOURCE,source_quote_run=QUOTE,source_quote_sha256='e'*64)
            self.assertEqual(current.quote_reference(db,'c'*32),(None,None))
            self.assertEqual(db.execute('SELECT count(*) FROM pricing_grants').fetchone()[0],1)

    def test_concurrent_references_bind_one_immutable_pair(self):
        for hashes in (('a','b'),('a','a')):
            with self.subTest(hashes=hashes),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'tasks.sqlite3'
                with closing(sqlite3.connect(path,isolation_level=None)) as db:current.tables(db)
                def bind(letter):
                    with closing(sqlite3.connect(path,timeout=5,isolation_level=None)) as db:
                        try:current.grant(db,'alice','d'*32,RUN,'daily_review','2099-01-01T00:00:00+00:00',SOURCE,source_quote_run=QUOTE,source_quote_sha256=letter*64)
                        except ValueError as error:
                            if str(error)!='pricing_grant_conflict':raise
                            return 'conflict'
                        return 'granted'
                with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(bind,hashes))
                self.assertEqual(results.count('granted'),2 if hashes[0]==hashes[1] else 1)
                with closing(sqlite3.connect(path)) as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM pricing_grants').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT count(*) FROM pricing_grant_sources').fetchone()[0],1)
                    self.assertIn(current.quote_reference(db,'d'*32),( (QUOTE,x*64) for x in hashes ))

    def test_reference_write_failure_is_atomic_and_preserves_callers_transaction(self):
        for outer in (False,True):
            with self.subTest(outer=outer),closing(sqlite3.connect(':memory:',isolation_level=None)) as db:
                current.tables(db);db.execute('CREATE TABLE caller_data(value TEXT)')
                if outer:
                    db.execute('BEGIN IMMEDIATE');db.execute("INSERT INTO caller_data VALUES('keep caller state')")
                class FailingReference:
                    @property
                    def in_transaction(self):return db.in_transaction
                    def execute(self,sql,*args):
                        if sql.startswith('INSERT OR IGNORE INTO pricing_grant_sources'):
                            raise sqlite3.OperationalError('disk full')
                        return db.execute(sql,*args)
                    def commit(self):return db.commit()
                    def rollback(self):return db.rollback()
                with self.assertRaisesRegex(sqlite3.OperationalError,'disk full'):
                    current.grant(FailingReference(),'alice','f'*32,RUN,'daily_review','2099-01-01T00:00:00+00:00',SOURCE,source_quote_run=QUOTE,source_quote_sha256='e'*64)
                self.assertEqual(db.execute('SELECT count(*) FROM pricing_grants').fetchone()[0],0)
                self.assertEqual(db.execute('SELECT count(*) FROM pricing_grant_sources').fetchone()[0],0)
                self.assertEqual(db.in_transaction,outer)
                if outer:
                    self.assertEqual(db.execute('SELECT value FROM caller_data').fetchone()[0],'keep caller state')
                    db.commit()

if __name__=='__main__':unittest.main()
