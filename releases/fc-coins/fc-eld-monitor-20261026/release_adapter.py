"""Existing CAS publisher, exact ELD observation files and API-only reload."""
import importlib.util
import subprocess
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
TARGETS={'source/observe.py':'/opt/fc27-price-observer/observe.py','source/eldorado.py':'/opt/fc27-price-observer/eldorado.py',
 'source/reference_observer_view.py':'/opt/fc27-cloud-browser/reference_observer_view.py',
 'source/fc27-reference-observer.js':'/var/www/dashboard/fc27-reference-observer.js','source/fc27-coins.html':'/var/www/dashboard/fc27-coins.html'}
def load_base():
 spec=importlib.util.spec_from_file_location('house_fc_release',HERE/'fc_v2_release_adapter.py');adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
 adapter.HERE=HERE;adapter.SCOPE='fc-eld-monitor-20261026';adapter.RESTART_FC=False;adapter.TARGETS=TARGETS;adapter.NEW=frozenset({'source/eldorado.py'})
 original=adapter.checked_manifest
 def exact_manifest(value):
  checked=deepcopy(value)
  for row in checked.get('files',[]):
   if row['candidate']=='source/observe.py' and row['target']==TARGETS[row['candidate']] and row.get('mode')=='0o600':row['mode']='0o644'
  original(checked)
  if next(r for r in value['files'] if r['candidate']=='source/observe.py')['mode']!='0o600':raise ValueError('private_observer_source_mode_required')
  if value.get('runtimeRequired',{}).get('fc27-price-observer.service')!={'ActiveState':'inactive'}:raise ValueError('observer_must_be_idle')
  return value
 adapter.checked_manifest=exact_manifest
 base=adapter.load_base()
 def restart(manifest,admission_fence=None):
  if manifest.get('scope')!=adapter.SCOPE:raise ValueError('exact_eld_scope_required')
  subprocess.run(['systemctl','restart','fc27-cloud-api.service'],check=True,timeout=30)
  subprocess.run(['systemctl','is-active','--quiet','fc27-cloud-api.service'],check=True,timeout=10)
 base.restart_for=restart
 return base
if __name__=='__main__':load_base().main()
