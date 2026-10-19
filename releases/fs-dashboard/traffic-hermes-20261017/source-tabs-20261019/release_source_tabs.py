"""Narrow extension of the frozen FS publisher, preserving CAS/locks/rollback."""
import contextlib, hashlib, json, os, stat, subprocess, sys, types
from pathlib import Path
SCOPE='traffic-source-tabs-20261019'
PACKAGE='workspace-native-20261019-traffic-v2'
STATIC='/var/lib/fs-navigation-formal-static/'
CONFIG='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
OLD=STATIC+'workspace-native-20261006-37fe775358df/'
TARGETS={**{'ui/'+n:STATIC+PACKAGE+'/'+n for n in ('google.js','google.css','shell.js')},
 'z-index.html':OLD+'index.html','zz-routes.conf':CONFIG,
 **{'data/'+str(i)+'_'+n:'/opt/mmoexp-marketing/details/'+n for i,n in enumerate(('game_mapping_20261019.json','game_dimensions.py','collect_details.py','detail_model.py'))},
 **{'range/'+n:'/opt/mmoexp-marketing/custom-range/'+n for n in ('custom_range.py','range_api.py')}}
PIN='57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'

def publisher():
 p=Path(__file__).with_name('release_navigation_base.py');raw=p.read_bytes()
 if hashlib.sha256(raw).hexdigest()!=PIN:raise ValueError('frozen publisher drift')
 source=raw.decode();needle='(QUERY_SCOPE,TRAFFIC_SCOPE,'
 if source.count(needle)!=2:raise ValueError('publisher activation seams changed')
 # Only extend the two apply/automatic rollback restart dispatch lists.
 source=source.replace(needle,'(SOURCE_TABS_SCOPE,QUERY_SCOPE,TRAFFIC_SCOPE,')
 b=types.ModuleType('frozen_publisher');b.__file__=str(p);b.SOURCE_TABS_SCOPE=SCOPE
 exec(compile(source,str(p),'exec'),b.__dict__)
 old_validate=b.validate;old_guards=b.guards
 b.expected_files=lambda m:set(TARGETS) if m.get('scope')==SCOPE else set()
 b.target_for=lambda rel:TARGETS[rel]
 def validate(m,stage):
  if m.get('scope')!=SCOPE or m.get('businessWrites') is not False or m.get('timersChanged') is not False:raise ValueError('scope boundary')
  if m.get('runtimeRequired')!={'nginx.service':{'ActiveState':'active'},'fs-marketing-range.service':{'ActiveState':'active'}}:raise ValueError('runtime boundary')
  return old_validate(m,stage)
 def guards(m,root,reader_stopped=False):
  old_guards(m,root,reader_stopped)
  for target in TARGETS.values():
   p=b.rooted(root,target);b.no_target_link(p)
   for item in (p,*p.parents):
    if item.exists():
     s=item.stat()
     if s.st_uid!=0 or s.st_gid!=0 or s.st_mode&0o022:raise ValueError('unsafe target ownership')
    if item==root:break
 def restart(m,fence=None):
  if m.get('scope')!=SCOPE:raise ValueError('unknown activation')
  subprocess.run(['nginx','-t'],check=True)
  subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True)
  subprocess.run(['systemctl','reload','nginx.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','nginx.service','fs-marketing-range.service'],check=True)
 b.validate=validate;b.guards=guards;b.restart_for=restart
 old_locks=b.locks
 b.ui_only_locks=old_locks
 @contextlib.contextmanager
 def locks(root):
  import fcntl
  with old_locks(root):
   path=b.rooted(root,'/opt/mmoexp-marketing/data/verified-readonly/collector.lock')
   fd=os.open(str(path),os.O_RDWR|os.O_NOFOLLOW)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # Existing in-flight source imports must finish, never kill them.
    for proc in Path('/proc').glob('[0-9]*/cmdline'):
     try:cmd=proc.read_bytes().split(b'\0')
     except (OSError,ProcessLookupError):continue
     if any(arg.endswith((b'/custom_range.py',b'/collect_details.py')) for arg in cmd):raise ValueError('source reader busy; defer release')
    yield
   finally:os.close(fd)
 b.locks=locks
 return b

def main():
 b=publisher();stage=Path(__file__).parent;raw=(stage/'manifest.json').read_bytes();m=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
 action=sys.argv[1]
 if action=='inspect':out=b.inspect(m,stage)
 elif action=='apply':
  if len(sys.argv)!=4 or sys.argv[2]!=sha:raise ValueError('reviewed manifest SHA required')
  out=b.apply(m,stage,sha,raw,sys.argv[3])
 elif action=='rollback':out=b.rollback(Path(sys.argv[2]),sys.argv[3])
 else:raise ValueError('unsupported action')
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()
