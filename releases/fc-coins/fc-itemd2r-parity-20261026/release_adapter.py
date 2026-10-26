"""Exact temporary reference update through the existing FC/Hermes CAS publisher."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
TARGETS={'source/pricing_v2.py':'/opt/fc27-cloud-browser/pricing_v2.py','source/hermes_pricing_bridge.py':'/opt/fc27-cloud-browser/hermes_pricing_bridge.py','source/pricing_simulation.py':'/opt/fs-hermes-fc/pricing_simulation.py','source/fc27-quote-cloud.js':'/var/www/dashboard/fc27-quote-cloud.js','source/fc27-coins.html':'/var/www/dashboard/fc27-coins.html'}
def load_base():
 spec=importlib.util.spec_from_file_location('house_fc_release',HERE/'fc_v2_release_adapter.py');adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
 adapter.HERE=HERE;adapter.SCOPE='fc-itemd2r-parity-20261026';adapter.RESTART_FC=True;adapter.TARGETS=TARGETS;adapter.NEW=frozenset()
 return adapter.load_base()
if __name__=='__main__':load_base().main()
