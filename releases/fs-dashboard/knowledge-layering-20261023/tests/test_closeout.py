import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
spec = importlib.util.spec_from_file_location('closeout_under_test', ROOT / 'tools/knowledge_closeout.py')
co = importlib.util.module_from_spec(spec)
spec.loader.exec_module(co)


class Closeout(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'knowledge').mkdir()
        (self.root / 'knowledge/index.json').write_text(json.dumps({'entries': []}), encoding='utf-8')
        self.runtime = 'releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py'
        p = self.root / self.runtime
        p.parent.mkdir(parents=True)
        p.write_text('offline fixture', encoding='utf-8')
        with patch.object(co.subprocess, 'check_output', return_value='a'*40):
            self.plan = co.plan(self.root, 'b'*40, [self.runtime])
        self.db = co.connect(self.root / 'ledger.sqlite3')
        self.addCleanup(self.db.close)
        self.id = co.register(self.db, self.plan)
        self.approval = dict(source='direct_user', message_reference='offline-simulation-one-user-confirmation',
                             plan_sha256=self.plan['plan_sha256'], actions=self.plan['steps'], extra_authorities=[])

    def done(self, name, readback):
        step = co.next_step(self.db, self.id)
        operation = co.begin(self.db, self.id, name)
        receipt = dict(status='completed', operation_id=operation, readback=readback,
                       scope_verified=True, evidence='offline-fixture-readback')
        co.record(self.db, self.id, name, receipt)
        return receipt

    def test_one_confirmation_finishes_whole_scope_and_second_run_is_noop(self):
        self.assertFalse(co.next_step(self.db, self.id)['mutation_allowed'])
        co.approve(self.db, self.id, self.approval)
        native_calls = []
        original = '# 人工内容\n\n[旧链接](https://example.invalid/kept)'
        page = original
        for name in self.plan['steps']:
            co.verify_workspace(self.db, self.id, self.root)
            native_calls.append(name)
            if name == 'notion_sync':
                candidate = co.notion_candidate(page, 'fixed-version link; no production strategy change', self.id)
                page = candidate['content']
                self.assertIn(original, page)
                self.assertFalse(co.notion_candidate(page, 'fixed-version link; no production strategy change', self.id)['changed'])
            self.done(name, {'operation': self.id + ':' + name, 'verified': True})
        self.assertEqual(native_calls, ['git_version', 'server_publish', 'load_readback', 'notion_sync'])
        self.assertEqual(co.next_step(self.db, self.id)['state'], 'completed')
        self.assertEqual(co.register(self.db, self.plan), self.id)
        self.assertEqual(co.next_step(self.db, self.id)['state'], 'completed')

    def test_unknown_write_reconciles_original_id_without_second_publish(self):
        co.approve(self.db, self.id, self.approval)
        self.done('git_version', {'commit': 'c'*40})
        op = co.begin(self.db, self.id, 'server_publish')
        co.record(self.db, self.id, 'server_publish', dict(status='unknown', operation_id=op))
        self.assertFalse(co.next_step(self.db, self.id)['mutation_allowed'])
        with self.assertRaises(PermissionError):
            co.begin(self.db, self.id, 'server_publish')
        co.record(self.db, self.id, 'server_publish', dict(status='completed', operation_id=op,
                  readback={'original_release_id': op, 'previous_version_retained': True}, evidence='original-publisher-receipt', scope_verified=True))
        self.assertEqual(co.next_step(self.db, self.id)['name'], 'load_readback')

    def test_retry_before_write_keeps_same_approval_and_operation(self):
        co.approve(self.db, self.id, self.approval)
        op = co.begin(self.db, self.id, 'git_version')
        with self.assertRaisesRegex(ValueError, 'cannot_retry'):
            co.record(self.db, self.id, 'git_version', dict(status='retryable', operation_id=op))
        co.record(self.db, self.id, 'git_version', dict(status='retryable', operation_id=op, no_write_proven=True))
        self.assertEqual(co.begin(self.db, self.id, 'git_version'), op)

    def test_permission_scope_and_changed_files_stop(self):
        bad = dict(self.approval, extra_authorities=['new_credentials'])
        with self.assertRaises(PermissionError):
            co.approve(self.db, self.id, bad)
        co.approve(self.db, self.id, self.approval)
        (self.root / self.runtime).write_text('unapproved later change', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'scope_changed'):
            co.verify_workspace(self.db, self.id, self.root)
        op = co.begin(self.db, self.id, 'git_version')
        co.record(self.db, self.id, 'git_version', dict(status='denied', operation_id=op))
        self.assertEqual(co.next_step(self.db, self.id)['next_action'], 'reconcile_original_operation')

    def test_documents_do_not_schedule_restart_and_noop_other_changes(self):
        (self.root / 'knowledge/note.md').write_text('candidate', encoding='utf-8')
        with patch.object(co.subprocess, 'check_output', return_value='a'*40):
            doc = co.plan(self.root, 'b'*40, ['knowledge/note.md'])
            unrelated = co.plan(self.root, 'b'*40, [])
        self.assertFalse(doc['requires_restart'])
        self.assertEqual(doc['steps'], ['git_version', 'notion_sync'])
        self.assertEqual(unrelated['steps'], [])

    def test_notion_preserves_manual_links_and_rejects_conflicting_same_marker(self):
        original = '人工段落\n[关键链接](https://example.invalid/reference)'
        once = co.notion_candidate(original, 'approved summary', self.id)['content']
        self.assertTrue(once.endswith(original))
        with self.assertRaisesRegex(ValueError, 'managed_block_conflict'):
            co.notion_candidate(once, 'different summary', self.id)

    def test_accepted_write_without_readback_is_not_completion(self):
        co.approve(self.db, self.id, self.approval)
        op = co.begin(self.db, self.id, 'git_version')
        with self.assertRaisesRegex(ValueError, 'readback_required'):
            co.record(self.db, self.id, 'git_version', dict(status='completed', operation_id=op))
