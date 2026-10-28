"""Same existing queue, bounded original-ID recovery of proven pre-container lock busy."""
import ast
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import hashlib,json,os
from pathlib import Path
from types import SimpleNamespace
import tempfile,unittest,uuid
from unittest.mock import Mock,patch

SOURCE=Path(__file__).resolve().parents[1]/'source'
NOW=datetime(2026,10,29,3,tzinfo=timezone.utc)
class Clock(datetime):
    @classmethod
    def now(cls,tz=None):return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

class PlayerWriterQueue(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        for name in ('queue','jobs','player-sync','requests','executions','state'):(self.root/name).mkdir()
        (self.root/'state/price-writer.lock').touch();self.held=False
        @contextmanager
        def mutex():
            self.assertFalse(self.held);self.held=True
            try:yield
            finally:self.held=False
        host_os=SimpleNamespace(**{name:getattr(os,name) for name in ('open','fdopen','fsync','fstat','close','O_RDWR','O_WRONLY','O_CREAT','O_EXCL')},O_NOFOLLOW=getattr(os,'O_NOFOLLOW',0),chown=lambda *args:None)
        self.ns=dict(ROOT=self.root,JOBS=self.root/'jobs',QUEUE=self.root/'queue',datetime=Clock,timezone=timezone,
            json=json,hashlib=hashlib,os=host_os,uuid=uuid,queue_mutation=mutex,sync_directory=lambda *args:None,
            utc=lambda value:datetime.fromisoformat(value.replace('Z','+00:00')),load_player_sync_policy=lambda:dict(enabled=True,revision=10))
        def save(job):(self.root/'jobs'/(job['job_id']+'.json')).write_text(json.dumps(job,sort_keys=True))
        self.ns['save_job']=save
        worker=ast.parse((SOURCE/'fc27_cloud_worker.py').read_text())
        names={'_player_writer_available','_player_queue_expired','_player_not_sent_busy','_player_busy_retry_matches','_retry_player_lock_busy_locked','_retry_player_followups_locked','claim_next_job','handle'}
        functions=[node for node in worker.body if isinstance(node,ast.FunctionDef) and node.name in names]
        tick=ast.parse((SOURCE/'automation_tick.py').read_text());functions.append(next(n for n in tick.body if isinstance(n,ast.FunctionDef) and n.name=='exclusive_json'))
        exec(compile(ast.Module(body=functions,type_ignores=[]),'actual_worker_queue_functions','exec'),self.ns)
        self.available=Mock(return_value=True);self.ns['_player_writer_available']=self.available
        self.coin=str(uuid.uuid4());self.ident=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+self.coin))
        self.job=dict(job_id=self.ident,kind='player_sync',actor='system-automation',status='queued',created_at=NOW.isoformat(),request=dict(coin_execution_id=self.coin,config_revision=10))
        (self.root/'executions'/(self.coin+'.json')).write_text(json.dumps(dict(execution_id=self.coin,status='CONFIRMED')))

    def queue(self,job=None):
        job=deepcopy(job or self.job);path=self.root/'queue'/(job['job_id']+'.json');path.write_text(json.dumps(job));return path

    def failed_busy(self,job=None):
        job=deepcopy(job or self.job);job.update(status='failed',error='player_sync_not_confirmed',error_detail='busy',sync_exit_code=75,sync_result=dict(status='busy'),completed_at=NOW.isoformat())
        self.ns['save_job'](job);return job

    def retry(self):self.ns['_retry_player_followups_locked']()
    def claim(self):return self.ns['claim_next_job']()

    def test_busy_player_remains_byte_identical_unclaimed_and_other_work_can_run(self):
        path=self.queue();raw=path.read_bytes();other=dict(job_id=str(uuid.uuid4()),kind='collect',status='queued',created_at=NOW.isoformat());other_path=self.queue(other)
        os.utime(path,(1,1));os.utime(other_path,(2,2));self.available.return_value=False
        claimed=self.claim();self.assertEqual(claimed['job_id'],other['job_id']);self.assertEqual(path.read_bytes(),raw)
        self.assertFalse((self.root/'jobs'/(self.ident+'.json')).exists());self.assertIsNone(self.claim())
        self.assertEqual(path.read_bytes(),raw)

    def test_writer_release_claims_same_original_job_once(self):
        self.queue();self.available.return_value=False;self.assertIsNone(self.claim())
        self.available.return_value=True;claimed=self.claim();self.assertEqual(claimed['job_id'],self.ident)
        self.assertEqual(claimed['status'],'running');self.assertFalse(list((self.root/'queue').glob('*.json')))
        self.queue();self.assertRaisesRegex(ValueError,'queue_claim_needs_reconcile',self.claim)

    def test_original_queue_envelope_expires_prewrite_and_yields_to_other_work(self):
        job=deepcopy(self.job);job['created_at']=(NOW-timedelta(seconds=3701)).isoformat();self.queue(job)
        self.assertIsNone(self.claim());saved=json.loads((self.root/'jobs'/(self.ident+'.json')).read_text())
        self.assertEqual(saved['status'],'failed');self.assertEqual(saved['error_detail'],'player_writer_queue_timeout')
        self.assertFalse((self.root/'player-sync'/(self.ident+'.json')).exists());self.available.assert_not_called();self.retry()
        self.assertFalse(list((self.root/'queue').glob('*.json')))

    def test_shell_race_is_one_same_id_retry_with_failed_history_preserved(self):
        self.queue();job=self.claim();dispatch=Mock(side_effect=[(75,dict(status='busy')),(0,dict(status='confirmed',category_response='accepted'))]);self.ns['run_writer_request']=dispatch
        with self.assertRaisesRegex(ValueError,'player_sync_not_confirmed'):self.ns['handle'](job)
        self.assertEqual(job['sync_exit_code'],75);job.update(status='failed',error='player_sync_not_confirmed',completed_at=NOW.isoformat());self.ns['save_job'](job)
        old=(self.root/'jobs'/(self.ident+'.json')).read_bytes();self.retry();self.retry()
        queued=json.loads((self.root/'queue'/(self.ident+'.json')).read_text())
        self.assertEqual(queued['writer_lock_retry'],dict(attempt=1,failed_job_sha256=hashlib.sha256(old).hexdigest()))
        self.assertEqual(queued['writer_lock_failures'][0]['previous_job'],job)
        self.available.return_value=False;self.assertIsNone(self.claim());self.available.return_value=True
        resumed=self.claim();self.assertEqual(resumed['request'],job['request']);result=self.ns['handle'](resumed)
        self.assertEqual(result['status'],'confirmed');self.assertEqual(dispatch.call_count,2)
        self.assertTrue(all(call.args[0]['job_id']==self.ident for call in dispatch.call_args_list))

    def test_second_busy_race_is_exhausted_without_another_queue_entry(self):
        first=self.failed_busy();self.retry();resumed=self.claim();second=self.failed_busy(resumed)
        self.retry();self.retry();self.assertFalse(list((self.root/'queue').glob('*.json')))
        saved=json.loads((self.root/'jobs'/(self.ident+'.json')).read_text());self.assertEqual(saved['error_detail'],'player_writer_lock_retry_exhausted')
        self.assertEqual(saved['sync_result'],dict(status='busy'));self.assertEqual(saved['writer_lock_failures'][0]['previous_job'],first)

    def test_UNKNOWN_or_existing_category_ledger_never_gets_automatic_retry(self):
        for field,value in [('sync_exit_code',2),('sync_exit_code',None),('sync_exit_code',75.0),('sync_result',dict(status='needs_reconcile',post_response=dict(http_status=502))),('post_response',dict(http_status=502)),('result',dict(status='confirmed'))]:
            with self.subTest(field=field,value=value):
                job=self.failed_busy();job[field]=value;self.ns['save_job'](job);self.retry();self.assertFalse(list((self.root/'queue').glob('*.json')))
        job=self.failed_busy();(self.root/'player-sync'/(self.ident+'.json')).write_text('{}');self.retry()
        self.assertFalse(list((self.root/'queue').glob('*.json')));self.assertEqual(json.loads((self.root/'jobs'/(self.ident+'.json')).read_text()),job)

    def test_same_id_retry_rejects_failed_record_or_request_drift(self):
        old=self.failed_busy();self.retry();changed=deepcopy(old);changed['error_detail']='UNKNOWN';self.ns['save_job'](changed)
        with self.assertRaisesRegex(ValueError,'queue_claim_needs_reconcile'):self.claim()
        self.ns['save_job'](old);path=self.root/'queue'/(self.ident+'.json');queued=json.loads(path.read_text());queued['request']['config_revision']=11;path.write_text(json.dumps(queued))
        with self.assertRaisesRegex(ValueError,'queue_claim_needs_reconcile'):self.claim()

    def test_queue_metadata_write_failure_can_recover_without_dispatch(self):
        old=self.failed_busy();real=self.ns['exclusive_json'];self.ns['exclusive_json']=Mock(side_effect=OSError('temp IO'))
        self.retry();self.assertFalse(list((self.root/'queue').glob('*.json')));self.assertEqual(json.loads((self.root/'jobs'/(self.ident+'.json')).read_text()),old)
        self.ns['exclusive_json']=real;self.retry();self.assertEqual(len(list((self.root/'queue').glob('*.json'))),1)

    def test_running_saved_before_queue_unlink_failure_remains_uncertain_and_is_not_reclaimed(self):
        self.failed_busy();self.retry();real=Path.unlink;queue_path=self.root/'queue'/(self.ident+'.json')
        def fail(path,*args,**kwargs):
            if path==queue_path:raise OSError('claim crash after running persistence')
            return real(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):
            with self.assertRaises(OSError):self.claim()
        self.assertEqual(json.loads((self.root/'jobs'/(self.ident+'.json')).read_text())['status'],'running')
        with self.assertRaisesRegex(ValueError,'queue_claim_needs_reconcile'):self.claim()

    def test_expired_failed_busy_is_reported_not_queued(self):
        job=self.failed_busy();job['created_at']=(NOW-timedelta(seconds=3701)).isoformat();self.ns['save_job'](job);self.retry()
        saved=json.loads((self.root/'jobs'/(self.ident+'.json')).read_text());self.assertEqual(saved['error_detail'],'player_writer_queue_timeout');self.assertFalse(list((self.root/'queue').glob('*.json')))

    def test_existing_retry_crossing_deadline_keeps_failed_cas_until_claim_expires_and_yields(self):
        job=deepcopy(self.job);job['created_at']=(NOW-timedelta(seconds=3699)).isoformat();self.failed_busy(job)
        failed=self.root/'jobs'/(self.ident+'.json');old=failed.read_bytes();self.retry()
        queued=self.root/'queue'/(self.ident+'.json');pending=queued.read_bytes();os.utime(queued,(1,1))
        self.available.return_value=False;self.assertIsNone(self.claim())
        other=dict(job_id=str(uuid.uuid4()),kind='collect',status='queued',created_at=NOW.isoformat())
        other_path=self.queue(other);os.utime(other_path,(2,2));self.available.reset_mock()
        with patch.object(Clock,'now',return_value=NOW+timedelta(seconds=1)):
            self.retry()
            self.assertEqual(failed.read_bytes(),old);self.assertEqual(queued.read_bytes(),pending)
            self.assertEqual(self.claim()['job_id'],other['job_id'])
        saved=json.loads(failed.read_text());self.assertEqual(saved['error_detail'],'player_writer_queue_timeout')
        self.assertEqual(saved['writer_lock_failures'][0]['previous_job'],json.loads(old))
        self.assertFalse(queued.exists());self.available.assert_not_called()
        self.assertFalse((self.root/'player-sync'/(self.ident+'.json')).exists())

    def test_first_bootstrap_creates_only_original_lock_once_and_keeps_its_inode(self):
        source=ast.parse((SOURCE/'fc27_cloud_worker.py').read_text());node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_player_writer_available')
        path=self.root/'state/price-writer.lock';path.unlink()
        scope=dict(ROOT=self.root,os=self.ns['os']);exec(compile(ast.Module(body=[node],type_ignores=[]),'bootstrap_writer_lock','exec'),scope)
        import sys
        fcntl=SimpleNamespace(LOCK_EX=2,LOCK_NB=4,flock=Mock())
        with patch.dict(sys.modules,fcntl=fcntl):
            self.assertTrue(scope['_player_writer_available']());created=path.stat()
            self.assertTrue(scope['_player_writer_available']());again=path.stat()
        self.assertEqual((created.st_dev,created.st_ino),(again.st_dev,again.st_ino))
        self.assertEqual([p.name for p in (self.root/'state').iterdir()],['price-writer.lock'])
        self.assertEqual(fcntl.flock.call_count,2)
        if os.name=='posix':self.assertEqual(created.st_mode&0o777,0o600)

    @unittest.skipUnless(os.name=='posix','real Linux existing writer file lock')
    def test_real_existing_writer_lock_busy_release_and_missing_inode(self):
        import fcntl
        source=ast.parse((SOURCE/'fc27_cloud_worker.py').read_text());node=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='_player_writer_available')
        scope=dict(ROOT=self.root,os=os);exec(compile(ast.Module(body=[node],type_ignores=[]),'real_writer_lock','exec'),scope)
        self.assertTrue(scope['_player_writer_available']())
        with (self.root/'state/price-writer.lock').open('r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);self.assertFalse(scope['_player_writer_available']())
        self.assertTrue(scope['_player_writer_available']());(self.root/'state/price-writer.lock').unlink()
        self.assertTrue(scope['_player_writer_available']())
        fresh=(self.root/'state/price-writer.lock').stat();self.assertEqual(fresh.st_mode&0o777,0o600)
        self.assertTrue(scope['_player_writer_available']());self.assertEqual((self.root/'state/price-writer.lock').stat().st_ino,fresh.st_ino)


if __name__=='__main__':unittest.main()
