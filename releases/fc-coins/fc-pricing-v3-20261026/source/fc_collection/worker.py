"""Finite collector with bounded durable result spool; endpoint authenticates the node."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
import time
import uuid

from .adapters import SourceUnavailable, WarmLanguageRedirect
from .contracts import BINDING, encoded, fingerprint, instant, validate_observation


class BudgetedTransport:
    def __init__(self, endpoint, identity, task, fetch, clock, monotonic=time.monotonic, guard=None):
        self.endpoint, self.identity, self.task = endpoint, identity, task
        self.fetch, self.clock, self.monotonic = fetch, clock, monotonic
        self.used = 0
        self.guard = guard
        self.end = monotonic() + max(0, (instant(task['deadline_at']) - instant(clock())).total_seconds())

    def get(self, template_id):
        if self.guard is not None:
            self.guard()
        if self.monotonic() >= self.end:
            raise SourceUnavailable('deadline_expired')
        now = self.clock()
        request_started = self.monotonic()
        task = self.endpoint.renew_lease(self.identity, self.task['job_id'], self.task['attempt_id'],
                                         self.task['lease_epoch'], now)
        permit = self.endpoint.reserve_request(self.identity, task['job_id'], task['lease_epoch'], dict(count=1), now)
        self.used += 1
        margin = permit['clock_margin_seconds']
        if abs((instant(permit['issued_at']) - instant(self.clock())).total_seconds()) > margin:
            raise SourceUnavailable('clock_unverified')
        server_duration = (min(instant(permit['expires_at']), instant(task['lease_expires_at'])) - instant(permit['issued_at'])).total_seconds()
        timeout = min(self.end - self.monotonic(), 300, request_started + server_duration - margin - self.monotonic())
        if timeout <= 0:
            raise SourceUnavailable('permit_expired')
        try:
            result = self.fetch(task['source_id'], template_id, timeout)
        except WarmLanguageRedirect:
            self.endpoint.complete_request(self.identity, task['job_id'], task['lease_epoch'], permit['permit_id'], self.clock())
            raise
        except SourceUnavailable as exc:
            # An HTTP response is complete; unknown transport outcomes retain their original permit.
            if re.fullmatch(r'http_[1-5][0-9]{2}', str(exc)):
                self.endpoint.complete_request(self.identity, task['job_id'], task['lease_epoch'], permit['permit_id'], self.clock())
            raise
        self.endpoint.complete_request(self.identity, task['job_id'], task['lease_epoch'], permit['permit_id'], self.clock())
        return result


def collect_job(task, adapter, transport, clock):
    started = clock()
    try:
        result = adapter(task, transport)
    except SourceUnavailable as exc:
        result = dict(status='blocked' if str(exc) in ('http_401', 'http_403', 'http_429', 'challenge', 'captcha') else 'failed',
                      reason_code=str(exc), offers=[], evidence_hash='0' * 64)
        if exc.retry_after_seconds:
            result['retry_after_seconds'] = exc.retry_after_seconds
    except (OSError, TimeoutError):
        result = dict(status='failed', reason_code='transport_unavailable', offers=[], evidence_hash='0' * 64)
    except ValueError:
        result = dict(status='failed', reason_code='adapter_contract_invalid', offers=[], evidence_hash='0' * 64)
    body = {key: task[key] for key in BINDING}
    body.update(schema_version=1, observation_id=uuid.uuid4().hex, request_budget_used=transport.used,
                capture_started_at=instant(started).isoformat(), capture_finished_at=instant(clock()).isoformat())
    if not isinstance(result, dict) or set(result) - {'status', 'reason_code', 'offers', 'evidence_hash', 'retry_after_seconds', 'platform_errors'}:
        raise ValueError('adapter_result_invalid')
    body.update(result)
    validate_observation(body, task, clock())
    return body


class Worker:
    def __init__(self, endpoint, identity, adapters, spool, fetch, *, clock=None):
        self.endpoint, self.identity, self.adapters, self.fetch = endpoint, identity, adapters, fetch
        self.spool = Path(spool)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if self.spool.is_symlink():
            raise ValueError('spool_invalid')
        self.spool.mkdir(mode=0o700, parents=True, exist_ok=True)

    def run_once(self, *, job_id=None, allow_claim=True, guard=None):
        for temporary in self.spool.glob('.pending-*'):
            if temporary.is_symlink() or not temporary.is_file() or temporary.stat().st_size > 65536:
                raise ValueError('spool_pending_invalid')
            try:
                pending = json.loads(temporary.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                temporary.unlink()
                continue
            if (not isinstance(pending, dict) or pending.get('node_id') != self.identity['node_id']
                    or not re.fullmatch(r'[a-f0-9]{32}', str(pending.get('observation_id', '')))):
                raise ValueError('spool_pending_invalid')
            destination = self.spool / (pending['observation_id'] + '.json')
            if destination.exists():
                if destination.read_bytes() != temporary.read_bytes():
                    raise ValueError('spool_conflict')
                temporary.unlink()
            else:
                os.replace(temporary, destination)
        files = list(self.spool.iterdir())
        if (len(files) > 32 or sum(path.stat().st_size for path in files) > 262144
                or any(path.is_symlink() or not path.is_file() or not re.fullmatch(r'[a-f0-9]{32}\.json', path.name)
                       for path in files)):
            raise ValueError('spool_limit_or_path_invalid')
        if files:
            path = sorted(files)[0]
            if path.stat().st_size > 65536:
                raise ValueError('spool_payload_invalid')
            body = json.loads(path.read_text(encoding='utf-8'))
            if body.get('node_id') != self.identity['node_id'] or not body.get('observation_id'):
                raise ValueError('spool_identity_invalid')
        else:
            options = dict(job_id=job_id) if job_id is not None else {}
            task = self.endpoint.claim_job(self.identity, list(self.adapters), self.clock(), **options) if allow_claim else None
            if task is None:
                return dict(status='idle')
            transport = BudgetedTransport(self.endpoint, self.identity, task, self.fetch, self.clock, guard=guard)
            body = collect_job(task, self.adapters[task['source_id']], transport, self.clock)
            path = self.spool / (body['observation_id'] + '.json')
            fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=str(self.spool))
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    stream.write(encoded(body))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
                if os.name != 'nt':
                    directory = os.open(str(self.spool), os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory)
                    finally:
                        os.close(directory)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        receipt = self.endpoint.submit_observation(self.identity, body, self.clock())
        if (receipt.get('observation_id') != body['observation_id'] or receipt.get('status') not in ('accepted', 'rejected')
                or receipt.get('payload_hash') != fingerprint(body)):
            raise ValueError('receipt_invalid')
        path.unlink()
        return receipt
