from datetime import timedelta
from io import BytesIO
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, coordinator, identity, observation


class CollectionProtocol(unittest.TestCase):
    def test_budget_denial_keeps_its_reason_instead_of_becoming_parser_failure(self):
        from fc_collection.protocol import CallbackEndpoint, write_message
        from fc_collection.adapters import SourceUnavailable
        response = BytesIO()
        write_message(response, dict(kind='reply', id=1, error='request_budget_unavailable'))
        response.seek(0)
        endpoint = CallbackEndpoint(None, identity(), response, BytesIO())
        with self.assertRaisesRegex(SourceUnavailable, 'request_budget_unavailable'):
            endpoint.reserve_request(identity(), 'job', 1, dict(count=1), NOW)

    def test_frame_rejects_unbounded_nonobject_and_nonfinite_input(self):
        from fc_collection.protocol import read_message
        for body in (b'x' * 131073, b'[]\n', b'{"x":NaN}\n', b'{"x":1}', b'not-json\n',
                     b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}\n'):
            with self.subTest(size=len(body)), self.assertRaises(ValueError):
                read_message(BytesIO(body))

    def test_callbacks_cannot_forward_shell_identity_clock_or_other_jobs(self):
        from fc_collection.protocol import handle_callback
        with tempfile.TemporaryDirectory() as folder:
            c = coordinator(Path(folder) / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            base = dict(kind='call', id=1, method='reserve_request',
                        params=dict(job_id=task['job_id'], lease_epoch=1, request_group=dict(count=1)))
            invalid = [dict(base, method='shell'), dict(base, params=dict(base['params'], node_id='187')),
                       dict(base, params=dict(base['params'], now=NOW.isoformat())),
                       dict(base, params=dict(base['params'], job_id='another-job'))]
            for message in invalid:
                reply = handle_callback(c, identity(), task, message, lambda: NOW)
                self.assertIn('error', reply)
            good = handle_callback(c, identity(), task, base, lambda: NOW)
            self.assertEqual(good['result']['node_id'], '183')

    def test_worker_and_coordinator_exchange_real_budget_and_durable_ack(self):
        from fc_collection.protocol import handle_callback, read_message, serve_task, write_message
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            c = coordinator(root / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            left, right = socket.socketpair()
            self.addCleanup(left.close); self.addCleanup(right.close)
            left.settimeout(5); right.settimeout(5)
            parent, child = left.makefile('rwb', buffering=0), right.makefile('rwb', buffering=0)
            self.addCleanup(parent.close); self.addCleanup(child.close)
            failures = []
            def adapter(job, transport):
                transport.get('offer')
                body = observation(job)
                return {key: body[key] for key in ('status', 'reason_code', 'offers', 'evidence_hash')}
            def run():
                try:
                    serve_task(task, identity(), {'ItemD2R': adapter}, {'ItemD2R': 'test-adapter-1'},
                               root / 'spool', lambda *_: b'fixture', child, child, lambda: NOW)
                except BaseException as exc:
                    failures.append(exc)
            thread = threading.Thread(target=run, daemon=True)
            thread.start()
            count = 0
            while True:
                message = read_message(parent)
                if message['kind'] == 'done':
                    self.assertEqual(message['result']['status'], 'accepted')
                    break
                count += 1
                self.assertLess(count, 10)
                write_message(parent, handle_callback(c, identity(), task, message, lambda: NOW))
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failures, [])
            self.assertEqual(len(c.accepted(task['job_id'], NOW)), 1)
            self.assertEqual(list((root / 'spool').iterdir()), [])

    def test_remote_task_cannot_smuggle_writer_fields_or_wrong_boot(self):
        from fc_collection.protocol import validate_task
        with tempfile.TemporaryDirectory() as folder:
            c = coordinator(Path(folder) / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            for changed in (dict(task, command='id'), dict(task, node_boot_id='old-boot'),
                            dict(task, requested_platforms=['PS']), dict(task, total_request_budget=1000)):
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    validate_task(changed, identity(), {'ItemD2R': 'test-adapter-1'}, NOW)

    def test_measured_clock_margin_accepts_slightly_behind_worker(self):
        from fc_collection.protocol import validate_task
        with tempfile.TemporaryDirectory() as folder:
            c = coordinator(Path(folder) / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            validate_task(task, identity(), {'ItemD2R': 'test-adapter-1'}, NOW - timedelta(seconds=1))
            with self.assertRaises(ValueError):
                validate_task(task, identity(), {'ItemD2R': 'test-adapter-1'}, NOW - timedelta(seconds=3))

    def test_taskless_resend_returns_original_ack_after_rollout_and_expiry(self):
        import json
        from fc_collection.protocol import handle_callback, read_message, serve_replay, write_message
        from collection_cases import policy
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            c = coordinator(root / 'collection.sqlite3')
            task = c.claim_job(identity(), ['ItemD2R'], NOW)
            c.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
            body = dict(observation(task), observation_id='b' * 32)
            original = c.submit_observation(identity(), body, NOW)
            c.configure_source('ItemD2R', dict(policy(), generation=2, mode='off'))
            new_identity = identity(boot='boot-2')
            later = NOW + timedelta(seconds=1000)
            c.register_node(new_identity, ['ItemD2R'], later)
            spool = root / 'spool'; spool.mkdir()
            (spool / ('b' * 32 + '.json')).write_text(json.dumps(body))
            left, right = socket.socketpair()
            self.addCleanup(left.close); self.addCleanup(right.close)
            left.settimeout(5); right.settimeout(5)
            parent, child = left.makefile('rwb', buffering=0), right.makefile('rwb', buffering=0)
            self.addCleanup(parent.close); self.addCleanup(child.close)
            thread = threading.Thread(target=lambda: serve_replay(new_identity, spool, child, child, lambda: later), daemon=True)
            thread.start()
            callback = read_message(parent)
            self.assertEqual(callback['method'], 'submit_observation')
            write_message(parent, handle_callback(c, new_identity, None, callback, lambda: later))
            final = read_message(parent)
            self.assertEqual(final['result'], original)
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(list(spool.iterdir()), [])
            self.assertEqual(c.accepted(task['job_id'], later), [])
