"""Final acceptance fixes through the same publisher and scoped tool restart."""
import subprocess
import release_tools as tools
adapter=tools.adapter

adapter.SCOPE='fs-user-analytics-acceptance-recovery-20261023'
adapter.TARGETS={
    **adapter.TARGETS,
    'runtime/user_jobs.py':'/opt/fs-hermes-fc/user_jobs.py',
    'units/fs-user-analytics.service':'/etc/systemd/system/fs-user-analytics.service',
    'ui/users.js':'/var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js',
}
adapter.NEW=frozenset()
adapter.AUTHORIZED_TIMERS=frozenset(['/etc/systemd/system/fs-user-analytics.service'])


def load_base():
    base=tools.load_base()
    restart=base.restart_for
    def reload_job(manifest,admission_fence=None):
        if manifest.get('scope')!=adapter.SCOPE:
            return restart(manifest,admission_fence)
        if admission_fence is None:raise ValueError('existing_admission_fence_required')
        restart(manifest,admission_fence)
        subprocess.run(['systemctl','daemon-reload'],check=True,timeout=20)
        subprocess.run(['systemctl','is-active','--quiet','fs-user-analytics.timer'],check=True)
    base.restart_for=reload_job
    return base


if __name__=='__main__':load_base().main()
