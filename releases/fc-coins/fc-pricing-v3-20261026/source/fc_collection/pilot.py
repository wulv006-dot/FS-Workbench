"""One explicit shadow run, two fixed public requests, never a pricing input or timer."""
import json
import os
from pathlib import Path
import sys
import time
from datetime import timedelta

from .contracts import build_job, encoded, fingerprint, label, to_fc_quote_rows
from .coordinator import Coordinator
from .protocol import utc
from .public_sources import VERSIONS
from .ssh_client import Session, ssh_command


def source_policy(generation=1):
    # shortcut: manual diagnostics allow one final warm-redirect repair; production needs its own policy.
    if type(generation) is not int or not 1 <= generation <= 4:
        raise ValueError('pilot_diagnostic_limit_reached')
    # 2 x existing 18s HTTP + 10s SSH setup + clock/callback allowance fit 60s.
    return dict(origin='https://www.arab-ut.com', nodes=['183'], mode='shadow',
        generation=generation, adapter_version=VERSIONS['ArabUT'],
        policy_version='arab-shadow-recheck-v' + str(generation) if generation > 1 else 'arab-shadow-two-request-v1',
        lease_seconds=60, request_timeout_seconds=20, clock_margin_seconds=2, stable_seconds=5,
        window_seconds=86400, max_requests=7 if generation == 4 else 2 * generation, concurrency=1, retry_after_seconds=60)


def configure_recheck(coordinator, state, run_id, previous):
    if run_id != label(previous) + '-recheck':
        raise ValueError('pilot_recheck_id_invalid')
    path = state / (previous + '.json')
    if path.is_symlink() or not path.is_file():
        raise ValueError('pilot_original_required')
    original = json.loads(path.read_text())
    previous_generation = original.get('assignment_generation')
    if type(previous_generation) is not int:
        raise ValueError('pilot_original_terminal_failure_required')
    target_policy = source_policy(previous_generation + 1)
    with coordinator.transaction() as db:
        rows = [(row['state'], json.loads(row['body'])) for row in db.execute('SELECT state,body FROM collection_jobs')]
        roots = [body['parent_run_id'] for _, body in rows if body['assignment_generation'] == 1]
        if len(roots) != 1:
            raise ValueError('pilot_recheck_lifetime_budget_invalid')
        parents = [roots[0] + '-recheck' * offset for offset in range(previous_generation + 1)]
        jobs = {body['parent_run_id']: (state, body) for state, body in rows}
        if (previous != parents[-2] or run_id != parents[-1] or set(jobs) - set(parents)
                or len(jobs) != len(rows) or db.execute('SELECT COALESCE(SUM(count),0) FROM collection_permits').fetchone()[0] > target_policy['max_requests']):
            raise ValueError('pilot_recheck_lifetime_budget_invalid')
        for generation, parent in enumerate(parents[:-1], 1):
            manifest_path = state / (parent + '.json')
            if manifest_path.is_symlink() or not manifest_path.is_file():
                raise ValueError('pilot_original_required')
            manifest = json.loads(manifest_path.read_text())
            old_state, stored = jobs.get(parent, (None, {}))
            used = 1 if generation == 3 and target_policy['generation'] == 4 else 2
            reason = 'redirect_denied' if used == 1 else 'adapter_contract_invalid'
            if (old_state != 'COMPLETED' or manifest.get('source_id') != 'ArabUT'
                    or manifest.get('parent_run_id') != parent or manifest.get('assignment_generation') != generation
                    or any(stored.get(key) != value for key, value in manifest.items())
                    or stored.get('request_budget_reserved') != used or stored.get('attempts') != 1
                    or db.execute('SELECT COALESCE(SUM(count),0) FROM collection_permits WHERE job=?',
                                  (manifest['job_id'],)).fetchone()[0] != used):
                raise ValueError('pilot_original_terminal_failure_required')
            observations = db.execute('SELECT body,receipt,payload_hash FROM collection_observations WHERE job=?',
                                      (manifest['job_id'],)).fetchall()
            body = json.loads(observations[0]['body']) if len(observations) == 1 else {}
            receipt = json.loads(observations[0]['receipt']) if len(observations) == 1 else {}
            if (body.get('status') != 'failed' or body.get('reason_code') != reason
                    or body.get('request_budget_used') != used or body.get('offers') != []
                    or receipt.get('status') != 'accepted' or fingerprint(body) != receipt.get('payload_hash')
                    or fingerprint(body) != observations[0]['payload_hash']):
                raise ValueError('pilot_original_terminal_failure_required')
        policy = coordinator._get(db, 'collection_sources', 'ArabUT') or {}
        if (db.execute('SELECT COUNT(*) FROM collection_sources').fetchone()[0] != 1
                or not any(all(policy.get(key) == value for key, value in source_policy(generation).items())
                           for generation in (previous_generation, previous_generation + 1))):
            raise ValueError('pilot_recheck_policy_conflict')
        # Fence the previous generation in the same transaction that verified its budget.
        coordinator._put(db, 'collection_sources', 'ArabUT', dict(target_policy,
                         blocked=policy['blocked'], cooldown_until=policy['cooldown_until']))
    return target_policy


def run(config_path, state, run_id, *, recheck_of=None):
    label(run_id)
    state = Path(state)
    if recheck_of is not None and not (state / 'collection.sqlite3').is_file():
        raise ValueError('pilot_original_required')
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = json.loads(Path(config_path).read_text())
    command = ssh_command(config)
    coordinator = Coordinator(state / 'collection.sqlite3')
    if recheck_of is not None:
        policy = configure_recheck(coordinator, state, run_id, recheck_of)
    else:
        policy = source_policy()
        coordinator.configure_source('ArabUT', policy)
    health = None
    for index in range(2):
        with Session(command) as session:
            current = session.health('183', config['worker_digest'], margin=2)
        if current['adapters'].get('ArabUT') != VERSIONS['ArabUT']:
            raise ValueError('pilot_adapter_version_invalid')
        if health and current['node_boot_id'] != health['node_boot_id']:
            raise ValueError('pilot_node_unstable')
        health = current
        principal = {key: health[key] for key in ('node_id', 'node_boot_id')}
        coordinator.register_node(principal, ['ArabUT'], utc())
        if index == 0:
            time.sleep(5)
    # A new lease is not needed to reconcile a previously spooled observation.
    for _ in range(32):
        with Session(command) as session:
            receipt = session.resend(principal, coordinator)
        if receipt.get('status') == 'idle':
            break
    else:
        raise ValueError('pilot_spool_not_drained')
    request_path = state / (run_id + '.json')
    if request_path.exists():
        request = json.loads(request_path.read_text())
    else:
        created = utc()
        request = build_job(dict(run_id=run_id, created_at=created.isoformat()), 'ArabUT',
            dict(requested_platforms=['PS', 'XBOX'], region_scope=[21],
                 quantity_scope=dict(purchase_quantity='100', quantity_unit='K'), discount_scope='coupon_excluded',
                 currency='USD', policy_version=policy['policy_version'], adapter_version=VERSIONS['ArabUT'],
                 assignment_generation=policy['generation'], total_attempt_limit=1, total_request_budget=2),
            (created + timedelta(seconds=60)).isoformat())
        with request_path.open('x', encoding='utf-8') as stream:
            stream.write(encoded(request))
            stream.flush()
            os.fsync(stream.fileno())
    with coordinator.transaction() as db:
        other = db.execute("SELECT id FROM collection_jobs WHERE id<>? AND state IN ('PENDING','LEASED','RETRY_WAIT') LIMIT 1",
                           (request['job_id'],)).fetchone()
    if other:
        return dict(status='original_run_pending', job_id=other['id'], pricing_consumption=False)
    coordinator.enqueue(request)
    accepted = coordinator.accepted(request['job_id'], utc())
    if not accepted:
        task = coordinator.claim_job(principal, ['ArabUT'], utc())
        if task is not None:
            with Session(command) as session:
                session.run(task, principal, coordinator)
        accepted = coordinator.accepted(request['job_id'], utc())
    if not accepted:
        return dict(status='not_verified', job_id=request['job_id'], pricing_consumption=False)
    with coordinator.transaction() as db:
        task = coordinator._get(db, 'collection_jobs', request['job_id'])
    projected = to_fc_quote_rows(accepted, task, utc())
    result = dict(status='valid_shadow_observation' if projected['offers'] else 'source_unavailable',
        job_id=request['job_id'], offers=len(projected['offers']), pricing_consumption=False,
        request_budget_used=sum(body['request_budget_used'] for body in accepted),
        observed_at=[row['captured_at'] for row in projected['offers']],
        source_reasons=[body['reason_code'] for body in accepted], node_id=principal['node_id'])
    return result


def main():
    os.umask(0o077)
    if len(sys.argv) not in (4, 6) or len(sys.argv) == 6 and sys.argv[4] != '--recheck-of':
        raise ValueError('pilot_arguments_required')
    print(encoded(run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3],
                      recheck_of=sys.argv[5] if len(sys.argv) == 6 else None)))


if __name__ == '__main__':
    main()
