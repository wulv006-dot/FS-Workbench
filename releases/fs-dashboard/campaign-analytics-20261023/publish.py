"""Campaign-only adapter of the existing locked, journalled CAS publisher."""
import hashlib, importlib.util, json, subprocess
from pathlib import Path

HERE=Path(__file__).resolve().parent
BASE_SHA='5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
base=HERE/'native/release_navigation_base.py'
if not base.exists():base=HERE.parent/'menu-cache-20261015/native/release_navigation.py'
if hashlib.sha256(base.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('publisher bytes changed')
spec=importlib.util.spec_from_file_location('campaign_base',base);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SCOPE='fs-campaign-dashboard-20261023'
SPECIAL={'navigation.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf','navigation.json':'/var/www/dashboard/fs-home/navigation.json','module-registry.json':'/var/www/dashboard/fs-home/module-registry.json','fs-campaign-dashboard.service':'/etc/systemd/system/fs-campaign-dashboard.service'}

def target(rel):
 if rel in SPECIAL:return SPECIAL[rel]
 if rel.startswith('app/') and '..' not in Path(rel).parts and Path(rel).suffix in ('.js','.mjs','.cjs','.html','.css','.json','.webp','.png','.svg','.md'):
  return '/opt/fs-campaign-dashboard/'+rel[4:]
 raise ValueError('outside campaign scope')

def expected(manifest):
 if manifest.get('scope')!=SCOPE:raise ValueError('wrong scope')
 return set(manifest['targets'])

def validate(manifest,stage):
 files=manifest['files'];names={r['candidate'] for r in files}
 if manifest.get('schemaVersion')!=1 or names!=expected(manifest) or len(names)!=len(files) or not set(SPECIAL).issubset(names):raise ValueError('incomplete exact manifest')
 for r in files:
  if r['target']!=target(r['candidate']) or manifest['targets'][r['candidate']]!=r['target']:raise ValueError('target changed')
  if not m.HASH.fullmatch(r['sha256']) or r['beforeSha256'] is not None and not m.HASH.fullmatch(r['beforeSha256']):raise ValueError('invalid hash')
  p=stage/'candidate'/r['candidate'];m.no_target_link(p)
  if m.digest(p)!=r['sha256']:raise ValueError('candidate changed')
 return files

def guards(manifest,root):
 required={'/opt/auth-portal/auth_portal.py','/opt/fs-access-policy/rbac.py'}
 if {r['path'] for r in manifest['unchangedRequired']}!=required:raise ValueError('authentication guard missing')
 for r in manifest['unchangedRequired']:
  if m.digest(m.rooted(root,r['path']))!=r['sha256']:raise ValueError('authentication baseline changed')
 if root==Path('/'):
  subprocess.run(['systemctl','is-active','--quiet','auth-portal','nginx'],check=True)

def restart(manifest,admission_fence=None):
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 if Path(SPECIAL['fs-campaign-dashboard.service']).exists():
  subprocess.run(['systemctl','enable','fs-campaign-dashboard.service'],check=True)
  subprocess.run(['systemctl','restart','fs-campaign-dashboard.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','fs-campaign-dashboard.service'],check=True)
 else:
  subprocess.run(['systemctl','stop','fs-campaign-dashboard.service'],check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)

m.QUERY_SCOPE=SCOPE;m.target_for=target;m.expected_files=expected;m.validate=validate;m.guards=guards;m.restart_for=restart
if __name__=='__main__':m.main()
