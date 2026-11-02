from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'source'))
from collection_cases import NOW, context, coordinator, identity, observation, policy


class CollectionLimits(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'collection.sqlite3'
        self.c = coordinator(self.path)
        self.task = self.c.claim_job(identity(), ['ItemD2R'], NOW)

    def test_partition_keeps_request_permit_after_lease_and_restart(self):
        self.c.reserve_request(identity(), self.task['job_id'], 1, dict(count=1), NOW)
        from fc_collection.coordinator import Coordinator
        recovered = Coordinator(self.path)
        self.assertIsNone(recovered.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=23)))
        task = recovered.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=33))
        self.assertEqual(task['lease_epoch'], 2)

    def test_unknown_network_result_consumes_budget_across_attempts(self):
        self.c.reserve_request(identity(), self.task['job_id'], 1, dict(count=6), NOW)
        task = self.c.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=33))
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.c.reserve_request(identity('187'), task['job_id'], 2, dict(count=1), NOW + timedelta(seconds=33))

    def test_renewal_does_not_extend_business_deadline_or_reset_budget(self):
        self.c.reserve_request(identity(), self.task['job_id'], 1, dict(count=6), NOW)
        task = self.c.renew_lease(identity(), self.task['job_id'], self.task['attempt_id'], 1, NOW + timedelta(seconds=10))
        self.assertEqual(task['request_budget_reserved'], 6)
        self.assertEqual(task['deadline_at'], self.task['deadline_at'])
        with self.assertRaisesRegex(ValueError, 'lease'):
            self.c.renew_lease(identity(), task['job_id'], task['attempt_id'], 1, NOW + timedelta(minutes=10))

    def test_shared_origin_budget_and_cooldown_cannot_be_reset_by_config(self):
        self.c.configure_source('Lootbar', policy())
        body = observation(self.task)
        body.update(status='blocked', reason_code='http_429', offers=[], retry_after_seconds=120)
        self.c.reserve_request(identity(), self.task['job_id'], 1, dict(count=1), NOW)
        receipt = self.c.submit_observation(identity(), body, NOW)
        self.assertEqual(receipt['status'], 'accepted')
        self.c.configure_source('ItemD2R', dict(policy(), generation=2))
        from fc_collection.contracts import build_job
        other = build_job(dict(run_id='other-run', created_at=NOW.isoformat()), 'Lootbar', context(),
                          (NOW + timedelta(minutes=10)).isoformat())
        self.c.enqueue(other)
        self.c.register_node(identity(), ['ItemD2R', 'Lootbar'], NOW - timedelta(seconds=6))
        self.assertIsNone(self.c.claim_job(identity(), ['Lootbar'], NOW + timedelta(seconds=119)))
        self.assertIsNotNone(self.c.claim_job(identity(), ['Lootbar'], NOW + timedelta(seconds=120)))

    def test_403_blocks_whole_origin_without_switching_nodes(self):
        self.c.reserve_request(identity(), self.task['job_id'], 1, dict(count=1), NOW)
        body = observation(self.task)
        body.update(status='blocked', reason_code='http_403', offers=[])
        self.assertEqual(self.c.submit_observation(identity(), body, NOW)['status'], 'accepted')
        self.c.configure_source('ItemD2R', dict(policy(), generation=2))
        from fc_collection.contracts import build_job
        self.c.enqueue(build_job(dict(run_id='run-2', created_at=NOW.isoformat()), 'ItemD2R',
            dict(context(), assignment_generation=2), (NOW + timedelta(minutes=10)).isoformat()))
        self.assertIsNone(self.c.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(hours=1)))

    def test_rejected_unknown_fields_never_persist_secret_payload(self):
        body = dict(observation(self.task), token='never-persist-this-secret')
        receipt = self.c.submit_observation(identity(), body, NOW)
        self.assertEqual(receipt['status'], 'rejected')
        with self.c.transaction() as db:
            stored = '\n'.join(row['body'] for row in db.execute('SELECT body FROM collection_observations'))
        self.assertNotIn('never-persist-this-secret', stored)

    def test_unregistered_origin_consumer_cannot_loosen_shared_limits(self):
        with self.assertRaises(ValueError):
            self.c.configure_source('Lootbar', dict(policy(), max_requests=600))

    def test_temporary_http_failure_retries_with_remaining_budget_after_safe_deadline(self):
        self.c.reserve_request(identity(), self.task['job_id'], 1, dict(count=1), NOW)
        body = observation(self.task)
        body.update(status='failed', reason_code='http_502', offers=[])
        self.assertEqual(self.c.submit_observation(identity(), body, NOW)['status'], 'accepted')
        self.assertIsNone(self.c.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=23)))
        retried = self.c.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=33))
        self.assertIsNotNone(retried)
        self.assertEqual(retried['lease_epoch'], 2)
        self.assertEqual(retried['request_budget_reserved'], 1)

    def test_primary_disappears_before_claim_backup_can_take_new_job(self):
        from fc_collection.contracts import build_job
        self.c.enqueue(build_job(dict(run_id='run-2', created_at=NOW.isoformat()), 'ItemD2R', context(),
            (NOW + timedelta(minutes=10)).isoformat()))
        # The first leased job remains protected; the new unclaimed job can use the healthy backup.
        task = self.c.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=23))
        self.assertIsNotNone(task)
        second = self.c.claim_job(identity('187'), ['ItemD2R'], NOW + timedelta(seconds=23))
        self.assertIsNotNone(second)
        self.assertNotEqual(task['job_id'], second['job_id'])


class RestrictedTransport(unittest.TestCase):
    def transport(self):
        from fc_collection.adapters import RestrictedHTTP
        return RestrictedHTTP({'ItemD2R': {'offer': dict(host='example.org', path='/offer', max_bytes=1024)}})

    def test_arbitrary_url_unknown_template_and_unsafe_dns_rejected(self):
        transport = self.transport()
        for template in ('http://127.0.0.1/', 'https://example.org/offer', 'unknown'):
            with self.subTest(template=template), self.assertRaises(ValueError):
                transport.fetch('ItemD2R', template, 1)
        for ip in ('127.0.0.1', '10.1.2.3', '169.254.169.254', '::1', '100.64.0.1'):
            with self.subTest(ip=ip), patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', (ip, 443))]), self.assertRaises(ValueError):
                transport.fetch('ItemD2R', 'offer', 1)

    def test_request_registry_rejects_auth_paths_and_insecure_endpoints(self):
        from fc_collection.adapters import RestrictedHTTP
        for change in ({'path': '//127.0.0.1/'}, {'path': '/offer?token=secret'},
                       {'host': 'localhost'}, {'max_bytes': 0}, {'headers': {'Authorization': 'secret'}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                RestrictedHTTP({'ItemD2R': {'offer': {**dict(host='example.org', path='/offer', max_bytes=1024), **change}}})

    def test_slow_dns_is_bounded_before_any_connection(self):
        import time
        def resolver(*args, **kwargs):
            time.sleep(.5)
            return [(2, 1, 6, '', ('93.184.216.34', 443))]
        start = time.monotonic()
        with patch('socket.getaddrinfo', side_effect=resolver), patch('fc_collection.adapters.PinnedHTTPS',
                side_effect=ValueError('connection_must_not_start')), self.assertRaises(ValueError):
            self.transport().fetch('ItemD2R', 'offer', .01)
        self.assertLess(time.monotonic() - start, .4)

    def test_response_header_wait_is_cancelled_at_whole_request_deadline(self):
        import threading
        import time
        from fc_collection.adapters import SourceUnavailable
        cancelled = threading.Event()
        class Connection:
            def __init__(self, *args):
                pass
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                cancelled.wait(.5)
                raise SourceUnavailable('request_timeout')
            def abort(self):
                cancelled.set()
            def close(self):
                pass
        start = time.monotonic()
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('fc_collection.adapters.PinnedHTTPS', Connection), self.assertRaises(SourceUnavailable):
            self.transport().fetch('ItemD2R', 'offer', .02)
        self.assertTrue(cancelled.is_set())
        self.assertLess(time.monotonic() - start, .4)

    def test_tls_verification_failure_does_not_become_a_node_retry(self):
        import ssl
        from fc_collection.adapters import SourceUnavailable
        class Connection:
            def __init__(self, *args):
                pass
            def request(self, *args, **kwargs):
                raise ssl.SSLCertVerificationError('certificate_mismatch')
            def abort(self):
                pass
            def close(self):
                pass
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('93.184.216.34', 443))]), \
                patch('fc_collection.adapters.PinnedHTTPS', Connection), \
                self.assertRaisesRegex(SourceUnavailable, 'tls_validation_failed'):
            self.transport().fetch('ItemD2R', 'offer', 1)
