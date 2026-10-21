"""Two existing tool targets through the original FC/FS publisher."""
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE
adapter.SCOPE='fc-pricing-v2-original-receipts-20261022'
adapter.TARGETS={'source/pricing_operations.py':'/opt/fs-hermes-fc/pricing_operations.py',
                 'source/hermes_pricing_bridge.py':'/opt/fc27-cloud-browser/hermes_pricing_bridge.py'}
adapter.NEW=frozenset()

if __name__=='__main__':adapter.load_base().main()
