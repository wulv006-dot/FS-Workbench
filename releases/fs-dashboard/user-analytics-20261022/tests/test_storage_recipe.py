"""Frozen private replay, permissions and bounded memory; invented fixture facts only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
import hashlib,json,shutil,sqlite3,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
BASE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'source'))
from user_contract import canonical,digest,stamp
from user_store import Store
from user_query import Service
from user_lifecycle import analyze

NOW=stamp('2026-10-22T12:00:00+08:00')
def order(n,paid,email='a@example.test',gid='1327',status='1'):
    return dict(id=n,order_no='fixture-'+str(n),paytime=paid,email=email,gid=gid,uid=0,site_id='266',pay_status=status,status='11')

class Recipe(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.config=json.loads((BASE/'source/user_config.json').read_text('utf-8'))
        self.config.update(snapshot_storage='recipe-v1',history_origins={'global:':'2026-01-01','project:1327':'2026-01-01'})
        self.store=Store(Path(self.tmp.name)/'live',b'x'*32,self.config)
        self.allowed=True
        self.service=Service(self.store,lambda u,q,p:self.allowed and (u=='admin' or u=='reader' and not p),clock=lambda:NOW)
        self.addCleanup(lambda:self.service.private_cache_timer.cancel() if self.service.private_cache_timer else None)
        self.load([order(1,'2026-10-01'),order(2,'2026-10-05'),order(3,'2026-10-20',email='b@example.test')])
    def load(self,rows):
        return self.store.replace_window('266','2026-01-01','2026-10-22',rows,NOW.isoformat())
    def query(self,**more):
        return self.service.query(dict(start='2026-10-01',end_exclusive='2026-10-22',state_basis='period_end',**more),'admin')
    def stored(self,ident):
        with self.store.db() as db:
            ref=json.loads(db.execute('SELECT members FROM snapshots WHERE id=?',(ident,)).fetchone()[0])
            text=db.execute('SELECT body FROM snapshot_members WHERE id=?',(ref['member_ref'],)).fetchone()[0]
        return ref,json.loads(text),len(text.encode())
    def expected(self,value,config=None):
        _,rows,jobs=self.store.read(analytics=True)
        _,private=analyze(rows,jobs,value['query'],config or self.config)
        self.store.decorate_private_v1(private,rows,value['query'],config or self.config,True)
        private.pop('events',None)
        return private
    def test_public_stores_recipe_and_private_replays_same_content(self):
        value=self.query();ref,recipe,size=self.stored(value['snapshot_id'])
        self.assertEqual(recipe['contract'],'fs-users-private-replay-v1')
        self.assertNotIn('records',recipe);self.assertNotIn('events',recipe)
        actual=self.store.snapshot(value['snapshot_id'])[2]
        self.assertEqual(actual,self.expected(value))
        self.assertEqual(digest(actual),recipe['private_sha256'])
        self.assertEqual(self.service.members(dict(snapshot_id=value['snapshot_id'],group='purchasers'),'admin')['total'],2)
        self.assertEqual(self.service.export(dict(snapshot_id=value['snapshot_id'],group='purchasers'),'admin')['total'],2)
    def test_refund_payment_time_change_and_new_order_preserve_old_snapshot(self):
        value=self.query();before=self.store.snapshot(value['snapshot_id'])[2]
        self.load([order(1,'2026-10-01',status='2'),order(2,'2026-09-20'),order(3,'2026-10-20',email='b@example.test'),order(4,'2026-10-21',email='c@example.test')])
        self.assertEqual(self.store.snapshot(value['snapshot_id'])[2],before)
        newer=self.query();self.assertNotEqual(newer['data_version'],value['data_version'])
        self.assertNotEqual(self.store.snapshot(newer['snapshot_id'])[2],before)
        with self.store.db() as db:db.execute("UPDATE orders SET paid_at='2026-09-01T00:00:00+08:00' WHERE order_key='admin:266:fixture-2'")
        # Unversioned foreign writes are detected by the frozen checksum.
        with self.assertRaisesRegex(ValueError,'snapshot_replay_integrity'):self.store.snapshot(newer['snapshot_id'])
    def test_ES_flags_effective_history_and_projects_are_frozen(self):
        flags={hashlib.sha256(b'fixture-1').hexdigest():'new',hashlib.sha256(b'fixture-3').hexdigest():'old','unused-hash':'conflict'}
        self.service.customer_type_reader=lambda q:(flags,dict(status='complete',sourceVersion='fixture-v1'))
        value=self.service.query(dict(start='2026-10-01'),'admin')
        before=self.store.snapshot(value['snapshot_id'])[2]
        _,recipe,_=self.stored(value['snapshot_id'])
        self.assertNotIn('unused-hash',recipe['config']['period_customer_types'])
        flags.clear();self.config['projects']['1327']['series']='changed-after-snapshot'
        self.config['history_origins'].clear()
        self.assertEqual(self.store.snapshot(value['snapshot_id'])[2],before)
    def test_legacy_inline_and_member_ref_keep_reading_and_same_ID_reference(self):
        self.config['snapshot_storage']='full';legacy=self.query();ref=self.stored(legacy['snapshot_id'])[0]
        self.config['snapshot_storage']='recipe-v1';self.service.cache.clear();same=self.query()
        self.assertEqual(same,legacy);self.assertEqual(self.stored(same['snapshot_id'])[0],ref)
        private=self.store.snapshot(same['snapshot_id'])[2]
        with self.store.db() as db:db.execute('UPDATE snapshots SET members=? WHERE id=?',(canonical(private),same['snapshot_id']))
        self.assertEqual(self.store.snapshot(same['snapshot_id'])[2],private)
    def test_compatible_reader_survives_writer_policy_rollback(self):
        value=self.query();ref=self.stored(value['snapshot_id'])[0];before=self.store.snapshot(value['snapshot_id'])[2]
        self.config['snapshot_storage']='full';self.service.cache.clear()
        self.assertEqual(self.query(),value);self.assertEqual(self.stored(value['snapshot_id'])[0],ref)
        self.assertEqual(self.store.snapshot(value['snapshot_id'])[2],before)
    def test_large_legacy_inline_is_not_decoded_by_cache_token(self):
        value=self.query();private=self.store.snapshot(value['snapshot_id'])[2]
        self.assertGreater(len(canonical(private)),256)
        with self.store.db() as db:db.execute('UPDATE snapshots SET members=? WHERE id=?',(canonical(private),value['snapshot_id']))
        with patch('user_store.json.loads',side_effect=AssertionError('large legacy double decode')):
            self.assertIsNone(self.store.snapshot_token(value['snapshot_id']))
        self.assertEqual(self.store.snapshot(value['snapshot_id'])[2],private)
    def test_frozen_v1_does_not_depend_on_future_live_analyze(self):
        value=self.query();before=self.store.snapshot(value['snapshot_id'])[2]
        with patch('user_lifecycle.analyze',side_effect=AssertionError('future live version')):
            self.assertEqual(self.store.snapshot(value['snapshot_id'])[2],before)
    def test_corrupt_recipe_or_private_checksum_refuses(self):
        value=self.query();ref,recipe,_=self.stored(value['snapshot_id'])
        recipe['private_sha256']='0'*64
        with self.store.db() as db:db.execute('UPDATE snapshot_members SET body=? WHERE id=?',(canonical(recipe),ref['member_ref']))
        with self.assertRaisesRegex(ValueError,'snapshot_members_integrity'):self.store.snapshot(value['snapshot_id'])
        with self.store.db() as db:
            db.execute('INSERT INTO snapshot_members VALUES(?,?)',(digest(recipe),canonical(recipe)))
            db.execute('UPDATE snapshots SET members=? WHERE id=?',(canonical({'member_ref':digest(recipe),'member_kind':'recipe-v1'}),value['snapshot_id']))
        with self.assertRaisesRegex(ValueError,'snapshot_replay_integrity'):self.store.snapshot(value['snapshot_id'])
    def test_revoke_after_cache_warm_and_denied_request_never_replays(self):
        value=self.query();args=dict(snapshot_id=value['snapshot_id'],group='purchasers')
        with patch.object(self.store,'read_at',wraps=self.store.read_at) as read:
            with self.assertRaises(PermissionError):self.service.members(args,'reader')
            self.assertEqual(read.call_count,0)
            self.service.members(args,'admin');self.assertEqual(read.call_count,1)
            self.allowed=False
            with self.assertRaises(PermissionError):self.service.members(args,'admin')
            self.assertEqual(read.call_count,1)
    def test_corruption_is_not_hidden_by_warm_private_cache(self):
        value=self.query();args=dict(snapshot_id=value['snapshot_id'],group='purchasers')
        self.service.members(args,'admin')
        ref,recipe,_=self.stored(value['snapshot_id']);recipe['private_sha256']='0'*64
        with self.store.db() as db:db.execute('UPDATE snapshot_members SET body=? WHERE id=?',(canonical(recipe),ref['member_ref']))
        with self.assertRaisesRegex(ValueError,'snapshot_members_integrity'):self.service.members(args,'admin')
    def test_returned_member_objects_cannot_mutate_cached_frozen_records(self):
        value=self.query();args=dict(snapshot_id=value['snapshot_id'],group='purchasers')
        original=self.service.members(args,'admin')
        mutated=self.service.members(args,'admin');mutated['rows'][0]['project_ids'].append('99999')
        self.assertEqual(self.service.members(args,'admin'),original)
        exported=self.service.export(args,'admin');exported['rows'][0]['stage']='invalid'
        self.assertEqual(self.service.members(args,'admin'),original)
    def test_single_flight_and_short_one_entry_memory_cache(self):
        value=self.query();args=dict(snapshot_id=value['snapshot_id'],group='purchasers');original=self.store.snapshot
        def slow(ident):time.sleep(.03);return original(ident)
        with patch.object(self.store,'snapshot',side_effect=slow) as replay:
            with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(lambda _:self.service.members(args,'admin'),range(4)))
            self.assertEqual(replay.call_count,1);self.assertTrue(all(r==rows[0] for r in rows))
            with patch('user_query.monotonic',return_value=self.service.private_cache[1]+1):self.service.members(args,'admin')
            self.assertEqual(replay.call_count,2)
    def test_restore_copy_replays_old_recipe_after_refund(self):
        value=self.query();expected=self.store.snapshot(value['snapshot_id'])[2]
        self.load([order(1,'2026-10-01',status='2'),order(2,'2026-10-05'),order(3,'2026-10-20',email='b@example.test')])
        root=Path(self.tmp.name)/'restored';root.mkdir(mode=0o700)
        self.store.backup(root/'customers.sqlite3')
        before=(root/'customers.sqlite3').read_bytes();names={p.name for p in root.iterdir()}
        restored=Store(root,b'x'*32,deepcopy(self.config),read_only=True)
        self.assertEqual(restored.snapshot(value['snapshot_id'])[2],expected)
        with self.assertRaises(sqlite3.OperationalError):
            with restored.db() as db:db.execute("UPDATE meta SET value='0' WHERE key='revision'")
        self.assertEqual((root/'customers.sqlite3').read_bytes(),before)
        self.assertEqual({p.name for p in root.iterdir()},names)
    def test_idle_expiry_and_old_callback_cannot_clear_new_snapshot(self):
        first=self.query();self.service.members(dict(snapshot_id=first['snapshot_id'],group='purchasers'),'admin')
        deadline=self.service.private_cache[1]
        second=self.query(scope='project',scope_id='1327')
        self.service.members(dict(snapshot_id=second['snapshot_id'],group='purchasers'),'admin')
        with patch('user_query.monotonic',return_value=deadline+500):self.service.expire_private_cache(deadline)
        self.assertEqual(self.service.private_cache[0],second['snapshot_id'])
        next_deadline=self.service.private_cache[1]
        self.service.private_cache_timer.cancel()
        with patch('user_query.monotonic',return_value=next_deadline+1):self.service.expire_private_cache(next_deadline)
        self.assertIsNone(self.service.private_cache)
        self.assertIsNone(self.service.private_cache_timer)
    def test_different_snapshot_concurrency_keeps_one_cache_entry(self):
        first=self.query();second=self.query(scope='project',scope_id='1327')
        original=self.store.snapshot;active=[0];maximum=[0];lock=threading.Lock()
        def slow(ident):
            with lock:active[0]+=1;maximum[0]=max(maximum[0],active[0])
            try:time.sleep(.02);return original(ident)
            finally:
                with lock:active[0]-=1
        with patch.object(self.store,'snapshot',side_effect=slow):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(lambda ident:self.service.members(dict(snapshot_id=ident,group='purchasers'),'admin'),[first['snapshot_id'],second['snapshot_id']]))
        self.assertEqual(maximum[0],1)
        self.assertEqual([r['snapshot_id'] for r in results],[first['snapshot_id'],second['snapshot_id']])
        self.assertIn(self.service.private_cache[0],[first['snapshot_id'],second['snapshot_id']])
    def test_fixture_storage_reduction_not_a_production_percent_claim(self):
        self.load([order(i,'2026-10-01',email='fixture-%s@example.test'%i) for i in range(1,501)])
        value=self.query();_,recipe,size=self.stored(value['snapshot_id'])
        private=self.store.snapshot(value['snapshot_id'])[2]
        self.assertLess(size,len(canonical(private).encode())//10)
        self.assertLess(size,20000)
        print('fixture_storage_bytes',json.dumps(dict(recipe=size,private=len(canonical(private).encode()),customers=500)))

if __name__=='__main__':unittest.main()
