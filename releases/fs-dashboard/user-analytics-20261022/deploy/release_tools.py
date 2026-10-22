"""Four-file tool recovery over the same frozen publisher; no schedule/auth/UI changes."""
from pathlib import Path
import subprocess
import release as adapter

adapter.SCOPE='fs-user-analytics-tool-recovery-20261023'
adapter.TARGETS={
    'runtime/user_query.py':'/opt/fs-hermes-fc/user_query.py',
    'runtime/user_tools.py':'/opt/fs-hermes-fc/user_tools.py',
    'runtime/user_http.py':'/opt/fs-hermes-fc/user_http.py',
    'integration/fs_readonly.py':'/var/lib/fs-hermes-fc/profile/plugins/fs-readonly/__init__.py',
}
adapter.NEW=frozenset()
adapter.AUTHORIZED_TIMERS=frozenset()


def load_base():
    base=adapter.load_base();restart=base.restart_for
    def scoped_restart(manifest,admission_fence=None):
        if manifest.get('scope')!=adapter.SCOPE:
            return restart(manifest,admission_fence)
        if admission_fence is None:raise ValueError('existing_admission_fence_required')
        admission_fence.stop_then_unlock_database()
        restart(dict(manifest,scope=base.HERMES_WORKER_SCOPE),admission_fence)
        restart(dict(manifest,scope=base.DEEP_SCOPE),admission_fence)
        base.hermes_quiescent(Path('/'))
        subprocess.run(['systemctl','restart','fs-hermes-desktop.service'],check=True,timeout=60)
        subprocess.run(['systemctl','is-active','--quiet','fs-hermes-desktop.service'],check=True)
    base.restart_for=scoped_restart
    return base


if __name__=='__main__':load_base().main()
