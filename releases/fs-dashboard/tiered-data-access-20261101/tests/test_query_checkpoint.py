from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import RLock,Event
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
        f.engine=engine;f.jobs=engine.jobs;f.subs=engine.subscriptions
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

    def test_old_generation_late_success_and_failure_cannot_overwrite_new_generation(self):
        for outcome in ('success','failure'):
            for final in ('queued','complete','cancelled'):
                with self.subTest(outcome=outcome,final=final):
                    f=fixtures.Jobs();f.setUp()
                    store=Checkpoints(Archive(Path(self.tmp.name)/(outcome+final)));store.initialize();f.engine.checkpoint=store.save
                    first=f.submit();key=f.key(first);entered,release=Event(),Event()
                    def adapter(request):
                        entered.set();self.assertTrue(release.wait(5))
                        if outcome=='failure':raise RuntimeError('late failure')
                        return f.reply()
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future=pool.submit(f.engine.step,key,adapter)
                        self.assertTrue(entered.wait(5));old=deepcopy(f.jobs[key])
                        f.engine.cancel('a',first);second=f.submit();generation=f.jobs[key]['generation']
                        if final=='complete':f.engine.step(key,lambda r:f.reply())
                        if final=='cancelled':f.engine.cancel('a',second)
                        release.set();future.result()
                    jobs,subs=store.load()
                    self.assertEqual(jobs[key]['generation'],generation);self.assertEqual(jobs[key]['status'],final)
                    with self.assertRaisesRegex(ValueError,'generation_conflict'):store.save(key,old,{first:f.subs[first]})
                    self.assertEqual(store.load()[0][key]['generation'],generation)
                    recovered=Engine(jobs=jobs,subscriptions=subs,cache={},authorize=f.engine.authorize,secret=b'x'*32,lock=RLock(),checkpoint=store.save)
                    recovered.recover(lambda *a:True)
                    self.assertEqual(recovered.jobs[key]['generation'],generation)
                    if final=='cancelled':self.assertEqual(recovered.jobs[key]['status'],'cancelled')

    def test_same_generation_stale_revision_is_rejected_and_resume_requires_true(self):
        f=self.fixture;handle=f.submit();key=f.key(handle);old=deepcopy(f.jobs[key])
        f.engine.step(key,lambda r:dict(f.reply(),complete=False,next_cursor='next'))
        with self.assertRaisesRegex(ValueError,'generation_conflict'):self.store.save(key,old,{handle:f.subs[handle]})
        engine=self.restart();engine.jobs[key]['status']='queued'
        engine.recover(lambda *a:{'allowed':False})
        self.assertEqual(engine.jobs[key]['error'],'source_unstable')

    def test_abandoned_pin_detection_keeps_live_unknown_referenced_and_legacy_pins(self):
        f=self.fixture;handle=f.submit();f.engine.step(f.key(handle),lambda r:f.reply())
        now=[0];owner=dict(machine_id='fixture-machine',boot_id='fixture-boot',pid=123,start_token='start1')
        artifacts=Artifacts(self.archive,clock=lambda:now[0],lease_owner=lambda:owner);artifacts.initialize()
        receipt=artifacts.create(f.engine,'a',handle,ttl=1);ident=receipt['artifact_id']
        with artifacts.download(f.engine,'a',handle,ident) as chunks:
            now[0]=2
            self.assertEqual(artifacts.abandoned_pin_candidates(liveness=lambda o:True,reference_status=lambda i:'unreferenced'),[])
            self.assertEqual(artifacts.abandoned_pin_candidates(liveness=lambda o:None,reference_status=lambda i:'unreferenced'),[])
            self.assertEqual(artifacts.abandoned_pin_candidates(liveness=lambda o:False,reference_status=lambda i:'referenced'),[])
            candidates=artifacts.abandoned_pin_candidates(liveness=lambda o:False,reference_status=lambda i:'unreferenced')
            self.assertEqual(candidates[0]['artifact_id'],ident)
            with closing(self.archive.database()) as db:self.assertEqual(db.execute('SELECT pins FROM range_query_artifacts').fetchone()[0],1)
        self.assertEqual(artifacts.expired_candidates(reference_status=lambda i:'referenced'),[])
        with closing(self.archive.database(True)) as db,db:db.execute('UPDATE range_query_artifacts SET pins=1')
        self.assertEqual(artifacts.abandoned_pin_candidates(liveness=lambda o:False,reference_status=lambda i:'unreferenced'),[])

if __name__=='__main__':unittest.main()
