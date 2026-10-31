"""Campaign-only adapter of the existing locked, journalled CAS publisher."""
import hashlib, importlib.util, json, subprocess
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath

HERE=Path(__file__).resolve().parent
BASE_SHA='5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357'
base=HERE/'native/release_navigation_base.py'
if not base.exists():base=HERE.parent/'menu-cache-20261015/native/release_navigation.py'
if hashlib.sha256(base.read_bytes()).hexdigest()!=BASE_SHA:raise ValueError('publisher bytes changed')
spec=importlib.util.spec_from_file_location('campaign_base',base);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SCOPE='fs-campaign-dashboard-20261023'
SPECIAL={'navigation.conf':'/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf','navigation.json':'/var/www/dashboard/fs-home/navigation.json','module-registry.json':'/var/www/dashboard/fs-home/module-registry.json','fs-campaign-dashboard.service':'/etc/systemd/system/fs-campaign-dashboard.service'}
REQUIRED_SPECIAL=set(SPECIAL)
RUNTIME_SPECIAL={'fs-campaign-runtime.service':'/etc/systemd/system/fs-campaign-runtime.service','runtime.env':'/etc/fs-campaign-runtime.env'}
SPECIAL.update(RUNTIME_SPECIAL)
STATS_SPECIAL={'fs-campaign-statistics-refresh.service':'/etc/systemd/system/fs-campaign-statistics-refresh.service','fs-campaign-statistics-refresh.timer':'/etc/systemd/system/fs-campaign-statistics-refresh.timer'}
SPECIAL.update(STATS_SPECIAL)
STATS_PAYLOAD=set(STATS_SPECIAL)|{'app/analytics/statistics-refresh.mjs','app/analytics/statistics-retry.mjs','backend/statistics_refresh.py','app/analytics/production-server.mjs','app/analytics/dashboard.js'}
BACKEND_FILES={'bridge.py','catalog-mapping.json','campaign_backend/__init__.py','campaign_backend/adapters.py','campaign_backend/attribution.py','campaign_backend/catalog.py','campaign_backend/models.py','campaign_backend/provider.py','campaign_backend/core.py','campaign_backend/ledger.py','campaign_backend/coupon_draft.py','campaign_backend/benefits.py','campaign_backend/analysis.py','campaign_backend/services.py','campaign_backend/discount_revenue.py'}
BACKEND_FILES.add('statistics_refresh.py')
BACKEND_FILES.add('google_traffic.py')

def target(rel):
 if rel in SPECIAL:return SPECIAL[rel]
 if rel.startswith('backend/') and rel[8:] in BACKEND_FILES:return '/opt/fs-campaign-dashboard/'+rel
 if '\\' not in rel and PurePosixPath(rel).as_posix()==rel and rel.startswith('app/') and '..' not in PurePosixPath(rel).parts and PurePosixPath(rel).suffix in ('.js','.mjs','.cjs','.html','.css','.json','.webp','.png','.svg','.jpg','.jpeg','.gif','.woff2','.xml','.txt','.md'):
  return '/opt/fs-campaign-dashboard/'+rel[4:]
 raise ValueError('outside campaign scope')

def expected(manifest):
 if manifest.get('scope')!=SCOPE:raise ValueError('wrong scope')
 return set(manifest['targets'])

def validate(manifest,stage):
 files=manifest['files'];names={r['candidate'] for r in files}
 if manifest.get('schemaVersion')!=1 or names!=expected(manifest) or len(names)!=len(files) or not REQUIRED_SPECIAL.issubset(names):raise ValueError('incomplete exact manifest')
 if names.intersection(RUNTIME_SPECIAL) and not set(RUNTIME_SPECIAL).issubset(names):raise ValueError('runtime unit and environment must be staged together')
 if names.intersection(STATS_SPECIAL) and not STATS_PAYLOAD.issubset(names):raise ValueError('statistics timer requires its exact paired service and readers')
 if names.intersection({'app/analytics/statistics-refresh.mjs','app/analytics/server.mjs','app/analytics/discount-revenue.mjs'}) and 'app/analytics/statistics-retry.mjs' not in names:raise ValueError('statistics retry dependency must be staged with its consumers')
 if 'app/analytics/google-traffic.mjs' in names and 'backend/google_traffic.py' not in names:raise ValueError('Google reader requires its paired Python bridge')
 if 'app/analytics/production-server.mjs' in names and b"from './google-traffic.mjs'" in (stage/'candidate/app/analytics/production-server.mjs').read_bytes() and not {'app/analytics/google-traffic.mjs','backend/google_traffic.py'}.issubset(names):raise ValueError('Google endpoint requires its exact reader closure')
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
  if set(manifest['targets']).intersection(STATS_SPECIAL) and datetime.now().astimezone().utcoffset()!=timedelta(hours=8):raise ValueError('statistics calendar requires observed187 UTC+08 timezone')

def restart(manifest,admission_fence=None):
 subprocess.run(['nginx','-t'],check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 if Path(SPECIAL['fs-campaign-dashboard.service']).exists():
  subprocess.run(['systemctl','enable','fs-campaign-dashboard.service'],check=True)
  subprocess.run(['systemctl','restart','fs-campaign-dashboard.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','fs-campaign-dashboard.service'],check=True)
 else:
  subprocess.run(['systemctl','stop','fs-campaign-dashboard.service'],check=True)
 if Path(SPECIAL['fs-campaign-runtime.service']).exists():
  subprocess.run(['systemctl','enable','fs-campaign-runtime.service'],check=True)
  subprocess.run(['systemctl','restart','fs-campaign-runtime.service'],check=True)
  subprocess.run(['systemctl','is-active','--quiet','fs-campaign-runtime.service'],check=True)
 elif any(r['candidate'] in RUNTIME_SPECIAL for r in manifest['files']):
  subprocess.run(['systemctl','stop','fs-campaign-runtime.service'],check=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 if set(manifest.get('targets',{})).intersection(STATS_SPECIAL):
  timer='fs-campaign-statistics-refresh.timer';service='fs-campaign-statistics-refresh.service'
  if all(Path(p).exists() for p in STATS_SPECIAL.values()):
   subprocess.run(['systemctl','enable',timer],check=True)
   subprocess.run(['systemctl','start',timer],check=True)
  else:
   subprocess.run(['systemctl','stop',timer,service],check=False)
   subprocess.run(['systemctl','disable',timer],check=False)

m.QUERY_SCOPE=SCOPE;m.target_for=target;m.expected_files=expected;m.validate=validate;m.guards=guards;m.restart_for=restart
if __name__=='__main__':m.main()
