"""One187 fallback after the original source lease/permits, never an alternate-IP retry pool."""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import time
import uuid

from .adapters import RestrictedHTTP
from .contracts import instant
from .public_sources import REGISTRY, arab_adapter
from .worker import Worker

LOCAL_STATE = Path('/var/lib/fc27-cloud/collection-local')


@contextmanager
def local_worker_lock(path):
    import fcntl
    descriptor = os.open(str(path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError('collection_local_lock_invalid')
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def run_fallback(coordinator, task, routing):
    from .client import read_routing, source_ready, utc
    routing = dict(routing)
    source = source_ready(coordinator, routing)
    if '187' not in source['nodes']:
        raise ValueError('collection_local_not_assigned')
    if LOCAL_STATE.is_symlink():
        raise ValueError('collection_local_state_invalid')
    LOCAL_STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with local_worker_lock(LOCAL_STATE / 'worker.lock'):
        if read_routing() != routing or utc() >= instant(task['deadline_at']):
            raise ValueError('collection_routing_changed_or_expired')
        coordinator.quarantine_node('183', utc(), 60)
        principal = dict(node_id='187', node_boot_id=uuid.uuid4().hex)
        coordinator.register_node(principal, ['ArabUT'], utc())
        worker = Worker(coordinator, principal, {'ArabUT': arab_adapter}, LOCAL_STATE / 'spool',
                        RestrictedHTTP(REGISTRY).fetch, clock=utc)
        while utc() < instant(task['deadline_at']):
            if read_routing() != routing:
                raise ValueError('collection_routing_changed')
            source_ready(coordinator, routing)
            with coordinator.transaction() as db:
                state = db.execute('SELECT state FROM collection_jobs WHERE id=?', (task['job_id'],)).fetchone()[0]
                current = coordinator._get(db, 'collection_jobs', task['job_id'])
            if state in ('COMPLETED', 'EXPIRED') or state == 'RETRY_WAIT' and current['attempts'] >= current['total_attempt_limit']:
                return
            attempted = current.get('node_id') == '187' and current['attempts'] > 0
            result = worker.run_once(job_id=task['job_id'], allow_claim=not attempted)
            if result.get('status') != 'idle':
                with coordinator.transaction() as db:
                    observed = db.execute('SELECT job FROM collection_observations WHERE id=?', (result['observation_id'],)).fetchone()
                if observed and observed[0] == task['job_id']:
                    return
                continue
            if attempted:
                return
            time.sleep(min(5, max(0, (instant(task['deadline_at']) - utc()).total_seconds())))
