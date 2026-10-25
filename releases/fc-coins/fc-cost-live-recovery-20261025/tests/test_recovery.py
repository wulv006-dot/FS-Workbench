"""Exercise the actual changed functions without a browser or business writes."""
import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import traceback
import unittest
import uuid

HERE = Path(__file__).resolve().parents[1]


def functions(filename, names, namespace, baseline=False):
    tree = ast.parse((HERE / ('baseline' if baseline else 'source') / filename).read_text())
    tree.body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
                 and node.name in names]
    exec(compile(tree, filename, 'exec'), namespace)
    return namespace


class Recovery(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('runs', 'quotes', 'previews', 'requests', 'executions', 'all-coin-sync', 'player-sync'):
            (self.root / name).mkdir()
        self.jid = str(uuid.uuid4())
        self.snapshot = dict(run_id=self.jid, status='incomplete', quote_status='NO_QUOTE',
                             reason='IGGM:http_blocked;P2PAH:global_order_transport_unavailable')
        (self.root / 'runs' / (self.jid + '.json')).write_text(json.dumps(self.snapshot))
        self.job = dict(kind='auto_cycle', status='failed', error='collection_incomplete',
                        request={'policy_revision': 40}, job_id=self.jid,
                        completed_at=datetime.now(timezone.utc).isoformat(),
                        snapshot=self.snapshot, error_detail=self.snapshot['reason'])
        self.ns = functions('automation_tick.py', {'valid_job_id', 'read_record', 'proven_prewrite_timeout'},
                            dict(ROOT=self.root, uuid=uuid, json=json,
                                 TRANSIENT_TIMEOUTS={'TimeoutError', 'page_read_timeout'}))

    def test_transport_retry_requires_prewrite_evidence(self):
        check = self.ns['proven_prewrite_timeout']
        self.assertTrue(check(self.job, 40))
        for folder in ('quotes', 'previews', 'requests', 'executions', 'all-coin-sync', 'player-sync'):
            path = self.root / folder / (self.jid + '.json')
            path.write_text('{}')
            self.assertFalse(check(self.job, 40), folder)
            path.unlink()
        self.job['writer_result'] = {'status': 'UNKNOWN'}
        self.assertFalse(check(self.job, 40))

    def test_unknown_auth_validation_and_policy_changes_do_not_fast_retry(self):
        for reason in ('RuntimeError', 'global_order_session_unavailable', 'login_expired',
                       'cost_delivery_type_unverified', 'global_order_transport_unavailable:extra'):
            self.snapshot['reason'] = 'P2PAH:' + reason
            self.job['error_detail'] = self.snapshot['reason']
            (self.root / 'runs' / (self.jid + '.json')).write_text(json.dumps(self.snapshot))
            self.assertFalse(self.ns['proven_prewrite_timeout'](self.job, 40), reason)
        self.assertFalse(self.ns['proven_prewrite_timeout'](self.job, 41))

    def test_existing_fast_retry_is_no_longer_shadowed(self):
        policy = dict(system_enabled=True, mode='auto', platforms=['PS'], revision=40, interval_minutes=120)
        now = datetime.now(timezone.utc)
        namespace = dict(datetime=datetime, timezone=timezone, timedelta=timedelta,
                         utc=datetime.fromisoformat, proven_readonly_cycle_failure=lambda *a: True,
                         retry_plan=lambda *a: {'status': 'retry_due'})
        old = functions('automation_tick.py', {'due'}, dict(namespace), baseline=True)['due']
        new = functions('automation_tick.py', {'due'}, dict(namespace))['due']
        self.assertEqual(old(policy, self.job, now), 'waiting')
        self.assertEqual(new(policy, self.job, now), 'retry_due')
        for status in ('retry_blocked', 'retry_waiting', 'retry_cooldown'):
            ns = functions('automation_tick.py', {'due'}, dict(namespace, retry_plan=lambda *a: {'status': status}))
            self.assertEqual(ns['due'](policy, self.job, now), status)
        ns = functions('automation_tick.py', {'due'}, dict(namespace, retry_plan=lambda *a: None))
        self.assertEqual(ns['due'](policy, self.job, now), 'waiting')
        self.assertEqual(ns['due'](policy, self.job, now + timedelta(minutes=121)), 'due')
        self.assertEqual(new(dict(policy, system_enabled=False), self.job, now), 'system_off')

    def failure(self, exc):
        ns = functions('collect_p2pah_cost.py', {'failure_result', 'CostPageError', 'timeout_diagnostic'},
                       dict(os=os, traceback=traceback, CollectorTimeoutError=TimeoutError))
        return ns['failure_result'](exc)

    def test_failure_codes_do_not_expose_broker_payload(self):
        for suffix in ('TimeoutError', 'ConnectionRefusedError', 'order_probe_unavailable', 'no_socket'):
            self.assertEqual(self.failure(RuntimeError('global_order_unavailable:' + suffix))['reason'],
                             'global_order_transport_unavailable')
        for suffix in ('login_expired', 'PermissionError', 'ValueError', 'cookie=secret-token'):
            value = self.failure(RuntimeError('global_order_unavailable:' + suffix))
            self.assertEqual(value['reason'], 'global_order_session_unavailable')
            self.assertNotIn(suffix, json.dumps(value))
        self.assertEqual(self.failure(RuntimeError('secret-token'))['reason'], 'RuntimeError')

    def test_trace_is_bounded_and_has_no_message(self):
        try:
            raise RuntimeError('secret-token')
        except RuntimeError as exc:
            value = self.failure(exc)
        self.assertNotIn('secret-token', json.dumps(value))
        self.assertTrue(value['diagnostic']['stack'])
        self.assertLessEqual(len(value['diagnostic']['stack']), 8)

    def test_session_is_applied_once_and_browser_cleanup_remains(self):
        tree = ast.parse((HERE / 'source/collect_p2pah_cost.py').read_text())
        collect = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'collect')
        calls = [n.func.id for n in ast.walk(collect) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        self.assertEqual(calls.count('open_backend'), 1)
        self.assertNotIn('login', calls)
        self.assertEqual(calls.count('close_backend'), 1)


if __name__ == '__main__':
    unittest.main()
