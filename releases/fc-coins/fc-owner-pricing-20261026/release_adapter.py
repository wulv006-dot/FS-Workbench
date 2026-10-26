"""Exact owner policy update through the existing FC/Hermes CAS publisher."""
import importlib.util
from copy import deepcopy
from pathlib import Path
HERE=Path(__file__).resolve().parent
TARGETS={**{'source/'+n:'/opt/fc27-cloud-browser/'+n for n in ('pricing_v2.py','server_quote_job.py','pricing_state.py','hermes_pricing_bridge.py')},
 'source/pricing_simulation.py':'/opt/fs-hermes-fc/pricing_simulation.py','source/pricing_probe.py':'/opt/fs-pricing-alerts/pricing_probe.py',
 'source/fc27-quote-cloud.js':'/var/www/dashboard/fc27-quote-cloud.js','source/fc27-coins.html':'/var/www/dashboard/fc27-coins.html'}
def load_base():
 spec=importlib.util.spec_from_file_location('house_fc_release',HERE/'fc_v2_release_adapter.py');adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
 adapter.HERE=HERE;adapter.SCOPE='fc-owner-pricing-20261026';adapter.RESTART_FC=True;adapter.TARGETS=TARGETS;adapter.NEW=frozenset()
 original=adapter.checked_manifest
 def exact_manifest(value):
  checked=deepcopy(value)
  for row in checked.get('files',[]):
   if row['candidate']=='source/pricing_probe.py' and row['target']=='/opt/fs-pricing-alerts/pricing_probe.py' and row.get('mode')=='0o600':row['mode']='0o644'
  original(checked)
  if next(r for r in value['files'] if r['candidate']=='source/pricing_probe.py')['mode']!='0o600':raise ValueError('preserve_existing_probe_mode')
  return value
 adapter.checked_manifest=exact_manifest
 return adapter.load_base()
if __name__=='__main__':load_base().main()
