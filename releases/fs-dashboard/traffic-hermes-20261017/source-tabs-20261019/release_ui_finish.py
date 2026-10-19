"""Five-file UI-only completion; runtime data and caches are protected, not replaced."""
import hashlib,json,subprocess,sys,types
from pathlib import Path
PACKAGE='workspace-native-20261019-traffic-v3'
STATIC='/var/lib/fs-navigation-formal-static/'
CONFIG='/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'
INDEX=STATIC+'workspace-native-20261006-37fe775358df/index.html'
TARGETS={**{'ui/'+n:STATIC+PACKAGE+'/'+n for n in ('google.js','google.css','shell.js')},'z-index.html':INDEX,'zz-routes.conf':CONFIG}
SCOPE='traffic-source-tabs-ui-finish-20261019'
def publisher():
 path=Path(__file__).with_name('release_source_tabs.py');m=types.ModuleType('ui_bridge');m.__file__=str(path);exec(compile(path.read_bytes(),str(path),'exec'),m.__dict__)
 m.SCOPE=SCOPE;m.TARGETS=TARGETS;b=m.publisher()
 def restart(manifest,fence=None):
  if manifest['scope']!=SCOPE:raise ValueError('unexpected UI scope')
  subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','nginx.service'],check=True)
 b.restart_for=restart
 return b
def main():
 stage=Path(__file__).parent;b=publisher();raw=(stage/'ui-manifest.json').read_bytes();m=json.loads(raw);sha=hashlib.sha256(raw).hexdigest()
 if sys.argv[1]=='inspect':out=b.inspect(m,stage)
 elif sys.argv[1]=='apply':out=b.apply(m,stage,sys.argv[2],raw,sys.argv[3])
 elif sys.argv[1]=='rollback':out=b.rollback(Path(sys.argv[2]),sys.argv[3])
 else:raise ValueError('invalid action')
 print(json.dumps(out))
if __name__=='__main__':main()
