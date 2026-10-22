"""Four existing UI and receipt targets through the original FC/FS publisher."""
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE
adapter.SCOPE='fc-pricing-v2-completion-ui-20261022'
adapter.TARGETS={'source/pricing_operations.py':'/opt/fs-hermes-fc/pricing_operations.py',
                 'source/pricing_state.py':'/opt/fc27-cloud-browser/pricing_state.py',
                 'source/fc27-quote-cloud.js':'/var/www/dashboard/fc27-quote-cloud.js',
                 'source/fc27-coins.html':'/var/www/dashboard/fc27-coins.html'}
adapter.NEW=frozenset()

if __name__=='__main__':adapter.load_base().main()
