"""FC V3 code release through the existing FS publisher and original FC locks."""
from contextlib import contextmanager, closing, ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
import types
import urllib.request

from target_map import DELTA_NAMES, DELTA_SCOPE, SHADOW_NAMES, SHADOW_SCOPE, targets

HERE = Path(__file__).resolve().parent
SCOPE = 'fc-pricing-v3-20261026'
# Exact Git LF normalization of the frozen original publisher (raw CRLF SHA 1d070ee8...).
BASE_SHA = '57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840'
FC_PUBLISHER = Path('/var/lib/fc27-cloud/maintenance/local-collection-20261017/publish.py')
FC_SHA = 'b811b3adc8d4fd13e53f252b61292f79d30a7e73e0fdac4df83fc8d183ba2f8e'
SOURCE = HERE.parent / 'candidate/source' if (HERE.parent / 'candidate/source').exists() else HERE.parent / 'source'
TARGETS = {'source/' + name: path for name, path in targets(SOURCE).items()}
DELTA_TARGETS = {name: TARGETS[name] for name in DELTA_NAMES}
SHADOW_TARGETS = {name: TARGETS[name] for name in SHADOW_NAMES}


def restart_with_hermes_readiness(base, original_restart, manifest, admission_fence):
    scope = manifest.get('scope')
    worker_deadline = time.monotonic() + 60 if scope == base.HERMES_WORKER_SCOPE else None
    try:
        return original_restart(manifest, admission_fence)
    except ValueError as exc:
        if scope != base.HERMES_WORKER_SCOPE or admission_fence is None or \
                str(exc) != 'Hermes worker health failed':
            raise
        # The frozen publisher probes this same endpoint for about five seconds.
        # A Docker cold start can take longer; keep its admission fence and
        # require the same authenticated capabilities contract before release.
        key_path = base.rooted(admission_fence.root, '/run/fs-hermes-fc/api-key')
        base.no_target_link(key_path)
        key = key_path.read_text('ascii').strip()
        request = urllib.request.Request(
            'http://127.0.0.1:8941/v1/capabilities',
            headers={'Authorization': 'Bearer ' + key})
        while time.monotonic() < worker_deadline:
            if subprocess.run(['systemctl', 'is-active', '--quiet', 'fs-hermes-fc.service'],
                              check=False, timeout=10).returncode == 0:
                try:
                    with urllib.request.urlopen(request, timeout=1) as response:
                        raw = response.read(128001)
                        if len(raw) > 128000 or not isinstance(json.loads(raw), dict):
                            raise ValueError('Hermes capabilities contract')
                        return
                except OSError:
                    pass
            time.sleep(min(1, max(0, worker_deadline - time.monotonic())))
        raise ValueError('Hermes worker health failed after 60s') from exc


def checked_manifest(value):
    rows = value.get('files', [])
    scope = value.get('scope')
    expected = (TARGETS if scope == SCOPE else DELTA_TARGETS if scope == DELTA_SCOPE else
                SHADOW_TARGETS if scope == SHADOW_SCOPE else {})
    if not expected or len(rows) != len(expected) or \
            {r['candidate']: r['target'] for r in rows} != expected:
        raise ValueError('exact_fc_v3_targets_required')
    if sum(r.get('beforeSha256') is None for r in rows) != (51 if scope == SCOPE else 0):
        raise ValueError('fc_v3_new_existing_target_boundary_changed')
    if any(r.get('owner') != '0:0' or r.get('mode') not in ('0o644', '0o700', '0o750', '0o755') for r in rows):
        raise ValueError('exact_fc_v3_target_metadata_required')
    if scope == SCOPE and next(r for r in rows if r['candidate'] == 'source/reconcile_price.sh')['mode'] != '0o755':
        raise ValueError('fc_v3_reconcile_script_must_be_executable')
    if value.get('businessWrites') is not False or value.get('timersChanged') is not False:
        raise ValueError('code_release_does_not_change_business_or_timer_state')
    if value.get('releaseReady') is not True:
        raise ValueError('reviewed_code_release_required')
    return value


def load_base():
    raw = (HERE / 'release_navigation_base.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASE_SHA:
        raise ValueError('frozen_publisher_drift')
    approved = checked_manifest(json.loads((HERE / 'approved-manifest.json').read_text('utf-8')))
    scope = approved['scope']
    active_targets = TARGETS if scope == SCOPE else DELTA_TARGETS if scope == DELTA_SCOPE else SHADOW_TARGETS
    new = frozenset(r['candidate'] for r in approved['files'] if r['beforeSha256'] is None)
    source = raw.decode('utf-8')
    anchor = "r.get('beforeSha256') is None for r in files if not ("
    if source.count(anchor) != 1:
        raise ValueError('frozen_new_file_anchor_drift')
    source = source.replace(anchor,
        "r.get('beforeSha256') is None for r in files if r['candidate'] not in V3_NEW if not (", 1)
    base = types.ModuleType('frozen_fc_v3_publisher')
    base.__file__ = str(HERE / 'release_navigation_base.py')
    base.V3_NEW = new
    exec(compile(source, base.__file__, 'exec'), base.__dict__)
    base.HERMES_HISTORY_SCOPE, base.HERMES_HISTORY_TARGETS = scope, active_targets
    base.expected_files = lambda m: set(active_targets) if m.get('scope') == scope else set()
    base.target_for = lambda relative: active_targets[relative]
    validate = base.validate

    def exact_validate(manifest, stage):
        if manifest != approved:
            raise ValueError('frozen_manifest_required')
        return validate(manifest, stage)

    base.validate = exact_validate

    original_quiescent = base.hermes_quiescent

    def quiescent(root):
        original_quiescent(root)
        for path, query in (
            ('/var/lib/fs-hermes-fc/fs/conversations/conversations.db',
             "SELECT count(*) FROM turns WHERE state IN ('preparing','dispatch_unknown','queued','running','stopping')"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',
             "SELECT count(*) FROM scan_jobs WHERE state='pending'"),
            ('/var/lib/fs-hermes-fc/fs/customer-tracking/tracking.db',
             "SELECT count(*) FROM milestones WHERE state IN ('claimed','creating','dispatch_unknown','queued','running')")):
            database = base.rooted(root, path)
            base.no_target_link(database)
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                if db.execute(query).fetchone()[0]:
                    raise ValueError('active_conversation_or_tracking')
        with closing(sqlite3.connect(base.rooted(root,
                '/var/lib/fs-hermes-fc/fs/tasks.sqlite3').as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='learning_events'").fetchone():
                if db.execute("SELECT count(*) FROM learning_events WHERE state IN ('running','unknown')").fetchone()[0]:
                    raise ValueError('active_or_unreconciled_learning')

    base.hermes_quiescent = quiescent
    if hashlib.sha256(FC_PUBLISHER.read_bytes()).hexdigest() != FC_SHA:
        raise ValueError('original_fc_publisher_drift')
    fc = types.ModuleType('original_fc_publisher')
    fc.__file__ = str(FC_PUBLISHER)
    exec(compile(FC_PUBLISHER.read_bytes(), str(FC_PUBLISHER), 'exec'), fc.__dict__)
    original_locks = base.locks

    @contextmanager
    def combined_locks(root):
        if root != Path('/'):
            raise ValueError('real_existing_release_locks_required')
        with original_locks(root), ExitStack() as stack:
            import fcntl, os, stat
            stack.enter_context(fc.api.queue_mutation())
            for name in fc.tick.RETRY_LOCKS:
                path = fc.ROOT / 'state' / name
                base.no_target_link(path)
                fd = os.open(str(path), os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
                stream = stack.enter_context(os.fdopen(fd, 'r+b'))
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1:
                    raise ValueError('unsafe_original_fc_lock')
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield

    base.locks = combined_locks
    original_guards = base.guards

    def guards(manifest, root, reader_stopped=False):
        original_guards(manifest, root, reader_stopped)
        if fc.tick.retry_guard() != 'ready' or fc.api.health()['incomplete_executions'] != 0:
            raise ValueError('original_fc_execution_not_quiescent')
        for row in manifest['files']:
            path = base.rooted(root, row['target'])
            if path.exists():
                info = path.stat()
                if info.st_uid != 0 or info.st_gid != 0 or oct(info.st_mode & 0o777) != row['mode']:
                    raise ValueError('fc_v3_target_metadata_drift')

    base.guards = guards
    original_atomic = base.atomic

    def atomic(path, data, mode=0o644):
        if str(path) == '/opt/fc27-cloud-browser/reconcile_price.sh':
            mode = 0o755
        return original_atomic(path, data, mode)

    base.atomic = atomic
    original_restart = base.restart_for

    def restart(manifest, admission_fence=None):
        restart_with_hermes_readiness(base, original_restart, manifest, admission_fence)
        if manifest.get('scope') in (SCOPE, DELTA_SCOPE, SHADOW_SCOPE):
            subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
            for name in ('fc27-cloud-api.service', 'fc27-cloud-worker.service'):
                subprocess.run(['systemctl', 'restart', name], check=True, timeout=30)
                subprocess.run(['systemctl', 'is-active', '--quiet', name], check=True, timeout=10)

    base.restart_for = restart
    return base


if __name__ == '__main__':
    load_base().main()
