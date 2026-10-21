"""Three copies of the single shared archive module, using existing publisher guards."""
import subprocess
import release
SCOPE='fs-daily-archive-metrics-fix-20261022'
TARGETS={'runtime/daily_archive.py':'/opt/fs-exact-range-20261001/daily_archive.py',
 'hermes/daily_archive.py':'/opt/fs-hermes-fc/daily_archive.py',
 'marketing/daily_archive.py':'/opt/mmoexp-marketing/custom-range/daily_archive.py'}


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    release.AUTHORIZED_TIMERS=frozenset()
    base=release.load_base();restart=base.restart_for
    def reload_readers(manifest,admission_fence=None):
        restart(manifest,admission_fence)
        if manifest.get('scope')==SCOPE:subprocess.run(['systemctl','restart','fs-marketing-range.service'],check=True,timeout=40)
    base.restart_for=reload_readers
    return base


if __name__=='__main__':load_base().main()
