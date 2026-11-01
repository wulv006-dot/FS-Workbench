from contextlib import closing
from threading import RLock
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'source'),str(ROOT/'releases/fs-dashboard/daily-archive-20261021/source')]
import test_range_jobs as fixtures
from daily_archive import Archive
from query_checkpoint import Checkpoints
from query_artifacts import Artifacts
from range_jobs import Engine
from date_policy import PolicyError


class Durable(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.Jobs();fixture.setUp();self.fixture=fixture
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.archive=Archive(Path(self.tmp.name)/'archive');self.store=Checkpoints(self.archive);self.store.initialize()
        fixture.engine.checkpoint=self.store.save

    def restart(self,resume=True):
        f=self.fixture;jobs,subs=self.store.load()
        engine=Engine(jobs=jobs,subscriptions=subs,cache={},authorize=f.engine.authorize,secret=b'x'*32,lock=RLock(),checkpoint=self.store.save)
        engine.recover(lambda q,w,c:resume and w=='fixed-fixture' and c=='fixture-source-v1')
        return engine

    def test_reserved_io_crash_resume_keeps_scope_watermark_and_budget(self):
        f=self.fixture;handle=f.submit();key=f.key(handle)
        def crash(request):raise SystemExit('injected process death')
        with self.assertRaises(SystemExit):f.engine.step(key,crash)
        engine=self.restart();requests=[]
        engine.step(key,lambda request:requests.append(request) or f.reply())
        self.assertEqual(engine.status('a',handle)['requests'],2)
        self.assertEqual((requests[0]['site_id'],requests[0]['watermark']),('266','fixed-fixture'))
        self.assertTrue(engine.status('a',handle)['complete'])

    def test_revoke_cancel_and_unstable_resume_do_not_call_source(self):
        f=self.fixture;handle=f.submit();key=f.key(handle)
        f.grants.pop('a');engine=self.restart()
        self.assertEqual(engine.jobs[key]['status'],'cancelled')
        f.grants['a']=dict(scope_hash='trusted-scope',permission_epoch='1',policy_version='fixture')
        handle=f.submit();engine=self.restart(False)
        self.assertEqual(engine.jobs[key]['error'],'source_unstable')

    def test_page_checkpoint_appends_only_new_rows_and_resumes_source_cursor(self):
        f=self.fixture;handle=f.submit();key=f.key(handle)
        f.engine.step(key,lambda request:dict(f.reply(),complete=False,next_cursor='page2'))
        engine=self.restart();requests=[]
        engine.step(key,lambda request:requests.append(request) or f.reply([dict(order_id='o2',amount='2')]))
        self.assertEqual(requests[0]['cursor'],'page2')
        self.assertEqual(len(engine.page('a',handle)['data']),2)
        with closing(self.archive.database()) as db:self.assertEqual(db.execute('SELECT count(*) FROM range_query_rows').fetchone()[0],2)
        self.store.save(key,engine.jobs[key],engine.subscriptions)
        with closing(self.archive.database()) as db:self.assertEqual(db.execute('SELECT count(*) FROM range_query_rows').fetchone()[0],2)

    def test_artifact_stream_reauthorizes_and_pin_blocks_expiry_candidate(self):
        f=self.fixture;handle=f.submit();f.engine.step(f.key(handle),lambda request:f.reply())
        clock=[0];artifacts=Artifacts(self.archive,clock=lambda:clock[0]);artifacts.initialize()
        receipt=artifacts.create(f.engine,'a',handle,ttl=1)
        with artifacts.download(f.engine,'a',handle,receipt['artifact_id']) as chunks:
            self.assertIn(b'o1',next(chunks));clock[0]=2
            self.assertEqual(artifacts.expired_candidates(),[])
        self.assertEqual(artifacts.expired_candidates()[0]['id'],receipt['artifact_id'])
        with self.assertRaises(StopIteration):next(chunks)
        with self.assertRaises(PolicyError):
            with artifacts.download(f.engine,'a',handle,receipt['artifact_id']):self.fail('expired download')

    def test_cancelled_or_revoked_artifact_cannot_continue_download(self):
        f=self.fixture;handle=f.submit();f.engine.step(f.key(handle),lambda request:f.reply())
        artifacts=Artifacts(self.archive);artifacts.initialize();receipt=artifacts.create(f.engine,'a',handle)
        with artifacts.download(f.engine,'a',handle,receipt['artifact_id']) as chunks:
            f.engine.cancel('a',handle)
            with self.assertRaises(PolicyError):next(chunks)
        with closing(self.archive.database()) as db:self.assertEqual(db.execute('SELECT pins FROM range_query_artifacts').fetchone()[0],0)

    def test_failed_checkpoint_reservation_prevents_source_io_and_success(self):
        f=self.fixture;handle=f.submit();key=f.key(handle)
        def fail(*args):raise OSError('injected disk full')
        f.engine.checkpoint=fail
        with self.assertRaisesRegex(PolicyError,'checkpoint_unavailable'):
            f.engine.step(key,lambda request:self.fail('source called after failed reservation'))
        self.assertEqual(f.engine.status('a',handle)['status'],'failed')
        self.assertFalse(f.cache)

if __name__=='__main__':unittest.main()
