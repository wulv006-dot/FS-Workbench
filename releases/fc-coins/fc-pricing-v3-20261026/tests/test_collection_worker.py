from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'source'))
from collection_cases import NOW, coordinator, identity, observation


class CollectionWorker(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.endpoint = coordinator(self.root / 'collection.sqlite3')

    def worker(self, endpoint=None, adapter=None):
        from fc_collection.worker import Worker
        return Worker(endpoint or self.endpoint, identity(), {'ItemD2R': adapter or self.adapter},
                      self.root / 'spool', self.transport, clock=lambda: NOW)

    def transport(self, source, template, timeout):
        self.assertEqual(source, 'ItemD2R')
        self.assertGreater(timeout, 0)
        return b'fixture'

    def adapter(self, task, transport):
        transport.get('offer')
        body = observation(task)
        return {key: body[key] for key in ('status', 'reason_code', 'offers', 'evidence_hash')}

    def test_lost_ack_retries_same_spooled_result_without_recapturing(self):
        calls = []
        def adapter(task, transport):
            calls.append(task['job_id'])
            return self.adapter(task, transport)
        endpoint = self.endpoint
        class LostACK:
            def __getattr__(self, name):
                return getattr(endpoint, name)
            def submit_observation(self, principal, body, now):
                endpoint.submit_observation(principal, body, now)
                raise OSError('ack_lost')
        with self.assertRaises(OSError):
            self.worker(LostACK(), adapter).run_once()
        self.assertEqual(len(list((self.root / 'spool').glob('*.json'))), 1)
        receipt = self.worker(adapter=adapter).run_once()
        self.assertEqual(receipt['status'], 'accepted')
        self.assertEqual(len(calls), 1)
        self.assertEqual(list((self.root / 'spool').glob('*.json')), [])

    def test_unavailable_coordinator_prevents_new_network_requests(self):
        endpoint = self.endpoint
        network = []
        class Partition:
            def __getattr__(self, name):
                return getattr(endpoint, name)
            def reserve_request(self, *args):
                raise OSError('coordinator_unavailable')
        def adapter(task, transport):
            transport.get('offer')
            network.append('sent')
        receipt = self.worker(Partition(), adapter).run_once()
        self.assertEqual(network, [])
        self.assertEqual(receipt['status'], 'accepted')

    def test_invalid_adapter_payload_never_enters_spool_or_receipt(self):
        def adapter(task, transport):
            return dict(self.adapter(task, transport), token='must-not-be-spooled')
        with self.assertRaises(ValueError):
            self.worker(adapter=adapter).run_once()
        self.assertEqual(list((self.root / 'spool').glob('*')), [])

    def test_full_spool_refuses_claim_before_capture(self):
        worker = self.worker()
        worker.spool.mkdir(exist_ok=True)
        for index in range(32):
            (worker.spool / ('%032x.json' % index)).write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError, 'spool'):
            worker.run_once()
        self.assertIsNotNone(self.endpoint.claim_job(identity(), ['ItemD2R'], NOW))

    def test_boot_change_allows_only_original_committed_receipt_ack(self):
        task = self.endpoint.claim_job(identity(), ['ItemD2R'], NOW)
        self.endpoint.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
        body = observation(task)
        old = self.endpoint.submit_observation(identity(), body, NOW)
        new_identity = identity(boot='boot-2')
        self.endpoint.register_node(new_identity, ['ItemD2R'], NOW + timedelta(seconds=1))
        self.assertEqual(self.endpoint.submit_observation(new_identity, body, NOW + timedelta(seconds=901)), old)

    def test_atomic_spool_crash_recovers_pending_result_without_new_capture(self):
        import json
        task = self.endpoint.claim_job(identity(), ['ItemD2R'], NOW)
        self.endpoint.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
        body = dict(observation(task), observation_id='a' * 32)
        worker = self.worker(adapter=lambda *_: self.fail('must not recapture'))
        (worker.spool / '.pending-abcdefgh').write_text(json.dumps(body), encoding='utf-8')
        self.assertEqual(worker.run_once()['status'], 'accepted')
        self.assertEqual(list(worker.spool.iterdir()), [])

    def test_clock_offset_cannot_extend_a_request_beyond_server_permit(self):
        from fc_collection.worker import BudgetedTransport
        task = self.endpoint.claim_job(identity(), ['ItemD2R'], NOW)
        endpoint = self.endpoint
        class ServerClock:
            def renew_lease(self, principal, job, attempt, epoch, now):
                return endpoint.renew_lease(principal, job, attempt, epoch, NOW)
            def reserve_request(self, principal, job, epoch, group, now):
                return endpoint.reserve_request(principal, job, epoch, group, NOW)
        sent = []
        transport = BudgetedTransport(ServerClock(), identity(), task,
            lambda *args: sent.append(args), clock=lambda: NOW - timedelta(seconds=4))
        with self.assertRaisesRegex(ValueError, 'clock'):
            transport.get('offer')
        self.assertEqual(sent, [])

    def test_parser_error_is_final_missing_evidence_without_node_retry_or_secret_log(self):
        def adapter(task, transport):
            transport.get('offer')
            raise ValueError('bad source contains token=must-not-persist')
        receipt = self.worker(adapter=adapter).run_once()
        self.assertEqual(receipt['status'], 'accepted')
        from collection_cases import job
        accepted = self.endpoint.accepted(job()['job_id'], NOW)
        self.assertEqual(accepted[0]['reason_code'], 'adapter_contract_invalid')
        self.assertNotIn('must-not-persist', str(accepted))
        self.assertIsNone(self.endpoint.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=100)))

    def test_wrong_receipt_hash_keeps_original_result_for_idempotent_ack(self):
        endpoint = self.endpoint
        class WrongHash:
            def __getattr__(self, name):
                return getattr(endpoint, name)
            def submit_observation(self, *args):
                return dict(endpoint.submit_observation(*args), payload_hash='0' * 64)
        with self.assertRaisesRegex(ValueError, 'receipt'):
            self.worker(WrongHash()).run_once()
        self.assertEqual(len(list((self.root / 'spool').glob('*.json'))), 1)
        self.assertEqual(self.worker(adapter=lambda *_: self.fail('no recapture')).run_once()['status'], 'accepted')

    def test_new_boot_rejects_uncommitted_old_result_once_and_drains_spool(self):
        import json
        task = self.endpoint.claim_job(identity(), ['ItemD2R'], NOW)
        self.endpoint.reserve_request(identity(), task['job_id'], 1, dict(count=1), NOW)
        body = dict(observation(task), observation_id='c' * 32)
        self.endpoint.register_node(identity(boot='boot-2'), ['ItemD2R'], NOW + timedelta(seconds=1))
        self.endpoint.claim_job(identity(boot='boot-2'), ['ItemD2R'], NOW + timedelta(seconds=33))
        from fc_collection.worker import Worker
        spool = self.root / 'spool'; spool.mkdir()
        (spool / ('c' * 32 + '.json')).write_text(json.dumps(body))
        worker = Worker(self.endpoint, identity(boot='boot-2'), {}, spool, self.transport,
                        clock=lambda: NOW + timedelta(seconds=33))
        receipt = worker.run_once()
        self.assertEqual(receipt['status'], 'rejected')
        self.assertEqual(receipt['reason'], 'lease_invalid')
        self.assertEqual(list(spool.iterdir()), [])
        self.assertEqual(self.endpoint.submit_observation(identity(boot='boot-2'), body,
            NOW + timedelta(seconds=34)), receipt)
