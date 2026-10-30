"""One local, locked and time-bounded aggregate refresh. No credentials in argv/logs."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import uuid

try:
    import fcntl
except ImportError:
    fcntl = None


def interrupted(signum, frame):
    raise InterruptedError('RUN_INTERRUPTED')


def record_failure(directory, run_id, reason):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink() or (directory.stat().st_mode & 0o077):
        raise ValueError('INSECURE_SNAPSHOT_DIRECTORY')
    target = directory / 'status.json'
    state = {'schemaVersion': 1, 'lastSuccessfulRunAt': None}
    if target.exists():
        if target.is_symlink() or target.stat().st_size > 65536:
            raise ValueError('INVALID_SNAPSHOT_FILE')
        state = json.loads(target.read_text())
        if state.get('schemaVersion') != 1:
            raise ValueError('INVALID_SNAPSHOT_FILE')
    if state.get('lastAttempt', {}).get('runId') == run_id and state['lastAttempt'].get('status') != 'running':
        return
    now = datetime.now(timezone.utc).isoformat()
    attempt = state.get('lastAttempt', {}) if state.get('lastAttempt', {}).get('runId') == run_id else {'runId': run_id, 'startedAt': now}
    state['lastAttempt'] = {**attempt, 'status': 'failed', 'reason': reason, 'finishedAt': now}
    raw = (json.dumps(state, separators=(',', ':')) + '\n').encode()
    if len(raw) > 65536:
        raise ValueError('SNAPSHOT_SIZE_LIMIT')
    fd, name = tempfile.mkstemp(prefix='.status-', dir=str(directory))
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
        fd = os.open(str(directory), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def run(node, worker, directory, lock, timeout=390, retry_blocked=False):
    if fcntl is None:
        raise RuntimeError('POSIX_FLOCK_REQUIRED')
    flags = os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(lock), flags, 0o600)
    child = None
    run_id = str(uuid.uuid4())
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 75, {'status': 'busy', 'reason': 'STATISTICS_REFRESH_ALREADY_RUNNING'}
        args = [str(node), str(worker), '--directory', str(directory), '--run-id', run_id]
        if retry_blocked:
            args.append('--retry-blocked')
        try:
            child = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        except OSError:
            record_failure(directory, run_id, 'RUN_START_FAILED')
            return 1, {'status': 'failed', 'runId': run_id, 'reason': 'RUN_START_FAILED'}
        try:
            stdout, stderr = child.communicate(timeout=timeout)
        except (subprocess.TimeoutExpired, InterruptedError):
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.communicate(timeout=5)
            record_failure(directory, run_id, 'RUN_TIMEOUT_OR_INTERRUPTED')
            return 124, {'status': 'failed', 'runId': run_id, 'reason': 'RUN_TIMEOUT_OR_INTERRUPTED'}
        if child.returncode not in (0, 2):
            record_failure(directory, run_id, 'RUN_PROCESS_FAILED')
        # Never relay arbitrary subprocess output, stack traces or credentials to the journal.
        return child.returncode, {'status': 'success' if child.returncode == 0 else 'partial' if child.returncode == 2 else 'failed', 'runId': run_id, 'exitCode': child.returncode}
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--retry-blocked', action='store_true', help='Manual only, after the blocked source has been corrected/authorized')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    code, result = run('/usr/local/node/bin/node', '/opt/fs-campaign-dashboard/analytics/statistics-refresh.mjs',
                       '/var/lib/fs-campaign-dashboard/statistics-refresh', '/var/lock/fs-campaign-statistics-refresh.lock',
                       retry_blocked=args.retry_blocked)
    print(json.dumps(result))
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print(json.dumps({'status': 'failed', 'reason': 'STATISTICS_REFRESH_WRAPPER_FAILED'}))
        sys.exit(1)
