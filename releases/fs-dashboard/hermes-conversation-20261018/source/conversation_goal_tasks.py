"""Durable local outbox in an injected, existing TaskStore database.

QUEUED means only a private reservation. No FC spec/task, lease, run, worker,
provider, scheduler or business write is created. The host supplies the trusted
ledger path and current authorization; a digest is never an access grant.
"""
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import uuid

from conversation_goals import EVIDENCE_FIELDS, _identifier, _json, _pairs, _sha, _text


BINDING_FIELDS = {'owner', 'cid', 'goal_id', 'scope_ref', 'request_id', 'intent_sha256'}
HANDOFF_FIELDS = {'task_id', 'revision', 'goal', 'constraints', 'evidence',
                  'completed_actions', 'next_step'}
OUTBOX = 'conversation_goal_outbox_v1'
IDENTITY = 'conversation_goal_outbox_identity_v1'
TASK_COLUMNS = [('id', 'TEXT', 0, 1), ('owner', 'TEXT', 1, 0),
                ('fingerprint', 'TEXT', 1, 0), ('spec', 'TEXT', 1, 0),
                ('state', 'TEXT', 1, 0), ('version', 'INTEGER', 1, 0),
                ('run_id', 'TEXT', 0, 0), ('lease', 'TEXT', 0, 0),
                ('tokens', 'INTEGER', 1, 0), ('rounds', 'INTEGER', 1, 0)]
OUTBOX_COLUMNS = [('owner', 'TEXT', 1, 1), ('request_id', 'TEXT', 1, 2),
                  ('binding_json', 'TEXT', 1, 0), ('handoff_json', 'TEXT', 1, 0),
                  ('fingerprint', 'TEXT', 1, 0), ('receipt_ref', 'TEXT', 1, 0),
                  ('task_id', 'TEXT', 0, 0), ('lease', 'TEXT', 0, 0), ('run_id', 'TEXT', 0, 0)]


def _schema(db, table, expected):
    actual = [(r['name'], r['type'].upper(), r['notnull'], r['pk'])
              for r in db.execute('PRAGMA table_info(' + table + ')')]
    if actual != expected:
        raise OSError('goal_task_ledger_schema_unavailable')


def _handoff_json(value, binding):
    if (not isinstance(value, dict) or set(value) != HANDOFF_FIELDS
            or value['task_id'] != binding['request_id']
            or type(value['revision']) is not int or value['revision'] < 1
            or not all(_text(value[k]) for k in ('goal', 'next_step'))
            or not isinstance(value['constraints'], list)
            or not all(isinstance(v, str) for v in value['constraints'])
            or not isinstance(value['completed_actions'], list)
            or not all(_text(v) for v in value['completed_actions'])
            or not isinstance(value['evidence'], list)):
        raise ValueError('goal_task_handoff_contract')
    for ref in value['evidence']:
        if (not isinstance(ref, dict) or set(ref) != EVIDENCE_FIELDS
                or not all(_text(ref[k]) for k in EVIDENCE_FIELDS - {'missing'})
                or not isinstance(ref['missing'], list)
                or not all(isinstance(v, str) for v in ref['missing'])):
            raise ValueError('goal_task_evidence_references')
    # Match B1's original UTF-8 size bound, including its normal JSON spacing.
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) > 32768:
        raise ValueError('goal_task_handoff_too_large')
    return _json(value)


class ConversationGoalTasks:
    def __init__(self, tasks, owner, cid, authorize, *, expected_path=None):
        _identifier(owner)
        _identifier(cid)
        if not callable(authorize):
            raise PermissionError('goal_task_scope_unavailable')
        if expected_path is None:
            raise OSError('goal_task_expected_path_required')
        self.tasks, self.owner, self.cid, self.authorize = tasks, owner, cid, authorize
        expected = Path(expected_path)
        if not expected.is_absolute():
            raise OSError('goal_task_absolute_path_required')
        self.path = expected.resolve(strict=True)
        self.file_identity = None
        self.ledger_id = None
        self._check_path()
        with self._db() as db:
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if (OUTBOX in tables) != (IDENTITY in tables):
                raise OSError('goal_task_ledger_namespace_damaged')
            if OUTBOX not in tables:
                db.execute('''CREATE TABLE conversation_goal_outbox_v1 (
                    owner TEXT NOT NULL, request_id TEXT NOT NULL,
                    binding_json TEXT NOT NULL, handoff_json TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, receipt_ref TEXT NOT NULL,
                    task_id TEXT, lease TEXT, run_id TEXT, PRIMARY KEY(owner,request_id))''')
                db.execute('''CREATE TABLE conversation_goal_outbox_identity_v1 (
                    id INTEGER PRIMARY KEY, ledger_id TEXT NOT NULL)''')
                db.execute('INSERT INTO conversation_goal_outbox_identity_v1 VALUES(1,?)', (uuid.uuid4().hex,))
            self.ledger_id = self._namespace(db)

    def _check_path(self):
        # Never use TaskStore.db(): sqlite3.connect(path) could create an empty
        # replacement between an existence check and open. mode=rw below cannot.
        actual = Path(self.tasks.path)
        if not actual.is_absolute() or actual.is_symlink() or self.path.is_symlink():
            raise OSError('goal_task_ledger_path_unavailable')
        actual = actual.resolve(strict=True)
        if os.path.normcase(str(actual)) != os.path.normcase(str(self.path)):
            raise OSError('goal_task_ledger_path_mismatch')
        info = self.path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise OSError('goal_task_ledger_not_regular')
        identity = (info.st_dev, info.st_ino)
        if self.file_identity is not None and identity != self.file_identity:
            raise OSError('goal_task_ledger_replaced')
        self.file_identity = identity

    @contextmanager
    def _db(self):
        self._check_path()
        try:
            with closing(sqlite3.connect(self.path.as_uri() + '?mode=rw', uri=True,
                                         timeout=5, isolation_level=None)) as db:
                db.row_factory = sqlite3.Row
                with db:
                    db.execute('BEGIN IMMEDIATE')
                    self._check_path()
                    _schema(db, 'tasks', TASK_COLUMNS)
                    unique = []
                    for index in db.execute('PRAGMA index_list(tasks)'):
                        if index['unique'] and not index['partial']:
                            name = index['name'].replace('"', '""')
                            unique.append(tuple(r['name'] for r in db.execute('PRAGMA index_info("' + name + '")')))
                    if ('owner', 'fingerprint') not in unique or ('run_id',) not in unique:
                        raise OSError('goal_task_original_schema_unavailable')
                    yield db
                    self._check_path()
        except sqlite3.Error as exc:
            # Storage/commit failures are never authoritative not_found. A
            # caller must reconcile the original ID, not infer rollback.
            raise OSError('goal_task_ledger_unavailable') from exc

    def _namespace(self, db):
        _schema(db, OUTBOX, OUTBOX_COLUMNS)
        _schema(db, IDENTITY, [('id', 'INTEGER', 0, 1), ('ledger_id', 'TEXT', 1, 0)])
        rows = db.execute('SELECT * FROM conversation_goal_outbox_identity_v1').fetchall()
        if (len(rows) != 1 or rows[0]['id'] != 1
                or not isinstance(rows[0]['ledger_id'], str)
                or not re.fullmatch('[a-f0-9]{32}', rows[0]['ledger_id'])
                or self.ledger_id is not None and rows[0]['ledger_id'] != self.ledger_id):
            raise OSError('goal_task_ledger_identity_damaged')
        return rows[0]['ledger_id']

    def _binding(self, binding):
        if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS:
            raise ValueError('goal_task_binding_contract')
        for key in BINDING_FIELDS - {'intent_sha256', 'scope_ref'}:
            _identifier(binding[key])
        if (not _text(binding['scope_ref']) or len(binding['scope_ref']) > 2048
                or not isinstance(binding['intent_sha256'], str)
                or not re.fullmatch('[a-f0-9]{64}', binding['intent_sha256'])):
            raise ValueError('goal_task_binding_reference')
        if binding['owner'] != self.owner or binding['cid'] != self.cid:
            raise PermissionError('goal_task_host_binding')
        frozen = json.loads(_json(binding))
        self._authorize(frozen)
        return frozen

    def _authorize(self, binding):
        # Called outside task DB transactions: no reverse goal/DB lock order.
        if self.authorize(self.owner, binding['scope_ref']) is not True:
            raise PermissionError('goal_task_scope_unavailable')

    def _reference(self, binding, fingerprint):
        return 'goal_outbox_' + _sha(_json(dict(ledger=self.ledger_id, binding=binding,
                                               fingerprint=fingerprint))) + '_v1'

    def _lookup(self, db, binding):
        self._namespace(db)
        row = db.execute('SELECT * FROM conversation_goal_outbox_v1 WHERE owner=? AND request_id=?',
                         (self.owner, binding['request_id'])).fetchone()
        if row is None:
            return dict(binding=binding, status='not_found', receipt_ref=self._reference(binding, None)), None
        try:
            stored = json.loads(row['binding_json'], object_pairs_hook=_pairs)
            handoff = json.loads(row['handoff_json'], object_pairs_hook=_pairs)
            payload = _handoff_json(handoff, stored)
            fingerprint = _sha(_json(dict(binding=stored, handoff=handoff)))
            if (_json(stored) != row['binding_json'] or payload != row['handoff_json']
                    or fingerprint != row['fingerprint']
                    or row['owner'] != stored['owner'] or row['request_id'] != stored['request_id']
                    or row['receipt_ref'] != self._reference(stored, fingerprint)
                    or any(row[k] is not None for k in ('task_id', 'lease', 'run_id'))):
                raise ValueError('stored_outbox_changed')
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
            raise OSError('goal_task_outbox_damaged') from exc
        if stored != binding:
            raise ValueError('goal_task_binding_conflict')
        return dict(binding=stored, status='queued', receipt_ref=row['receipt_ref']), row

    def submit(self, *, binding, handoff):
        frozen = self._binding(binding)
        handoff_json = _handoff_json(handoff, frozen)
        fingerprint = _sha(_json(dict(binding=frozen, handoff=json.loads(handoff_json))))
        with self._db() as db:
            receipt, row = self._lookup(db, frozen)
            if row is not None:
                if row['fingerprint'] != fingerprint:
                    raise ValueError('goal_task_intent_conflict')
            else:
                ref = self._reference(frozen, fingerprint)
                db.execute('INSERT INTO conversation_goal_outbox_v1 VALUES(?,?,?,?,?,?,NULL,NULL,NULL)',
                           (self.owner, frozen['request_id'], _json(frozen), handoff_json, fingerprint, ref))
                receipt = dict(binding=frozen, status='queued', receipt_ref=ref)
        self._authorize(frozen)
        return receipt

    def lookup(self, *, binding):
        frozen = self._binding(binding)
        with self._db() as db:
            receipt, _ = self._lookup(db, frozen)
        self._authorize(frozen)
        return receipt

    def verify_receipt(self, receipt, binding):
        current = self.lookup(binding=binding)
        try:
            return isinstance(receipt, dict) and _json(receipt) == _json(current)
        except (ValueError, TypeError, UnicodeError, RecursionError):
            return False
