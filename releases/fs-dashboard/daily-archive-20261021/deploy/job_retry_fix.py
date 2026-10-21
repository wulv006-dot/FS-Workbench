"""Update only the next-invocation CLI; no running service or timer is restarted."""
import release
SCOPE='fs-archive-job-retry-20261022'
TARGETS={'runtime/archive_jobs.py':'/opt/fs-exact-range-20261001/archive_jobs.py'}


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    release.AUTHORIZED_TIMERS=frozenset()
    base=release.load_base()
    def next_invocation(manifest,admission_fence=None):
        if admission_fence is None:raise ValueError('archive admission fence required')
    base.restart_for=next_invocation
    return base


if __name__=='__main__':load_base().main()
