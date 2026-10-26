"""Independent read-only consumer of the production V3 outbox."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import os
import logging
from pathlib import Path
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fc_pricing_v3.simulation import LOCAL, Shadow


PRODUCTION = Path('/var/lib/fc27-cloud/v3/control.sqlite3')
SHADOW = Path('/var/lib/fc-pricing-v3-shadow/shadow.sqlite3')
LOG = logging.getLogger('fc_pricing_v3.shadow')


def maintenance_cutoff(now):
    local = now.astimezone(LOCAL)
    if (local.hour, local.minute) < (0, 10):
        return None
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def tick(shadow, production_path, now, last_maintenance=None):
    result = shadow.consume(production_path)
    cutoff = maintenance_cutoff(now)
    if cutoff and cutoff != last_maintenance:
        if shadow.summary(cutoff):
            shadow.prune(now)
            last_maintenance = cutoff
    return result, last_maintenance


def validate_shadow_state(path):
    if os.name != 'posix' or Path(path) != SHADOW:
        return
    state = path.parent.stat()
    if (state.st_uid != os.geteuid() or state.st_gid != os.getegid() or
            state.st_mode & 0o7777 != 0o2750):
        raise RuntimeError('shadow_state_permissions_invalid')


@contextmanager
def single_consumer(path):
    if os.name != 'posix':
        yield
        return
    import fcntl
    with Path(path).open('a+b') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('shadow_consumer_already_running') from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def run(production_path=PRODUCTION, shadow_path=SHADOW, interval=15, sleep=time.sleep):
    validate_shadow_state(shadow_path)
    with single_consumer(Path(shadow_path).parent / 'worker.lock'):
        shadow = Shadow(shadow_path)
        last_maintenance = None
        while True:
            try:
                result, last_maintenance = tick(shadow, production_path, datetime.now(timezone.utc), last_maintenance)
                if result['status'] != 'processed':
                    LOG.warning('shadow consumption deferred: %s', result)
                if result['events'] == 100:
                    continue
            except Exception:
                LOG.exception('shadow consumption failed; durable cursor retained for retry')
            sleep(interval)


def main():
    parser = argparse.ArgumentParser(description='FC Pricing V3 read-only shadow consumer')
    parser.add_argument('--production-db', type=Path, default=PRODUCTION)
    parser.add_argument('--shadow-db', type=Path, default=SHADOW)
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    if not 1 <= args.interval <= 300:
        parser.error('interval must be 1 to 300 seconds')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    run(args.production_db, args.shadow_db, args.interval)


if __name__ == '__main__':
    main()
