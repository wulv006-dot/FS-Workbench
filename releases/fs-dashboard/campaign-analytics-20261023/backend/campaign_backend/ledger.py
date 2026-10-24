"""Durable at-most-one dispatch. A crash after claim remains unknown forever until readback."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .core import ContractError, canonical, identity


def now():
    return datetime.now(timezone.utc).isoformat()


class ObjectOperationBusy(ContractError):
    def __init__(self, operation_ids):
        super().__init__('OBJECT_OPERATION_IN_PROGRESS')
        self.operation_ids = operation_ids


def object_key(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('kind'), str):
        return None
    if not payload['kind'].strip() or payload['kind'] != payload['kind'].strip() or any(ord(c) < 32 for c in payload['kind']):
        return None
    values = [payload.get('site_id'), payload.get('native_id')]
    if any(type(value) not in (int, str) or not str(value).isascii() or not str(value).isdecimal()
           or len(str(value)) > 19 or int(value) < 1 for value in values):
        return None
    return canonical([str(int(values[0])), identity(payload['kind']), str(int(values[1]))])


class OperationLedger:
    def __init__(self, path):
        self.path = str(path)
        if not self.path or self.path == ':memory:':
            raise ContractError('DURABLE_LEDGER_REQUIRED')
        with self._connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY, payload TEXT NOT NULL, payload_hash TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('pending','unknown','confirmed','rejected')),
                dispatched INTEGER NOT NULL DEFAULT 0, result TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS operation_objects (
                operation_id TEXT PRIMARY KEY, object_key TEXT)''')
            db.execute('CREATE INDEX IF NOT EXISTS operation_object_key ON operation_objects(object_key)')
            db.execute('CREATE INDEX IF NOT EXISTS operation_active_state ON operations(state)')

    @staticmethod
    def _backfill_active_objects(db):
        # Existing pending/unknown rows from the older schema must also block new IDs after upgrade.
        rows = db.execute('''SELECT o.operation_id,o.payload FROM operations o
            LEFT JOIN operation_objects k ON k.operation_id=o.operation_id
            WHERE o.state IN ('pending','unknown') AND k.operation_id IS NULL''').fetchall()
        for row in rows:
            db.execute('INSERT INTO operation_objects VALUES (?,?)',
                       (row['operation_id'], object_key(json.loads(row['payload']))))

    @staticmethod
    def _object_owners(db, key, excluding=None):
        if key is None:
            return []
        return [row['operation_id'] for row in db.execute('''SELECT o.operation_id FROM operations o
            JOIN operation_objects k ON k.operation_id=o.operation_id
            WHERE k.object_key=? AND o.state IN ('pending','unknown') AND o.operation_id!=?
            ORDER BY o.created_at,o.operation_id''', (key, excluding or ''))]

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def lookup(self, operation_id):
        identity(operation_id)
        with self._connection() as db:
            row = db.execute('SELECT * FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        if row is None:
            return None
        result = json.loads(row['result']) if row['result'] else None
        return dict(operation_id=row['operation_id'], state=row['state'],
                    dispatched=bool(row['dispatched']), payload_hash=row['payload_hash'],
                    dispatch_state=(result or {}).get('dispatch_state', 'unknown' if row['dispatched'] else 'not_started'),
                    result=result,
                    created_at=row['created_at'], updated_at=row['updated_at'])

    def prepare(self, operation_id, payload):
        identity(operation_id)
        encoded = canonical(payload)
        digest = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._backfill_active_objects(db)
            row = db.execute('SELECT payload FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if row is not None and row['payload'] != encoded:
                raise ContractError('REQUEST_CONFLICT')
            if row is None:
                key = object_key(payload)
                owners = self._object_owners(db, key)
                if owners:
                    raise ObjectOperationBusy(owners)
                db.execute('INSERT INTO operations VALUES (?,?,?,\'pending\',0,NULL,?,?)',
                           (operation_id, encoded, digest, now(), now()))
                db.execute('INSERT INTO operation_objects VALUES (?,?)', (operation_id, key))
        return self.lookup(operation_id)

    def request_payload(self, operation_id):
        """Trusted service use only; never return the stored request through a public bridge."""
        identity(operation_id)
        with self._connection() as db:
            row = db.execute('SELECT payload FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        if row is None:
            raise ContractError('OPERATION_NOT_FOUND')
        return json.loads(row['payload'])

    def reject_unstarted(self, operation_id, payload, reason_code):
        """A durable preflight rejection cannot overtake a worker that already claimed dispatch."""
        self.prepare(operation_id, payload)
        result = dict(state='rejected', reason_code=reason_code, dispatch_state='not_started')
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE operations SET state='rejected',result=?,updated_at=? WHERE operation_id=? AND state='pending' AND dispatched=0",
                       (canonical(result), now(), operation_id))
        return self.lookup(operation_id)

    def execute(self, operation_id, payload, adapter):
        # An adapter must only return safe references, never raw upstream responses or credentials.
        if not adapter.enabled:
            raise ContractError('MAIN_INTEGRATION_REQUIRED')
        payload = json.loads(canonical(payload))
        self.prepare(operation_id, payload)
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            self._backfill_active_objects(db)
            current = db.execute('SELECT state FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            owners = self._object_owners(db, object_key(payload), operation_id)
            if current['state'] == 'pending' and owners:
                raise ObjectOperationBusy(owners)
            changed = db.execute('''UPDATE operations SET state='unknown',dispatched=1,updated_at=?
                WHERE operation_id=? AND state='pending' AND dispatched=0''', (now(), operation_id)).rowcount
        if not changed:
            return self.lookup(operation_id)
        try:
            result = adapter.dispatch_once(operation_id, payload)
            self._record(operation_id, result)
        except Exception:
            # Transport failure, malformed reply and process interruption do not prove rejection.
            pass
        return self.lookup(operation_id)

    def _record(self, operation_id, result):
        if (not isinstance(result, dict) or set(result) - {'state', 'upstream_ref', 'reason_code', 'dispatch_state'}
                or result.get('state') not in ('confirmed', 'rejected', 'unknown')
                or any(not isinstance(v, str) for v in result.values())):
            raise ContractError('INVALID_MUTATION_READBACK')
        if result['state'] == 'confirmed' and not result.get('upstream_ref'):
            raise ContractError('UPSTREAM_REFERENCE_REQUIRED')
        with self._connection() as db:
            db.execute('''UPDATE operations SET state=?,result=?,updated_at=?
                WHERE operation_id=? AND state='unknown' ''',
                       (result['state'], canonical(result), now(), operation_id))

    def reconcile(self, operation_id, adapter):
        operation = self.lookup(operation_id)
        if operation is None:
            raise ContractError('OPERATION_NOT_FOUND')
        if operation['state'] != 'unknown':
            return operation
        try:
            # Query the original request, never infer "not executed" from a timeout or missing page.
            with self._connection() as db:
                payload = json.loads(db.execute('SELECT payload FROM operations WHERE operation_id=?',
                                                (operation_id,)).fetchone()['payload'])
            self._record(operation_id, adapter.readback(operation_id, payload))
        except Exception:
            pass
        return self.lookup(operation_id)


class MutationAdapter:
    """Intentionally disabled. Supply a reviewed adapter only after exact request/readback mapping."""
    enabled = False

    def dispatch_once(self, operation_id, payload):
        raise ContractError('MAIN_INTEGRATION_REQUIRED')

    def readback(self, operation_id, payload):
        return {'state': 'unknown', 'reason_code': 'MAPPING_UNVERIFIED'}
