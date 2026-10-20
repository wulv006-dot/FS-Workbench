"""Read-only eligibility for one recovery probe per natural collection cycle.

Never clears a ledger, changes a failed job, or declares a write confirmed.
"""
from datetime import datetime, timezone
import hashlib
import json
import uuid


def recovery_job_id(parent_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, 'fc27-player-recovery:' + parent_id))


def candidate(root, config, cycle_id, read_bytes, resolved_execution, at=None, active_job_id=None):
    at = at or datetime.now(timezone.utc)
    def read(key):
        return json.loads(read_bytes(key))
    if not config.get('enabled'):
        raise ValueError('recovery_player_disabled')
    for folder in ('queue', 'jobs', 'executions', 'all-coin-sync', 'player-sync'):
        path = root / folder
        if not path.is_dir() or path.is_symlink():
            raise ValueError('recovery_ledger_unavailable')
    if any((root / 'queue').glob('*.json')):
        raise ValueError('recovery_queue_busy')
    jobs = [read('jobs/' + p.name) for p in (root / 'jobs').glob('*.json')]
    if active_job_id is not None:
        active = [j for j in jobs if j.get('job_id') == active_job_id]
        if (active_job_id != recovery_job_id(cycle_id) or len(active) != 1
                or active[0].get('kind') != 'player_sync' or active[0].get('status') != 'running'
                or ((active[0].get('request') or {}).get('automatic_basis') or {}).get('parent_id') != cycle_id):
            raise ValueError('recovery_active_job_invalid')
        jobs = [j for j in jobs if j.get('job_id') != active_job_id]
    if any(j.get('status') == 'running' and j.get('job_id') != cycle_id for j in jobs):
        raise ValueError('recovery_job_running')
    players = [j for j in jobs if j.get('kind') == 'player_sync'
               and (j.get('request') or {}).get('config_revision') == config['revision']]
    if not players:
        raise ValueError('recovery_failure_missing')
    last = max(players, key=lambda j: j['created_at'])
    jid = last['job_id']
    if str(uuid.UUID(jid)) != jid:
        raise ValueError('recovery_job_id_invalid')
    result = last.get('sync_result') or {}
    if (last.get('status') != 'failed' or last.get('actor') != 'system-automation'
            or last.get('error') != 'player_sync_not_confirmed'
            or result.get('status') != 'blocked_before_write'
            or result.get('reason') != 'chenchao_auth_unavailable'
            or last.get('error_detail') != 'chenchao_auth_unavailable'
            or last.get('result')):
        raise ValueError('recovery_requires_reconciliation')
    completed = datetime.fromisoformat(last['completed_at'].replace('Z', '+00:00'))
    if completed.tzinfo is None or completed > at:
        raise ValueError('recovery_failure_timestamp_invalid')
    # Absence alone is not proof: it supplements the narrow typed prewrite error.
    ledger = root / 'player-sync' / (jid + '.json')
    if ledger.exists() or ledger.is_symlink():
        raise ValueError('recovery_player_write_may_have_started')
    audits = [read('executions/' + p.name) for p in (root / 'executions').glob('*.json')]
    if not audits or any(not resolved_execution(a) for a in audits):
        raise ValueError('recovery_coin_write_unconfirmed')
    all_rows = [read('all-coin-sync/' + p.name) for p in (root / 'all-coin-sync').glob('*.json')]
    if not all_rows or any(a.get('status') != 'confirmed' for a in all_rows):
        raise ValueError('recovery_all_write_unconfirmed')
    confirmed = [a for a in audits if a.get('status') == 'CONFIRMED' and a.get('sync_confirmed') is True]
    current = max(confirmed, key=lambda a: a['created_at']) if confirmed else None
    cid = (last.get('request') or {}).get('coin_execution_id')
    if (not current or current.get('execution_id') != cid or str(uuid.UUID(cid)) != cid
            or current.get('automatic') is not True
            or current.get('all_baseline', {}).get('status') != 'confirmed'):
        raise ValueError('recovery_coin_basis_changed')
    return {'kind': 'prewrite_auth_recovery', 'old_player_job_id': jid,
            'failed_job_sha256': hashlib.sha256(read_bytes('jobs/' + jid + '.json')).hexdigest(),
            'coin_execution_id': cid,
            'coin_execution_sha256': hashlib.sha256(read_bytes('executions/' + cid + '.json')).hexdigest(),
            'all_ledger_sha256': hashlib.sha256(read_bytes('all-coin-sync/' + cid + '.json')).hexdigest()}
