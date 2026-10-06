from pathlib import Path
import sys,json,ast,subprocess,re,hashlib,datetime,os,argparse
import tempfile,shutil
sys.dont_write_bytecode=True
from candidate_tree_contract import validate_tree,decode_unit_result,result_exit_code,source_bytes
unit_code=r'''
from pathlib import Path
import sys,json,unittest,unittest.mock,asyncio,io,socket,subprocess,types,os
sys.dont_write_bytecode=True
C=Path(sys.argv[1]);group=sys.argv[2]
real_connect=socket.socket.connect
def local_connect(self,address):
 if isinstance(address,tuple) and address[0] not in ('127.0.0.1','localhost','::1'):raise AssertionError('network not allowed in candidate checks')
 return real_connect(self,address)
socket.socket.connect=local_connect
def no_process(*a,**k):raise AssertionError('external process not allowed in unit checks')
subprocess.Popen=no_process
if group=='parser':
 d=C/'mmoexp_google_data/weekly_report/range_parser_fix_20261005/tests'
 sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.discover(str(d))
elif group=='engine':
 d=C/'docs/fc27-coins/discount-config-release-20261005/tests';sys.path[:0]=[str(d),str(C)]
 suite=unittest.defaultTestLoader.loadTestsFromName('test_fc27_quote_engine')
elif group=='discount-pure':
 f=types.ModuleType('fcntl');f.LOCK_EX=1;f.LOCK_NB=2;f.LOCK_UN=8
 def reject_flock(*a,**k):raise AssertionError('real Unix flock not available; lock path excluded from this group')
 f.flock=reject_flock;sys.modules['fcntl']=f
 sys.path[:0]=[str(C/'docs/fc27-coins/discount-config-release-20261005/tests'),str(C/'fc27_cloud_browser'),str(C)]
 import server_quote_job
 server_quote_job.ENGINE_FILE=C/'fc27_quote_engine.py'
 import test_discount_config
 if os.name=='nt':
  test_discount_config.PurePreviewTests.test_real_quote_owns_rules_snapshot_and_hash=unittest.skip('Linux ownership path requires os.chown; not emulated on Windows')(test_discount_config.PurePreviewTests.test_real_quote_owns_rules_snapshot_and_hash)
 suite=unittest.defaultTestLoader.loadTestsFromNames(['test_discount_config.RangeValidationTests','test_discount_config.PurePreviewTests'])
elif group=='weekly':
 d=C/'mmoexp_google_data/weekly_report';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.loadTestsFromName('test_weekly_contracts')
elif group=='google-collector':
 d=C/'mmoexp_google_data/implementation';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.loadTestsFromName('test_collector')
elif group=='integration':
 d=C/'tests/integration';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.discover(str(d),pattern='test_*guards.py')
elif group=='gateway':
 d=C/'fs_dashboard_overwrite_20261003';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.discover(str(d))
elif group=='migration':
 d=C/'tests/integration';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.loadTestsFromName('test_fc_migration_contract')
elif group=='revision3-contracts':
 d=C/'tests/integration';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.loadTestsFromName('test_revision3_contracts')
elif group=='google-details':
 d=C/'mmoexp_google_data/details';sys.path.insert(0,str(d));suite=unittest.defaultTestLoader.loadTestsFromName('test_details')
output=io.StringIO();r=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
print(json.dumps({'check':group,'testsRun':r.testsRun,'passed':r.wasSuccessful(),'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'failureTypes':[type(e).__name__ for e in []],'output':output.getvalue()}))
sys.exit(0 if r.wasSuccessful() else 1)
'''
REPO=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--tree-only',action='store_true',help='Read-only exact manifest/path/hash validation; do not run candidate suites')
 args=parser.parse_args()
 rows=validate_tree(REPO)
 if args.tree_only:
  print(json.dumps({'passed':True,'contentFiles':len(rows),'treeFiles':len(rows)+2,'scope':'manifest/path/hash/link validation only; no candidate code executed','gitModeValidation':{'promisedFiles':sum('gitMode' in row for row in rows),'status':'POSIX executable bits checked for promised gitMode; absent modes not promised' if os.name=='posix' else 'Windows executable bits unverified; promised gitMode syntax checked only'}}))
  return 0
 ROOT=Path(tempfile.mkdtemp(prefix='fs-candidate-check-'))
 C=ROOT/'candidate';R=ROOT/'review';R.mkdir()
 for row in rows:
  target=C/row['path']
  target.parent.mkdir(parents=True,exist_ok=True)
  target.write_bytes(source_bytes(REPO,row))
 results=[]
 pyfiles=list(C.rglob('*.py'));jsfiles=list(C.rglob('*.js'))+list(C.rglob('*.cjs'))
 for p in pyfiles:ast.parse(p.read_text(encoding='utf-8-sig'),filename=str(p.relative_to(C)))
 results.append({'check':'python-parse','files':len(pyfiles),'passed':True})
 for p in jsfiles:
  r=subprocess.run(['node','--check',str(p)],capture_output=True,text=True,timeout=20)
  if r.returncode:raise RuntimeError('JS syntax failed: '+str(p.relative_to(C)))
 results.append({'check':'javascript-parse','files':len(jsfiles),'passed':True})
 
 
 for group in ['parser','engine','discount-pure','weekly','google-collector','google-details','integration','gateway','migration','revision3-contracts']:
  env=os.environ.copy();env['PYTHONIOENCODING']='utf-8'
  r=subprocess.run([sys.executable,'-B','-c',unit_code,str(C),group],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60,cwd=C,env=env)
  obj=decode_unit_result(r,group)
  (R/('test-'+group+'.json')).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
  results.append({k:v for k,v in obj.items() if k!='output'})
 
 # Dedicated pure Node child for the real Python/JS rev25 matrix; no writer is imported/executed.
 matrix=subprocess.run([sys.executable,'-B',str(C/'tests/integration/test_fc_rev25_matrix.py')],
  capture_output=True,text=True,encoding='utf-8',timeout=30,cwd=C)
 obj={'check':'rev25-matrix','passed':matrix.returncode==0,'output':matrix.stdout,'error':matrix.stderr}
 (R/'test-rev25-matrix.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 results.append({k:v for k,v in obj.items() if k not in ('output','error')})
 
 js_tests=[('date-range','fs_date_theme_fix_20261001/test_range.cjs'),
           ('calendar','fc_calendar_trim_20261004/test_calendar.cjs'),
           ('aion2-state','aion2_dashboard_20261004/test_status.cjs'),
           ('nba-pure','tests/integration/test_nba_pure_guards.cjs'),
           ('nba-routes','tests/integration/test_nba_wired_routes.cjs'),
           ('range-async','tests/integration/test_range_async_contract.cjs'),
           ('nba-bound','tests/integration/test_nba_bound_writer.cjs')]
 for group,rel in js_tests:
  p=C/rel
  if group=='calendar':
   source=C/'fc27_ops_cloud/data/fc-analytics.js'
   (p.parent/'fc-analytics.js').write_bytes(source.read_bytes())
  r=subprocess.run(['node',str(p)],capture_output=True,text=True,timeout=20,cwd=p.parent)
  results.append({'check':group,'passed':r.returncode==0,'returncode':r.returncode})
  (R/('test-'+group+'.json')).write_text(json.dumps({'passed':r.returncode==0,'output':r.stdout,'error':r.stderr},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 report={'testedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'productionChanges':False,
  'scope':'isolated Windows source checks and synthetic fixtures; no live account, sampling or price writes',
  'passed':result_exit_code(results)==0,'results':results,
  'notExercised':['real Unix flock/concurrent production jobs','real production account login/save','excluded raw-business-data fixture suites','deployment','other computer merge']}
 (R/'test-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 sys.stdout.reconfigure(encoding='utf-8');print(json.dumps(report,ensure_ascii=False,indent=2))
 
 return result_exit_code(results)

if __name__=='__main__':
 sys.exit(main())
