"""Archive inputs stay pinned across a query; historical recipes need no raw XLSX."""
from contextlib import contextmanager,nullcontext
import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from test_weekly import WeeklyFixture,FRIDAY,OLD,types,weekly,stamp

class PublicationArchive(WeeklyFixture):
    def test_query_holds_archive_only_until_flags_then_releases_before_store_analysis(self):
        active=[]
        @contextmanager
        def lease():
            active.append(True)
            try:yield
            finally:active.pop()
        def flags(*a,**k):
            self.assertTrue(active);return self.flags,self.flag_info
        original=self.store.read_at
        def read(*a,**k):
            self.assertFalse(active);return original(*a,**k)
        with patch.object(types,'publication_archive_access',lease),patch.object(types,'read_pinned_flags',side_effect=flags),patch.object(self.store,'read_at',side_effect=read):
            result=self.service.query(dict(start='2026-10-19'),'admin')
            self.service.query(dict(start='2026-10-19'),'admin')
        self.assertFalse(active);self.assertIn('snapshot_id',result)
    def test_saved_private_recipe_replays_when_es_is_unavailable(self):
        public=self.service.query(dict(start='2026-10-19'),'admin');before=self.store.snapshot(public['snapshot_id'])
        self.store.replace_window('266','2026-10-19','2026-10-26',[],FRIDAY.isoformat())
        with patch.object(types,'read_pinned_flags',side_effect=AssertionError('frozen recipe must not reopen ES')),patch.object(types,'publication_archive_access',side_effect=AssertionError('snapshot read must not acquire archive')):
            self.assertEqual(self.service.query(dict(snapshot_id=public['snapshot_id']),'admin'),public)
            self.assertEqual(self.store.snapshot(public['snapshot_id']),before)
    def test_publication_consumes_actual_pinned_identity_reader(self):
        archive=Path(self.tmp.name)/'archive';archive.mkdir(mode=0o700)
        raw=json.dumps([dict(order=r['order_no'],time=r['paytime'],new='是',buyer_id='buyer-'+str(r['id']),uid='0') for r in self.rows]).encode()
        h=hashlib.sha256(raw).hexdigest();p=archive/(h+'.xlsx');p.write_bytes(raw);p.chmod(0o600)
        v=dict(query=dict(profile='ALL',start='2026-10-19',end='2026-10-26'),captured_at='2026-10-28T02:00:00+08:00',file_sha256=[h],file_set=dict(declared_files=1,failed_files=0))
        manifest=json.dumps(v).encode();name=hashlib.sha256(manifest).hexdigest()+'.json';p=archive/name;p.write_bytes(manifest);p.chmod(0o600)
        def dataset(rows,*args):return dict(rows=[dict(r,order=hashlib.sha256(r['order'].encode()).hexdigest()) for r in rows])
        es=SimpleNamespace(MAX_FILE=32*1024*1024,archive_access=lambda root:nullcontext(),excel_path=lambda root,d:root/(d+'.xlsx'),parse_files=lambda files:([r for b in files for r in json.loads(b)],[hashlib.sha256(b).hexdigest() for b in files],0),make_dataset=dataset,COLUMNS=dict(time='time',order='order',new_customer='new'))
        inventory=[dict(name=name,sha256=hashlib.sha256(manifest).hexdigest())]
        def flags(q,m,root=None,_identity=False):return types._read_pinned_flags(q,m,archive,_identity=_identity)
        state=dict(contract='fs-users-weekly-work-v1',phase='publish',cadence='daily',start='2026-10-19T00:00:00+08:00',cutoff='2026-10-27T00:00:00+08:00',base_publication=self.publication['publication_id'])
        with patch.dict(sys.modules,es_order_structure=es),patch.object(types,'manifest_inventory',return_value=inventory),patch.object(types,'read_pinned_flags',side_effect=flags):
            result=weekly.run(self.store,state,self.publication,FRIDAY,lambda:0)
        self.assertEqual(result['status'],'complete');self.assertEqual(state['identity_evidence']['changed_rows'],2)

class ReviewWindows(unittest.TestCase):
    def test_fresh_review_is_three_calendar_exports_even_if_daily_was_requested(self):
        calls=[]
        def fresh(q,after,cycle):calls.append(q);return dict(status='available')
        with patch.dict(sys.modules,es_order_structure=SimpleNamespace(server_bundle_after=fresh)),patch.object(types,'read_flags',return_value=({},dict(status='complete'))):
            out=types.ensure_period('2026-09-01','2026-11-05',now=stamp('2026-11-05T04:18:00+08:00'),daily=True,fresh_after='2026-11-05T04:00:00+08:00',cycle_id='ur_fixed')
        self.assertEqual(out['status'],'complete');self.assertEqual([(q['start'],q['end']) for q in calls],[('2026-09-01','2026-09-30'),('2026-10-01','2026-10-31'),('2026-11-01','2026-11-04')])
if __name__=='__main__':unittest.main()
