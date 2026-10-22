"""Clarify the existing page labels without restarting pricing services."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('fc_v2_existing_publisher',HERE/'fc_v2_release_adapter.py')
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
adapter.HERE=HERE;adapter.SCOPE='fc-pricing-v2-margin-labels-20261022'
adapter.TARGETS={'source/fc27-coins.html':'/var/www/dashboard/fc27-coins.html'}
adapter.NEW=frozenset();adapter.RESTART_FC=False
if __name__=='__main__':adapter.load_base().main()
