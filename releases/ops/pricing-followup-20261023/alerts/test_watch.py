"""Self-contained watch contracts; transport and homes are isolated fixtures."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parent
common = types.ModuleType('common')
common.sha = lambda data: hashlib.sha256(data).hexdigest()


def age(stamp, now):
    value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    if value.utcoffset() is None:
        raise ValueError('timezone_required')
    return (now - value).total_seconds()


common.age = age
HAS_FCNTL = os.name == 'posix'
modules = {'common': common}
if not HAS_FCNTL:
    stub = types.ModuleType('fcntl')
    stub.LOCK_EX, stub.LOCK_NB = 2, 4
    stub.flock = lambda *args: None
    modules['fcntl'] = stub
spec = importlib.util.spec_from_file_location('isolated_watch', ROOT/'source/watch.py')
watch = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, modules):
    spec.loader.exec_module(watch)


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.now = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)
        self.messages = []
        watch.write(self.home/'private-target.json', {'target': 'test-only', 'owners': {}})
        self.snapshot()

    def snapshot(self, issues=None, repair=None, **more):
        watch.write(self.home/'snapshot.json', dict(exported_at=self.now.isoformat(), issues=issues or [], repair=repair or {}, **more))

    def supplement(self, issues=None, stamp=None):
        watch.write(self.home/'pricing-snapshot.json', {'exported_at': (stamp or self.now).isoformat(), 'issues': issues or []})

    def transport(self, text, target):
        self.messages.append(text)
        pending = watch.read(self.home/'watch-state.json')['pending_event']
        self.assertEqual(watch.read(self.home/'outbox'/(pending+'.json'))['state'], 'sending')
        return {'success': True, 'message_id': 'fixture-'+str(len(self.messages))}

    def run_watch(self, pricing=False, transport=None):
        return watch.run(self.home, transport or self.transport, self.now, pricing_only=pricing)

    def test_legacy_full_first_install_unchanged(self):
        self.assertEqual(self.run_watch()['state'], 'healthy_quiet')
        self.assertEqual(self.messages, [])
        self.assertFalse(watch.read(self.home/'watch-state.json')['pricing_installed'])

    def test_owned_fault_includes_original_id_and_recovers(self):
        code = 'rpg_pricing_unknown:J20261023123249'
        self.supplement([code])
        self.assertEqual(self.run_watch(True)['state'], 'sent')
        self.assertIn(code, self.messages[-1])
        self.supplement([])
        self.assertEqual(self.run_watch(True)['state'], 'sent')
        self.assertIn('FC/RPG', self.messages[-1])
        self.assertIn('已恢复', self.messages[-1])
        self.assertIn(code, self.messages[-1])

    def test_pricing_mode_does_not_ack_new_general_or_repair(self):
        self.snapshot(['brain_ui_dependencies_missing'], {'status': 'new'}, brain={'repairable': True})
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch(True)
        state = watch.read(self.home/'watch-state.json')
        self.assertEqual(state['issues'], ['fc_pricing_failed:job-a'])
        self.assertEqual(state['repair_summary'], {})
        self.assertFalse((self.home/'request.json').exists())
        self.assertNotIn('brain_ui', self.messages[-1])
        self.assertNotIn('自修', self.messages[-1])

    def test_pricing_preserves_previously_acknowledged_general_and_repair(self):
        self.snapshot(['brain_ui_dependencies_missing'], {'incident': 'old', 'status': 'completed'})
        self.run_watch()
        self.snapshot(['new_general'], {'incident': 'new', 'status': 'new'})
        self.supplement(['rpg_pricing_partial:J-a'])
        self.run_watch(True)
        state = watch.read(self.home/'watch-state.json')
        self.assertIn('brain_ui_dependencies_missing', state['issues'])
        self.assertNotIn('new_general', state['issues'])
        self.assertEqual(state['repair_summary']['incident'], 'old')

    def test_legacy_state_inherits_only_provably_acknowledged_repair(self):
        repair = {'incident': 'old', 'status': 'done'}
        self.snapshot(['general_problem'], repair)
        self.run_watch()
        previous = watch.read(self.home/'watch-state.json')
        previous.pop('repair_summary')
        watch.write(self.home/'watch-state.json', previous)
        self.supplement(['rpg_pricing_unknown:J-a'])
        self.run_watch(True)
        self.assertEqual(watch.read(self.home/'watch-state.json')['repair_summary']['incident'], 'old')

    def test_original_full_repair_request_preserved(self):
        self.snapshot(['brain_ui_dependencies_missing'], brain={'repairable': True})
        self.run_watch()
        self.assertEqual(watch.read(self.home/'request.json')['action'], 'brain-theme')

    def test_pricing_recovery_does_not_clear_or_announce_general_as_recovered(self):
        self.snapshot(['general_problem'])
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch()
        self.supplement([])
        self.run_watch(True)
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['general_problem'])
        self.assertNotIn('general_problem', self.messages[-1])
        self.assertIn('FC/RPG', self.messages[-1])

    def test_full_and_pricing_share_signature_and_do_not_duplicate(self):
        self.snapshot(['general_problem'], {'incident': 'r', 'status': 'done'})
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch()
        self.assertEqual(self.run_watch(True)['state'], 'unchanged_quiet')
        self.assertEqual(self.run_watch()['state'], 'unchanged_quiet')
        self.assertEqual(len(self.messages), 1)

    def test_full_old_general_snapshot_cannot_override_fresh_owned(self):
        self.snapshot(['general_problem', 'fc_pricing_failed:obsolete'])
        self.supplement(['rpg_pricing_unknown:current'])
        self.run_watch()
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['general_problem', 'rpg_pricing_unknown:current'])

    def test_missing_after_install_retains_unresolved_price_and_marks_missing(self):
        self.supplement(['rpg_pricing_unknown:J-a'])
        self.run_watch(True)
        (self.home/'pricing-snapshot.json').unlink()
        self.run_watch()
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['pricing_monitor_snapshot_missing', 'rpg_pricing_unknown:J-a'])

    def test_pricing_first_missing_explicit(self):
        self.run_watch(True)
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['pricing_monitor_snapshot_missing'])

    def test_stale_cannot_recover_unresolved_issue(self):
        self.supplement(['fc_pricing_unknown:job-a'])
        self.run_watch(True)
        self.supplement([], self.now-timedelta(seconds=601))
        self.run_watch(True)
        issues = watch.read(self.home/'watch-state.json')['issues']
        self.assertIn('fc_pricing_unknown:job-a', issues)
        self.assertIn('pricing_monitor_snapshot_stale', issues)

    def test_older_fresh_pricing_snapshot_cannot_roll_back(self):
        self.supplement(['fc_pricing_unknown:new'])
        self.run_watch(True)
        self.supplement([], self.now-timedelta(seconds=10))
        self.run_watch(True)
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['fc_pricing_unknown:new', 'pricing_monitor_snapshot_regressed'])

    def test_non_owned_supplement_rejected(self):
        self.supplement(['brain_ui_dependencies_missing'])
        self.run_watch(True)
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['pricing_monitor_snapshot_invalid'])

    def test_invalid_export_timestamp_is_explicit(self):
        watch.write(self.home/'pricing-snapshot.json', {'exported_at': 123, 'issues': []})
        self.run_watch(True)
        self.assertEqual(watch.read(self.home/'watch-state.json')['issues'], ['pricing_monitor_snapshot_invalid'])

    def test_unknown_same_scope_across_modes_never_retried(self):
        self.supplement(['fc_pricing_failed:job-a'])
        calls = []
        def unknown(text, target):
            calls.append(text)
            return {'success': True}
        self.assertEqual(self.run_watch(True, unknown)['state'], 'notification_unknown_no_retry')
        first = watch.read(self.home/'watch-state.json')['pending_event']
        self.assertEqual(self.run_watch(False, unknown)['event'], first)
        self.assertEqual(self.run_watch(True, unknown)['event'], first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(list((self.home/'outbox').glob('*.json'))), 1)

    def test_transport_exception_not_retried(self):
        self.supplement(['fc_pricing_failed:job-a'])
        def fail(text, target):
            raise TimeoutError()
        self.run_watch(True, fail)
        self.assertEqual(self.run_watch()['state'], 'notification_unknown_no_retry')
        self.assertEqual(self.messages, [])

    def test_old_unknown_preserved_without_blocking_independent_new_event(self):
        event = 'a'*64
        watch.write(self.home/'outbox'/(event+'.json'), {'state': 'unknown'})
        self.supplement(['fc_pricing_failed:new'])
        self.assertEqual(self.run_watch(True)['state'], 'sent')
        self.assertEqual(watch.read(self.home/'outbox'/(event+'.json')), {'state': 'unknown'})
        self.assertIn(event, watch.read(self.home/'watch-state.json')['unknown_notification_events'])

    def test_new_scope_sent_preserves_old_unknown_and_omits_its_fault_body(self):
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch(True, lambda text, target: {'success': True})
        first = watch.read(self.home/'watch-state.json')['pending_event']
        self.supplement(['fc_pricing_failed:job-a', 'rpg_pricing_unknown:job-b'])
        self.assertEqual(self.run_watch(True)['state'], 'sent')
        self.assertIn('rpg_pricing_unknown:job-b', self.messages[-1])
        self.assertNotIn('fc_pricing_failed:job-a', self.messages[-1])
        self.assertEqual(watch.read(self.home/'outbox'/(first+'.json'))['state'], 'unknown')
        self.assertIn(first, watch.read(self.home/'watch-state.json')['unknown_notification_events'])
        self.assertEqual(self.run_watch()['state'], 'unchanged_quiet')

    def test_unknown_fault_recovery_is_separate_fact_not_retry(self):
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch(True, lambda text, target: {'success': True})
        first = watch.read(self.home/'watch-state.json')['pending_event']
        self.supplement([])
        self.assertEqual(self.run_watch(True)['state'], 'sent')
        self.assertIn('已恢复项', self.messages[-1])
        self.assertIn('fc_pricing_failed:job-a', self.messages[-1])
        self.assertEqual(watch.read(self.home/'outbox'/(first+'.json'))['state'], 'unknown')

    def test_old_sent_outbox_reconciled_without_send(self):
        self.supplement(['fc_pricing_failed:job-a'])
        issues = ['fc_pricing_failed:job-a']
        signature = common.sha(json.dumps({'issues': issues, 'repair': {key: None for key in ('incident', 'status', 'error')}}, sort_keys=True).encode())
        event = common.sha(('None'+'None'+signature).encode())
        watch.write(self.home/'outbox'/(event+'.json'), {'state': 'sent', 'message_id': 'old'})
        self.assertEqual(self.run_watch(True)['state'], 'reconciled_sent')
        self.assertEqual(self.messages, [])

    def test_sent_journal_crash_reconciles_exact_target(self):
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch(True)
        event = next((self.home/'outbox').glob('*.json')).stem
        target = watch.read(self.home/'watch-state.json')
        watch.write(self.home/'watch-state.json', {'pending_event': event})
        self.supplement(['rpg_pricing_unknown:new'])
        self.assertEqual(self.run_watch(True)['state'], 'reconciled_sent')
        self.assertEqual(watch.read(self.home/'watch-state.json'), target)
        self.assertEqual(len(self.messages), 1)

    def test_unchanged_fresh_metadata_advances_without_notification(self):
        self.supplement(['fc_pricing_failed:job-a'])
        self.run_watch(True)
        self.now += timedelta(seconds=30)
        self.supplement(['fc_pricing_failed:job-a'])
        self.assertEqual(self.run_watch(True)['state'], 'unchanged_quiet')
        self.assertEqual(watch.read(self.home/'watch-state.json')['pricing_exported_at'], self.now.isoformat())
        self.assertEqual(len(self.messages), 1)

    @unittest.skipUnless(HAS_FCNTL, 'real fcntl cross-process check requires Linux')
    def test_two_processes_share_one_lock_and_one_send(self):
        self.supplement(['fc_pricing_failed:job-a'])
        context = multiprocessing.get_context('fork')
        entered, release = context.Event(), context.Event()
        result_queue = context.Queue()
        def worker():
            def blocked_transport(text, target):
                entered.set()
                if not release.wait(5): raise TimeoutError()
                return {'message_id': 'one-real-fixture'}
            result_queue.put(self.run_watch(True, blocked_transport))
        process = context.Process(target=worker)
        process.start()
        try:
            self.assertTrue(entered.wait(5))
            self.assertEqual(self.run_watch()['state'], 'concurrent_check_skipped')
            self.assertEqual(self.messages, [])
        finally:
            release.set()
            process.join(5)
            if process.is_alive(): process.terminate(); process.join()
        self.assertEqual(result_queue.get(timeout=2)['state'], 'sent')
        self.assertEqual(self.run_watch(True)['state'], 'unchanged_quiet')


if __name__ == '__main__':
    unittest.main()
