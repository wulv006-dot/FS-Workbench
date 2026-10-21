"""One existing API target through the original FC/FS publisher."""
import importlib.util
from pathlib import Path

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE
adapter.SCOPE='fc-pricing-v2-publication-receipt-20261022'
adapter.TARGETS={'source/fc27_cloud_api.py':'/opt/fc27-cloud-browser/fc27_cloud_api.py',
                 'source/pricing_sources.py':'/opt/fc27-cloud-browser/pricing_sources.py',
                 'source/business-baseline.md':'/opt/fs-hermes-fc/business-baseline.md'}
adapter.NEW=frozenset()

if __name__=='__main__':adapter.load_base().main()
