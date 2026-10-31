"""Real temp TaskStore/ConversationStore databases, no host/runtime construction."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Barrier, Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(MODULE / 'source'), str(MODULE.parent / 'hermes-fc-pilot-20261013')]
from pilot import TaskStore
from conversation_store import ConversationStore
from conversation_goals import ConversationGoals
from conversation_goal_tasks import ConversationGoalTasks, IDENTITY, OUTBOX


class GoalTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tasks.sqlite3'
        self.tasks = TaskStore(self.path)
        self.store = ConversationStore(Path(self.temp.name) / 'conversations')
        self.cid = self.store.create('alice')['conversation_id']
        self.allowed = True
        self.binding = dict(owner='alice', cid=self.cid, goal_id='goal-1',
                            scope_ref='project:1327/v1', request_id='original-request-1', intent_sha256='a' * 64)
        self.handoff = dict(task_id=self.binding['request_id'], revision=2, goal='合成目标',
                            constraints=['只读'], evidence=[dict(ref='ua_frozen', source='frozen-summary',
                            as_of='2026-10-31T00:00:00Z', coverage='partial', missing=['refunds'], version='facts-v1')],
                            completed_actions=[], next_step='核显式检查点；无业务写入')
        self.queue = self.reopen()

    def authorize(self, owner, scope):
        return self.allowed if owner in ('alice', 'bob') and scope == 'project:1327/v1' else False

    def reopen(self, **kwargs):
        return ConversationGoalTasks(self.tasks, 'alice', self.cid, self.authorize,
                                     expected_path=kwargs.get('expected_path', self.path))

    def submit(self, *, queue=None, binding=None, handoff=None):
        return (queue or self.queue).submit(binding=binding or self.binding,
                                           handoff=self.handoff if handoff is None else handoff)

    def rows(self, table):
        with self.tasks.db() as db:
            return [tuple(row) for row in db.execute('SELECT * FROM ' + table)]

    def prepared_goal(self):
        goals = ConversationGoals(self.store, 'alice', self.cid, self.authorize)
        value = dict(version='b2_goal_state_v1', revision=1, goal_id='goal-1', owner='alice',
                     scope_ref=self.binding['scope_ref'], objective=self.handoff['goal'],
                     constraints=['只读'], status='active', next_check_at='2026-11-02T10:00:00+08:00',
                     updated_at='2026-11-01T10:00:00+08:00', evidence=[], completed_actions=[],
                     work=dict(request_id=self.binding['request_id'], fact_version='host-facts-v1',
                               checkpoint_at=None, status='prepared', receipt_ref=None, receipt_digest=None))
        goals.cas_goal('goal-1', expected_revision=0, mutation_id='create-goal-1', state=value)
        return goals, value

    def test_authoritative_missing_then_stable_queued_receipt_and_null_runtime_bindings(self):
        missing = self.queue.lookup(binding=self.binding)
        self.assertEqual(missing['status'], 'not_found')
        self.assertTrue(self.queue.verify_receipt(missing, self.binding))
        queued = self.submit()
        self.assertEqual(set(queued), {'binding', 'status', 'receipt_ref'})
        self.assertEqual(queued['status'], 'queued')
        self.assertNotEqual(missing['receipt_ref'], queued['receipt_ref'])
        self.assertFalse(self.queue.verify_receipt(missing, self.binding))
        self.assertTrue(self.queue.verify_receipt(queued, self.binding))
        self.assertEqual(self.rows('tasks'), [])
        with self.tasks.db() as db:
            self.assertEqual(tuple(db.execute('SELECT task_id,lease,run_id FROM ' + OUTBOX).fetchone()), (None, None, None))
        self.assertFalse(hasattr(self.queue, 'record'))

    def test_submit_response_loss_reopen_original_id_no_duplicate(self):
        original = self.submit()  # Pretend this return value was lost in transport.
        reopened = self.reopen()
        found = reopened.lookup(binding=self.binding)
        self.assertEqual(found, original)
        self.assertTrue(reopened.verify_receipt(found, self.binding))
        self.assertEqual(self.submit(queue=reopened), original)
        reordered = dict(reversed(list(self.handoff.items())))
        self.assertEqual(self.submit(queue=reopened, handoff=reordered), original)
        self.assertEqual(len(self.rows(OUTBOX)), 1)
        original['binding']['goal_id'] = 'caller-mutated'
        self.assertEqual(reopened.lookup(binding=self.binding)['binding']['goal_id'], 'goal-1')

    def test_full_payload_fingerprint_rejects_changed_handoff_with_same_logical_digest(self):
        self.submit()
        for field, value in (('goal', 'changed'), ('revision', 3), ('constraints', ['changed']),
                             ('completed_actions', ['different-action']), ('next_step', 'different'),
                             ('evidence', [])):
            changed = deepcopy(self.handoff)
            changed[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, 'intent_conflict'):
                    self.submit(handoff=changed)
        self.assertEqual(len(self.rows(OUTBOX)), 1)

    def test_same_owner_request_id_cannot_move_cid_goal_scope_or_digest(self):
        self.submit()
        for field, value in (('goal_id', 'other-goal'), ('intent_sha256', 'b' * 64)):
            changed = dict(self.binding, **{field: value})
            with self.assertRaisesRegex(ValueError, 'binding_conflict'):
                self.queue.lookup(binding=changed)
            with self.assertRaisesRegex(ValueError, 'binding_conflict'):
                self.submit(binding=changed)
        other_cid = self.store.create('alice')['conversation_id']
        other = ConversationGoalTasks(self.tasks, 'alice', other_cid, self.authorize, expected_path=self.path)
        with self.assertRaisesRegex(ValueError, 'binding_conflict'):
            other.lookup(binding=dict(self.binding, cid=other_cid))
        other_scope = ConversationGoalTasks(self.tasks, 'alice', self.cid, lambda *_: True, expected_path=self.path)
        with self.assertRaisesRegex(ValueError, 'binding_conflict'):
            other_scope.lookup(binding=dict(self.binding, scope_ref='project:another'))

    def test_other_owner_is_isolated_and_host_identity_cannot_be_overridden(self):
        alice = self.submit()
        bob_cid = self.store.create('bob')['conversation_id']
        bob = ConversationGoalTasks(self.tasks, 'bob', bob_cid, self.authorize, expected_path=self.path)
        bob_binding = dict(self.binding, owner='bob', cid=bob_cid)
        self.assertEqual(bob.lookup(binding=bob_binding)['status'], 'not_found')
        bob_receipt = bob.submit(binding=bob_binding, handoff=self.handoff)
        self.assertNotEqual(bob_receipt['receipt_ref'], alice['receipt_ref'])
        for binding in (bob_binding, dict(self.binding, cid=bob_cid)):
            with self.assertRaisesRegex(PermissionError, 'host_binding'):
                self.queue.lookup(binding=binding)
        self.assertFalse(bob.verify_receipt(alice, bob_binding))
        self.assertEqual(len(self.rows(OUTBOX)), 2)

    def test_concurrent_same_intent_has_one_reservation_and_same_receipt(self):
        queues = [self.reopen(), self.reopen()]
        barrier = Barrier(2)

        def submit(index):
            barrier.wait(timeout=10)
            return self.submit(queue=queues[index])

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, (0, 1)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.rows(OUTBOX)), 1)
        self.assertEqual(self.rows('tasks'), [])

    def test_concurrent_conflicting_handoffs_have_one_winner(self):
        queues = [self.reopen(), self.reopen()]
        barrier = Barrier(2)

        def submit(index):
            handoff = dict(self.handoff, next_step='variant-' + str(index))
            barrier.wait(timeout=10)
            try:
                return self.submit(queue=queues[index], handoff=handoff)
            except ValueError as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(submit, (0, 1)))
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertIn('goal_task_intent_conflict', results)
        self.assertEqual(len(self.rows(OUTBOX)), 1)

    def test_scope_requires_literal_true_before_cached_or_missing_receipts(self):
        receipt = self.submit()
        for allowed in (False, None, 1, 'true'):
            self.allowed = allowed
            with patch.object(self.queue, '_check_path', side_effect=AssertionError('must not open DB')):
                for operation in (lambda: self.submit(), lambda: self.queue.lookup(binding=self.binding),
                                  lambda: self.queue.verify_receipt(receipt, self.binding)):
                    with self.assertRaisesRegex(PermissionError, 'scope_unavailable'):
                        operation()

    def test_post_io_revocation_returns_no_cached_receipt_and_keeps_original_reservation(self):
        original = self.queue._lookup

        def revoke(*args):
            result = original(*args)
            self.allowed = False
            return result

        with patch.object(self.queue, '_lookup', side_effect=revoke):
            with self.assertRaises(PermissionError):
                self.submit()
        self.allowed = True
        self.assertEqual(self.queue.lookup(binding=self.binding)['status'], 'queued')
        self.assertEqual(len(self.rows(OUTBOX)), 1)

    def test_absent_expected_path_wrong_path_and_missing_file_never_create_empty_db(self):
        with self.assertRaisesRegex(OSError, 'expected_path_required'):
            ConversationGoalTasks(self.tasks, 'alice', self.cid, self.authorize)
        missing = Path(self.temp.name) / 'missing.sqlite3'
        with self.assertRaises(OSError):
            self.reopen(expected_path=missing)
        self.assertFalse(missing.exists())
        other = TaskStore(Path(self.temp.name) / 'other.sqlite3')
        with self.assertRaisesRegex(OSError, 'path_mismatch'):
            ConversationGoalTasks(other, 'alice', self.cid, self.authorize, expected_path=self.path)
        self.path.unlink()
        with self.assertRaises(OSError):
            self.queue.lookup(binding=self.binding)
        self.assertFalse(self.path.exists())

    def test_missing_between_stat_and_connect_mode_rw_does_not_recreate(self):
        connect = sqlite3.connect

        def removed_before_open(*args, **kwargs):
            self.assertTrue(kwargs.get('uri'))
            self.assertTrue(args[0].endswith('?mode=rw'))
            self.path.unlink()
            return connect(*args, **kwargs)

        with patch('conversation_goal_tasks.sqlite3.connect', side_effect=removed_before_open):
            with self.assertRaisesRegex(OSError, 'ledger_unavailable'):
                self.queue.lookup(binding=self.binding)
        self.assertFalse(self.path.exists())

    def test_existing_wrong_schema_corrupt_db_and_replaced_file_fail_closed(self):
        wrong = Path(self.temp.name) / 'wrong.sqlite3'
        with closing(sqlite3.connect(wrong)) as db:
            db.execute('CREATE TABLE tasks (id TEXT)')
        with self.assertRaisesRegex(OSError, 'schema_unavailable'):
            ConversationGoalTasks(SimpleNamespace(path=str(wrong)), 'alice', self.cid, self.authorize, expected_path=wrong)
        with closing(sqlite3.connect(wrong)) as db:
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [('tasks',)])
        # Matching columns with only a partial uniqueness constraint are not the
        # original authoritative TaskStore schema either.
        partial = Path(self.temp.name) / 'partial-schema.sqlite3'
        with self.tasks.db() as db:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='tasks'").fetchone()[0]
        with closing(sqlite3.connect(partial)) as db, db:
            db.execute(sql.replace(', UNIQUE(owner,fingerprint)', ''))
            db.execute("CREATE UNIQUE INDEX partial_owner ON tasks(owner,fingerprint) WHERE state='QUEUED'")
        with self.assertRaisesRegex(OSError, 'original_schema_unavailable'):
            ConversationGoalTasks(SimpleNamespace(path=str(partial)), 'alice', self.cid, self.authorize, expected_path=partial)
        corrupt = Path(self.temp.name) / 'corrupt.sqlite3'
        corrupt.write_bytes(b'not a sqlite database')
        with self.assertRaisesRegex(OSError, 'ledger_unavailable'):
            ConversationGoalTasks(SimpleNamespace(path=str(corrupt)), 'alice', self.cid, self.authorize, expected_path=corrupt)
        replacement = TaskStore(Path(self.temp.name) / 'replacement.sqlite3')
        self.path.rename(Path(self.temp.name) / 'original.sqlite3')
        Path(replacement.path).rename(self.path)
        with self.assertRaisesRegex(OSError, 'ledger_replaced'):
            self.queue.lookup(binding=self.binding)

    def test_io_error_and_missing_private_schema_are_not_not_found_or_repaired(self):
        with patch('conversation_goal_tasks.sqlite3.connect', side_effect=sqlite3.OperationalError('synthetic-io')):
            with self.assertRaisesRegex(OSError, 'ledger_unavailable'):
                self.queue.lookup(binding=self.binding)
        with self.tasks.db() as db:
            db.execute('DROP TABLE ' + OUTBOX)
        with self.assertRaises(OSError):
            self.queue.lookup(binding=self.binding)
        with self.assertRaisesRegex(OSError, 'namespace_damaged'):
            self.reopen()

    def test_ledger_identity_and_injected_task_path_cannot_drift(self):
        self.submit()
        with self.tasks.db() as db:
            db.execute('UPDATE ' + IDENTITY + " SET ledger_id=?", ('0' * 32,))
        with self.assertRaisesRegex(OSError, 'identity_damaged'):
            self.queue.lookup(binding=self.binding)
        missing = Path(self.temp.name) / 'new-unconfigured.sqlite3'
        self.tasks.path = str(missing)
        with self.assertRaises(OSError):
            self.queue.lookup(binding=self.binding)
        self.assertFalse(missing.exists())

    def test_corrupt_outbox_or_fake_runtime_binding_is_never_success(self):
        self.submit()
        original = self.rows(OUTBOX)[0]
        for column, value in (('handoff_json', '{}'), ('fingerprint', 'b' * 64),
                              ('receipt_ref', 'fake'), ('task_id', 'fake-task'),
                              ('lease', 'fake-lease'), ('run_id', 'run_fake')):
            with self.subTest(column=column):
                with self.tasks.db() as db:
                    db.execute('DELETE FROM ' + OUTBOX)
                    db.execute('INSERT INTO ' + OUTBOX + ' VALUES(?,?,?,?,?,?,?,?,?)', original)
                    db.execute('UPDATE ' + OUTBOX + ' SET ' + column + '=?', (value,))
                with self.assertRaisesRegex(OSError, 'outbox_damaged'):
                    self.queue.lookup(binding=self.binding)

    def test_receipts_are_ledger_scoped_exact_and_cannot_claim_running_or_completed(self):
        receipt = self.submit()
        for status in ('running', 'completed', 'unknown'):
            self.assertFalse(self.queue.verify_receipt(dict(receipt, status=status), self.binding))
        self.assertFalse(self.queue.verify_receipt(dict(receipt, evidence=[]), self.binding))
        self.assertFalse(self.queue.verify_receipt(dict(receipt, receipt_ref='fake'), self.binding))
        other_tasks = TaskStore(Path(self.temp.name) / 'separate.sqlite3')
        other = ConversationGoalTasks(other_tasks, 'alice', self.cid, self.authorize, expected_path=other_tasks.path)
        other_receipt = self.submit(queue=other)
        self.assertNotEqual(other_receipt['receipt_ref'], receipt['receipt_ref'])
        self.assertFalse(other.verify_receipt(receipt, self.binding))

    def test_invalid_binding_handoff_body_or_size_leaves_no_reservation(self):
        for value in (dict(self.binding, intent_sha256='bad'), dict(self.binding, url='https://invalid'),
                      dict(self.binding, scope_ref='')):
            with self.assertRaises(ValueError):
                self.submit(binding=value)
        for value in (dict(self.handoff, task_id='wrong-original-id'), dict(self.handoff, rows=['raw']),
                      dict(self.handoff, revision=True), dict(self.handoff, goal='中' * 12000),
                      dict(self.handoff, evidence=[dict(self.handoff['evidence'][0], orders=['raw'])])):
            with self.assertRaises(ValueError):
                self.submit(handoff=value)
        self.assertEqual(self.rows(OUTBOX), [])

    def test_insert_failure_rolls_back_without_changing_original_tasks(self):
        with self.tasks.db() as db:
            db.execute('CREATE TRIGGER fail_outbox BEFORE INSERT ON ' + OUTBOX +
                       " BEGIN SELECT RAISE(ABORT,'synthetic-reservation-failure'); END")
        with self.assertRaisesRegex(OSError, 'ledger_unavailable'):
            self.submit()
        self.assertEqual(self.rows(OUTBOX), [])
        self.assertEqual(self.rows('tasks'), [])

    def test_goal_admission_serializes_pause_and_outbox_without_reverse_goal_write(self):
        goals, prepared = self.prepared_goal()
        attempted = Event()

        def pause():
            value = deepcopy(prepared)
            value.update(revision=2, status='paused')
            attempted.set()
            return goals.cas_goal('goal-1', expected_revision=1, mutation_id='pause-during-queue', state=value)

        with ThreadPoolExecutor(max_workers=1) as pool:
            with goals.admission('goal-1', expected_revision=1, request_id=self.binding['request_id']):
                future = pool.submit(pause)
                self.assertTrue(attempted.wait(timeout=5))
                with self.assertRaises(TimeoutError):
                    future.result(timeout=0.05)
                receipt = self.submit()
            self.assertEqual(future.result(timeout=10)['state']['status'], 'paused')
        self.assertTrue(self.queue.verify_receipt(receipt, self.binding))
        self.assertEqual(self.rows('tasks'), [])

    def test_pause_wins_before_admission_zero_reservations(self):
        goals, prepared = self.prepared_goal()
        prepared.update(revision=2, status='paused')
        goals.cas_goal('goal-1', expected_revision=1, mutation_id='pause-first', state=prepared)
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            with goals.admission('goal-1', expected_revision=1, request_id=self.binding['request_id']):
                self.submit()
        self.assertEqual(self.rows(OUTBOX), [])

    def test_goal_transaction_rollback_does_not_erase_committed_outbox(self):
        goals, _ = self.prepared_goal()
        with self.assertRaisesRegex(OSError, 'synthetic-admission-exit'):
            with goals.admission('goal-1', expected_revision=1, request_id=self.binding['request_id']):
                self.submit()
                raise OSError('synthetic-admission-exit')
        self.assertEqual(goals.load_goal('goal-1')['revision'], 1)
        self.assertEqual(self.reopen().lookup(binding=self.binding)['status'], 'queued')
        self.assertEqual(len(self.rows(OUTBOX)), 1)
        self.assertEqual(self.rows('tasks'), [])

    def test_existing_fc_task_spec_state_and_schema_are_untouched(self):
        spec = dict(period=dict(start='2026-10-01', end_exclusive='2026-10-02', timezone='Asia/Shanghai'),
                    snapshot_id='original_snapshot', template_version='original_template',
                    knowledge_version='original_knowledge', budget_policy_id='original_policy')
        original = self.tasks.create('alice', spec)
        before = self.rows('tasks')
        with self.tasks.db() as db:
            schema = db.execute("SELECT sql FROM sqlite_master WHERE name='tasks'").fetchone()[0]
        self.submit()
        self.queue.lookup(binding=self.binding)
        self.assertEqual(self.rows('tasks'), before)
        self.assertEqual(self.tasks.get(original['id'], 'alice'), original)
        with self.tasks.db() as db:
            self.assertEqual(db.execute("SELECT sql FROM sqlite_master WHERE name='tasks'").fetchone()[0], schema)


if __name__ == '__main__':
    unittest.main()
