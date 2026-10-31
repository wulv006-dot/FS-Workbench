"""Real temporary SQLite tests; authorization is synthetic and never a grant."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing, contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Barrier, Event
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from conversation_goals import ConversationGoals, MAX_STATE_BYTES
from conversation_store import ConversationStore


def state(goal_id='goal-1', revision=1, owner='alice', scope='project:1327/v1'):
    return dict(version='b2_goal_state_v1', revision=revision, goal_id=goal_id,
                owner=owner, scope_ref=scope, objective='合成验收：核显式检查点',
                constraints=['只读必要摘要'], status='active',
                next_check_at='2026-11-02T10:00:00+08:00',
                updated_at='2026-11-01T10:00:00+08:00', work=None,
                evidence=[], completed_actions=[])


class GoalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ConversationStore(self.temp.name)
        self.cid = self.store.create('alice')['conversation_id']
        self.allowed = True
        self.checks = []
        self.goals = ConversationGoals(self.store, 'alice', self.cid, self.authorize)

    def authorize(self, owner, scope):
        self.checks.append((owner, scope))
        return self.allowed if owner == 'alice' and scope == 'project:1327/v1' else False

    def put(self, value=None, expected=0, mutation='mutation-1', goals=None):
        value = state() if value is None else value
        return (goals or self.goals).cas_goal(value['goal_id'], expected_revision=expected,
                                            mutation_id=mutation, state=value)

    def rows(self, table):
        with self.store.db() as db:
            return [tuple(row) for row in db.execute('SELECT * FROM ' + table)]

    def prepared(self, goal_id='goal-1'):
        value = state(goal_id)
        value['work'] = dict(request_id='original-task-1', fact_version='host-composite-v1',
                             checkpoint_at=None, status='prepared', receipt_ref=None, receipt_digest=None)
        return value

    def test_create_two_revisions_and_reconnect(self):
        self.assertIsNone(self.goals.load_goal('missing'))
        first = self.put()
        self.assertEqual(first, dict(applied=True, replayed=False, goal_id='goal-1',
                                    revision=1, state=state(), mutation_id='mutation-1'))
        second_state = state(revision=2)
        second_state['status'] = 'paused'
        second = self.put(second_state, 1, 'mutation-2')
        reopened = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)
        self.assertEqual(reopened.load_goal('goal-1'), second_state)
        self.assertEqual(second['revision'], 2)
        self.assertEqual(len(self.rows('conversation_goal_mutations_v1')), 2)
        first['state']['objective'] = 'caller changed receipt'
        loaded = reopened.load_goal('goal-1')
        loaded['constraints'].append('caller changed load')
        self.assertEqual(reopened.load_goal('goal-1'), second_state)

    def test_lost_receipt_original_mutation_replays_old_version_without_writing(self):
        self.put()  # Simulate the caller losing the committed return value.
        self.put(state(revision=2), 1, 'mutation-2')
        before = self.rows('conversation_goals_v1'), self.rows('conversation_goal_mutations_v1')
        reopened = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)
        receipt = self.put(goals=reopened)
        self.assertTrue(receipt['applied'])
        self.assertTrue(receipt['replayed'])
        self.assertEqual(receipt['revision'], 1)
        self.assertEqual(reopened.load_goal('goal-1')['revision'], 2)
        self.assertEqual(before, (self.rows('conversation_goals_v1'), self.rows('conversation_goal_mutations_v1')))

    def test_mutation_fingerprint_covers_payload_revision_and_goal(self):
        self.put()
        changed = state()
        changed['objective'] = 'different'
        for value, expected in ((changed, 0), (state(revision=2), 1), (state('goal-2'), 0)):
            with self.subTest(value=value['goal_id'], expected=expected):
                with self.assertRaisesRegex(ValueError, 'mutation_conflict'):
                    self.put(value, expected)
        self.assertIsNone(self.goals.load_goal('goal-2'))
        self.assertEqual(self.goals.load_goal('goal-1'), state())
        # Different JSON object insertion order is the same full payload.
        self.assertTrue(self.put(dict(reversed(list(state().items()))))['replayed'])

    def test_concurrent_different_mutations_only_one_revision_wins(self):
        self.put()
        barrier = Barrier(2)

        def attempt(index):
            goals = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)
            proposed = state(revision=2)
            proposed['objective'] += str(index)
            barrier.wait(timeout=10)
            try:
                return self.put(proposed, 1, 'race-' + str(index), goals)
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (1, 2)))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn('goal_revision_conflict', results)
        self.assertEqual(self.goals.load_goal('goal-1')['revision'], 2)
        self.assertEqual(len(self.rows('conversation_goal_mutations_v1')), 2)

    def test_concurrent_same_mutation_is_one_commit_and_one_replay(self):
        barrier = Barrier(2)

        def attempt(_):
            goals = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)
            barrier.wait(timeout=10)
            return self.put(goals=goals)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, (1, 2)))
        self.assertEqual(sorted(result['replayed'] for result in results), [False, True])
        self.assertEqual(len(self.rows('conversation_goals_v1')), 1)
        self.assertEqual(len(self.rows('conversation_goal_mutations_v1')), 1)

    def test_original_conversation_owner_precedes_scope_check(self):
        calls = []
        with self.assertRaisesRegex(LookupError, 'conversation_not_found'):
            ConversationGoals(self.store, 'bob', self.cid, lambda *args: calls.append(args) or True)
        self.assertEqual(calls, [])
        self.put()
        with self.store.db() as db:
            db.execute('UPDATE conversations SET owner=? WHERE id=?', ('bob', self.cid))
        self.checks.clear()
        for operation in (lambda: self.goals.load_goal('goal-1'), lambda: self.put()):
            with self.assertRaisesRegex(LookupError, 'conversation_not_found'):
                operation()
        self.assertEqual(self.checks, [])

    def test_cross_owner_cid_goal_and_mutation_cannot_rebind(self):
        self.put()
        for owner in ('alice', 'bob'):
            other_cid = self.store.create(owner)['conversation_id']
            goals = ConversationGoals(self.store, owner, other_cid, lambda *_: True)
            with self.assertRaisesRegex(LookupError, 'goal_not_found'):
                goals.load_goal('goal-1')
            with self.assertRaisesRegex(LookupError, 'goal_not_found'):
                self.put(state(owner=owner), goals=goals)
            with self.assertRaisesRegex(ValueError, 'mutation_conflict'):
                self.put(state('other-goal-' + owner, owner=owner), goals=goals)
        self.assertEqual(len(self.rows('conversation_goals_v1')), 1)

    def test_revoke_and_strict_true_before_cached_state_or_replay(self):
        self.put()
        for value in (False, None, 1, 'true'):
            self.allowed = value
            for operation in (lambda: self.goals.load_goal('goal-1'), lambda: self.put(),
                              lambda: self.put(state(revision=2), 1, 'new-mutation')):
                with self.assertRaisesRegex(PermissionError, 'scope_unavailable'):
                    operation()
        self.allowed = True
        self.assertTrue(self.put()['replayed'])

    def test_creation_denied_and_scope_owner_goal_bindings_immutable(self):
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.put()
        self.assertEqual(self.rows('conversation_goals_v1'), [])
        self.allowed = True
        self.put()
        for field, value, error in (('owner', 'bob', 'identity_conflict'),
                                    ('scope_ref', 'project:other', 'scope_conflict')):
            proposed = state(revision=2)
            proposed[field] = value
            with self.assertRaisesRegex(ValueError, error):
                self.put(proposed, 1, 'change-' + field)
        with self.assertRaisesRegex(ValueError, 'identity_conflict'):
            self.goals.cas_goal('goal-1', expected_revision=1, mutation_id='wrong-goal',
                                state=state('goal-2', 2))
        self.assertEqual(self.goals.load_goal('goal-1'), state())

    def test_stale_revision_invalid_inputs_and_size_never_overwrite(self):
        self.put()
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.put(mutation='new-stale-id')
        cases = []
        for key, value in (('revision', True), ('revision', 9), ('version', 'future_v2'),
                           ('objective', '中' * MAX_STATE_BYTES), ('evidence', [{'rows': ['raw']}]),
                           ('work', {'orders': ['raw']}), ('scope_ref', None)):
            proposed = state(revision=2)
            proposed[key] = value
            cases.append(proposed)
        cases.append(dict(state(revision=2), rows=['not a minimal goal state']))
        for proposed in cases:
            with self.subTest(proposed=list(proposed)):
                with self.assertRaises(ValueError):
                    self.put(proposed, 1, 'invalid')
        for revision in (True, -1, 1.0, 2 ** 63):
            with self.assertRaises(ValueError):
                self.put(state(revision=2), revision, 'bad-expected')
        self.assertEqual(self.goals.load_goal('goal-1'), state())
        self.assertEqual(len(self.rows('conversation_goal_mutations_v1')), 1)

    def test_damaged_state_load_and_cas_fail_without_repair(self):
        self.put()
        original = self.rows('conversation_goals_v1')[0]
        for raw in ('{}', '[]', '{bad', json.dumps(dict(state(), version='bad')),
                    '{"revision":1,"revision":2}'):
            with self.subTest(raw=raw):
                with self.store.db() as db:
                    db.execute('UPDATE conversation_goals_v1 SET state_json=?,state_sha256=?',
                               (raw, hashlib.sha256(raw.encode()).hexdigest()))
                before = self.rows('conversation_goals_v1')
                for operation in (lambda: self.goals.load_goal('goal-1'),
                                  lambda: self.put(state(revision=2), 1, 'repair-attempt')):
                    with self.assertRaisesRegex(ValueError, 'state_damaged'):
                        operation()
                self.assertEqual(self.rows('conversation_goals_v1'), before)
        with self.store.db() as db:
            db.execute('DELETE FROM conversation_goals_v1')
            db.execute('INSERT INTO conversation_goals_v1 VALUES(?,?,?,?,?,?,?)', original)
            db.execute('UPDATE conversation_goals_v1 SET revision=8')
        with self.assertRaisesRegex(ValueError, 'state_damaged'):
            self.goals.load_goal('goal-1')

    def test_corrupt_mutation_receipt_cannot_replay_or_overwrite(self):
        self.put()
        with self.store.db() as db:
            db.execute("UPDATE conversation_goal_mutations_v1 SET receipt_json='{}'")
        with self.assertRaisesRegex(ValueError, 'mutation_damaged'):
            self.put()
        self.assertEqual(self.goals.load_goal('goal-1'), state())
        self.assertEqual(len(self.rows('conversation_goal_mutations_v1')), 1)

    def test_sql_failure_rolls_back_goal_and_mutation_together(self):
        self.put()
        with self.store.db() as db:
            db.execute('''CREATE TRIGGER fail_goal_mutation BEFORE INSERT ON conversation_goal_mutations_v1
                          BEGIN SELECT RAISE(ABORT, 'synthetic-mutation-failure'); END''')
        for value, expected in ((state(revision=2), 1), (state('new-goal'), 0)):
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'synthetic-mutation-failure'):
                self.put(value, expected, 'failed-mutation')
        self.assertEqual(self.goals.load_goal('goal-1'), state())
        self.assertIsNone(self.goals.load_goal('new-goal'))
        self.assertEqual(len(self.rows('conversation_goal_mutations_v1')), 1)

    def test_failure_before_commit_rolls_back_both_records(self):
        original_db = self.store.db

        @contextmanager
        def interrupted_db():
            with original_db() as db:
                yield db
                raise OSError('synthetic-before-commit')

        with patch.object(self.store, 'db', interrupted_db):
            with self.assertRaisesRegex(OSError, 'before-commit'):
                self.put()
        self.assertEqual(self.rows('conversation_goals_v1'), [])
        self.assertEqual(self.rows('conversation_goal_mutations_v1'), [])
        self.assertFalse(self.put()['replayed'])

    def test_reference_only_prepared_unknown_and_terminal_states_survive_reopen(self):
        prepared = state()
        prepared['work'] = dict(request_id='original-task-1', fact_version='host-composite-v1',
                                checkpoint_at=None, status='prepared', receipt_ref=None, receipt_digest=None)
        self.put(prepared)
        unknown = deepcopy(prepared)
        unknown['revision'] = 2
        unknown['work'].update(status='unknown', receipt_ref='receipt-original-task-1', receipt_digest='a' * 64)
        self.put(unknown, 1, 'mutation-2')
        terminal = deepcopy(unknown)
        terminal['revision'] = 3
        terminal['work']['status'] = 'completed'
        terminal['evidence'] = [dict(ref='ua_frozen', source='authorized-frozen', as_of='2026-10-31T00:00:00Z',
                                     coverage='partial', missing=['refunds'], version='host-composite-v1')]
        terminal['completed_actions'] = ['receipt-original-task-1']
        self.put(terminal, 2, 'mutation-3')
        reopened = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)
        self.assertEqual(reopened.load_goal('goal-1'), terminal)
        self.assertTrue(self.put(prepared, goals=reopened)['replayed'])
        self.assertEqual(reopened.load_goal('goal-1')['status'], 'active')
        self.assertEqual(reopened.load_goal('goal-1')['work']['request_id'], 'original-task-1')

    def test_existing_public_tables_and_conversation_state_untouched(self):
        names = ('conversations', 'turns', 'events', 'artifacts', 'actions')
        before = {name: self.rows(name) for name in names}
        self.put()
        self.assertEqual(before, {name: self.rows(name) for name in names})

    def test_admission_rejects_pause_winner_and_stale_revision(self):
        self.put(self.prepared())
        paused = self.prepared()
        paused.update(revision=2, status='paused')
        self.put(paused, 1, 'pause-first')
        for revision, error in ((1, 'revision_conflict'), (2, 'admission_denied')):
            with self.assertRaisesRegex(ValueError, error):
                with self.goals.admission('goal-1', expected_revision=revision, request_id='original-task-1'):
                    self.fail('paused goal admitted')

    def test_admission_holds_goal_lock_until_local_task_reservation_finishes(self):
        self.put(self.prepared())
        attempted = Event()
        task_path = Path(self.temp.name) / 'synthetic-original-task-ledger.db'
        with closing(sqlite3.connect(task_path)) as tasks, tasks:
            tasks.execute('CREATE TABLE tasks (request_id TEXT PRIMARY KEY, state TEXT)')

        # Construct the worker before admission: its ConversationStore constructor
        # may initialize unrelated tables, which also requires the same DB lock.
        other = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)

        def existing_host_pause():
            proposed = self.prepared()
            proposed.update(revision=2, status='paused')
            attempted.set()
            return self.put(proposed, 1, 'pause-during-reserve', other)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.goals.admission('goal-1', expected_revision=1, request_id='original-task-1') as admitted:
                future = pool.submit(existing_host_pause)
                self.assertTrue(attempted.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.05)
                with closing(sqlite3.connect(task_path)) as tasks, tasks:
                    tasks.execute('INSERT INTO tasks VALUES(?,?)', (admitted['work']['request_id'], 'queued'))
                admitted['status'] = 'caller-changed-copy'
            self.assertEqual(future.result(timeout=10)['revision'], 2)
        self.assertEqual(self.goals.load_goal('goal-1')['status'], 'paused')
        with closing(sqlite3.connect(task_path)) as tasks, tasks:
            self.assertEqual(tasks.execute('SELECT * FROM tasks').fetchall(), [('original-task-1', 'queued')])

    def test_admission_exception_releases_lock_and_writes_no_half_state(self):
        self.put(self.prepared())
        before = self.rows('conversation_goals_v1'), self.rows('conversation_goal_mutations_v1')
        with self.assertRaisesRegex(RuntimeError, 'synthetic-reserve-failed'):
            with self.goals.admission('goal-1', expected_revision=1, request_id='original-task-1') as admitted:
                admitted['work']['request_id'] = 'different'
                raise RuntimeError('synthetic-reserve-failed')
        self.assertEqual(before, (self.rows('conversation_goals_v1'), self.rows('conversation_goal_mutations_v1')))
        # An independent connection can immediately update after failure.
        other = ConversationGoals(ConversationStore(self.temp.name), 'alice', self.cid, self.authorize)
        proposed = self.prepared()
        proposed.update(revision=2, status='paused')
        self.assertTrue(self.put(proposed, 1, 'after-failure', other)['applied'])

    def test_admission_requires_matching_prepared_original_request(self):
        variants = [(None, 'active'), ('queued', 'active'), ('unknown', 'active'),
                    ('completed', 'active'), ('prepared', 'stopped')]
        for index, (work_status, status) in enumerate(variants):
            proposed = self.prepared('goal-' + str(index))
            proposed['status'] = status
            if work_status is None:
                proposed['work'] = None
            else:
                proposed['work']['status'] = work_status
            self.put(proposed, mutation='prepare-' + str(index))
            with self.assertRaisesRegex(ValueError, 'admission_denied'):
                with self.goals.admission(proposed['goal_id'], expected_revision=1, request_id='original-task-1'):
                    self.fail('non-prepared goal admitted')
        self.put(self.prepared('fresh-goal'), mutation='prepare-fresh')
        with self.assertRaisesRegex(ValueError, 'admission_denied'):
            with self.goals.admission('fresh-goal', expected_revision=1, request_id='different-request'):
                self.fail('wrong task admitted')

    def test_admission_rechecks_scope_owner_and_goal_binding(self):
        self.put(self.prepared())
        self.allowed = False
        with self.assertRaisesRegex(PermissionError, 'scope_unavailable'):
            with self.goals.admission('goal-1', expected_revision=1, request_id='original-task-1'):
                self.fail('revoked goal admitted')
        self.allowed = True
        other_cid = self.store.create('alice')['conversation_id']
        other = ConversationGoals(self.store, 'alice', other_cid, self.authorize)
        with self.assertRaisesRegex(LookupError, 'goal_not_found'):
            with other.admission('goal-1', expected_revision=1, request_id='original-task-1'):
                self.fail('cross-conversation admission')


if __name__ == '__main__':
    unittest.main()
