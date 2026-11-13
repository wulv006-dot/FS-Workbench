"""187-only, opt-in ArabUT routing. No implicit direct read after a remote failure."""
from datetime import datetime, timezone
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import stat
import time

from .contracts import ARAB_TABLE_SCOPE, build_job, instant, integer, to_arab_status, fingerprint
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


def read_routing_file(path):
    if not path.exists() and not path.is_symlink():
        return dict(schema_version=1, remote_result_mode='off', assignment_generation=0)
    private_file(path)
    value = json.loads(path.read_text())
    if (not isinstance(value, dict) or set(value) != {'schema_version', 'remote_result_mode', 'assignment_generation'}
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['remote_result_mode'] not in ('off', 'shadow', 'consume')):
        raise ValueError('collection_routing_invalid')
    integer(value['assignment_generation'])
    return value


def read_routing():
    return read_routing_file(ROUTING)


def check_routing(expected):
    if read_routing() != expected:
        from .adapters import SourceUnavailable
        raise SourceUnavailable('collection_routing_changed')


def source_ready(coordinator, routing, *, consume_only=False, source_id='ArabUT'):
    with coordinator.transaction() as db:
        source = (coordinator._get(db, 'collection_sources', source_id) if consume_only
                  else coordinator._source_ready(db, source_id, utc()))
    if (not source or source['mode'] != 'consume' or source['generation'] != routing['assignment_generation']
            or source['origin'] != {'ArabUT':'https://www.arab-ut.com','Lootbar':'https://www.lootbar.com'}[source_id]
            or source['nodes'][0] != '183' or source['adapter_version'] != VERSIONS[source_id]
            or source_id == 'Lootbar' and source['nodes'] != ['183']):
        raise ValueError('collection_source_not_ready')
    return source


def collect_remote(parent, routing, *, source_id='ArabUT', trigger_sha256=None, price_table=False):
    if not isinstance(parent, dict) or set(parent) != {'run_id', 'created_at', 'deadline_at'}:
        raise ValueError('collection_parent_required')
    # Opening the candidate must never create a second ledger or reset pilot budgets.
    if DATABASE.is_symlink() or not DATABASE.is_file():
        raise ValueError('collection_original_ledger_required')
    coordinator = Coordinator(DATABASE)
    def ready(**kw):
        return source_ready(coordinator, routing, **kw, **({'source_id':source_id} if source_id != 'ArabUT' else {}))
    def routing_now():
        if source_id == 'ArabUT':
            return read_routing()
        from .lootbar import ROUTING as path
        return read_routing_file(path)
    def guard():
        if routing_now() != routing:
            from .adapters import SourceUnavailable
            raise SourceUnavailable('collection_routing_changed')
    source = ready(consume_only=True)
    from .lootbar import REQUEST_BUDGET
    task = build_job(parent, source_id, dict(requested_platforms=['PS', 'XBOX', 'PC'], region_scope=[0] if source_id == 'Lootbar' else [21],
        quantity_scope=ARAB_TABLE_SCOPE if price_table else dict(purchase_quantity='100', quantity_unit='K'),
        discount_scope='coupon_excluded', currency='native' if price_table else 'USD',
        policy_version=source['policy_version'], adapter_version=source['adapter_version'],
        assignment_generation=source['generation'], total_attempt_limit=2 if '187' in source['nodes'] and not price_table else 1,
        total_request_budget=1 if price_table else REQUEST_BUDGET if source_id == 'Lootbar' else 8 if '187' in source['nodes'] else 4), parent['deadline_at'])
    with coordinator.transaction() as db:
        key = fingerprint([source_id, parent['run_id']])
        pin = dict(routing, created_at=task['created_at'], task_context_hash=task['task_context_hash'])
        if source_id == 'Lootbar':
            if not isinstance(trigger_sha256, str) or len(trigger_sha256) != 64 or any(c not in '0123456789abcdef' for c in trigger_sha256):
                raise ValueError('lootbar_original_trigger_required')
            pin['trigger_sha256'] = trigger_sha256
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
        try:
            ready()
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
                coordinator.register_node(principal, list(VERSIONS), utc())
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
            if routing_now() != routing:
                raise ValueError('collection_routing_changed')
            ready()
            leased = coordinator.claim_job(principal, [source_id], utc(), job_id=task['job_id'])
            if leased is not None:
                remaining = (instant(leased['deadline_at']) - utc()).total_seconds()
                if remaining > 0:
                    with Session(command, max_seconds=min(90, remaining)) as session:
                        session.run(leased, principal, coordinator, guard=guard)
            accepted = coordinator.accepted(task['job_id'], utc())
        except (OSError, ValueError, TimeoutError, EOFError):
            if '187' not in source['nodes']:
                raise
        accepted = coordinator.accepted(task['job_id'], utc())
    retryable = {'transport_unavailable', 'request_timeout', 'dns_unavailable', 'http_500', 'http_502', 'http_503', 'http_504'}
    if '187' in source['nodes'] and (not accepted or any(body['node_id'] == '183' and body['status'] == 'failed' and body['reason_code'] in retryable for body in accepted)):
        from .failover import run_fallback
        run_fallback(coordinator, task, routing)
        accepted = coordinator.accepted(task['job_id'], utc())
    if routing_now() != routing:
        raise ValueError('collection_routing_changed')
    ready(consume_only=True)
    with coordinator.transaction() as db:
        task = coordinator._get(db, 'collection_jobs', task['job_id'])
    if utc() >= instant(task['deadline_at']):
        raise ValueError('collection_parent_expired')
    if source_id == 'Lootbar':
        from .contracts import to_fc_quote_rows
        return to_fc_quote_rows(accepted, task, utc())
    return to_arab_status(accepted, task, utc())


def legacy_ready(source_id='ArabUT'):
    if not DATABASE.exists():
        return True
    if DATABASE.is_symlink():
        return False
    with closing(sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        source = db.execute('SELECT body FROM collection_sources WHERE id=?', (source_id,)).fetchone()
        if source is None:
            return True
        source = json.loads(source[0])
        now = utc().timestamp()
        for row in db.execute('SELECT body FROM collection_sources'):
            shared = json.loads(row[0])
            if shared['origin'] == source['origin'] and (shared['blocked'] or shared['cooldown_until'] > now):
                return False
        if db.execute('SELECT 1 FROM collection_permits p LEFT JOIN collection_permit_completions c ON p.id=c.id '
                      'WHERE p.origin=? AND c.id IS NULL AND p.expires>? LIMIT 1',
                      (source['origin'], now - source['clock_margin_seconds'])).fetchone():
            return False
        for row in db.execute("SELECT body FROM collection_jobs WHERE source=? AND state='LEASED'", (source_id,)):
            if instant(json.loads(row[0])['lease_expires_at']).timestamp() + source['clock_margin_seconds'] > now:
                return False
    return True


def arab_normal(local, parent=None, *, pinned=None, price_table=False):
    is_local = isinstance(pinned, dict) and pinned.get('mode') == 'local'
    try:
        routing = dict(remote_result_mode='off') if is_local else read_routing()
    except (OSError, ValueError):
        return dict(status='unavailable', reason='collection_routing_invalid', offers=[])
    if routing['remote_result_mode'] != 'consume':
        if price_table:
            return dict(status='unavailable', reason='arab_price_table_requires_source_lease', offers=[])
        # The bounded independent shadow driver owns remote shadow requests.
        try:
            if not legacy_ready():
                return dict(status='unavailable', reason='collection_origin_not_ready', offers=[])
        except (OSError, ValueError, sqlite3.Error):
            return dict(status='unavailable', reason='collection_origin_state_unavailable', offers=[])
        return local()
    try:
        return collect_remote(parent, routing, price_table=True) if price_table else collect_remote(parent, routing)
    except (OSError, ValueError, TimeoutError, EOFError, sqlite3.Error):
        return dict(status='unavailable', reason='remote_collection_unavailable', offers=[])
