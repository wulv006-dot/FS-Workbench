"""Portable frozen projection tests; real POSIX Store lifecycle is in Linux suite."""
from contextlib import closing
from copy import deepcopy
import hashlib,os,sqlite3,sys,tempfile,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'source'))
from user_store import Store
from user_query import Service
from user_contract import canonical
import user_member_index as index


class Keyset(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store.__new__(Store);self.store.root=Path(self.tmp.name);self.store.path=self.store.root/'customers.sqlite3';self.store.key=b'x'*32;self.store.read_only=False
        self.store.config=dict(member_keyset_index=True,member_export_max_bytes=8*1024*1024)
        with closing(sqlite3.connect(self.store.path)) as db:
            db.executescript('CREATE TABLE snapshots(id TEXT PRIMARY KEY,query TEXT,body TEXT,members TEXT);CREATE TABLE snapshot_members(id TEXT PRIMARY KEY,body TEXT);')
        index.initialize(self.store)
        self.query=dict(scope='site',scope_id='266',state_basis='period_cohort',start='2026-10-01',end_exclusive='2026-11-01')
        self.public=dict(data_version='7',coverage=dict(identity_deduplication_complete=True))
        self.private=dict(records={str(i):dict(customer_id=str(i),period_repeated=i%2==0,period_entry_customer_type=['new','old','unknown','conflict'][i%4],amount=str(i)) for i in range(20)},members=dict(purchasers=[str(i) for i in range(20)]))
        self.frozen=self.store.save_snapshot(self.query,self.public,self.private);index.build(self.store,self.frozen,self.private)
        self.allowed=True;self.epoch='1'
        self.service=Service(self.store,lambda *a:self.allowed,permission_epoch=lambda *a:self.epoch)
        self.args=dict(snapshot_id=self.frozen['snapshot_id'],group='purchasers')

    def install_export_host(self,after_drain=None):
        self.artifacts={};self.publish_calls=[]
        def prepare(header,stream):
            raw=b''.join(canonical(row).encode()+b'\n' for row in stream)
            receipt=dict(contract='fs-member-export-receipt-v1',status='prepared',artifact_id='fixture-artifact',snapshot_id=header['snapshot_id'],data_version=header['data_version'],export_filter_hash=header['export_filter_hash'],rows=header['total'],bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
            self.artifacts[receipt['artifact_id']]=dict(receipt)
            if after_drain:after_drain(receipt)
            return receipt
        def verify(user,header,receipt):return self.artifacts.get(receipt['artifact_id'])==receipt
        def publish(user,header,prepared,revalidate):
            revalidate();self.publish_calls.append(prepared['artifact_id'])
            receipt=dict(prepared,status='published');self.artifacts[receipt['artifact_id']]=receipt
            return receipt
        self.service.export_sink=prepare;self.service.export_verifier=verify;self.service.export_publisher=publish

    def test_service_page_never_replays_facts_and_preserves_order_filters_and_exact_total(self):
        with patch.object(self.service,'private_snapshot',side_effect=AssertionError('full private read')),patch.object(self.store,'read_at',side_effect=AssertionError('full facts read')):
            first=self.service.members(dict(self.args,limit=3,customer_type='unknown'),'admin')
            self.assertEqual(first['total'],10)
            self.assertEqual([r['customer_id'] for r in first['rows']],['2','3','6'])
            second=self.service.members(dict(self.args,limit=3,customer_type='unknown',cursor=first['next_cursor']),'admin')
            self.assertEqual([r['customer_id'] for r in second['rows']],['7','10','11'])

    def test_cursor_bound_to_snapshot_filters_owner_and_permission_epoch(self):
        cursor=self.service.members(dict(self.args,limit=1),'admin')['next_cursor']
        for args,user in [(dict(self.args,cursor=cursor,repeat_status='repeated'),'admin'),(dict(self.args,cursor=cursor),'other')]:
            with self.assertRaises(ValueError):self.service.members(args,user)
        self.epoch='2'
        with self.assertRaises(ValueError):self.service.members(dict(self.args,cursor=cursor),'admin')
        self.allowed=False
        with self.assertRaises(PermissionError):self.service.members(self.args,'admin')

    def test_streaming_export_uses_db_pages_and_rejects_undrained_sink(self):
        self.install_export_host()
        with patch.object(self.service,'private_snapshot',side_effect=AssertionError('full private read')):
            result=self.service.export(self.args,'admin')
        self.assertTrue(result['complete']);self.assertEqual(result['exported_rows'],20)
        self.service.export_sink=lambda header,stream:dict(artifact_id='false-success')
        with self.assertRaisesRegex(index.IndexUnavailable,'incomplete'):self.service.export(self.args,'admin')

    def test_failed_cancelled_missing_handle_or_unverified_sink_never_completes(self):
        for change in (dict(status='failed'),dict(status='cancelled'),dict(artifact_id=''),dict(artifact_id=None)):
            self.install_export_host(after_drain=lambda receipt:receipt.update(change))
            with self.subTest(change=change),self.assertRaises(index.IndexUnavailable):self.service.export(self.args,'admin')
            self.assertEqual(self.publish_calls,[])
        self.install_export_host();self.service.export_verifier=lambda *a:False
        with self.assertRaisesRegex(index.IndexUnavailable,'unverified'):self.service.export(self.args,'admin')
        self.assertEqual(self.publish_calls,[])

    def test_last_page_revocation_or_epoch_change_prevents_publication(self):
        for revoke in ('permission','epoch'):
            self.allowed=True;self.epoch='1'
            def after(receipt):
                if revoke=='permission':self.allowed=False
                else:self.epoch='2'
            self.install_export_host(after_drain=after)
            with self.subTest(revoke=revoke),self.assertRaises(PermissionError):self.service.export(self.args,'admin')
            self.assertEqual(self.publish_calls,[])

    def test_publisher_must_revalidate_and_return_verified_published_receipt(self):
        self.install_export_host()
        self.service.export_publisher=lambda user,header,prepared,revalidate:dict(prepared,status='published')
        with self.assertRaisesRegex(index.IndexUnavailable,'not_authorized'):self.service.export(self.args,'admin')
        self.install_export_host()
        def cancelled(user,header,prepared,revalidate):revalidate();return dict(prepared,status='cancelled')
        self.service.export_publisher=cancelled
        with self.assertRaises(index.IndexUnavailable):self.service.export(self.args,'admin')

    def test_projection_reused_and_source_revision_changes_keep_old_snapshot(self):
        before=self.service.members(self.args,'admin')
        index.build(self.store,self.frozen,self.private)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM member_projection_bodies').fetchone()[0],20)
        newer=deepcopy(self.private);newer['records']['1']['amount']='corrected'
        public=self.store.save_snapshot(self.query,dict(self.public,data_version='8'),newer);index.build(self.store,public,newer)
        self.assertEqual(self.service.members(self.args,'admin'),before)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM member_projection_bodies').fetchone()[0],21)

    def test_identical_private_input_reuses_group_reference_set_across_snapshots(self):
        public=self.store.save_snapshot(self.query,dict(self.public,data_version='8'),self.private);index.build(self.store,public,self.private)
        with self.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM member_projection_rows').fetchone()[0],20)
            self.assertEqual(db.execute('SELECT count(*) FROM member_projection_sets').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM member_projection_groups').fetchone()[0],2)
        self.assertEqual(self.service.members(dict(self.args,snapshot_id=public['snapshot_id']),'admin')['total'],20)

    def test_index_budget_stops_before_adding_projection_rows(self):
        self.store.config['member_projection_max_rows']=1
        public=self.store.save_snapshot(self.query,dict(self.public,data_version='8'),self.private)
        with self.assertRaisesRegex(index.IndexUnavailable,'budget_exhausted'):index.build(self.store,public,self.private)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM member_projection_rows').fetchone()[0],20)

    def test_estimated_byte_actual_page_and_time_budgets_leave_no_partial_ready_index(self):
        for budget in ('member_projection_max_estimated_bytes','member_projection_max_new_bytes','member_projection_max_seconds'):
            with self.subTest(budget=budget):
                private=dict(records={str(i):dict(customer_id=str(i),amount='new') for i in range(1000)},members=dict(purchasers=[str(i) for i in range(1000)]))
                public=self.store.save_snapshot(self.query,dict(self.public,data_version='9'),private)
                self.store.config[budget]=1
                ticks=iter([0,0,0,0,0,100]);kwargs=dict(clock=lambda:next(ticks,100)) if budget.endswith('seconds') else {}
                with self.assertRaisesRegex(index.IndexUnavailable,'budget_exhausted'):index.build(self.store,public,private,**kwargs)
                with self.store.db() as db:
                    self.assertEqual(db.execute('SELECT count(*) FROM member_projection_bodies').fetchone()[0],20)
                    self.assertEqual(db.execute('SELECT count(*) FROM member_projection_rows').fetchone()[0],20)
                    self.assertEqual(db.execute('SELECT count(*) FROM member_projection_groups').fetchone()[0],1)
                    self.assertEqual(db.execute('SELECT count(*) FROM member_projection_sets').fetchone()[0],1)
                self.store.config.pop(budget)

    def test_missing_index_fails_without_implicit_rebuild(self):
        with self.store.db() as db:db.execute('DELETE FROM member_projection_groups')
        with patch.object(self.store,'snapshot',side_effect=AssertionError('implicit full replay')):
            with self.assertRaises(index.IndexUnavailable):self.service.members(self.args,'admin')

    def test_builder_cannot_sign_projection_that_disagrees_with_frozen_input(self):
        wrong=deepcopy(self.private);wrong['records']['1']['amount']='wrong'
        with self.assertRaisesRegex(ValueError,'recipe_mismatch'):index.build(self.store,self.frozen,wrong)

    def test_missing_projection_members_do_not_export_false_complete(self):
        with self.store.db() as db:db.execute('DELETE FROM member_projection_rows WHERE ordinal=5')
        with self.assertRaisesRegex(ValueError,'incomplete'):list(self.service.export_iter(self.args,'admin'))

    def test_tampered_projection_and_noncanonical_cursor_rejected(self):
        for cursor in (0,False,'','00.fake',{},'c_old_legacy_id'):
            with self.subTest(cursor=cursor),self.assertRaises(ValueError):self.service.members(dict(self.args,cursor=cursor),'admin')
        with self.store.db() as db:db.execute("UPDATE member_projection_rows SET ref='bad' WHERE ordinal=0")
        with self.assertRaisesRegex(ValueError,'integrity'):self.service.members(self.args,'admin')

    def test_first_page_sql_vm_cost_does_not_materialize_larger_membership(self):
        original=self.store.db
        def measure(args):
            steps=[0]
            @contextmanager
            def counted():
                with original() as db:
                    db.set_progress_handler(lambda:steps.__setitem__(0,steps[0]+1) or 0,1)
                    yield db
            with patch.object(self.store,'db',counted),patch.object(self.service,'private_snapshot',side_effect=AssertionError('full replay')):
                page=self.service.members(dict(args,limit=3),'admin')
            return page,steps[0]
        before=measure(self.args)
        private=dict(records={str(i):dict(customer_id=str(i),period_repeated=True,period_entry_customer_type='new',amount='1') for i in range(20000)},members=dict(purchasers=[str(i) for i in range(20000)]))
        public=self.store.save_snapshot(self.query,dict(self.public,data_version='9'),private);index.build(self.store,public,private)
        after=measure(dict(self.args,snapshot_id=public['snapshot_id']))
        self.assertEqual(len(after[0]['rows']),3);self.assertEqual(after[0]['total'],20000)
        self.assertLess(after[1],before[1]+200)
        print('SYNTHETIC member first-page VM:',dict(members_before=20,members_after=20000,before=before[1],after=after[1]))

    def test_stream_revocation_between_pages_does_not_finish_or_scan_all(self):
        private=dict(records={str(i):dict(customer_id=str(i),amount='1') for i in range(400)},members=dict(purchasers=[str(i) for i in range(400)]))
        public=self.store.save_snapshot(self.query,dict(self.public,data_version='9'),private);index.build(self.store,public,private)
        stream=self.service.export_iter(dict(self.args,snapshot_id=public['snapshot_id']),'admin')
        for _ in range(200):next(stream)
        self.allowed=False
        with self.assertRaises(PermissionError):next(stream)


@unittest.skipUnless(os.name=='posix','real writer/recipe integration runs in Linux, no POSIX permission mock')
class WriterRecipe(unittest.TestCase):
    def test_original_recipe_and_real_date_correction_keep_indexed_old_snapshot(self):
        import test_storage_recipe as fixtures
        fixture=fixtures.Recipe();fixture.setUp();self.addCleanup(fixture.doCleanups)
        fixture.config['member_keyset_index']=True;index.initialize(fixture.store)
        fixture.service.permission_epoch=lambda *a:'fixture-epoch'
        frozen=fixture.query();query,public,private=fixture.store.snapshot(frozen['snapshot_id'])
        expected=[private['records'][cid] for cid in private['members']['purchasers']]
        args=dict(snapshot_id=frozen['snapshot_id'],group='purchasers',limit=200)
        self.assertEqual(fixture.service.members(args,'admin')['rows'],expected)
        fixture.load([fixtures.order(1,'2026-09-01',status='2'),fixtures.order(2,'2026-10-05')])
        self.assertEqual(fixture.service.members(args,'admin')['rows'],expected)
        self.assertEqual(fixture.store.snapshot(frozen['snapshot_id'])[2],private)

if __name__=='__main__':unittest.main()
