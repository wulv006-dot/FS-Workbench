"""One explicit shadow run, two fixed public requests, never a pricing input or timer."""
import json
import os
from pathlib import Path
import sys
import time
from datetime import timedelta

from .contracts import build_job, encoded, label, to_fc_quote_rows
from .coordinator import Coordinator
from .protocol import utc
from .public_sources import VERSIONS
from .ssh_client import Session, ssh_command


def run(config_path, state, run_id):
    label(run_id)
    state = Path(state)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    config = json.loads(Path(config_path).read_text())
    command = ssh_command(config)
    coordinator = Coordinator(state / 'collection.sqlite3')
    # 2 x existing 18s HTTP + 10s SSH setup + clock/callback allowance fit 60s.
    coordinator.configure_source('ArabUT', dict(origin='https://www.arab-ut.com', nodes=['183'], mode='shadow',
        generation=1, adapter_version=VERSIONS['ArabUT'], policy_version='arab-shadow-two-request-v1',
        lease_seconds=60, request_timeout_seconds=20, clock_margin_seconds=2, stable_seconds=5,
        window_seconds=86400, max_requests=2, concurrency=1, retry_after_seconds=60))
    health = None
    for index in range(2):
        with Session(command) as session:
            current = session.health('183', config['worker_digest'], margin=2)
        if current['adapters'] != VERSIONS:
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
                 currency='USD', policy_version='arab-shadow-two-request-v1', adapter_version=VERSIONS['ArabUT'],
                 assignment_generation=1, total_attempt_limit=1, total_request_budget=2),
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


if __name__ == '__main__':
    os.umask(0o077)
    if len(sys.argv) != 4:
        raise ValueError('pilot_arguments_required')
    print(encoded(run(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])))
