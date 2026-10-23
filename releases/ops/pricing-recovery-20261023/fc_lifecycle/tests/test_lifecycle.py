import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import subprocess
import json
import hashlib
import tempfile
import types
import sys
import ast
from contextlib import nullcontext

SOURCE = Path(__file__).resolve().parents[1] / 'source/browser_lifecycle.py'
spec = importlib.util.spec_from_file_location('lifecycle', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class LifecycleTests(unittest.TestCase):
    def test_existing_queue_retry_and_price_guards_are_unchanged(self):
        baseline=SOURCE.parents[1]/'baseline/automation_tick.py'
        self.assertEqual(hashlib.sha256(baseline.read_bytes()).hexdigest(),
                         '5f674ee3e9b701934326c1303c8dcd94f68620faea3d62e832e6421b02e50096')
        original=ast.parse(baseline.read_text(encoding='utf-8'))
        original.body=[n for n in original.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name!='tick']
        tree=ast.parse((SOURCE.parent/'automation_tick.py').read_text(encoding='utf-8'))
        tree.body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name!='tick']
        self.assertEqual(ast.dump(tree),ast.dump(original))

    def test_browser_is_checked_before_due_cycle_is_enqueued(self):
        tree=ast.parse((SOURCE.parent/'automation_tick.py').read_text(encoding='utf-8'))
        tick=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='tick')
        calls={n.func.id:n.lineno for n in ast.walk(tick) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)}
        self.assertLess(calls['maintain'],calls['_tick_locked'])

    def test_healthy_memory_never_recycles(self):
        self.assertEqual(m.decision({}, 'ok', m.MEMORY_LIMIT-1, 10000), 'healthy')

    def test_high_memory_refreshes_before_restart(self):
        self.assertEqual(m.decision({}, 'ok', m.MEMORY_LIMIT, 10000), 'reload')

    def test_memory_not_released_escalates_once(self):
        p = dict(action='reload', state='verified', at=9900)
        self.assertEqual(m.decision(p, 'ok', m.MEMORY_LIMIT, 10000), 'restart')

    def test_released_memory_does_not_restart(self):
        p = dict(action='reload', state='verified', at=9900)
        self.assertEqual(m.decision(p, 'ok', 500000, 10000), 'healthy')

    def test_stale_reload_not_proof_of_failed_release(self):
        p = dict(action='reload', state='verified', at=9000)
        self.assertEqual(m.decision(p, 'ok', m.MEMORY_LIMIT, 10000), 'reload')

    def test_single_transport_failure_only_records(self):
        self.assertEqual(m.decision({}, 'failed', 300, 10000), 'confirm_transport_failure')

    def test_wrong_page_identity_never_restarts_browser(self):
        self.assertEqual(m.decision({'transport_failed_at':9900}, 'invalid', m.MEMORY_LIMIT, 10000), 'browser_identity_requires_review')

    def test_second_immediate_failure_still_waits(self):
        self.assertEqual(m.decision({'transport_failed_at':9999}, 'failed', 300, 10000), 'confirm_transport_failure')

    def test_repeated_transport_failure_recovers(self):
        self.assertEqual(m.decision({'transport_failed_at':9900}, 'failed', 300, 10000), 'restart')

    def test_restart_cooldown_does_not_loop(self):
        p = dict(transport_failed_at=9900, last_restart_at=9800)
        self.assertEqual(m.decision(p, 'failed', 300, 10000), 'restart_cooldown')

    def test_unknown_or_interrupted_never_replays(self):
        for state in ('started', 'unknown'):
            with self.subTest(state=state):
                self.assertEqual(m.decision({'state':state}, 'failed', m.MEMORY_LIMIT, 10000), 'reconcile_required')

    def test_http_success_does_not_replace_real_transport(self):
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'timeout')):
            self.assertEqual(m.probe()['status'], 'failed')

    def test_timeout_is_bounded_and_reported(self):
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 8)):
            self.assertEqual(m.probe()['reason'], 'browser_connection_timeout')

    def test_actual_transport_contract_required(self):
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"status":"ok"}\n', '')):
            self.assertEqual(m.probe(), {'status':'ok'})

    def test_changed_reply_is_not_healthy(self):
        with patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"status":"ok","unexpected":true}', '')):
            with self.assertRaises(ValueError): m.probe()

    def test_container_identity_rejects_path_traversal(self):
        with patch.object(m.subprocess, 'check_output', return_value='../other'):
            with self.assertRaises(ValueError): m.memory_bytes()

    def test_probe_never_reads_sessions_or_writes_prices(self):
        compile(m.PROBE, '<browser-probe>', 'exec')
        for forbidden in ('cookies(', 'local_storage', 'storage_state', 'request.post', 'set_cookies'):
            self.assertNotIn(forbidden, m.PROBE)

    def test_unknown_restart_is_reconciled_from_original_container(self):
        p=dict(action='restart',before_container=dict(id='same',started_at='old'))
        current=dict(id='same',started_at='new',running=True,restarting=False)
        self.assertEqual(m.reconcile_outcome(p,current,'failed'),'failed_after_restart')

    def test_unknown_restart_not_replayed_if_not_proven_finished(self):
        p=dict(action='restart',before_container=dict(id='same',started_at='old'))
        current=dict(id='same',started_at='old',running=True,restarting=False)
        self.assertEqual(m.reconcile_outcome(p,current,'failed'),'unknown')

    def test_unknown_restart_in_progress_stays_unknown(self):
        p=dict(action='restart',before_container=dict(id='same',started_at='old'))
        current=dict(id='same',started_at='new',running=True,restarting=True)
        self.assertEqual(m.reconcile_outcome(p,current,'failed'),'unknown')

    def test_failed_readonly_reload_not_replayed(self):
        self.assertEqual(m.reconcile_outcome({'action':'reload'},{},'failed'),'failed_readonly_reload')


class MaintenanceBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('state', 'queue', 'jobs', 'recovery-receipts'):
            (self.root/name).mkdir()
        (self.root/'state/snapshot.lock').touch()
        self.policy = dict(system_enabled=True, mode='auto')
        self.mode = {'mode':'server'}
        self.health = {'incomplete_executions':0}
        tick = types.SimpleNamespace(ROOT=self.root, load_policy=lambda:self.policy,
                                     queue_mutation=nullcontext, RETRY_LOCKS=['snapshot.lock'], retry_guard=lambda:'ready')
        modules = {'automation_tick':tick, 'fc27_cloud_api':types.SimpleNamespace(health=lambda:self.health),
                   'local_collection':types.SimpleNamespace(config=lambda:self.mode),
                   'snapshot_layer':types.SimpleNamespace(atomic_json=lambda p,v:p.write_text(json.dumps(v))),
                   'fcntl':types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda *a:None)}
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules, modules).start()
        self.isolation = self.root/'order-isolation.json'
        self.service = self.root/'order-service.py'
        self.service.write_text('isolated_browser')
        self.isolation.write_text(json.dumps(dict(status='verified',durability_verified=True,container='fs-order-browser',
            service_sha256=hashlib.sha256(self.service.read_bytes()).hexdigest())))
        patch.object(m, 'ORDER_ISOLATION', self.isolation).start()
        patch.object(m, 'ORDER_SERVICE', self.service).start()
        self.probe = patch.object(m, 'probe', return_value={'status':'ok'}).start()
        patch.object(m, 'memory_bytes', return_value=1000).start()
        patch.object(m, 'container_state', return_value=dict(id='same',started_at='old',running=True,restarting=False)).start()
        self.command = patch.object(m.subprocess, 'run').start()

    def test_healthy_idle_does_not_restart_or_reload(self):
        self.assertEqual(m.maintain()['status'], 'healthy')
        self.probe.assert_called_once_with()
        self.command.assert_not_called()

    def test_local_collection_not_touched(self):
        self.mode['mode'] = 'local'
        self.assertEqual(m.maintain()['status'], 'not_applicable')
        self.probe.assert_not_called()

    def test_automation_off_not_touched(self):
        self.policy['system_enabled'] = False
        self.assertEqual(m.maintain()['status'], 'not_applicable')
        self.probe.assert_not_called()

    def test_queued_job_blocks_recovery(self):
        (self.root/'queue/job.json').write_text('{}')
        self.assertEqual(m.maintain()['status'], 'busy')
        self.probe.assert_not_called()

    def test_running_job_blocks_recovery(self):
        (self.root/'jobs/job.json').write_text('{"status":"running"}')
        self.assertEqual(m.maintain()['status'], 'busy')
        self.probe.assert_not_called()

    def test_unknown_price_execution_blocks_recovery(self):
        self.health['incomplete_executions'] = 1
        self.assertEqual(m.maintain()['status'], 'busy')
        self.probe.assert_not_called()

    def test_reverted_order_broker_blocks_fc_restart(self):
        self.service.write_text('shared_browser_again')
        self.assertEqual(m.maintain()['status'], 'order_browser_isolation_required')
        self.probe.assert_not_called()

    def test_missing_isolation_blocks_fc_restart(self):
        self.isolation.unlink()
        self.assertEqual(m.maintain()['status'], 'order_browser_isolation_required')
        self.probe.assert_not_called()

    def test_unverified_restart_durability_blocks_fc_restart(self):
        d=json.loads(self.isolation.read_text())
        d['durability_verified']=False
        self.isolation.write_text(json.dumps(d))
        self.assertEqual(m.maintain()['status'], 'order_browser_isolation_required')
        self.probe.assert_not_called()

    def test_high_memory_reloads_and_keeps_one_receipt(self):
        with patch.object(m, 'memory_bytes', return_value=m.MEMORY_LIMIT):
            result = m.maintain()
        self.assertEqual(result['action'], 'reload')
        self.assertEqual(self.probe.call_args_list[-1].args, ('reload',))
        self.command.assert_not_called()
        self.assertEqual(len(list((self.root/'recovery-receipts').glob('*.json'))), 1)
        state = json.loads((self.root/'state/browser-lifecycle.json').read_text())
        self.assertEqual(state['state'], 'verified')
        self.assertEqual(state['price_requests'], 0)

    def test_unknown_action_is_readback_only_on_original_id(self):
        state = dict(state='unknown',event_id='original',action='restart')
        (self.root/'state/browser-lifecycle.json').write_text(json.dumps(state))
        result = m.maintain()
        self.assertEqual(result['status'], 'reconciled_without_replay')
        self.assertEqual(result['event_id'], 'original')
        self.command.assert_not_called()

    def test_unknown_still_unhealthy_never_restarts(self):
        (self.root/'state/browser-lifecycle.json').write_text('{"state":"unknown","event_id":"original"}')
        self.probe.return_value={'status':'failed'}
        self.assertEqual(m.maintain()['status'], 'reconcile_required')
        self.command.assert_not_called()


if __name__ == '__main__': unittest.main()
