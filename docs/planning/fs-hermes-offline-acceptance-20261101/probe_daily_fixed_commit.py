"""Narrow probes, fixed Git objects, temporary Archive, no production calls."""
import json, os, subprocess, sys, tempfile, types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_support import read_sources,install_guard
ROOT=Path(__file__).resolve().parent
REPO=Path(os.environ.get('FS_ACCEPTANCE_REPO', str(ROOT.parents[2]))).resolve()
SHA='934f501caa345969eb80104fcc187dbfd9b40e27'
paths={'date_policy':'releases/fs-dashboard/tiered-data-access-20261101/source/date_policy.py',
       'daily_archive':'releases/fs-dashboard/daily-archive-20261021/source/daily_archive.py',
       'daily_facts':'releases/fs-dashboard/tiered-data-access-20261101/source/daily_facts.py'}
sources=read_sources(REPO,SHA,{'date_policy': 'releases/fs-dashboard/tiered-data-access-20261101/source/date_policy.py', 'daily_archive': 'releases/fs-dashboard/daily-archive-20261021/source/daily_archive.py', 'daily_facts': 'releases/fs-dashboard/tiered-data-access-20261101/source/daily_facts.py'})
install_guard()
for name,data in sources.items():
    mod=types.ModuleType(name);sys.modules[name]=mod
    exec(compile(data,SHA+':'+paths[name],'exec'),mod.__dict__)
from daily_archive import Archive
from daily_facts import Facts
registry={'fixture':dict(metric_contract='v1',currencies=['CNY','USD'],timezone='Asia/Shanghai',
                        date_semantics='shipping_transaction_at',additive_metrics=['sales'])}
with tempfile.TemporaryDirectory() as directory:
    archive=Archive(Path(directory)/'archive');facts=Facts(archive,registry);facts.initialize()
    def publish(seq,amount,complete=True):
        return facts.publish('fixture','trusted','2026-10-01','CNY',seq,{'sales':str(amount)},
                             source_complete=complete,source_watermark='fixture-'+str(seq))
    def read():return facts.read('fixture','trusted','2026-10-01','2026-10-02','CNY')
    publish(1,10)
    try:publish(2,0,False)
    except ValueError as e:source_error=str(e)
    failed_read=read()
    facts.mark_dirty('fixture','trusted','event-1','2026-10-01',None,'refund',currency='CNY')
    dirty_before=read()
    original_database=archive.database
    class Connection:
        def __init__(self,db):self.db=db
        def execute(self,sql,args=()):
            if sql.startswith('SELECT business_date FROM dirty_days'):
                # Actual second connection commits a complete replacement between
                # the reader's two queries; no replacement of candidate code.
                archive.database=original_database
                publish(2,20)
            return self.db.execute(sql,args)
        def close(self):self.db.close()
    archive.database=lambda create=False: original_database(create) if create else Connection(original_database())
    mixed=read();archive.database=original_database
    after=read()
    try:facts.mark_dirty('fixture','trusted','event-1','2026-10-01',None,'refund',currency='USD')
    except ValueError as e:currency_error=str(e)
    result={'commit':SHA,'source_failure':{'error':source_error,'read_complete':failed_read['complete'],
              'old_sales':failed_read['rows'][0]['metrics']['sales']},
            'mixed_snapshot':{'dirty_before':dirty_before['dirty'],'read_complete':mixed['complete'],
              'read_sales':mixed['rows'][0]['metrics']['sales'],'actual_sales_after':after['rows'][0]['metrics']['sales']},
            'same_event_second_currency':currency_error,'production_validated':False}
    print(json.dumps(result))
