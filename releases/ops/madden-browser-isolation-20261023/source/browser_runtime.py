"""Original Madden CLI entry: one bounded worker, on-demand competitor browser."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
import urllib.request

ROOT = Path('/opt/madden-workbench')
CONTAINER = 'madden-cloud-browser'
STATE = ROOT / 'evidence/browser-runtime.json'
LOCK = ROOT / 'evidence/browser-job.lock'


def call(args, **kwargs):
    return subprocess.run(['docker', *args], capture_output=True, text=True,
                          timeout=kwargs.pop('timeout', 15), **kwargs)


def state(**patch):
    from madden_nfl_27.store import _write_json
    previous = json.loads(STATE.read_text()) if STATE.is_file() else {}
    previous.update(patch, observed_at=time.time())
    _write_json(STATE, previous)


def inspect(name):
    result = call(['inspect', name])
    if result.returncode:
        if 'No such object:' in result.stderr or 'No such container:' in result.stderr:
            return None
        raise RuntimeError('madden_container_inspect_unverified')
    return json.loads(result.stdout)[0]


def workers():
    result = call(['ps', '-q', '--filter', 'name=^madden-job-'])
    if result.returncode:
        raise RuntimeError('madden_worker_inventory_unverified')
    return result.stdout.split()


def stop_idle():
    if workers():
        return False
    current = inspect(CONTAINER)
    if not current:
        state(status='container_missing')
        raise RuntimeError('original_madden_browser_required')
    if current['State']['Running']:
        result = call(['stop', '--time', '10', CONTAINER], timeout=15)
        after = inspect(CONTAINER)
        if result.returncode or not after or after['State']['Running']:
            state(status='cleanup_unverified')
            raise RuntimeError('madden_idle_stop_unverified')
    state(status='idle_stopped', worker=None, competitor_running=False)
    return True


def release_idle():
    with open(LOCK, 'a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return stop_idle()


def needs_competitors(argv):
    return not any(value.split('=', 1)[0] in
                   ('--snapshot-out', '--targets-json', '--restore', '--from-evidence')
                   for value in argv)


def command(argv, budget, original, name, external):
    if not 1 <= budget <= 2700 or argv[:2] != ['-u', 'run_pipeline.py']:
        raise ValueError('original_madden_pipeline_required')
    network = 'container:' + original['Id'] if external else original['HostConfig']['NetworkMode']
    return ['run', '--rm', '--init', '--name', name, '--network', network,
            '--user', 'fc27chrome', '--memory', '2g', '--memory-swap', '2g',
            '--shm-size', '512m', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
            '--mount', 'type=bind,src=' + str(ROOT) + ',dst=' + str(ROOT),
            '--workdir', str(ROOT), '--env', 'MADDEN_ISOLATED_BACKEND=1',
            '--env', 'MADDEN_CDP_ENDPOINT=' + ('http://127.0.0.1:9222' if external else ''),
            '--env', 'TMPDIR=' + str(ROOT / 'tmp'), '--env', 'TZ=Asia/Shanghai',
            '--entrypoint', 'timeout', original['Image'], '--signal=TERM', '--kill-after=1s',
            str(budget) + 's', 'python3', *argv]


def run(argv, budget):
    # Lock spans all original CLI work; idle maintenance cannot stop an active job.
    with open(LOCK, 'a+b') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = inspect(CONTAINER)
        if not original or not re.fullmatch(r'sha256:[a-f0-9]{64}', original['Image']):
            raise RuntimeError('original_madden_browser_required')
        external = needs_competitors(argv)
        name = 'madden-job-' + uuid.uuid4().hex
        worker_command = command(argv, budget, original, name, external)
        if workers():
            raise RuntimeError('madden_previous_worker_still_running')
        state(status='preparing', worker=name, backend='isolated_ephemeral_chrome')
        try:
            if external:
                result = call(['start', CONTAINER])
                if result.returncode:
                    raise RuntimeError('madden_competitor_start_unverified')
                deadline = time.monotonic() + 12
                while True:
                    try:
                        with urllib.request.urlopen('http://127.0.0.1:9232/json/version', timeout=2) as response:
                            if json.load(response).get('webSocketDebuggerUrl'):
                                break
                    except (OSError, ValueError):
                        pass
                    if time.monotonic() >= deadline:
                        raise RuntimeError('madden_competitor_not_ready')
                    time.sleep(0.25)
            state(status='running', competitor_running=external)
            # Original argv/operation ID and stdout are unchanged. The container timeout
            # survives a killed host CLI; the original scheduler performs later idle cleanup.
            result = subprocess.run(['docker', *worker_command])
            remaining = inspect(name)
            if remaining and remaining['State']['Running']:
                state(status='worker_exit_unverified')
                raise RuntimeError('madden_worker_exit_unverified')
            if remaining:
                removed = call(['rm', name])
                if removed.returncode:
                    raise RuntimeError('madden_worker_cleanup_unverified')
            return result.returncode
        finally:
            # This stops only the competitor container, never the Order identity browser.
            # A still-running owned worker keeps its network browser until its own deadline.
            stop_idle()


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:], int(os.environ.get('MADDEN_PIPELINE_TIMEOUT', '2700'))))
