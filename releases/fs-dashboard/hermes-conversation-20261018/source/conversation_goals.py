"""Private goal CAS ledger in ConversationStore's existing SQLite database.

The host supplies authenticated owner/cid and a current scope validator. This
module neither grants scope nor interprets business transitions or dispatches
tasks. Mutation receipts survive reconnects and are never execution permission.
"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json


MAX_STATE_BYTES = 32768
MAX_REVISION = 2 ** 63 - 1
STATE_FIELDS = {
    'version', 'revision', 'goal_id', 'owner', 'scope_ref', 'objective',
    'constraints', 'status', 'next_check_at', 'updated_at', 'work', 'evidence',
    'completed_actions',
}
WORK_FIELDS = {'request_id', 'fact_version', 'checkpoint_at', 'status',
               'receipt_ref', 'receipt_digest'}
EVIDENCE_FIELDS = {'ref', 'source', 'as_of', 'coverage', 'missing', 'version'}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _identifier(value):
    if not _text(value) or len(value) > 256 or any(ord(c) < 32 for c in value):
        raise ValueError('goal_identifier')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(',', ':'))


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate_json_key')
        result[key] = value
    return result


def _state_json(state):
    """Check the bounded v1 reference envelope; B owns transition semantics."""
    if not isinstance(state, dict) or set(state) != STATE_FIELDS:
        raise ValueError('goal_state_contract')
    if state['version'] != 'b2_goal_state_v1':
        raise ValueError('goal_state_version')
    if type(state['revision']) is not int or not 1 <= state['revision'] <= MAX_REVISION:
        raise ValueError('goal_state_revision')
    _identifier(state['goal_id'])
    _identifier(state['owner'])
    if not all(_text(state[k]) for k in ('scope_ref', 'objective', 'next_check_at', 'updated_at')):
        raise ValueError('goal_state_reference')
    if state['status'] not in ('active', 'paused', 'stopped'):
        raise ValueError('goal_state_status')
    if not isinstance(state['constraints'], list) or not all(isinstance(v, str) for v in state['constraints']):
        raise ValueError('goal_constraints')
    if not isinstance(state['completed_actions'], list) or not all(_text(v) for v in state['completed_actions']):
        raise ValueError('goal_action_references')
    if not isinstance(state['evidence'], list) or any(
        not isinstance(e, dict) or set(e) != EVIDENCE_FIELDS
        or not all(_text(e[k]) for k in EVIDENCE_FIELDS - {'missing'})
        or not isinstance(e['missing'], list) or not all(isinstance(v, str) for v in e['missing'])
        for e in state['evidence']
    ):
        raise ValueError('goal_evidence_references')
    work = state['work']
    if work is not None:
        if (not isinstance(work, dict) or set(work) != WORK_FIELDS
                or not all(_text(work[k]) for k in ('request_id', 'fact_version'))
                or work['status'] not in ('prepared', 'queued', 'running', 'provider_returned',
                                          'unknown', 'completed', 'failed', 'cancelled')
                or any(work[k] is not None and not _text(work[k])
                       for k in ('checkpoint_at', 'receipt_ref', 'receipt_digest'))):
            raise ValueError('goal_work_references')
    encoded = _json(state)
    if len(encoded.encode('utf-8')) > MAX_STATE_BYTES:
        raise ValueError('goal_state_too_large')
    return encoded


class ConversationGoals:
    def __init__(self, store, owner, cid, authorize):
        _identifier(owner)
        if not callable(authorize):
            raise PermissionError('goal_scope_unavailable')
        self.store, self.owner, self.cid, self.authorize = store, owner, cid, authorize
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            store._owned(db, owner, cid)
            # execute(), not executescript(): DDL and subsequent writes keep the
            # original context manager's transaction/rollback boundary.
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_goals_v1 (
                goal_id TEXT PRIMARY KEY, owner TEXT NOT NULL, cid TEXT NOT NULL,
                scope_ref TEXT NOT NULL, revision INTEGER NOT NULL,
                state_json TEXT NOT NULL, state_sha256 TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS conversation_goal_mutations_v1 (
                mutation_id TEXT PRIMARY KEY, owner TEXT NOT NULL, cid TEXT NOT NULL,
                goal_id TEXT NOT NULL, expected_revision INTEGER NOT NULL,
                fingerprint TEXT NOT NULL, receipt_json TEXT NOT NULL,
                receipt_sha256 TEXT NOT NULL)''')

    def _authorize(self, scope_ref):
        if not _text(scope_ref) or self.authorize(self.owner, scope_ref) is not True:
            raise PermissionError('goal_scope_unavailable')

    def _read(self, db, goal_id):
        row = db.execute('SELECT * FROM conversation_goals_v1 WHERE goal_id=?', (goal_id,)).fetchone()
        if row is None:
            return None
        if row['owner'] != self.owner or row['cid'] != self.cid:
            raise LookupError('goal_not_found')
        # Recheck the persisted scope before parsing/returning cached state.
        self._authorize(row['scope_ref'])
        try:
            state = json.loads(row['state_json'], object_pairs_hook=_pairs)
            if (_sha(row['state_json']) != row['state_sha256']
                    or _state_json(state) != row['state_json']
                    or (state['goal_id'], state['owner'], state['scope_ref'], state['revision'])
                    != (goal_id, self.owner, row['scope_ref'], row['revision'])):
                raise ValueError('stored_binding')
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
            raise ValueError('goal_state_damaged') from exc
        return state

    def load_goal(self, goal_id):
        _identifier(goal_id)
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, self.owner, self.cid)
            return self._read(db, goal_id)

    @contextmanager
    def admission(self, goal_id, *, expected_revision, request_id):
        """Serialize a fresh prepared proposal with pause/stop and other CAS.

        The host may only reserve/enqueue the original task while holding this
        lock, not wait for a provider. Its task ledger must not acquire another
        write connection to this same conversation DB. An external reservation
        cannot be rolled back here: exit errors require original-ID reconciliation.
        """
        _identifier(goal_id)
        _identifier(request_id)
        if type(expected_revision) is not int or not 1 <= expected_revision <= MAX_REVISION:
            raise ValueError('goal_expected_revision')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, self.owner, self.cid)
            current = self._read(db, goal_id)
            if current is None:
                raise LookupError('goal_not_found')
            if current['revision'] != expected_revision:
                raise ValueError('goal_revision_conflict')
            work = current['work']
            if (current['status'] != 'active' or work is None
                    or work['status'] != 'prepared' or work['request_id'] != request_id):
                raise ValueError('goal_admission_denied')
            yield deepcopy(current)

    def cas_goal(self, goal_id, *, expected_revision, mutation_id, state):
        _identifier(goal_id)
        _identifier(mutation_id)
        if type(expected_revision) is not int or not 0 <= expected_revision < MAX_REVISION:
            raise ValueError('goal_expected_revision')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.store._owned(db, self.owner, self.cid)
            current = self._read(db, goal_id)
            encoded = _state_json(state)
            # Freeze caller data before handing any value to the host validator.
            proposed = json.loads(encoded)
            if proposed['goal_id'] != goal_id or proposed['owner'] != self.owner:
                raise ValueError('goal_identity_conflict')
            if current is None:
                self._authorize(proposed['scope_ref'])
            elif proposed['scope_ref'] != current['scope_ref']:
                raise ValueError('goal_scope_conflict')
            if proposed['revision'] != expected_revision + 1:
                raise ValueError('goal_state_revision')
            fingerprint = _sha(_json(dict(owner=self.owner, cid=self.cid, goal_id=goal_id,
                                         expected_revision=expected_revision,
                                         mutation_id=mutation_id, state=proposed)))
            old = db.execute('SELECT * FROM conversation_goal_mutations_v1 WHERE mutation_id=?',
                             (mutation_id,)).fetchone()
            if old is not None:
                if ((old['owner'], old['cid'], old['goal_id'], old['expected_revision'], old['fingerprint'])
                        != (self.owner, self.cid, goal_id, expected_revision, fingerprint)):
                    raise ValueError('goal_mutation_conflict')
                try:
                    receipt = json.loads(old['receipt_json'], object_pairs_hook=_pairs)
                    expected = dict(applied=True, replayed=False, goal_id=goal_id,
                                    revision=proposed['revision'], state=proposed, mutation_id=mutation_id)
                    if (_sha(old['receipt_json']) != old['receipt_sha256']
                            or old['receipt_json'] != _json(expected) or receipt != expected
                            or current is None or current['revision'] < receipt['revision']
                            or (current['revision'] == receipt['revision'] and current != proposed)):
                        raise ValueError('stored_receipt')
                except (ValueError, TypeError, KeyError, UnicodeError, RecursionError) as exc:
                    raise ValueError('goal_mutation_damaged') from exc
                receipt['replayed'] = True
                return receipt
            if (current['revision'] if current else 0) != expected_revision:
                raise ValueError('goal_revision_conflict')
            if current is None:
                db.execute('INSERT INTO conversation_goals_v1 VALUES(?,?,?,?,?,?,?)',
                           (goal_id, self.owner, self.cid, proposed['scope_ref'], proposed['revision'],
                            encoded, _sha(encoded)))
            else:
                updated = db.execute('''UPDATE conversation_goals_v1
                    SET revision=?,state_json=?,state_sha256=?
                    WHERE goal_id=? AND owner=? AND cid=? AND revision=?''',
                    (proposed['revision'], encoded, _sha(encoded), goal_id,
                     self.owner, self.cid, expected_revision))
                if updated.rowcount != 1:
                    raise ValueError('goal_revision_conflict')
            receipt = dict(applied=True, replayed=False, goal_id=goal_id,
                           revision=proposed['revision'], state=proposed, mutation_id=mutation_id)
            receipt_json = _json(receipt)
            db.execute('INSERT INTO conversation_goal_mutations_v1 VALUES(?,?,?,?,?,?,?,?)',
                       (mutation_id, self.owner, self.cid, goal_id, expected_revision,
                        fingerprint, receipt_json, _sha(receipt_json)))
            return receipt
