"""Two exact static files through the existing FC CAS publisher."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCOPE = 'fc-request-rejection-recovery-20261026'
TARGETS = {
    'source/fc27-quote-cloud.js': '/var/www/dashboard/fc27-quote-cloud.js',
    'source/fc27-coins.html': '/var/www/dashboard/fc27-coins.html',
}


def load_base():
    spec = importlib.util.spec_from_file_location('house_fc_release', HERE / 'fc_v2_release_adapter.py')
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.HERE = HERE
    adapter.SCOPE = SCOPE
    adapter.RESTART_FC = False
    adapter.TARGETS = TARGETS
    adapter.NEW = frozenset()
    base = adapter.load_base()

    # The base aliases this scope to Hermes history for manifest validation;
    # its transaction collector lock does not guard these two FC static files.
    @contextmanager
    def static_live_lock(manifest, root):
        if manifest.get('scope') != SCOPE or {r['target'] for r in manifest['files']} != set(TARGETS.values()):
            raise ValueError('exact_static_scope_required')
        yield

    base.live_lock = static_live_lock

    def no_restart(manifest, admission_fence=None):
        if manifest.get('scope') != SCOPE:
            raise ValueError('exact_static_scope_required')

    base.restart_for = no_restart
    return base


if __name__ == '__main__':
    load_base().main()
