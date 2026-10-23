"""Read original pricing receipts; never collect prices, log in or replay writes."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

STATE = Path('/var/lib/fs-pricing-alerts')
PROFILE = Path('/var/lib/fs-hermes-fc/profile/ops-watchdog')
DB = Path('/opt/d4follow/data/iggm_follow.db')
CACHE_RECOVERY = Path('/var/lib/fs-order-session/rpg-cache-recovery-20261023.json')


def read(path, default=None):
    try:
        if path.is_symlink() or path.stat().st_size > 4*1024*1024:
            raise ValueError('bounded_regular_receipt_required')
        return json.loads(path.read_text('utf-8'))
    except FileNotFoundError:
        return default


def classify_jobs(rows, baseline, retained):
    """An unrelated successful collection cannot acknowledge a price write."""
    unresolved = dict(retained)
    legacy = []
    for row in rows:
        jid = row['id']
        if not re.fullmatch(r'J[0-9]{14}(?:-[0-9]+)?', jid):
            raise ValueError('original_job_id_required')
        result = json.loads(row['result_json'] or '{}')
        if not isinstance(result, dict):
            raise ValueError('job_result_shape')
        state = result.get('write_state')
        reason = None
        if state in ('unknown', 'partial'):
            reason = state
        elif jid in baseline and not state:
            if row['status'] == 'failed' or (result.get('clearcache_wanted') is True and result.get('clearcache_ok') is not True):
                legacy.append(jid)
                if unresolved.get(jid) in ('cache_failed', 'cache_unconfirmed'):
                    unresolved.pop(jid)
                continue
        elif jid not in baseline and result.get('clearcache_wanted') is True and result.get('clearcache_ok') is not True:
            reason = 'cache_failed' if result.get('clearcache_ok') is False else 'cache_unconfirmed'
        elif row['status'] == 'failed':
            reason = 'write_failed' if state else 'execution_unclassified'
        elif result.get('fail') or result.get('mismatch'):
            reason = 'row_verification_failed'
        elif row['status'] == 'done' and state == 'confirmed':
            if result.get('operation_id') != jid or result.get('original_job_id') != jid:
                reason = 'receipt_identity_mismatch'
            elif not result.get('clearcache_wanted') or result.get('clearcache_ok') is True:
                unresolved.pop(jid, None)
        if reason:
            unresolved[jid] = reason
    return unresolved, legacy


def rpg_rows(db=DB):
    with sqlite3.connect('file:'+str(db)+'?mode=ro', uri=True, timeout=2) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.row_factory = sqlite3.Row
        rows = conn.execute('SELECT id,status,result_json FROM local_job ORDER BY id DESC LIMIT 2001').fetchall()
    if len(rows) > 2000:
        raise ValueError('job_scan_coverage_limit')
    return [dict(row) for row in rows]


def reconcile_cache(unresolved, receipt):
    response = receipt.get('response') or {}
    jid = receipt.get('original_job_id')
    if (receipt.get('status') == 'verified' and receipt.get('price_requests') == 0
            and receipt.get('original_clearcache_ok') is False
            and type(receipt.get('original_backend_writes')) is int
            and receipt['original_backend_writes'] >= 0
            and response.get('http') == 200 and response.get('code') == 1
            and response.get('confirmed') is True
            and unresolved.get(jid) in ('cache_failed', 'cache_unconfirmed')):
        unresolved.pop(jid)
    return unresolved


def browser_memory():
    template = ('{"id":{{json .Id}},"restart_count":{{.RestartCount}},'
                '"started_at":{{json .State.StartedAt}},"running":{{.State.Running}},'
                '"oom_killed":{{.State.OOMKilled}},"limit":{{.HostConfig.Memory}}}')
    value = json.loads(subprocess.check_output(
        ['docker','inspect','--format',template,'fc27-cloud-browser'], text=True, timeout=5))
    cid = value['id']
    if not re.fullmatch('[a-f0-9]{64}', cid):
        raise ValueError('container_identity')
    root = Path('/sys/fs/cgroup/memory/docker')/cid
    stat = dict(line.split() for line in (root/'memory.stat').read_text().splitlines())
    value.update(usage_bytes=int((root/'memory.usage_in_bytes').read_text()),
                 rss_bytes=int(stat['total_rss']), cache_bytes=int(stat['total_cache']))
    return value


def collect(now, previous, baseline, raw, rows, memory, cache_receipt=None, lifecycle=None, extra_issues=()):
    issues = []
    legacy_codes = set(previous.get('legacy_issue_codes', []))
    for issue in raw.get('issues', []):
        if issue.get('level') != 'critical':
            continue
        code = issue['code']
        legacy_codes.add(code)
        prefix = 'rpg_pricing_' if code.startswith(('rpg_', 'd4_', 'poe2_', 'aion2_')) else 'fc_pricing_'
        issues.append(prefix+code)
    for code in extra_issues:
        if not code.startswith('coin_') and code != 'business_write_unresolved':
            raise ValueError('pricing_extra_code_required')
        legacy_codes.add(code)
        issues.append('fc_pricing_'+code)
    if raw.get('status') == 'unverified':
        issues.append('pricing_monitor_fc_probe_unverified')
    for operation in raw.get('unknown_operations') or []:
        import uuid
        if str(uuid.UUID(operation['operation_id'])) != operation['operation_id']:
            raise ValueError('original_operation_id_required')
        issues.append('fc_pricing_unresolved:'+operation['operation_id'])
    unresolved, legacy = classify_jobs(rows, baseline, previous.get('rpg_unresolved', {}))
    reconcile_cache(unresolved, cache_receipt or {})
    issues += ['rpg_pricing_'+reason+':'+jid for jid,reason in sorted(unresolved.items())]
    if not memory['running']:
        issues.append('fc_pricing_browser_stopped')
    if memory['usage_bytes'] >= 1536*1024*1024:
        issues.append('fc_pricing_browser_memory_high')
    lifecycle = lifecycle or {}
    if lifecycle.get('transport_failed_at') is not None:
        issues.append('fc_pricing_actual_browser_connection_failed')
    if lifecycle.get('state') == 'unknown':
        issues.append('fc_pricing_browser_recovery_unknown:'+str(lifecycle.get('event_id')))
    planned_verified = (lifecycle.get('startup_source_sha256') is not None
                        and lifecycle.get('state') in ('verified', 'verified_after_unknown', 'verified_after_readonly_reconciliation')
                        and lifecycle.get('reconciled_container', {}).get('started_at') == memory['started_at'])
    old_memory = previous.get('memory', {})
    restart = old_memory and (memory['restart_count'] > old_memory.get('restart_count', 0)
                             or memory['started_at'] != old_memory.get('started_at'))
    # A restart is an event even when the browser is healthy again at observation time.
    recovery_event = previous.get('browser_restart_event')
    if restart:
        recovery_event = {'started_at':memory['started_at'], 'restart_count':memory['restart_count'],
                          'oom_killed':memory['oom_killed'], 'observed_at':now.isoformat()}
    if recovery_event and planned_verified and recovery_event['started_at'] == memory['started_at']:
        recovery_event = dict(recovery_event, planned_startup_acceptance_verified=True)
    if recovery_event and not recovery_event.get('planned_startup_acceptance_verified') and (now-datetime.fromisoformat(recovery_event['observed_at'])).total_seconds() < 600:
        issues.append('fc_pricing_browser_restarted:'+recovery_event['started_at'])
    return dict(exported_at=now.isoformat(), issues=sorted(set(issues)),
                legacy_issue_codes=sorted(legacy_codes),
                rpg_unresolved=unresolved, legacy_unclassified=legacy,
                memory=memory, browser_restart_event=recovery_event,
                fc_job=raw.get('coin', {}).get('job', {}),
                source_scope='original_jobs_and_receipts_only')


def main():
    import fcntl
    sys.path.insert(0, '/opt/fc-ops-readonly-monitor')
    from collector import atomic, probe
    sys.path.insert(0, '/opt/fs-hermes-ops')
    from common import assess
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE/'lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        now = datetime.now(timezone.utc)
        previous = read(STATE/'latest.json', {})
        baseline = read(STATE/'legacy-baseline.json')
        if baseline is None:
            raise ValueError('reviewed_legacy_baseline_required')
        try:
            raw = probe()
            raw_codes = {item['code'] for item in raw.get('issues', [])}
            extras = [code for code in assess(raw, now) if code not in raw_codes
                      and (code.startswith('coin_') or code == 'business_write_unresolved')]
            value = collect(now, previous, baseline['job_ids'], raw, rpg_rows(), browser_memory(), read(CACHE_RECOVERY, {}),
                            read(Path('/var/lib/fc27-cloud/state/browser-lifecycle.json'), {}), extras)
        except Exception as error:
            value = dict(previous, exported_at=now.isoformat(),
                         issues=sorted(set(previous.get('issues', []) + ['pricing_monitor_read_failed:'+type(error).__name__])))
        atomic(STATE/'latest.json', value)
        # Original IDs and per-minute samples retain both healthy and failed natural cycles.
        sample = now.strftime('%Y%m%dT%H%M')
        atomic(STATE/'samples'/(sample+'.json'), value)
        for old in sorted((STATE/'samples').glob('*.json'))[:-20160]:
            old.unlink()
        atomic(PROFILE/'pricing-snapshot.json', value)
        result = subprocess.run(['docker','exec','-u','0','fs-hermes-desktop','/opt/hermes/.venv/bin/python','-B',
                                 '/profile/scripts/fs-ops-watchdog/watch.py','pricing-check'],
                                capture_output=True, text=True, timeout=35)
        atomic(STATE/'last-delivery.json', {'checked_at':now.isoformat(), 'exit_code':result.returncode,
                                          'result':result.stdout[-1200:], 'stderr_type':bool(result.stderr)})
        if result.returncode:
            raise RuntimeError('original_notification_needs_reconciliation')


if __name__ == '__main__':
    main()
