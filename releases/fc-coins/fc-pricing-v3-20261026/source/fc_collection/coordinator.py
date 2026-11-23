"""187-local collection ledger. Network waits never run inside a transaction."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit
import uuid

from .contracts import (CONTEXT, SOURCES, build_job, encoded, fingerprint, instant, integer, label,
                        validate_observation)


class Coordinator:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS collection_jobs
                    (id TEXT PRIMARY KEY, source TEXT NOT NULL, state TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_sources (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_nodes (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_run_routes (id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_observations
                    (id TEXT PRIMARY KEY, node TEXT NOT NULL, boot TEXT NOT NULL, job TEXT NOT NULL,
                     payload_hash TEXT NOT NULL, body TEXT NOT NULL, receipt TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS collection_permits
                    (id TEXT PRIMARY KEY, origin TEXT NOT NULL, job TEXT NOT NULL, epoch INTEGER NOT NULL,
                     expires REAL NOT NULL, count INTEGER NOT NULL, created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS collection_permit_origin ON collection_permits(origin,created);
                CREATE TABLE IF NOT EXISTS collection_permit_completions
                    (id TEXT PRIMARY KEY, completed REAL NOT NULL);
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _get(self, db, table, key):
        row = db.execute('SELECT body FROM ' + table + ' WHERE id=?', (key,)).fetchone()
        return json.loads(row['body']) if row else None

    def _put(self, db, table, key, value):
        db.execute('INSERT OR REPLACE INTO ' + table + '(id,body) VALUES (?,?)', (key, encoded(value)))

    def configure_source(self, source, policy):
        fields = {'origin', 'nodes', 'mode', 'generation', 'adapter_version', 'policy_version',
                  'lease_seconds', 'request_timeout_seconds', 'clock_margin_seconds', 'stable_seconds',
                  'window_seconds', 'max_requests', 'concurrency', 'retry_after_seconds'}
        if source not in SOURCES or set(policy) != fields or policy['mode'] not in ('off', 'shadow', 'consume'):
            raise ValueError('source_policy_invalid')
        parsed = urlsplit(policy['origin'])
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.path or parsed.query or parsed.fragment
                or policy['origin'] != 'https://' + parsed.hostname):
            raise ValueError('source_origin_invalid')
        if not policy['nodes'] or len(set(policy['nodes'])) != len(policy['nodes']):
            raise ValueError('nodes_invalid')
        for value in policy['nodes']:
            label(value)
        for key in fields - {'origin', 'nodes', 'mode', 'adapter_version', 'policy_version'}:
            integer(policy[key], 0 if key in ('clock_margin_seconds', 'stable_seconds') else 1,
                    86400 if key == 'window_seconds' else 10000)
        label(policy['adapter_version']); label(policy['policy_version'])
        with self.transaction() as db:
            old = self._get(db, 'collection_sources', source) or {}
            for row in db.execute('SELECT id,body FROM collection_sources'):
                shared = json.loads(row['body'])
                if (row['id'] != source and shared['origin'] == policy['origin'] and
                        any(shared[key] != policy[key] for key in
                            ('window_seconds', 'max_requests', 'concurrency', 'clock_margin_seconds'))):
                    raise ValueError('shared_origin_limits_conflict')
            if old and policy['generation'] < old['generation']:
                raise ValueError('generation_regression')
            if old and any(old[key] != policy[key] for key in fields - {'mode'}) and policy['generation'] == old['generation']:
                raise ValueError('policy_change_requires_generation')
            self._put(db, 'collection_sources', source, dict(policy,
                blocked=old.get('blocked', False), cooldown_until=old.get('cooldown_until', 0)))

    def register_node(self, identity, capabilities, now):
        self._identity_fields(identity)
        if not capabilities or set(capabilities) - SOURCES or len(set(capabilities)) != len(capabilities):
            raise ValueError('capabilities_invalid')
        with self.transaction() as db:
            old = self._get(db, 'collection_nodes', identity['node_id'])
            since = old.get('healthy_since') if old and old['node_boot_id'] == identity['node_boot_id'] else None
            self._put(db, 'collection_nodes', identity['node_id'], dict(identity,
                capabilities=capabilities, healthy_since=since or instant(now).isoformat(),
                last_seen=instant(now).isoformat(), unavailable_until=(old or {}).get('unavailable_until', 0)))

    def quarantine_node(self, node_id, now, seconds):
        label(node_id)
        integer(seconds, 1, 300)
        with self.transaction() as db:
            node = self._get(db, 'collection_nodes', node_id)
            if node:
                node.update(healthy_since=None, unavailable_until=max(node.get('unavailable_until', 0),
                                                                    instant(now).timestamp() + seconds))
                self._put(db, 'collection_nodes', node_id, node)

    def _identity_fields(self, identity):
        if not isinstance(identity, dict) or set(identity) != {'node_id', 'node_boot_id'}:
            raise ValueError('identity_invalid')
        label(identity['node_id']); label(identity['node_boot_id'])

    def _node(self, db, identity):
        self._identity_fields(identity)
        node = self._get(db, 'collection_nodes', identity['node_id'])
        if not node or node['node_boot_id'] != identity['node_boot_id']:
            raise ValueError('identity_invalid')
        return node

    def enqueue(self, task):
        expected = build_job(dict(run_id=task['parent_run_id'], created_at=task['created_at']),
                             task['source_id'], {key: task[key] for key in CONTEXT}, task['deadline_at'])
        if task != expected:
            raise ValueError('job_invalid')
        with self.transaction() as db:
            old = self._get(db, 'collection_jobs', task['job_id'])
            if old:
                if any(old[key] != value for key, value in task.items()):
                    raise ValueError('job_conflict')
                return old
            body = dict(task, attempts=0, lease_epoch=0, request_budget_reserved=0)
            db.execute('INSERT INTO collection_jobs VALUES (?,?,?,?)',
                       (task['job_id'], task['source_id'], 'PENDING', encoded(body)))
            return body

    def _save_job(self, db, task, state):
        db.execute('UPDATE collection_jobs SET state=?,body=? WHERE id=?', (state, encoded(task), task['job_id']))

    def _source_ready(self, db, source, now):
        policy = self._get(db, 'collection_sources', source)
        if not policy or policy['mode'] == 'off':
            return None
        for row in db.execute('SELECT body FROM collection_sources'):
            shared = json.loads(row['body'])
            if shared['origin'] == policy['origin'] and (shared['blocked'] or shared['cooldown_until'] > instant(now).timestamp()):
                return None
        return policy

    def claim_job(self, identity, capabilities, now, *, job_id=None):
        now = instant(now)
        with self.transaction() as db:
            node = self._node(db, identity)
            node['last_seen'] = now.isoformat()
            self._put(db, 'collection_nodes', identity['node_id'], node)
            if not node.get('healthy_since') or now.timestamp() < node.get('unavailable_until', 0):
                return None
            query = "SELECT body,state FROM collection_jobs WHERE state IN ('PENDING','LEASED','RETRY_WAIT')"
            for row in db.execute(query + (' AND id=?' if job_id is not None else '') + ' ORDER BY rowid',
                                  (job_id,) if job_id is not None else ()).fetchall():
                task = json.loads(row['body'])
                policy = self._source_ready(db, task['source_id'], now)
                if (not policy or task['source_id'] not in capabilities or task['source_id'] not in node['capabilities']
                        or identity['node_id'] not in policy['nodes']
                        or (now - instant(node['healthy_since'])).total_seconds() < policy['stable_seconds']
                        or any(task[key] != policy[name] for key, name in (
                            ('assignment_generation', 'generation'), ('adapter_version', 'adapter_version'),
                            ('policy_version', 'policy_version')))):
                    continue
                if now >= instant(task['deadline_at']) or task['attempts'] >= task['total_attempt_limit']:
                    if row['state'] == 'PENDING' or now >= instant(task['lease_expires_at']):
                        self._save_job(db, task, 'EXPIRED')
                    continue
                if row['state'] in ('LEASED', 'RETRY_WAIT'):
                    until = instant(task['lease_expires_at']).timestamp()
                    pending = db.execute('SELECT MAX(p.expires) FROM collection_permits p LEFT JOIN '
                        'collection_permit_completions c ON p.id=c.id WHERE p.job=? AND c.id IS NULL',
                        (task['job_id'],)).fetchone()[0]
                    if now.timestamp() < max(until, pending or 0, task.get('retry_not_before', 0)) + policy['clock_margin_seconds']:
                        continue
                elif identity['node_id'] != policy['nodes'][0]:
                    primary = self._get(db, 'collection_nodes', policy['nodes'][0])
                    if (primary and primary.get('healthy_since') and primary.get('unavailable_until', 0) <= now.timestamp()
                            and (now - instant(primary['last_seen'])).total_seconds() <= policy['lease_seconds'] + policy['clock_margin_seconds']):
                        continue
                task.update(identity, attempts=task['attempts'] + 1, lease_epoch=task['lease_epoch'] + 1,
                    attempt_id=uuid.uuid4().hex, lease_started_at=now.isoformat(),
                    clock_margin_seconds=policy['clock_margin_seconds'], lease_expires_at=min(now + timedelta(seconds=policy['lease_seconds']),
                                                                   instant(task['deadline_at'])).isoformat())
                self._save_job(db, task, 'LEASED')
                return task
        return None

    def _lease(self, db, identity, task, epoch, now, attempt=None):
        self._node(db, identity)
        policy = self._source_ready(db, task['source_id'], now)
        if (not policy or task.get('node_id') != identity['node_id'] or task.get('node_boot_id') != identity['node_boot_id']
                or epoch != task['lease_epoch'] or (attempt is not None and attempt != task['attempt_id'])
                or instant(now) >= min(instant(task['lease_expires_at']), instant(task['deadline_at']))
                or policy['generation'] != task['assignment_generation']):
            raise ValueError('lease_invalid')
        state = db.execute('SELECT state FROM collection_jobs WHERE id=?', (task['job_id'],)).fetchone()[0]
        if state != 'LEASED':
            raise ValueError('lease_invalid')
        return policy

    def renew_lease(self, identity, job_id, attempt_id, lease_epoch, now):
        with self.transaction() as db:
            task = self._get(db, 'collection_jobs', job_id)
            if not task:
                raise ValueError('lease_invalid')
            policy = self._lease(db, identity, task, lease_epoch, now, attempt_id)
            task['lease_expires_at'] = min(instant(now) + timedelta(seconds=policy['lease_seconds']),
                                           instant(task['deadline_at'])).isoformat()
            self._save_job(db, task, 'LEASED')
            return task

    def _reserve_origin(self, db, policy, job, epoch, count, now, expires):
        origin = policy['origin']
        used = db.execute('SELECT COALESCE(SUM(count),0) FROM collection_permits WHERE origin=? AND created>?',
            (origin, now.timestamp() - policy['window_seconds'])).fetchone()[0]
        active = db.execute('SELECT COUNT(*) FROM collection_permits p LEFT JOIN collection_permit_completions c '
            'ON p.id=c.id WHERE p.origin=? AND p.expires>? AND c.id IS NULL',
            (origin, now.timestamp() - policy['clock_margin_seconds'])).fetchone()[0]
        if used + count > policy['max_requests'] or active >= policy['concurrency']:
            raise ValueError('request_budget_unavailable')
        permit = uuid.uuid4().hex
        db.execute('INSERT INTO collection_permits VALUES (?,?,?,?,?,?,?)',
                   (permit, origin, job, epoch, expires.timestamp(), count, now.timestamp()))
        return permit

    @contextmanager
    def package_requests(self, source, run_id, count, now, *, subprocess_owned=False):
        from .contracts import PACKAGE_ORIGINS
        if source not in {'Lootbar', *PACKAGE_ORIGINS} or type(count) != int or not 1 <= count <= 3:
            raise ValueError('package_request_scope')
        now = instant(now)
        with self.transaction() as db:
            policy = self._source_ready(db, source, now)
            origin = 'https://www.lootbar.com' if source == 'Lootbar' else PACKAGE_ORIGINS[source]
            if not policy or policy['mode'] != 'consume' or policy['origin'] != origin:
                raise ValueError('collection_source_not_ready')
            # A local relay can wait 12 seconds for pickup and 30 seconds for three page reads.
            minimum = 30 if source == 'Lootbar' else 45
            expires = now + timedelta(seconds=max(minimum, policy['request_timeout_seconds']))
            permit = self._reserve_origin(db, policy, run_id, 0, count, now, expires)
        # subprocess.run waits for the primary child even when it fails. An SSH relay
        # that disconnects may still have a live reader until its permit expires.
        finished = subprocess_owned
        try:
            yield
            finished = True
        finally:
            if finished:
                with self.transaction() as db:
                    db.execute('INSERT OR IGNORE INTO collection_permit_completions VALUES (?,?)',
                               (permit, datetime.now(timezone.utc).timestamp()))

    def reserve_request(self, identity, job_id, lease_epoch, request_group, now):
        if set(request_group) != {'count'}:
            raise ValueError('request_group_invalid')
        count = integer(request_group['count'])
        now = instant(now)
        with self.transaction() as db:
            task = self._get(db, 'collection_jobs', job_id)
            if not task:
                raise ValueError('lease_invalid')
            policy = self._lease(db, identity, task, lease_epoch, now)
            if task['request_budget_reserved'] + count > task['total_request_budget']:
                raise ValueError('request_budget_unavailable')
            expires = min(now + timedelta(seconds=policy['request_timeout_seconds']), instant(task['deadline_at']))
            permit_id = self._reserve_origin(db, policy, job_id, lease_epoch, count, now, expires)
            permit = dict(permit_id=permit_id, job_id=job_id, lease_epoch=lease_epoch,
                          node_id=identity['node_id'], node_boot_id=identity['node_boot_id'],
                          count=count, issued_at=now.isoformat(), expires_at=expires.isoformat(),
                          clock_margin_seconds=policy['clock_margin_seconds'])
            task['request_budget_reserved'] += count
            self._save_job(db, task, 'LEASED')
            return permit

    def complete_request(self, identity, job_id, lease_epoch, permit_id, now):
        with self.transaction() as db:
            task = self._get(db, 'collection_jobs', job_id)
            if not task:
                raise ValueError('lease_invalid')
            self._lease(db, identity, task, lease_epoch, now)
            permit = db.execute('SELECT id FROM collection_permits WHERE id=? AND job=? AND epoch=?',
                                (permit_id, job_id, lease_epoch)).fetchone()
            if permit is None:
                raise ValueError('permit_invalid')
            db.execute('INSERT OR IGNORE INTO collection_permit_completions VALUES (?,?)',
                       (permit_id, instant(now).timestamp()))
            return dict(permit_id=permit_id, status='completed')

    def submit_observation(self, identity, body, now):
        self._identity_fields(identity)
        label(body.get('observation_id'))
        digest = fingerprint(body)
        if len(encoded(body).encode('utf-8')) > 65536:
            raise ValueError('observation_too_large')
        with self.transaction() as db:
            old = db.execute('SELECT * FROM collection_observations WHERE id=?', (body['observation_id'],)).fetchone()
            if old:
                if old['node'] != identity['node_id']:
                    raise ValueError('identity_invalid')
                if old['payload_hash'] != digest:
                    raise ValueError('observation_conflict')
                return json.loads(old['receipt'])
            task = self._get(db, 'collection_jobs', body.get('job_id'))
            if not task or body.get('node_id') != identity['node_id']:
                raise ValueError('identity_invalid')
            self._node(db, identity)
            reason = None
            try:
                policy = self._lease(db, identity, task, body.get('lease_epoch'), now, body.get('attempt_id'))
                validate_observation(body, task, now)
                reserved = db.execute('SELECT COALESCE(SUM(count),0) FROM collection_permits WHERE job=? AND epoch=?',
                                      (task['job_id'], task['lease_epoch'])).fetchone()[0]
                if body['request_budget_used'] > reserved or (body['offers'] and body['request_budget_used'] < 1):
                    raise ValueError('request_budget_invalid')
            except ValueError as exc:
                reason = str(exc)
            receipt = dict(receipt_id=uuid.uuid4().hex, observation_id=body['observation_id'], payload_hash=digest,
                           status='rejected' if reason else 'accepted', accepted_at=instant(now).isoformat(), reason=reason)
            db.execute('INSERT INTO collection_observations VALUES (?,?,?,?,?,?,?)',
                (body['observation_id'], identity['node_id'], identity['node_boot_id'], body['job_id'],
                 digest, encoded(body if not reason else dict(
                     observation_id=body['observation_id'], reason=reason, rejected=True)), encoded(receipt)))
            if not reason:
                transient = body['status'] == 'failed' and body['reason_code'] in (
                    'http_500', 'http_502', 'http_503', 'http_504', 'transport_unavailable', 'request_timeout', 'dns_unavailable')
                if transient:
                    task['retry_not_before'] = instant(now).timestamp() + min(60, 5 * 2 ** min(task['attempts'] - 1, 4))
                self._save_job(db, task, 'RETRY_WAIT' if transient else 'COMPLETED')
                if body['reason_code'] in ('http_401', 'http_403', 'challenge', 'captcha'):
                    policy['blocked'] = True
                if body['reason_code'] == 'http_429':
                    policy['cooldown_until'] = instant(now).timestamp() + max(
                        policy['retry_after_seconds'], body.get('retry_after_seconds', 0))
                self._put(db, 'collection_sources', task['source_id'], policy)
            return receipt

    def accepted(self, job_id, now):
        with self.transaction() as db:
            task = self._get(db, 'collection_jobs', job_id)
            if not task:
                return []
            policy = self._get(db, 'collection_sources', task['source_id'])
            if not policy or policy['mode'] == 'off' or policy['generation'] != task['assignment_generation']:
                return []
            result = []
            for row in db.execute('SELECT body,receipt FROM collection_observations WHERE job=? ORDER BY rowid', (job_id,)):
                body, receipt = json.loads(row['body']), json.loads(row['receipt'])
                if receipt['status'] == 'accepted':
                    try:
                        validate_observation(body, task, now)
                    except ValueError:
                        continue
                    result.append(body)
            return result
