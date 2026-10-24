"""Durable at-most-one dispatch. A crash after claim remains unknown forever until readback."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .core import ContractError, canonical, identity


def now():
    return datetime.now(timezone.utc).isoformat()


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
        return dict(operation_id=row['operation_id'], state=row['state'],
                    dispatched=bool(row['dispatched']), payload_hash=row['payload_hash'],
                    result=json.loads(row['result']) if row['result'] else None,
                    created_at=row['created_at'], updated_at=row['updated_at'])

    def prepare(self, operation_id, payload):
        identity(operation_id)
        encoded = canonical(payload)
        digest = hashlib.sha256(encoded.encode('utf-8')).hexdigest()
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT payload FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
            if row is not None and row['payload'] != encoded:
                raise ContractError('REQUEST_CONFLICT')
            if row is None:
                db.execute('INSERT INTO operations VALUES (?,?,?,\'pending\',0,NULL,?,?)',
                           (operation_id, encoded, digest, now(), now()))
        return self.lookup(operation_id)

    def execute(self, operation_id, payload, adapter):
        # An adapter must only return safe references, never raw upstream responses or credentials.
        if not adapter.enabled:
            raise ContractError('MAIN_INTEGRATION_REQUIRED')
        payload = json.loads(canonical(payload))
        self.prepare(operation_id, payload)
        with self._connection() as db:
            db.execute('BEGIN IMMEDIATE')
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
        if (not isinstance(result, dict) or set(result) - {'state', 'upstream_ref', 'reason_code'}
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
