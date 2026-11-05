"""Sales release using the existing locked, CAS-protected navigation publisher."""
import contextlib,fcntl,json,sys,subprocess,sqlite3
from pathlib import Path
P=Path(__file__).parent
sys.path.insert(0,'/opt/fs-release-stage/traffic-source-tabs-20261019-v3')
import release_ui_finish as ui
ui.TARGETS=json.loads((P/'targets.json').read_text())
b=ui.publisher();original_locks=b.locks
@contextlib.contextmanager
def locks(root):
 with original_locks(root):
  with open('/opt/sales-dashboard/.run.lock','a+') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   yield
b.locks=locks
def restart(manifest,fence=None):
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','restart','auth-portal.service'],check=True)
 subprocess.run(['systemctl','reload','nginx.service'],check=True)
 subprocess.run(['systemctl','is-active','--quiet','nginx.service','auth-portal.service'],check=True)
b.restart_for=restart
raw=(P/'manifest.json').read_bytes();m=json.loads(raw)
if sys.argv[1]=='inspect':out=b.inspect(m,P)
elif sys.argv[1]=='apply':
 # An online SQLite backup includes committed WAL rows. Recovery preserves it;
 # code rollback must never replace live orders with an old database.
 with sqlite3.connect('/opt/sales-dashboard/data/history.db') as src:
  with sqlite3.connect(str(P/'history.before.db')) as dst:src.backup(dst)
 out=b.apply(m,P,sys.argv[2],raw,sys.argv[3])
elif sys.argv[1]=='rollback':out=b.rollback(Path(sys.argv[2]),sys.argv[3])
else:raise ValueError('unsupported action')
print(json.dumps(out))
