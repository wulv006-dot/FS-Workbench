"""187-only, opt-in ArabUT routing. No implicit direct read after a remote failure."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

from .contracts import build_job, instant, integer, to_arab_status, fingerprint
from .coordinator import Coordinator
from .public_sources import VERSIONS
from .ssh_client import Session, ssh_command

ROUTING = Path('/var/lib/fc27-cloud/collection-access/routing.json')
ACCESS = ROUTING.with_name('access.json')
DATABASE = Path('/var/lib/fc27-cloud/collection-shadow/collection.sqlite3')


def utc():
    return datetime.now(timezone.utc)


def private_file(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('collection_private_file_invalid')
    if os.name == 'posix':
        info = path.stat()
        if info.st_uid != 0 or info.st_nlink != 1 or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError('collection_private_file_permissions_invalid')


def read_routing():
    if not ROUTING.exists() and not ROUTING.is_symlink():
        return dict(schema_version=1, remote_result_mode='off', assignment_generation=0)
    private_file(ROUTING)
    value = json.loads(ROUTING.read_text())
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'remote_result_mode', 'assignment_generation'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['remote_result_mode'] not in ('off', 'shadow', 'consume')):
        raise ValueError('collection_routing_invalid')
    integer(value['assignment_generation'])
    return value


def source_ready(coordinator, routing):
    with coordinator.transaction() as db:
        source = coordinator._source_ready(db, 'ArabUT', utc())
    if (not source or source['mode'] != 'consume' or source['generation'] != routing['assignment_generation']
            or source['origin'] != 'https://www.arab-ut.com' or source['nodes'][0] != '183'
            or source['adapter_version'] != VERSIONS['ArabUT']):
        raise ValueError('collection_source_not_ready')
    return source


def collect_remote(parent, routing):
    if not isinstance(parent, dict) or set(parent) != {'run_id', 'created_at', 'deadline_at'}:
        raise ValueError('collection_parent_required')
    # Opening the candidate must never create a second ledger or reset pilot budgets.
    if DATABASE.is_symlink() or not DATABASE.is_file():
        raise ValueError('collection_original_ledger_required')
    coordinator = Coordinator(DATABASE)
    source = source_ready(coordinator, routing)
    task = build_job(parent, 'ArabUT', dict(requested_platforms=['PS', 'XBOX'], region_scope=[21],
        quantity_scope=dict(purchase_quantity='100', quantity_unit='K'), discount_scope='coupon_excluded', currency='USD',
        policy_version=source['policy_version'], adapter_version=source['adapter_version'],
        assignment_generation=source['generation'], total_attempt_limit=1, total_request_budget=3), parent['deadline_at'])
    with coordinator.transaction() as db:
        key = fingerprint(['ArabUT', parent['run_id']])
        pin = dict(routing, created_at=task['created_at'], task_context_hash=task['task_context_hash'])
        original_pin = coordinator._get(db, 'collection_run_routes', key)
        if original_pin and original_pin != pin:
            raise ValueError('collection_original_route_conflict')
        coordinator._put(db, 'collection_run_routes', key, pin)
        original = coordinator._get(db, 'collection_jobs', task['job_id'])
    if original:
        if any(original[key] != value for key,value in task.items() if key != 'deadline_at'):
            raise ValueError('collection_original_context_conflict')
        task = original
    else:
        coordinator.enqueue(task)
    accepted = coordinator.accepted(task['job_id'], utc())
    if not accepted:
        remaining = (instant(task['deadline_at']) - utc()).total_seconds()
        if remaining <= 0:
            raise ValueError('collection_original_pending_or_expired')
        private_file(ACCESS)
        access = json.loads(ACCESS.read_text())
        command = ssh_command(access)
        principal = None
        for index in range(2):
            remaining = (instant(task['deadline_at']) - utc()).total_seconds()
            if remaining <= 0:
                raise ValueError('collection_parent_expired')
            with Session(command, max_seconds=min(15, remaining)) as session:
                health = session.health('183', access['worker_digest'], margin=source['clock_margin_seconds'])
            if health['adapters'] != VERSIONS:
                raise ValueError('collection_adapter_version_invalid')
            current = {key:health[key] for key in ('node_id', 'node_boot_id')}
            if principal and current != principal:
                raise ValueError('collection_node_unstable')
            principal = current
            coordinator.register_node(principal, ['ArabUT'], utc())
            if index == 0:
                if source['stable_seconds'] > min(10, remaining - 15):
                    raise ValueError('collection_parent_insufficient_time')
                time.sleep(source['stable_seconds'])
        # Reconcile an original durable spool before claiming a new task.
        for _ in range(32):
            remaining = (instant(task['deadline_at']) - utc()).total_seconds()
            if remaining <= 0:
                raise ValueError('collection_parent_expired')
            with Session(command, max_seconds=min(10, remaining)) as session:
                receipt = session.resend(principal, coordinator)
            if receipt.get('status') == 'idle':
                break
        else:
            raise ValueError('collection_spool_not_drained')
        if read_routing() != routing:
            raise ValueError('collection_routing_changed')
        source_ready(coordinator, routing)
        leased = coordinator.claim_job(principal, ['ArabUT'], utc(), job_id=task['job_id'])
        if leased is not None:
            remaining = (instant(leased['deadline_at']) - utc()).total_seconds()
            if remaining > 0:
                with Session(command, max_seconds=min(90, remaining)) as session:
                    session.run(leased, principal, coordinator)
        accepted = coordinator.accepted(task['job_id'], utc())
    if read_routing() != routing:
        raise ValueError('collection_routing_changed')
    source_ready(coordinator, routing)
    with coordinator.transaction() as db:
        task = coordinator._get(db, 'collection_jobs', task['job_id'])
    if utc() >= instant(task['deadline_at']):
        raise ValueError('collection_parent_expired')
    return to_arab_status(accepted, task, utc())


def arab_normal(local, parent=None, *, pinned=None):
    if isinstance(pinned, dict) and pinned.get('mode') == 'local':
        return local()
    try:
        routing = read_routing()
    except (OSError, ValueError):
        return dict(status='unavailable', reason='collection_routing_invalid', offers=[])
    if routing['remote_result_mode'] != 'consume':
        # The bounded independent shadow driver owns remote shadow requests.
        return local()
    try:
        return collect_remote(parent, routing)
    except (OSError, ValueError, TimeoutError, EOFError, sqlite3.Error):
        return dict(status='unavailable', reason='remote_collection_unavailable', offers=[])
