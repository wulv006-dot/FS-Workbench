"""Synthetic-only index time/space fixture; never opens an existing customer DB."""
from contextlib import closing
import json,sqlite3,sys,tempfile,time,tracemalloc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'user-analytics-20261022/source'))
from user_store import Store
from user_contract import digest
import user_member_index as index


def measure(rows):
    with tempfile.TemporaryDirectory() as temp:
        store=Store.__new__(Store);store.root=Path(temp);store.path=store.root/'customers.sqlite3';store.key=b'x'*32;store.read_only=False;store.config={}
        with closing(sqlite3.connect(store.path)) as db:
            db.executescript('PRAGMA journal_mode=WAL;CREATE TABLE snapshots(id TEXT PRIMARY KEY,query TEXT,body TEXT,members TEXT);CREATE TABLE snapshot_members(id TEXT PRIMARY KEY,body TEXT);')
        index.initialize(store)
        private=dict(records={str(i):dict(customer_id=str(i),period_repeated=True,period_entry_customer_type='new',amount='1.00') for i in range(rows)},members=dict(purchasers=[str(i) for i in range(rows)]))
        query=dict(scope='site',scope_id='fixture',state_basis='period_cohort',start='2026-10-01',end_exclusive='2026-11-01')
        recipe=dict(contract='fs-users-private-replay-v1',query=query,data_version='1',private_sha256=digest(private),config={},jobs=[],global_allowed=False)
        public=store.save_snapshot(query,dict(data_version='1'),recipe)
        with store.db() as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)');baseline=db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
        tracemalloc.start();start=time.perf_counter();index.build(store,public,private);elapsed=time.perf_counter()-start;_,heap=tracemalloc.get_traced_memory();tracemalloc.stop()
        with store.db() as db:
            first=db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        public2=store.save_snapshot(query,dict(data_version='2'),dict(recipe,data_version='2'));index.build(store,public2,private)
        with store.db() as db:
            second=db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
            bodies=db.execute('SELECT count(*) FROM member_projection_bodies').fetchone()[0]
            refs=db.execute('SELECT count(*) FROM member_projection_rows').fetchone()[0]
        return dict(synthetic=True,members=rows,baseline_bytes=baseline,first_index_additional_bytes=first-baseline,second_snapshot_additional_bytes=second-first,body_rows=bodies,reference_rows=refs,index_seconds=elapsed,python_heap_peak_bytes=heap,production_wal_peak=None,production_rss=None,recipe_replay_not_tested=True)


if __name__=='__main__':print(json.dumps([measure(1000),measure(10000)],indent=2))
