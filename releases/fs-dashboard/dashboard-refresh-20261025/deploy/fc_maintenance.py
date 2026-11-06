"""FC-only, before-write range stop over the existing CAS/journal publisher.

This is a controlled read outage, not graceful completion of HTTP/background
queries. The approved window must allow systemd to cancel those reads. No
timer, writer, P0 service, unit definition or range source is changed.
"""
from contextlib import contextmanager
from functools import wraps
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.request

SCOPE = 'fc-dashboard-20261106'
RANGE = 'fs-business-range.service'


class RangeControl:
    def __init__(self, root):
        if Path(root).resolve() != Path('/'):
            raise ValueError('fc_live_control_requires_system_root')
        self.before = None
        self.group = None
        self.allow_stopped = False

    def state(self):
        keys = ('LoadState', 'ActiveState', 'SubState', 'MainPID', 'ControlPID',
                'UnitFileState', 'KillMode', 'SendSIGKILL', 'ControlGroup', 'TimeoutStopUSec',
                'Job', 'TriggeredBy', 'Triggers')
        output = subprocess.check_output(['systemctl', 'show', RANGE, '--no-pager',
            *['--property=' + key for key in keys]], text=True, timeout=10)
        return dict(line.split('=', 1) for line in output.splitlines() if '=' in line)

    def remember(self, manifest):
        expected = manifest.get('maintenanceBefore', {})
        if set(expected) != {RANGE}:
            raise ValueError('fc_exact_range_maintenance_required')
        previous = expected[RANGE]
        required = {'ActiveState', 'UnitFileState', 'KillMode', 'SendSIGKILL', 'TimeoutStopUSec'}
        if (not isinstance(previous, dict) or not required <= set(previous)
                or previous['ActiveState'] != 'active'
                or manifest.get('runtimeRequired', {}).get(RANGE, {}).get('ActiveState') != 'active'):
            raise ValueError('fc_original_range_state_required')
        self.before = self.state()
        recovering_stopped = self.allow_stopped and self.before.get('ActiveState') == 'inactive'
        if any(self.before.get(key) != value for key, value in previous.items()
               if not (recovering_stopped and key == 'ActiveState')):
            raise ValueError('fc_original_range_state_drift')
        if not recovering_stopped:
            self._running()
        if (self.before.get('KillMode') != 'control-group'
                or self.before.get('SendSIGKILL') != 'yes'
                or self.before.get('ControlGroup') not in
                    (('', '/system.slice/' + RANGE) if recovering_stopped else ('/system.slice/' + RANGE,))):
            raise ValueError('fc_range_control_group_required')
        # Pin the controller while the known live unit exists. Missing membership
        # files cannot be mistaken for an empty group after stopping the unit.
        relative = 'system.slice/' + RANGE
        for controller in (Path('/sys/fs/cgroup'), Path('/sys/fs/cgroup/systemd')):
            group = controller / relative
            if ((group / 'cgroup.procs').is_file() or
                    recovering_stopped and (controller / 'cgroup.procs').is_file()):
                self.group = group
                break
        if self.group is None:
            raise ValueError('fc_range_cgroup_unavailable')
        if recovering_stopped:
            self.stopped()

    def _running(self):
        state = self.state()
        self._no_pending_job_or_trigger(state)
        if (state.get('LoadState') != 'loaded' or state.get('ActiveState') != 'active'
                or state.get('SubState') != 'running'
                or not state.get('MainPID', '').isascii()
                or not state.get('MainPID', '').isdecimal() or int(state['MainPID']) <= 0
                or state.get('ControlPID') != '0'):
            raise ValueError('fc_range_not_running')
        return state

    @staticmethod
    def _no_pending_job_or_trigger(state):
        # CentOS systemd reports an empty Job for no pending operation. Some
        # versions report 0. A timed-out client does not cancel its systemd job.
        if 'Job' not in state or state['Job'] not in ('', '0'):
            raise ValueError('fc_range_systemd_job_pending_or_unknown')
        if state.get('TriggeredBy') != '' or state.get('Triggers') != '':
            raise ValueError('fc_range_automatic_trigger_not_allowed')

    def stopped(self):
        state = self.state()
        self._no_pending_job_or_trigger(state)
        if (state.get('LoadState') != 'loaded' or state.get('ActiveState') != 'inactive'
                or state.get('MainPID') != '0' or state.get('ControlPID') != '0'
                or any(state.get(key) != self.before.get(key) for key in
                       ('UnitFileState', 'KillMode', 'SendSIGKILL', 'TimeoutStopUSec'))):
            raise ValueError('fc_range_stop_not_confirmed')
        if self.group is None:
            raise ValueError('fc_range_cgroup_unavailable')
        if self.group.exists():
            members = list(self.group.rglob('cgroup.procs'))
            if not members or any(path.read_text().strip() for path in members):
                raise ValueError('fc_range_cgroup_not_empty')

    def quiesce(self, fence):
        subprocess.run(['systemctl', 'stop', RANGE], check=True, timeout=110)
        self.stopped()
        # Keep the original file admission fence for the whole transaction. Only
        # release its SQLite reservation after all old unit processes are gone.
        fence.unlock_database()

    def healthy(self):
        self._running()
        with urllib.request.urlopen('http://127.0.0.1:8931/health', timeout=2) as response:
            if response.status != 200 or json.load(response).get('ok') is not True:
                raise ValueError('fc_range_health_failed')

    def restore_unchanged(self):
        # Only reached before any target replacement: original bytes are intact.
        if self.before.get('ActiveState') == 'inactive':
            self.stopped()
            return  # Failed recovery of already-stopped code must remain stopped.
        state = self.state()
        self._no_pending_job_or_trigger(state)
        if state.get('ActiveState') == 'inactive':
            subprocess.run(['systemctl', 'start', RANGE], check=True, timeout=35)
        elif state.get('ActiveState') != 'active':
            raise ValueError('fc_original_range_recovery_unknown')
        deadline = time.monotonic() + 25
        while True:
            try:
                self.healthy()
                return
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise ValueError('fc_original_range_recovery_failed') from None
                time.sleep(.1)


def extend(base, scope=SCOPE, control_factory=RangeControl):
    if scope != SCOPE or base.HERMES_HISTORY_SCOPE != scope:
        raise ValueError('fc_original_scope_not_bound')
    original_admission = base.hermes_admission_fence
    original_guards, original_rollback = base.guards, base.rollback_journal
    original_inspect = base.inspect
    original_rollback_entry = base.rollback
    owned = threading.local()

    def current(root):
        return getattr(owned, 'root', None) == Path(root).resolve()

    @contextmanager
    def admission(manifest, root):
        with original_admission(manifest, root) as fence:
            if manifest.get('scope') != scope:
                yield fence
                return
            if fence is None or current(root):
                raise ValueError('fc_original_admission_fence_required')
            control = control_factory(root)
            control.allow_stopped = getattr(owned, 'rolling_back', False)
            control.remember(manifest)
            try:
                control.quiesce(fence)
                owned.root, owned.control, owned.fence = Path(root).resolve(), control, fence
                yield fence
            finally:
                owned.root = owned.control = owned.fence = None
                if fence.modified and not fence.confirmed:
                    control.quiesce(fence)
                else:
                    try:
                        if fence.modified:
                            control.healthy()
                        else:
                            control.restore_unchanged()
                    except Exception:
                        # A failed final health/recovery check cannot reopen a
                        # known-bad or unconfirmed reader, even after hash commit.
                        fence.confirmed = False
                        control.quiesce(fence)
                        raise

    def guards(manifest, root, reader_stopped=False):
        if manifest.get('scope') != scope or not current(root):
            return original_guards(manifest, root, reader_stopped)
        owned.control.stopped()
        expected = {key: dict(value) for key, value in manifest.get('runtimeRequired', {}).items()}
        if expected.get(RANGE, {}).get('ActiveState') != 'active':
            raise ValueError('fc_original_reader_requirement_changed')
        expected[RANGE]['ActiveState'] = 'inactive'
        return original_guards(dict(manifest, runtimeRequired=expected), root, False)

    def rollback_journal(backup, journal, root):
        if journal['manifest'].get('scope') == scope:
            if not current(root):
                raise ValueError('fc_rollback_requires_stopped_reader')
            # A health/restart failure may have brought up the candidate process.
            # Stop it again before restoring even the first old target.
            owned.control.quiesce(owned.fence)
        return original_rollback(backup, journal, root)

    def inspect(manifest, stage, root=Path('/')):
        if manifest.get('scope') == scope and not current(root):
            control = control_factory(root)
            control.remember(manifest)
            control.healthy()
        return original_inspect(manifest, stage, root)

    @wraps(original_rollback_entry)
    def rollback(backup, approved_sha, root=Path('/')):
        # A previous failed rollback deliberately leaves the reader stopped. Its
        # recovery must not require starting that unconfirmed code just to enter.
        owned.rolling_back = True
        try:
            return original_rollback_entry(backup, approved_sha, root)
        finally:
            owned.rolling_back = False

    base.hermes_admission_fence, base.guards = admission, guards
    base.rollback_journal, base.inspect = rollback_journal, inspect
    base.rollback = rollback
    return base


def load_base(version=None):
    import fc_dashboard_release
    return extend(fc_dashboard_release.load_base(version))


if __name__ == '__main__':
    load_base().main()
