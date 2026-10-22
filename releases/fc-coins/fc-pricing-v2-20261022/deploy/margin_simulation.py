"""Keep the qualified simulator pinned to the released v14 core."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE;adapter.SCOPE='fc-pricing-v2-margin-simulation-20261022'
adapter.TARGETS={'source/pricing_simulation.py':'/opt/fs-hermes-fc/pricing_simulation.py'}
adapter.NEW=frozenset();adapter.RESTART_FC=False
if __name__=='__main__':adapter.load_base().main()
