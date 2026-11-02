from contextlib import nullcontext
from datetime import timedelta
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'source'))
from collection_cases import NOW, identity, observation, policy
from test_collection_routing import quote, arab_context
from fc_collection.contracts import build_job, to_arab_status
from fc_collection.coordinator import Coordinator
from fc_collection.public_sources import VERSIONS


class Failover(unittest.TestCase):
    def setUp(self):
        from fc_collection import client, failover
        self.client, self.failover = client, failover
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.now = NOW
        self.routing = dict(schema_version=1, remote_result_mode='consume', assignment_generation=1)
        self.endpoint = Coordinator(self.folder / 'state.sqlite3')
        self.source = dict(policy(), origin='https://www.arab-ut.com', adapter_version=VERSIONS['ArabUT'])
        self.endpoint.configure_source('ArabUT', self.source)
        self.endpoint.register_node(identity(), ['ArabUT'], NOW - timedelta(seconds=6))
        self.job = build_job(dict(run_id='parent-1', created_at=NOW.isoformat()), 'ArabUT',
            dict(arab_context(), total_attempt_limit=2, total_request_budget=6), (NOW + timedelta(seconds=200)).isoformat())
        self.endpoint.enqueue(self.job)
        self.old = self.endpoint.claim_job(identity(), ['ArabUT'], NOW)
        self.permit = self.endpoint.reserve_request(identity(), self.old['job_id'], self.old['lease_epoch'], dict(count=1), NOW)
        self.requests = []
        def fetch(source, template, timeout):
            self.requests.append((source, template, self.now))
            return b'' if template == 'warm' else json.dumps(quote()).encode()
        patches = [patch.object(client, 'utc', side_effect=lambda: self.now),
            patch.object(client, 'read_routing', side_effect=lambda: self.routing.copy()),
            patch.object(failover, 'LOCAL_STATE', self.folder / 'local'),
            patch.object(failover, 'local_worker_lock', return_value=nullcontext()),
            patch.object(failover.time, 'sleep', side_effect=self.advance),
            patch.object(failover.RestrictedHTTP, 'fetch', side_effect=fetch)]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)

    def run_local(self):
        return self.failover.run_fallback(self.endpoint, self.job, self.routing)

    def test_partition_waits_for_old_lease_and_unknown_permit_then_new_epoch_once(self):
        self.run_local()
        self.assertGreaterEqual((self.requests[0][2] - NOW).total_seconds(), 32)
        with self.endpoint.transaction() as db:
            latest = self.endpoint._get(db, 'collection_jobs', self.job['job_id'])
            self.assertEqual((latest['lease_epoch'], latest['attempts'], latest['node_id']), (2, 2, '187'))
            self.assertEqual(db.execute('SELECT SUM(count) FROM collection_permits').fetchone()[0], 3)
        projected = to_arab_status(self.endpoint.accepted(self.job['job_id'], self.now), latest, self.now)
        self.assertEqual(len(projected['offers']), 2)
        late = observation(self.old)
        late['offers'] = []
        late.update(status='failed', reason_code='transport_unavailable')
        receipt = self.endpoint.submit_observation(identity(), late, self.now)
        self.assertEqual(receipt['status'], 'rejected')
        self.assertEqual(self.endpoint.submit_observation(identity(), late, self.now), receipt)

    def test_known_completed_failed_request_still_waits_for_lease_and_keeps_failed_receipt(self):
        self.endpoint.complete_request(identity(), self.old['job_id'], self.old['lease_epoch'], self.permit['permit_id'], NOW)
        failed = observation(self.old)
        failed.update(offers=[], status='failed', reason_code='transport_unavailable')
        receipt = self.endpoint.submit_observation(identity(), failed, NOW)
        self.run_local()
        self.assertGreaterEqual((self.requests[0][2] - NOW).total_seconds(), 22)
        self.assertEqual(self.endpoint.submit_observation(identity(), failed, self.now), receipt)

    def test_global_denial_and_cooldown_never_switch_exit(self):
        for blocked, cooldown in ((True, 0), (False, NOW.timestamp() + 100)):
            with self.endpoint.transaction() as db:
                source = self.endpoint._get(db, 'collection_sources', 'ArabUT')
                source.update(blocked=blocked, cooldown_until=cooldown)
                self.endpoint._put(db, 'collection_sources', 'ArabUT', source)
            with self.assertRaises(ValueError):
                self.run_local()
            self.assertEqual(self.requests, [])

    def test_turnoff_while_waiting_prevents_local_request(self):
        def stop(seconds):
            self.advance(seconds)
            self.routing['remote_result_mode'] = 'off'
        with patch.object(self.failover.time, 'sleep', side_effect=stop), self.assertRaises(ValueError):
            self.run_local()
        self.assertEqual(self.requests, [])

    def test_recovered_primary_waits_cooldown_and_does_not_preempt_backup(self):
        self.endpoint.quarantine_node('183', NOW, 60)
        self.endpoint.register_node(identity(), ['ArabUT'], NOW + timedelta(seconds=1))
        self.assertIsNone(self.endpoint.claim_job(identity(), ['ArabUT'], NOW + timedelta(seconds=40), job_id=self.job['job_id']))
        other = build_job(dict(run_id='other', created_at=NOW.isoformat()), 'ArabUT',
            dict(arab_context(), total_attempt_limit=2, total_request_budget=6), self.job['deadline_at'])
        self.endpoint.enqueue(other)
        self.assertIsNone(self.endpoint.claim_job(identity(), ['ArabUT'], NOW + timedelta(seconds=59), job_id=other['job_id']))
        self.assertIsNotNone(self.endpoint.claim_job(identity(), ['ArabUT'], NOW + timedelta(seconds=60), job_id=other['job_id']))

    def test_real_client_reads_committed_receipt_before_considering_fallback_on_lost_ACK(self):
        from fc_collection.public_sources import arab_offers
        self.endpoint.complete_request(identity(), self.old['job_id'], self.old['lease_epoch'], self.permit['permit_id'], NOW)
        access = self.folder / 'access.json'
        access.write_text(json.dumps(dict(worker_digest='a'*64)))
        outer = self
        class Peer:
            def __init__(self, *a, **kw): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def health(self, *a, **kw): return dict(identity(), adapters=VERSIONS)
            def resend(self, *a): return dict(status='idle')
            def run(self, task, principal, endpoint):
                endpoint.reserve_request(principal, task['job_id'], task['lease_epoch'], dict(count=1), outer.now)
                body = observation(task, outer.now)
                body['offers'] = arab_offers(quote(), outer.now)
                outer.assertEqual(endpoint.submit_observation(principal, body, outer.now)['status'], 'accepted')
                raise OSError('lost ACK after committed receipt')
        parent = dict(run_id='client-parent', created_at=NOW.isoformat(), deadline_at=self.job['deadline_at'])
        with patch.object(self.client, 'DATABASE', self.endpoint.path), patch.object(self.client, 'ACCESS', access), \
                patch.object(self.client, 'private_file'), patch.object(self.client, 'ssh_command', return_value=[]), \
                patch.object(self.client, 'Session', Peer), patch.object(self.failover, 'run_fallback', side_effect=AssertionError('must read original ACK')):
            self.assertEqual(len(self.client.arab_normal(lambda: self.fail('direct fallback'), parent)['offers']), 2)

    def test_a_failed_local_capture_is_not_retried_by_the_same_fallback(self):
        with patch.object(self.failover.RestrictedHTTP, 'fetch', side_effect=OSError('source timeout')) as fetch:
            self.run_local()
            self.run_local()
        self.assertEqual(fetch.call_count, 1)


class LegacyRollback(unittest.TestCase):
    def test_off_respects_origin_block_cooldown_and_unknown_request_without_creating_new_job(self):
        from fc_collection import client
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            endpoint = Coordinator(folder / 'state.sqlite3')
            endpoint.configure_source('ArabUT', dict(policy(), origin='https://www.arab-ut.com'))
            routing = dict(schema_version=1, remote_result_mode='off', assignment_generation=1)
            local = Mock(return_value='legacy')
            with patch.object(client, 'DATABASE', endpoint.path), patch.object(client, 'read_routing', return_value=routing), \
                    patch.object(client, 'utc', return_value=NOW):
                self.assertEqual(client.arab_normal(local), 'legacy')
                for key, value in (('blocked', True), ('cooldown_until', NOW.timestamp()+30)):
                    with endpoint.transaction() as db:
                        source = endpoint._get(db, 'collection_sources', 'ArabUT')
                        source.update(blocked=False, cooldown_until=0)
                        source[key] = value
                        endpoint._put(db, 'collection_sources', 'ArabUT', source)
                    local.reset_mock()
                    self.assertEqual(client.arab_normal(local)['offers'], [])
                    local.assert_not_called()
                with endpoint.transaction() as db:
                    self.assertEqual(db.execute('SELECT COUNT(*) FROM collection_jobs').fetchone()[0], 0)


class LocalLock(unittest.TestCase):
    def test_full_bounded_spool_can_drain_original_ACK_without_claiming_new_work(self):
        from unittest.mock import Mock
        from fc_collection.contracts import fingerprint
        from fc_collection.worker import Worker
        endpoint = Mock()
        endpoint.claim_job.side_effect = AssertionError('spool must drain first')
        endpoint.submit_observation.side_effect = lambda _, body, now: dict(observation_id=body['observation_id'],
            status='accepted', payload_hash=fingerprint(body))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)
            for index in range(32):
                body = dict(node_id='187', observation_id='%032x' % index)
                (path / (body['observation_id'] + '.json')).write_text(json.dumps(body))
            worker = Worker(endpoint, identity('187'), {}, path, lambda *a: self.fail('no source GET'), clock=lambda: NOW)
            self.assertEqual(worker.run_once(allow_claim=False)['status'], 'accepted')
            self.assertEqual(len(list(path.iterdir())), 31)
            endpoint.claim_job.assert_not_called()

    @unittest.skipUnless(os.name == 'posix', '187 Linux flock behavior')
    def test_local_worker_lock_refuses_second_process_and_symlink(self):
        from fc_collection.failover import local_worker_lock
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'worker.lock'
            with local_worker_lock(path):
                with self.assertRaises(OSError):
                    with local_worker_lock(path):
                        self.fail('second worker acquired the lock')
            path.unlink()
            target = Path(folder) / 'keep'
            target.write_text('keep')
            path.symlink_to(target)
            with self.assertRaises(OSError):
                with local_worker_lock(path):
                    self.fail('symlink accepted')
            self.assertEqual(target.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
