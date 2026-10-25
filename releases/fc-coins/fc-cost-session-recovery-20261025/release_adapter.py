"""Cost-only cold-loaded files on the original publisher and original FC locks."""
import importlib.util
from pathlib import Path
HERE=Path(__file__).resolve().parent
SCOPE='fc-cost-session-recovery-20261025'


def load_base():
    spec=importlib.util.spec_from_file_location('original_adapter',HERE/'fc_v2_release_adapter.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    adapter.HERE=HERE;adapter.SCOPE=SCOPE;adapter.RESTART_FC=False
    adapter.TARGETS={
        'source/collect_p2pah_cost.py':'/opt/fc27-cloud-browser/collect_p2pah_cost.py',
        'source/collect_p2pah_cost.sh':'/opt/fc27-cloud-browser/collect_p2pah_cost.sh'}
    adapter.NEW=frozenset()
    base=adapter.load_base()
    # These files are loaded by the next owned executor, not by a running Hermes process.
    base.HERMES_HISTORY_SCOPE='hermes-history-update-20261018'
    base.DETAIL_SCOPE=SCOPE;base.DETAIL_TARGETS=adapter.TARGETS
    original=base.restart_for
    def restart(manifest,admission_fence=None):
        if manifest.get('scope')!=SCOPE:return original(manifest,admission_fence)
    base.restart_for=restart
    return base


if __name__=='__main__':load_base().main()
