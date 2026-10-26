"""Four exact Hermes targets through the existing CAS/backup/quiescent publisher."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
def load_base():
 spec=importlib.util.spec_from_file_location('existing_fc_release',HERE/'fc_v2_release_adapter.py')
 adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
 adapter.HERE=HERE;adapter.SCOPE='fc-review-channel-20261026';adapter.RESTART_FC=False
 adapter.TARGETS={'source/'+name:'/opt/fs-hermes-fc/'+name for name in
                  ('proxy_gateway.py','fs_inprocess.py','conversation_service.py','hermes_worker.py')}
 adapter.NEW=frozenset()
 return adapter.load_base()
if __name__=='__main__':load_base().main()
