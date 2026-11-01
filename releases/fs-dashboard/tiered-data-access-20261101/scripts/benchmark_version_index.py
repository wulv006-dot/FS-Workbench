"""Synthetic-only migration space/WAL/heap measurement; never opens a supplied DB."""
import json,sqlite3,sys,tempfile,time,tracemalloc
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'user-analytics-20261022/source'))
from user_version_index import build_batch,COLUMNS


def run(rows=10000):
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)/'synthetic.sqlite3'; db=sqlite3.connect(path)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO meta VALUES('revision','2');
                CREATE TABLE orders(order_key TEXT PRIMARY KEY,site TEXT,gid TEXT,customer_id TEXT,paid_at TEXT,valid INTEGER,body TEXT,revision INTEGER);
                CREATE TABLE revisions(id INTEGER PRIMARY KEY,reason TEXT,body TEXT);''')
            old=[dict(order_key='fixture-'+str(i),site='266',gid='1327',customer_id='opaque-fixture',paid_at='2026-09-01T00:00:00+08:00',valid=1,body='{"amount_usd":"1.00","id":"fixture"}',revision=1) for i in range(rows)]
            db.execute('INSERT INTO revisions VALUES(2,?,?)',('synthetic',json.dumps(old)))
            db.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?,?,?)',(tuple(dict(row,revision=2,paid_at='2026-10-01T00:00:00+08:00')[k] for k in COLUMNS.split(',')) for row in old))
            db.commit(); db.execute('PRAGMA wal_checkpoint(TRUNCATE)'); old=None
            before=path.stat().st_size
            tracemalloc.start(); started=time.perf_counter()
            with db: result=build_batch(db)
            elapsed=time.perf_counter()-started; _,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            wal=Path(str(path)+'-wal'); wal_bytes=wal.stat().st_size if wal.exists() else 0
            after=db.execute('PRAGMA page_count').fetchone()[0]*db.execute('PRAGMA page_size').fetchone()[0]
            return dict(synthetic=True,rows=rows,ready=result['ready'],baseline_db_bytes=before,indexed_db_logical_bytes=after,additional_logical_bytes=after-before,wal_bytes_after_commit=wal_bytes,python_heap_peak_bytes=peak,elapsed_seconds=elapsed,
                        production_compatibility='not_tested',peak_rss=None,lock_wait=None,warning='One old revision JSON is indivisible; migration duplicates historical bodies, not a storage-saving claim')
        finally: db.close()


if __name__=='__main__': print(json.dumps(run(),indent=2))
