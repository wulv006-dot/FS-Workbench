"""Replace only the current business contract through the original publisher."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE;adapter.SCOPE='fc-pricing-v2-knowledge-clarity-20261022'
adapter.TARGETS={'source/business-baseline.md':'/opt/fs-hermes-fc/business-baseline.md'}
adapter.NEW=frozenset();adapter.RESTART_FC=False
if __name__=='__main__':adapter.load_base().main()
