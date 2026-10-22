"""Both user-approved margin floors through the original CAS publisher."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE;adapter.SCOPE='fc-pricing-v2-dual-margin-20261022'
adapter.TARGETS={
 **{'source/'+n:'/opt/fc27-cloud-browser/'+n for n in ('pricing_v2.py','pricing_sources.py','hermes_pricing_bridge.py','restore_price.py','fc_observer.py')},
 **{'source/'+n:'/opt/fs-hermes-fc/'+n for n in ('pricing_simulation.py','pricing_operations.py','business-baseline.md','pricing_workflow.py')},
 **{'source/'+n:'/var/www/dashboard/'+n for n in ('fc27-coins.html','fc27-quote-cloud.js')},
}
adapter.NEW=frozenset()
if __name__=='__main__':adapter.load_base().main()
